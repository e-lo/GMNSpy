"""Schema validator — per-field Frictionless constraint checks (task 2.3 / issue #62).

This module is the **schema** half of the datagrove validation layer.
It takes a table expression (from any engine — ibis, polars, pandas)
plus a parsed Frictionless :class:`~datagrove.spec.model.Schema` and
emits :class:`~datagrove.reports.Issue` records — one per field-level
violation — into a :class:`~datagrove.reports.ValidationReport`.

Cross-engine strategy — ibis-first (architecture §6.1)
------------------------------------------------------

Every rule pushes its violation count down as an ibis predicate
(``expr[col].is_null()``, ``~expr[col].isin(allowed)``,
``expr[col] < bound``, …) — the count round-trips as a single SQL
aggregate, not a pandas materialisation. At Bay-Area scale (millions
of rows) this turns "count nulls in a required column" from a
gigabyte materialisation into a millisecond SQL ``COUNT(*) WHERE col
IS NULL``.

Only the per-rule sample used to populate row-context Issues is
materialised — capped at :data:`MAX_ROW_ISSUES` rows — and goes
through pyarrow (``.to_pyarrow().to_pylist()``), never pandas.
Pandas-backed and polars-backed sources route through
:func:`datagrove.validation._ibis.to_ibis`, which wraps them once per
orchestrator call as an ``ibis.memtable`` against the default
duckdb backend.

Per-rule code mapping (the dotted codes downstream tools grep for)
------------------------------------------------------------------

================  ================================================
Rule              Issue code (downstream-stable)
================  ================================================
required          ``schema.required``
type              ``schema.type``
enum              ``schema.enum``
minimum           ``schema.minimum``
maximum           ``schema.maximum``
min_length        ``schema.min_length``
max_length        ``schema.max_length``
pattern           ``schema.pattern``
unique            ``schema.unique``
================  ================================================

Severity defaults
-----------------

``required`` / ``type`` / ``unique`` → :class:`Severity.ERROR`.
``enum`` / ``pattern`` / ``minimum`` / ``maximum`` / ``min_length`` /
``max_length`` → :class:`Severity.WARNING`. If a field is both
``required=True`` AND has a min/max/length bound, the bound check
elevates to :class:`Severity.ERROR` (the field's contract is strict
enough that an out-of-range value is treated as broken).

v0.3 bug-class regressions
--------------------------

Three explicit regression tests live in
``packages/datagrove/tests/validation/test_schema_check.py`` and pin
the three v0.3 bug classes the architecture doc calls out:
``_unique_constraint`` (Series-vs-bool), ``apply_schema_to_df``
warning-list copy/paste, and the ``~s.str.contains(...)`` bool-of-Series
bug. The ibis-first refactor makes each of those structurally
impossible — predicates are ibis expressions (no Python truthiness),
the report classifies issues by their own ``severity`` (not by
re-filtering a single mixed list), and pattern checks enumerate
failing rows via a filtered sample.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import ibis

from datagrove.reports import Category, Issue, Severity, ValidationReport

from ._ibis import to_ibis

if TYPE_CHECKING:  # pragma: no cover - typing only
    import ibis.expr.types as ir

    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import Field, Schema

__all__ = [
    "MAX_ROW_ISSUES",
    "check_enum",
    "check_max_length",
    "check_maximum",
    "check_min_length",
    "check_minimum",
    "check_pattern",
    "check_required",
    "check_schema",
    "check_type",
    "check_unique",
]


# Per-rule row-Issue enumeration cap. Beyond this we emit one summary
# Issue plus the first ``MAX_ROW_ISSUES`` row-specific Issues. The cap
# protects callers (rich-console, HTML renderer) from million-issue
# reports while still letting a reviewer see concrete examples.
MAX_ROW_ISSUES: int = 100


# Internal column name used to surface the original row position into
# the materialised sample. We attach ``ibis.row_number()`` as this
# column inside :func:`_with_row_index`; per-rule enumerators read it
# back from the pyarrow sample so ``Issue.row`` is the source-of-truth
# row index, not the sample's 0-based offset.
_ROW_COL: str = "__dg_row__"


# Frictionless type → ibis dtype family. A column whose ibis dtype is
# not in the declared family fires ``schema.type``. Frictionless types
# not listed here (``date``, ``time``, ``object``, …) are skipped —
# the cross-engine type-map parity test gates the keyset.
#
# We compare by the ibis dtype's ``str()`` representation. Ibis exposes
# canonical lowercase names (``int64``, ``float64``, ``string``,
# ``boolean``); we accept the family substrings since duckdb may
# surface narrower variants (``int32``) for memtables of typed pandas.
_FRICTIONLESS_TO_IBIS_FAMILY: dict[str, tuple[str, ...]] = {
    "integer": ("int",),
    "number": ("int", "float", "decimal"),
    "boolean": ("bool",),
    "string": ("string",),
    # ``any`` is the GMNS escape hatch — every dtype is acceptable.
    "any": (),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_required(field: Field) -> bool:
    """Return ``True`` when ``field.constraints.required`` is ``True``."""
    return bool(field.constraints and field.constraints.required)


def _bound_severity(field: Field) -> Severity:
    """Pick the severity for a bound-style rule (min/max/length).

    Required fields elevate bound violations to ERROR. A required
    field's contract is already strict; an out-of-range value isn't a
    "maybe-legal-in-a-future-spec" gray area, it's a fully-broken row.
    """
    return Severity.ERROR if _is_required(field) else Severity.WARNING


def _with_row_index(table: ir.Table) -> ir.Table:
    """Attach a 0-based row-number column so enumerators carry positions.

    ibis ``row_number()`` is the SQL window function; the cast to int
    is defensive (ibis returns int64 universally but downstream code
    consumes the value as a plain ``int``).
    """
    if _ROW_COL in table.columns:
        return table
    return table.mutate(**{_ROW_COL: ibis.row_number().cast("int64")})


def _has_column(table: ir.Table, name: str) -> bool:
    """Return ``True`` iff ``name`` is a column on ``table``.

    Missing columns are a *structural* problem, not a *schema* problem
    (task 2.5 owns that). Schema rules silently skip absent fields so
    a partial dataset doesn't produce dozens of misleading findings.
    """
    return name in table.columns


def _count(predicate_table: ir.Table) -> int:
    """Push a ``COUNT(*)`` to the backend and return a plain int.

    Uses ``.to_pyarrow().as_py()`` rather than ``.execute()`` so the
    return type is statically inferrable as ``Any`` (which pyright
    accepts as an int) — ``.execute()`` is typed as
    ``DataFrame | Series | Scalar`` even though the scalar branch
    is the only one our usage hits.
    """
    return int(predicate_table.count().to_pyarrow().as_py())


def _sample(predicate_table: ir.Table, *, limit: int) -> list[dict[str, Any]]:
    """Materialise up to ``limit`` rows of ``predicate_table`` as pylist dicts.

    The pyarrow path keeps us pandas-free; ``to_pylist`` is the
    cheapest stable way to iterate a small sample row-by-row.
    """
    arrow = predicate_table.limit(limit).to_pyarrow()
    return arrow.to_pylist()


def _row_of(sample_row: dict[str, Any]) -> int:
    """Pull the source row index out of a sampled dict."""
    raw = sample_row.get(_ROW_COL)
    # Defensive cast: arrow may yield numpy ints depending on backend.
    return int(raw) if raw is not None else -1


def _emit_summary(
    *,
    severity: Severity,
    code: str,
    table_name: str,
    field: Field,
    total: int,
    summary_message: str,
    extra: dict[str, Any] | None = None,
) -> Issue:
    """Build the "showing first N of total" summary Issue.

    Unified across rules: ``extra["total_violations"]`` carries the
    full count; ``extra["sample_shown"]`` carries the cap. Renderers
    already understand both keys (HTML + JSON exercises pin the
    contract).
    """
    payload: dict[str, Any] = {"total_violations": total, "sample_shown": MAX_ROW_ISSUES}
    if extra:
        payload.update(extra)
    return Issue(
        severity=severity,
        category=Category.SCHEMA,
        code=code,
        message=summary_message,
        table=table_name,
        column=field.name,
        extra=payload,
    )


# ---------------------------------------------------------------------------
# Per-rule helpers — each takes an ibis Table, pushes a count, samples
# only when needed.
# ---------------------------------------------------------------------------


def check_required(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag null values in a required field.

    Returns an empty list when ``field.constraints.required`` is not
    truthy. Per-row Issues are emitted up to :data:`MAX_ROW_ISSUES`;
    beyond that one summary Issue records the total.

    Args:
        expr: Engine-native table expression (or a pre-normalised ibis
            Table when called from :func:`check_schema`).
        field: The :class:`~datagrove.spec.model.Field` to check.
        engine: The engine that produced ``expr``. Retained for
            signature compatibility; no longer used internally.
        table_name: Logical table name — populates ``Issue.table``.

    Returns:
        A list of :class:`Issue` records. Empty when the field is not
        required, absent from ``expr``, or has no nulls.
    """
    if not _is_required(field):
        return []
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    bad = table.filter(table[field.name].isnull())
    total = _count(bad)
    if total == 0:
        return []
    issues: list[Issue] = []
    for sample_row in _sample(bad, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.required",
                message=f"{table_name}.{field.name} row {row_idx}: required field is null",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Set {table_name}.{field.name} row {row_idx} to a non-null value.",
            )
        )
    if total > MAX_ROW_ISSUES:
        issues.append(
            _emit_summary(
                severity=Severity.ERROR,
                code="schema.required",
                table_name=table_name,
                field=field,
                total=total,
                summary_message=(
                    f"{table_name}.{field.name}: {total} required values are null (showing first {MAX_ROW_ISSUES})"
                ),
            )
        )
    return issues


