"""Foreign-key validator — cross-table referential integrity (task 2.4 / issue #63).

This module is the **referential-integrity** half of the datagrove
validation layer. It walks a :class:`~datagrove.spec.model.DataPackage`,
follows every declared :class:`~datagrove.spec.model.ForeignKey`, and
verifies that every non-null source-column value appears in the target
column. Cross-table FKs (``link.from_node_id -> node.node_id``) and
same-table self-references (``node.parent_node_id -> node.node_id``) are
both supported, and so are composite FKs (``[a, b] -> [x, y]``).

Each violation becomes one :class:`~datagrove.reports.Issue`
with ``category=Category.FOREIGN_KEY`` and a stable dotted code
(:data:`fk.missing_target`, :data:`fk.null_in_required_fk`,
:data:`fk.unverifiable`, :data:`fk.target_field_missing`). The
:class:`Issue.extra` dict carries ``target_table`` / ``target_field`` /
``value`` so the HTML renderer (task 2.2) can drive its expand-row panel
without re-parsing the message string.

Cross-engine strategy (read this — Lens C trade-off)
----------------------------------------------------

The Engine protocol gives us three different ``TableExpr`` types
(ibis, polars LazyFrame, pandas) and no shared filter/aggregate dialect.
We mirror :mod:`datagrove.validation.schema_check`'s decision:
**materialise each table exactly once via** :meth:`Engine.to_pandas`,
then run the FK comparisons on plain pandas Series. This costs the
memory of one DataFrame per table but means every per-FK helper is
written in one dialect and every engine gets identical issue counts +
codes (the cross-engine parity test pins this).

An ibis-only "push the join into the engine" alternative is documented
as a TODO on :func:`check_foreign_key` for a future Phase 5 optimisation
pass; we are not enabling it in 1.0 to keep the cross-engine matrix
trivially correct.

Per-FK code mapping (downstream-stable, dotted)
-----------------------------------------------

============================  =====================================================
Code                          When emitted
============================  =====================================================
``fk.missing_target``         A non-null source row's value(s) don't exist in the
                              target column(s). Severity: ERROR.
``fk.null_in_required_fk``    The source FK column is null AND the schema marks
                              that source field ``required=True``. Severity: ERROR.
``fk.unverifiable``           Target table isn't in the ``tables`` mapping — we
                              can't check the FK. Severity: WARNING (or ERROR
                              under ``strict=True``).
``fk.target_field_missing``   Target table is present but doesn't have the
                              target field — the spec references a missing
                              column. Severity: ERROR (spec bug, not data bug).
============================  =====================================================

v0.3 bug-class regression
-------------------------

The v0.3 ``foreign_keys.py`` raised ``TypeError`` on
``if s.isna(): ...`` when the source FK column contained nulls (the
Series-vs-bool truthiness trap). We pin the structural fix in two
ways:

1. No code path in this module coerces a Series to ``bool``. Null
   detection runs through ``col.isna()`` + boolean indexing, not
   ``if col.isna(): ...``.
2. ``test_v03_fk_validator_regression`` builds a source with both a
   null AND a real missing target and asserts both issue codes fire —
   the test fails immediately if the null branch crashes.

DirtyTracker note (task 2.6)
----------------------------

This validator does NOT stamp ``sync_state`` hashes. Task 2.6 wraps it
in a hash-aware layer that checks the content hash of the source table
+ target table before re-running the FK and stamps a fresh hash on a
clean pass. The hashes the wrapper needs are the same ones any
content-addressed cache would use — sha of the source column bytes +
sha of the target column bytes. This module deliberately doesn't depend
on the hash infrastructure so the dependency points only one way.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from datagrove.reports import Category, Issue, Severity, ValidationReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import DataPackage, ForeignKey

__all__ = [
    "MAX_ROW_ISSUES",
    "check_foreign_key",
    "check_foreign_keys",
]


# Per-FK row-Issue enumeration cap. Mirrors
# :data:`datagrove.validation.schema_check.MAX_ROW_ISSUES`. Beyond this
# the validator emits ``MAX_ROW_ISSUES`` per-row issues plus a single
# summary issue carrying the true count in ``extra["total_violations"]``.
MAX_ROW_ISSUES: int = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_field_list(fields: str | list[str]) -> list[str]:
    """Normalise the Frictionless ``fields`` declaration to a list.

    Frictionless allows ``fields`` to be either a single name or a list
    of names (for composite FKs). Internally we always work with the
    list shape so the composite path is the only path.
    """
    if isinstance(fields, str):
        return [fields]
    return list(fields)


def _materialise(engine: Engine, expr: TableExpr) -> pd.DataFrame:
    """Materialise ``expr`` via the engine's :meth:`Engine.to_pandas`.

    Mirrors :func:`schema_check._materialise`. If ``expr`` is already a
    DataFrame (the common case after the orchestrator pre-materialises),
    returns it unchanged.
    """
    if isinstance(expr, pd.DataFrame):
        return expr
    return engine.to_pandas(expr)


def _format_field_list(fields: list[str]) -> str:
    """Render a field list for use inside messages.

    Single-field FKs read as ``from_node_id``; composite FKs read as
    ``[a, b]``. Single-field rendering matches how a human would write
    the FK in prose; the bracketed form makes the composite case
    unambiguous.
    """
    if len(fields) == 1:
        return fields[0]
    return "[" + ", ".join(fields) + "]"


def _format_value(value: Any) -> str:
    """Render a source value (scalar or tuple) for use inside messages.

    Tuples (the composite case) come out as ``(1, 2)``; scalars use
    ``repr`` so strings get quoted and integers stay bare — keeping
    the rendering consistent with the schema-check helpers.
    """
    if isinstance(value, tuple):
        return "(" + ", ".join(repr(v) for v in value) + ")"
    return repr(value)


def _source_field_is_required(
    package: DataPackage | None,
    source_table_name: str,
    source_field: str,
) -> bool:
    """Look up whether ``source_field`` is marked ``required=True``.

    Returns ``False`` for any of: no package, table not declared, schema
    is still a string reference, field absent from schema, no
    constraints, ``required`` unset. The validator uses this to decide
    whether a null in the source column is just informational ("FK is
    null, can't check it") or an actual ``fk.null_in_required_fk``.
    """
    if package is None:
        return False
    for resource in package.resources:
        if resource.name != source_table_name:
            continue
        schema = resource.table_schema
        if schema is None or isinstance(schema, str):
            return False
        for field in schema.fields:
            if field.name != source_field:
                continue
            return bool(field.constraints and field.constraints.required)
        return False
    return False


def _emit_null_in_required_fk_issues(
    df: pd.DataFrame,
    source_table_name: str,
    source_fields: list[str],
    *,
    package: DataPackage | None,
) -> list[Issue]:
    """Emit ``fk.null_in_required_fk`` for null source values in required columns.

    Walks each source field; if the field is marked ``required=True``
    in the package schema, enumerates rows where the column is null.
    Bounded by :data:`MAX_ROW_ISSUES` per source field.
    """
    issues: list[Issue] = []
    for source_field in source_fields:
        if source_field not in df.columns:
            continue
        if not _source_field_is_required(package, source_table_name, source_field):
            continue
        col = cast(pd.Series, df[source_field])
        null_mask = cast(pd.Series, col.isna())
        selected = cast(pd.Series, null_mask[null_mask])
        null_rows = [int(i) for i in cast(list[Any], list(selected.index))]
        if not null_rows:
            continue
        for row in null_rows[:MAX_ROW_ISSUES]:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    category=Category.FOREIGN_KEY,
                    code="fk.null_in_required_fk",
                    message=(f"{source_table_name}.{source_field} row {row}: required FK column is null"),
                    table=source_table_name,
                    column=source_field,
                    row=row,
                    fix_hint=("Either populate the FK column or relax the required=True constraint."),
                )
            )
        if len(null_rows) > MAX_ROW_ISSUES:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    category=Category.FOREIGN_KEY,
                    code="fk.null_in_required_fk",
                    message=(
                        f"{source_table_name}.{source_field}: {len(null_rows)} required FK "
                        f"values are null (showing first {MAX_ROW_ISSUES})"
                    ),
                    table=source_table_name,
                    column=source_field,
                    extra={"total_violations": len(null_rows)},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Per-FK helper
# ---------------------------------------------------------------------------


def check_foreign_key(
    fk: ForeignKey,
    source_table_name: str,
    source_expr: TableExpr,
    target_table_name: str,
    target_expr: TableExpr | None,
    *,
    engine: Engine,
    package: DataPackage | None = None,
    strict: bool = False,
) -> list[Issue]:
    """Check a single :class:`~datagrove.spec.model.ForeignKey`.

    Materialises ``source_expr`` (and ``target_expr`` when present) via
    :meth:`Engine.to_pandas`, then compares non-null source values
    against the deduplicated set of target values. Composite FKs are
    handled by building tuples of the joint key on both sides.

    Args:
        fk: The :class:`~datagrove.spec.model.ForeignKey` to check.
        source_table_name: Logical name of the source table.
        source_expr: Engine-native table expression for the source.
            May also be a pre-materialised pandas DataFrame.
        target_table_name: Logical name of the target table. For
            self-referential FKs (``fk.reference.resource == ""``)
            callers should pass the source's own name.
        target_expr: Engine-native target table expression, or ``None``
            when the target table isn't available — in which case the
            helper emits one ``fk.unverifiable`` issue and returns.
        engine: The engine that produced the expressions. Used only
            for materialisation (cross-table set comparison runs in
            pandas).
        package: Optional :class:`~datagrove.spec.model.DataPackage`,
            consulted to determine whether a source FK column is
            ``required=True`` (which upgrades a null to
            ``fk.null_in_required_fk``). When ``None`` no null-vs-
            required check runs.
        strict: When ``True``, ``fk.unverifiable`` issues are ERROR
            instead of WARNING.

    Returns:
        A list of :class:`Issue` records. The list is empty when the
        FK is satisfied for every non-null source row, the source
        table omits the FK columns, or the target table is empty
        AND source has no non-null values.

    Examples:
        Clean single-field FK:

        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import ForeignKey, ForeignKeyReference
        >>> e = PandasEngine()
        >>> src = e.scan({"data": [{"id": 1, "ref": 1}, {"id": 2, "ref": 1}]})
        >>> tgt = e.scan({"data": [{"key": 1}]})
        >>> fk = ForeignKey(fields="ref",
        ...     reference=ForeignKeyReference(resource="tgt", fields="key"))
        >>> check_foreign_key(fk, "src", src, "tgt", tgt, engine=e)
        []

        Missing target value:

        >>> src = e.scan({"data": [{"id": 1, "ref": 99}]})
        >>> tgt = e.scan({"data": [{"key": 1}]})
        >>> issues = check_foreign_key(fk, "src", src, "tgt", tgt, engine=e)
        >>> issues[0].code
        'fk.missing_target'

        Unverifiable (no target table):

        >>> issues = check_foreign_key(fk, "src", src, "tgt", None, engine=e)
        >>> issues[0].code
        'fk.unverifiable'
    """
    source_fields = _as_field_list(fk.fields)
    target_fields = _as_field_list(fk.reference.fields)
    src_label = _format_field_list(source_fields)
    tgt_label = f"{target_table_name}.{_format_field_list(target_fields)}"

    # 1. Unverifiable — target table not in the mapping.
    if target_expr is None:
        severity = Severity.ERROR if strict else Severity.WARNING
        return [
            Issue(
                severity=severity,
                category=Category.FOREIGN_KEY,
                code="fk.unverifiable",
                message=(
                    f"{source_table_name} FK {src_label}->{tgt_label}: "
                    f"target table {target_table_name!r} missing from package"
                ),
                table=source_table_name,
                fix_hint=(
                    f"Provide the {target_table_name!r} table so the FK can be verified, "
                    f"or remove the FK from the spec."
                ),
                extra={
                    "target_table": target_table_name,
                    "target_field": ",".join(target_fields),
                },
            )
        ]

    src_df = _materialise(engine, source_expr)
    tgt_df = _materialise(engine, target_expr)

    issues: list[Issue] = []

    # 2. Target-field-missing — pure spec bug. One issue per missing
    # target field; report all of them so the spec author sees the full
    # list in one pass.
    missing_target_fields = [tf for tf in target_fields if tf not in tgt_df.columns]
    if missing_target_fields:
        for tf in missing_target_fields:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    category=Category.FOREIGN_KEY,
                    code="fk.target_field_missing",
                    message=(
                        f"{source_table_name} FK {src_label}->{tgt_label}: "
                        f"target field {tf!r} does not exist in {target_table_name}"
                    ),
                    table=source_table_name,
                    fix_hint=(
                        f"Add a {tf!r} column to {target_table_name!r}, or update "
                        f"the FK reference in the spec to point at an existing field."
                    ),
                    extra={
                        "target_table": target_table_name,
                        "target_field": tf,
                    },
                )
            )
        # Without the target fields we can't run the per-row check —
        # everything would look "missing". Return what we have.
        return issues

    # 3. Null-in-required-FK check — runs against source even before
    # we know whether the target has matches. This lets us still flag
    # required-null when the target column is empty.
    issues.extend(
        _emit_null_in_required_fk_issues(
            src_df,
            source_table_name,
            source_fields,
            package=package,
        )
    )

    # 4. Missing-target check — build the set of target keys, walk the
    # source, enumerate the rows whose key is not in the set.
    # Source columns may be absent (e.g., optional FK that wasn't
    # populated). If so there's nothing to check.
    if any(sf not in src_df.columns for sf in source_fields):
        return issues

    # Build target key set. For single-field FKs the set holds scalars;
    # for composite FKs it holds tuples. ``itertuples`` is the cheapest
    # pandas-native way to build tuple keys without per-row Python.
    tgt_sub = cast(pd.DataFrame, tgt_df[target_fields]).dropna()
    if len(target_fields) == 1:
        target_set: set[Any] = set(cast(pd.Series, tgt_sub[target_fields[0]]).tolist())
    else:
        target_set = {tuple(row) for row in tgt_sub.itertuples(index=False, name=None)}

    # Drop rows where ANY source key field is null — they're either
    # legitimately null-FK (and the null-in-required check above
    # covered them) or they can't be the subject of a referential
    # check. The mask is built via boolean operations on Series only;
    # at no point does the code coerce a Series to bool (v0.3 trap).
    src_keys = cast(pd.DataFrame, src_df[source_fields])
    non_null_mask = cast(pd.Series, src_keys.notna().all(axis=1))
    candidates = cast(pd.DataFrame, src_keys[non_null_mask])

    if candidates.empty:
        return issues

    if len(source_fields) == 1:
        single_col = source_fields[0]
        values = cast(pd.Series, candidates[single_col])
        membership = cast(pd.Series, values.isin(list(target_set)))
    else:
        tuples = [tuple(row) for row in candidates.itertuples(index=False, name=None)]
        membership_list = [t in target_set for t in tuples]
        membership = pd.Series(membership_list, index=candidates.index)

    bad_mask = cast(pd.Series, ~membership)
    selected_bad = cast(pd.Series, bad_mask[bad_mask])
    # ``int(i)`` round-trip so Issue.row is a plain int, not a numpy int.
    bad_index: list[int] = [int(i) for i in cast(list[Any], list(selected_bad.index))]

    if not bad_index:
        return issues

    total = len(bad_index)
    enumerated = bad_index[:MAX_ROW_ISSUES]

    for row in enumerated:
        if len(source_fields) == 1:
            value: Any = candidates.loc[row, source_fields[0]]
            value_repr = _format_value(value)
        else:
            value = tuple(cast(pd.Series, candidates.loc[row, source_fields]).tolist())
            value_repr = _format_value(value)
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.FOREIGN_KEY,
                code="fk.missing_target",
                message=(f"{source_table_name}.{src_label} row {row}: value {value_repr} not found in {tgt_label}"),
                table=source_table_name,
                column=src_label if len(source_fields) == 1 else None,
                row=row,
                fix_hint=(
                    f"Add a {target_table_name} row with "
                    f"{_format_field_list(target_fields)}={value_repr}, "
                    f"or remove the {source_table_name} row."
                ),
                extra={
                    "target_table": target_table_name,
                    "target_field": (target_fields[0] if len(target_fields) == 1 else ",".join(target_fields)),
                    "value": value,
                },
            )
        )

    if total > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.FOREIGN_KEY,
                code="fk.missing_target",
                message=(
                    f"{source_table_name}.{src_label}->{tgt_label}: "
                    f"{total} missing-target violations (showing first {MAX_ROW_ISSUES})"
                ),
                table=source_table_name,
                column=src_label if len(source_fields) == 1 else None,
                fix_hint=(f"Populate {tgt_label} with the missing keys, or fix the source rows."),
                extra={
                    "target_table": target_table_name,
                    "target_field": (target_fields[0] if len(target_fields) == 1 else ",".join(target_fields)),
                    "total_violations": total,
                },
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def check_foreign_keys(
    package: DataPackage,
    tables: Mapping[str, TableExpr],
    *,
    engine: Engine,
    report: ValidationReport | None = None,
    strict: bool = False,
) -> ValidationReport:
    """Validate every foreign key declared in ``package`` across ``tables``.

    Walks :attr:`package.resources`, picks up every
    :class:`~datagrove.spec.model.ForeignKey` declared on each
    resource's :class:`~datagrove.spec.model.Schema`, and routes each
    one through :func:`check_foreign_key`. Cross-table and same-table
    (``reference.resource == ""``) FKs are both handled.

    Each table in ``tables`` is materialised exactly once via
    :meth:`Engine.to_pandas` and the resulting DataFrame is shared
    across every FK that touches it — so a package with many FKs
    against the same target only pays the conversion cost for that
    target once.

    The :class:`ValidationReport` is mutated in place (or created if
    not given) and returned. Issue codes are stable:
    :data:`fk.missing_target`, :data:`fk.null_in_required_fk`,
    :data:`fk.unverifiable`, :data:`fk.target_field_missing`. See the
    module docstring for the severity and extra-dict contract.

    DirtyTracker (task 2.6) wraps this validator to stamp a fresh
    sync-state hash on a clean pass — this function deliberately
    doesn't depend on the hash infrastructure so the dependency is
    one-way.

    Args:
        package: :class:`~datagrove.spec.model.DataPackage` describing
            every table + its FKs.
        tables: Mapping ``{table_name: TableExpr}``. Tables absent
            from the mapping become :data:`fk.unverifiable` issues
            (one per FK pointing at them).
        engine: The :class:`~datagrove.engines.base.Engine` that
            produced the table expressions. Used for materialisation.
        report: Existing :class:`ValidationReport` to append into.
            Created when ``None``; returned in either case.
        strict: When ``True``, :data:`fk.unverifiable` issues are
            ERROR instead of WARNING. Use this in CI where a missing
            target table should fail the run.

    Returns:
        The :class:`ValidationReport` — the same instance as
        ``report`` if one was passed.

    Examples:
        Clean single-FK package:

        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import (
        ...     DataPackage, Resource, Schema, Field, ForeignKey, ForeignKeyReference,
        ... )
        >>> e = PandasEngine()
        >>> link = e.scan({"data": [{"link_id": 1, "from_node_id": 1}]})
        >>> node = e.scan({"data": [{"node_id": 1}]})
        >>> pkg = DataPackage(name="x", resources=[
        ...     Resource(name="node", path="node.csv",
        ...         schema=Schema(fields=[Field(name="node_id", type="integer")])),
        ...     Resource(name="link", path="link.csv",
        ...         schema=Schema(
        ...             fields=[Field(name="link_id", type="integer"),
        ...                     Field(name="from_node_id", type="integer")],
        ...             foreign_keys=[ForeignKey(fields="from_node_id",
        ...                 reference=ForeignKeyReference(resource="node",
        ...                                               fields="node_id"))],
        ...         )),
        ... ])
        >>> report = check_foreign_keys(pkg, {"link": link, "node": node}, engine=e)
        >>> report.is_clean
        True
    """
    if report is None:
        report = ValidationReport()

    # Materialise each provided table exactly once. The per-FK helper
    # accepts either a TableExpr or a DataFrame, so handing it a
    # DataFrame here short-circuits its own materialisation.
    materialised: dict[str, pd.DataFrame] = {}
    for name, expr in tables.items():
        materialised[name] = _materialise(engine, expr)

    for resource in package.resources:
        schema = resource.table_schema
        if schema is None or isinstance(schema, str):
            continue
        if not schema.foreign_keys:
            continue
        source_name = resource.name
        source_df = materialised.get(source_name)
        if source_df is None:
            # The source table itself isn't loaded — nothing we can
            # check. Structural (task 2.5) covers the "table missing"
            # case; we don't double-report it here.
            continue
        for fk in schema.foreign_keys:
            # Same-table reference: resource == "" → target is the
            # source itself. Otherwise the reference names a sibling.
            if fk.reference.resource == "":
                target_name = source_name
                target_df: pd.DataFrame | None = source_df
            else:
                target_name = fk.reference.resource
                target_df = materialised.get(target_name)
            for issue in check_foreign_key(
                fk,
                source_table_name=source_name,
                source_expr=source_df,
                target_table_name=target_name,
                target_expr=target_df,
                engine=engine,
                package=package,
                strict=strict,
            ):
                report.add_issue(issue)

    return report