def check_type(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag a column whose ibis dtype doesn't match ``field.type``.

    The check is at the *column* level — ibis carries one dtype per
    column. A column read from a CSV as strings (because a single cell
    wouldn't coerce) lands as ``string`` and won't match e.g.
    ``integer`` — exactly the v0.3 failure mode this rule pins.
    Frictionless types not in :data:`_FRICTIONLESS_TO_IBIS_FAMILY` (or
    ``any``) are skipped.
    """
    if not field.type:
        return []
    allowed = _FRICTIONLESS_TO_IBIS_FAMILY.get(field.type)
    if allowed is None or not allowed:
        # Unknown type OR "any" — nothing to check at the dtype level.
        return []
    table = to_ibis(expr)
    if not _has_column(table, field.name):
        return []
    actual = str(table[field.name].type()).lower()
    if any(fam in actual for fam in allowed):
        return []
    return [
        Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.type",
            message=(
                f"{table_name}.{field.name}: column dtype {actual!r} does not match "
                f"declared Frictionless type {field.type!r}"
            ),
            table=table_name,
            column=field.name,
            fix_hint=f"Coerce {table_name}.{field.name} to {field.type!r}.",
            extra={"actual_dtype": actual, "expected_type": field.type},
        )
    ]


def check_enum(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag values not in ``constraints.enum``.

    Null values are skipped (handled by :func:`check_required`).
    """
    if not field.constraints or not field.constraints.enum:
        return []
    allowed = list(field.constraints.enum)
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    col = table[field.name]
    bad = table.filter(col.notnull() & ~col.isin(allowed))
    total = _count(bad)
    if total == 0:
        return []
    issues: list[Issue] = []
    allowed_str = ", ".join(repr(v) for v in allowed)
    for sample_row in _sample(bad, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        value = sample_row.get(field.name)
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.enum",
                message=f"{table_name}.{field.name} row {row_idx}: value {value!r} not in enum [{allowed_str}]",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Use one of: {', '.join(str(v) for v in allowed)}.",
            )
        )
    if total > MAX_ROW_ISSUES:
        issues.append(
            _emit_summary(
                severity=Severity.WARNING,
                code="schema.enum",
                table_name=table_name,
                field=field,
                total=total,
                summary_message=(
                    f"{table_name}.{field.name}: {total} values outside enum (showing first {MAX_ROW_ISSUES})"
                ),
                extra={"allowed": allowed},
            )
        )
    return issues


def _check_numeric_bound(
    expr: TableExpr,
    field: Field,
    *,
    table_name: str,
    bound: Any,
    code: str,
    direction: str,
) -> list[Issue]:
    """Shared body for :func:`check_minimum` and :func:`check_maximum`.

    Builds the directional predicate (``col < bound`` or ``col > bound``),
    counts via SQL, samples up to :data:`MAX_ROW_ISSUES` rows for
    per-row Issues, and emits a single summary Issue if the count
    overflows the cap.
    """
    if bound is None:
        return []
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    col = table[field.name]
    if direction == "below":
        bad = table.filter(col.notnull() & (col < bound))
        rel = "below minimum"
        fix_word = "above"
    else:
        bad = table.filter(col.notnull() & (col > bound))
        rel = "above maximum"
        fix_word = "below"
    total = _count(bad)
    if total == 0:
        return []
    severity = _bound_severity(field)
    issues: list[Issue] = []
    for sample_row in _sample(bad, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        value = sample_row.get(field.name)
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=f"{table_name}.{field.name} row {row_idx}: value {value} {rel} {bound}",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Set {table_name}.{field.name} to a value {fix_word} {bound}.",
            )
        )
    if total > MAX_ROW_ISSUES:
        issues.append(
            _emit_summary(
                severity=severity,
                code=code,
                table_name=table_name,
                field=field,
                total=total,
                summary_message=(
                    f"{table_name}.{field.name}: {total} values {rel} {bound} (showing first {MAX_ROW_ISSUES})"
                ),
                extra={"bound": bound},
            )
        )
    return issues


def check_minimum(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag values strictly below ``field.constraints.minimum``."""
    if not field.constraints:
        return []
    return _check_numeric_bound(
        expr,
        field,
        table_name=table_name,
        bound=field.constraints.minimum,
        code="schema.minimum",
        direction="below",
    )


def check_maximum(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag values strictly above ``field.constraints.maximum``."""
    if not field.constraints:
        return []
    return _check_numeric_bound(
        expr,
        field,
        table_name=table_name,
        bound=field.constraints.maximum,
        code="schema.maximum",
        direction="above",
    )


def _check_length_bound(
    expr: TableExpr,
    field: Field,
    *,
    table_name: str,
    bound: int | None,
    code: str,
    direction: str,
) -> list[Issue]:
    """Shared body for :func:`check_min_length` / :func:`check_max_length`."""
    if bound is None:
        return []
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    col = table[field.name]
    # Cast to string before measuring length so int / mixed columns
    # don't blow up on the .length() call. Nulls are dropped first.
    # The bound goes through ``ibis.literal`` so pyright can model
    # the comparison as ``IntegerValue`` vs ``IntegerValue``.
    length = col.cast("string").length()
    bound_lit = ibis.literal(bound)
    if direction == "below":
        bad = table.filter(col.notnull() & (length < bound_lit))
        rel = f"shorter than min_length {bound}"
        fix_word = "at least"
    else:
        bad = table.filter(col.notnull() & (length > bound_lit))
        rel = f"longer than max_length {bound}"
        fix_word = "no more than"
    total = _count(bad)
    if total == 0:
        return []
    severity = _bound_severity(field)
    issues: list[Issue] = []
    for sample_row in _sample(bad, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        value = sample_row.get(field.name)
        char_len = len(str(value)) if value is not None else 0
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=f"{table_name}.{field.name} row {row_idx}: value {value!r} ({char_len} chars) {rel}",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Use a value {fix_word} {bound} characters in {table_name}.{field.name}.",
            )
        )
    if total > MAX_ROW_ISSUES:
        issues.append(
            _emit_summary(
                severity=severity,
                code=code,
                table_name=table_name,
                field=field,
                total=total,
                summary_message=(f"{table_name}.{field.name}: {total} values {rel} (showing first {MAX_ROW_ISSUES})"),
                extra={"bound": bound},
            )
        )
    return issues


def check_min_length(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag strings shorter than ``field.constraints.min_length``."""
    if not field.constraints:
        return []
    return _check_length_bound(
        expr,
        field,
        table_name=table_name,
        bound=field.constraints.min_length,
        code="schema.min_length",
        direction="below",
    )


def check_max_length(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag strings longer than ``field.constraints.max_length``."""
    if not field.constraints:
        return []
    return _check_length_bound(
        expr,
        field,
        table_name=table_name,
        bound=field.constraints.max_length,
        code="schema.max_length",
        direction="above",
    )


def check_pattern(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag strings that don't match ``field.constraints.pattern``.

    Uses ``re_search`` with explicit ``^``/``$`` anchors so the regex
    must match the entire value (Frictionless full-match semantics).
    Null values are skipped.

    This is the regression site for the v0.3
    ``~s.str.contains(...)`` bool-of-Series bug — the predicate lives
    in ibis SQL, so Python truthiness on a Series can't recur.
    """
    if not field.constraints or not field.constraints.pattern:
        return []
    pattern = field.constraints.pattern
    # Validate the regex up front; a bad pattern is a SPEC bug, not a
    # data bug, and we emit the same Issue shape so renderers don't
    # special-case it.
    import re

    try:
        re.compile(pattern)
    except re.error as e:
        return [
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.pattern",
                message=f"{table_name}.{field.name}: invalid regex {pattern!r} in schema ({e})",
                table=table_name,
                column=field.name,
                fix_hint=f"Fix the regex declared on {table_name}.{field.name}.",
            )
        ]
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    col = table[field.name].cast("string")
    # Anchor for full-match semantics — Frictionless ``pattern`` is a
    # full-string regex, not a search.
    full_pattern = pattern if pattern.startswith("^") else f"^{pattern}"
    if not full_pattern.endswith("$"):
        full_pattern = f"{full_pattern}$"
    bad = table.filter(table[field.name].notnull() & ~col.re_search(full_pattern))
    total = _count(bad)
    if total == 0:
        return []
    issues: list[Issue] = []
    for sample_row in _sample(bad, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        value = sample_row.get(field.name)
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.pattern",
                message=f"{table_name}.{field.name} row {row_idx}: value {value!r} does not match pattern {pattern!r}",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Make {table_name}.{field.name} match the regex {pattern!r}.",
            )
        )
    if total > MAX_ROW_ISSUES:
        issues.append(
            _emit_summary(
                severity=Severity.WARNING,
                code="schema.pattern",
                table_name=table_name,
                field=field,
                total=total,
                summary_message=(
                    f"{table_name}.{field.name}: {total} values fail pattern "
                    f"{pattern!r} (showing first {MAX_ROW_ISSUES})"
                ),
                extra={"pattern": pattern},
            )
        )
    return issues


def check_unique(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
) -> list[Issue]:
    """Flag duplicate values in a field declared ``unique=True``.

    Nulls are excluded from the uniqueness check (Frictionless
    convention — duplicates of null don't violate uniqueness; the
    ``required`` constraint handles nulls). Built as
    ``group_by(col).having(count > 1)`` so duplicate counting happens
    in SQL.

    This is the regression site for the v0.3 ``_unique_constraint``
    bug (``if s.dropna().duplicated(): ...`` on a Series). The ibis
    predicate can't trigger Series-bool ambiguity.
    """
    if not field.constraints or not field.constraints.unique:
        return []
    table = _with_row_index(to_ibis(expr))
    if not _has_column(table, field.name):
        return []
    col_name = field.name
    col = table[col_name]
    # Group non-null values; the values appearing in >1 row are the
    # duplicate set. Then anti-join with the original table to locate
    # the offending rows + row indices.
    non_null = table.filter(col.notnull())
    dup_values = non_null.group_by(col_name).aggregate(_n=non_null.count()).filter(ibis._["_n"] > 1)
    duplicate_count = _count(table.filter(col.isin(dup_values[col_name])))
    if duplicate_count == 0:
        return []
    issues: list[Issue] = [
        Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.unique",
            message=f"{table_name}.{field.name}: {duplicate_count} duplicate values",
            table=table_name,
            column=field.name,
            fix_hint=f"Remove or de-duplicate values in {table_name}.{field.name}.",
            extra={"total_violations": duplicate_count, "sample_shown": MAX_ROW_ISSUES},
        )
    ]
    dup_rows = table.filter(col.isin(dup_values[col_name]))
    for sample_row in _sample(dup_rows, limit=MAX_ROW_ISSUES):
        row_idx = _row_of(sample_row)
        value = sample_row.get(col_name)
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.unique",
                message=f"{table_name}.{field.name} row {row_idx}: duplicate value {value!r}",
                table=table_name,
                column=field.name,
                row=row_idx,
                fix_hint=f"Make {table_name}.{field.name} unique at row {row_idx}.",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


# Deterministic per-rule call order. Required runs first so a null value
# isn't double-reported by every downstream rule; type runs second so a
# column-wide dtype mismatch surfaces before the per-row enum/min/max
# noise it would generate.
_RULE_ORDER: tuple = (
    check_required,
    check_type,
    check_enum,
    check_minimum,
    check_maximum,
    check_min_length,
    check_max_length,
    check_pattern,
    check_unique,
)


def check_schema(
    expr: TableExpr,
    schema: Schema,
    *,
    engine: Engine,
    table_name: str,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """Validate ``expr`` against ``schema`` and populate a ValidationReport.

    Runs every per-field check declared in the Frictionless schema
    (required / type / enum / minimum / maximum / min_length /
    max_length / pattern / unique) and appends one or more
    :class:`Issue` records per violation to ``report``.

    The expression is **normalised to ibis once** at the top of the
    call — pandas / polars sources are wrapped as ``ibis.memtable``
    via :func:`datagrove.validation._ibis.to_ibis`. Each rule then
    pushes its violation count down as an ibis predicate (a SQL
    aggregate, not a pandas materialisation) and samples only the
    rows it needs for row-context Issues. At Bay-Area scale this is
    the difference between a millisecond ``COUNT(*)`` and a gigabyte
    materialisation.

    Args:
        expr: Engine-native lazy table expression to validate.
        schema: Parsed Frictionless :class:`~datagrove.spec.model.Schema`.
        engine: The :class:`~datagrove.engines.base.Engine` that produced
            ``expr``. Retained for signature compatibility; the
            ibis-first refactor no longer routes through it.
        table_name: Logical name of the table (populates ``Issue.table``).
        report: Optional existing :class:`ValidationReport` to append
            into. When ``None`` (the default), a fresh report is
            created. The same object is returned either way.

    Returns:
        The :class:`ValidationReport` — the same instance as ``report``
        if one was passed.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Schema, Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"id": 1}, {"id": 2}])
        >>> s = Schema(fields=[Field(name="id", type="any",
        ...     constraints=Constraints(required=True, unique=True))])
        >>> report = check_schema(expr, s, engine=e, table_name="t")
        >>> report.is_clean
        True
    """
    if report is None:
        report = ValidationReport()
    # Normalise to ibis once so every rule shares the same wrapped
    # table; the per-rule helpers also call ``to_ibis`` but it's a
    # pass-through on an ibis Table so we don't double-wrap.
    table = to_ibis(expr)
    for field in schema.fields:
        for rule in _RULE_ORDER:
            for issue in rule(table, field, engine=engine, table_name=table_name):
                report.add_issue(issue)
    return report
