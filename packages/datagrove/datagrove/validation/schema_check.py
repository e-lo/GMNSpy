"""Schema validator — per-field Frictionless constraint checks (task 2.3 / issue #62).

This module is the **schema** half of the datagrove validation layer.
It takes a table expression (from any engine — ibis, polars, pandas)
plus a parsed Frictionless :class:`~datagrove.spec.model.Schema` and
emits :class:`~datagrove.reports.Issue` records — one per
field-level violation — into a :class:`~datagrove.reports.ValidationReport`.

Cross-engine strategy (read this — Lens C trade-off)
----------------------------------------------------

The Engine protocol exposes three lazy table representations
(``ibis.expr.types.Table``, ``polars.LazyFrame``, ``pandas.DataFrame``)
with no common filter/aggregate dialect across all three. Rather than
write per-engine specialisations of every rule, we materialise once via
:meth:`Engine.to_pandas` and run the rules on the resulting
nullable-dtype DataFrame.

This is a deliberate **legibility-over-engine-specialisation** trade
(Lens C). The architecture promises lazy by default — and we still are,
because the schema check is a terminal operation in the validation
pipeline. Materialising at that boundary is the right place to spend
the memory.

The bounded-materialisation knob is on the *enumeration* side: the v0.3
bug was emitting one Issue per row for million-row failures. We cap
per-rule enumeration at :data:`MAX_ROW_ISSUES` and add one summary
issue when the count exceeds it.

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
bug. The module shape here makes each of those structurally impossible:
no rule uses ``if <Series>:`` semantics, the report classifies issues
by their own ``severity`` (not by re-filtering a single mixed list),
and pattern checks enumerate failing rows via boolean indexing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

from datagrove.reports import Category, Issue, Severity, ValidationReport

if TYPE_CHECKING:  # pragma: no cover - typing only
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


# ---------------------------------------------------------------------------
# Frictionless type → pandas-nullable dtype check
# ---------------------------------------------------------------------------

# The cross-engine ``to_pandas`` contract returns numpy-backed nullable
# dtypes — Int64 / Float64 / string / boolean. This map says, for a
# given Frictionless ``type`` name, which pandas dtype name(s) are
# acceptable. A column whose dtype is not in this set fires
# ``schema.type``. Frictionless types not listed here (``date``,
# ``time``, ``object`` etc.) are skipped — the cross-engine type-map
# parity test in the engines tree gates the keyset.
_FRICTIONLESS_TO_PANDAS: dict[str, frozenset[str]] = {
    "integer": frozenset({"Int64", "Int32", "int64", "int32"}),
    "number": frozenset({"Float64", "Float32", "float64", "float32", "Int64", "int64"}),
    "boolean": frozenset({"boolean", "bool"}),
    "string": frozenset({"string", "object"}),
    # ``any`` is the GMNS escape hatch — every dtype is acceptable.
    "any": frozenset(),
}


def _is_required(field: Field) -> bool:
    """Return ``True`` when ``field.constraints.required`` is ``True``."""
    return bool(field.constraints and field.constraints.required)


def _bound_severity(field: Field) -> Severity:
    """Pick the severity for a bound-style rule (min/max/length).

    Required fields elevate bound violations to ERROR. The rationale:
    a required field's contract is already strict; an out-of-range
    value isn't a "maybe-legal-in-a-future-spec" gray area, it's a
    fully-broken row.
    """
    return Severity.ERROR if _is_required(field) else Severity.WARNING


def _materialise(engine: Engine, expr: TableExpr) -> pd.DataFrame:
    """Materialise ``expr`` via the engine's cross-engine to_pandas contract.

    All per-rule helpers go through this single point so the choice of
    materialisation strategy lives in exactly one place. If ``expr`` is
    already a pandas DataFrame, returns it unchanged (used by
    :func:`check_schema` to avoid re-materialising for every rule).
    """
    if isinstance(expr, pd.DataFrame):
        return expr
    return engine.to_pandas(expr)


def _column_or_none(df: pd.DataFrame, name: str) -> pd.Series | None:
    """Return the named column or ``None`` if it isn't in the frame.

    Missing columns are a *structural* problem, not a *schema* problem
    (task 2.5 owns that). Schema rules silently skip absent fields so
    a partial dataset doesn't produce dozens of misleading findings.
    """
    if name in df.columns:
        return cast(pd.Series, df[name])
    return None


def _row_indices(mask: pd.Series) -> list[int]:
    """Return integer row indices where ``mask`` is True.

    ``Index.tolist()`` is typed as ``list[Hashable]`` in the pandas
    stubs (the index could legally hold tuples), but in practice every
    frame we receive here has a default ``RangeIndex``. Casting the
    intermediate through ``list[Any]`` lets the type-checker accept
    ``int(i)`` without resorting to per-call ``# type: ignore``.
    """
    selected = cast(pd.Series, mask[mask])
    raw: list[Any] = list(selected.index)
    return [int(i) for i in raw]


def _row_value_pairs(col: pd.Series, mask: pd.Series) -> list[tuple[int, Any]]:
    """Return ``(row_index, value)`` pairs from ``col`` where ``mask`` is True.

    Mirrors :func:`_row_indices` but also carries the offending value
    so per-row Issues can name it. Same Hashable-index caveat applies.
    """
    selected = cast(pd.Series, mask[mask])
    raw: list[Any] = list(selected.index)
    return [(int(i), col.loc[i]) for i in raw]


# ---------------------------------------------------------------------------
# Per-rule helpers
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
    truthy — non-required fields are exempt by definition.

    Per-row Issues are emitted up to :data:`MAX_ROW_ISSUES`; beyond
    that a single summary Issue records the total count.

    Args:
        expr: Engine-native table expression OR a pre-materialised
            pandas DataFrame (when called from :func:`check_schema`).
        field: The :class:`~datagrove.spec.model.Field` to check.
        engine: The engine that produced ``expr``. Used only for
            materialisation.
        table_name: Logical name of the table — populates ``Issue.table``.

    Returns:
        A list of :class:`Issue` records. Empty when the field is not
        required, absent from ``expr``, or has no nulls.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": 1}, {"x": None}])
        >>> f = Field(name="x", type="integer", constraints=Constraints(required=True))
        >>> issues = check_required(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.required'
        >>> issues[0].row
        1
    """
    if not _is_required(field):
        return []
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    null_mask = col.isna()
    null_rows = _row_indices(null_mask)
    if not null_rows:
        return []
    issues: list[Issue] = []
    for row in null_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.required",
                message=f"{table_name}.{field.name} row {row}: required field is null",
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Set {table_name}.{field.name} row {row} to a non-null value.",
            )
        )
    if len(null_rows) > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.required",
                message=(
                    f"{table_name}.{field.name}: {len(null_rows)} required values are null "
                    f"(showing first {MAX_ROW_ISSUES})"
                ),
                table=table_name,
                column=field.name,
                extra={"total_violations": len(null_rows)},
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
    """Flag a column whose pandas dtype doesn't match ``field.type``.

    The check is at the *column* level — pandas (and the engines that
    materialise through it) doesn't carry per-cell dtypes. A
    non-coercible value forces the whole column to ``object``, which
    won't match e.g. ``integer`` and so fires here. Frictionless types
    not in :data:`_FRICTIONLESS_TO_PANDAS` (or ``any``) are skipped.

    Args:
        expr: Engine-native table expression.
        field: The field to check.
        engine: The engine that produced ``expr``.
        table_name: Logical table name.

    Returns:
        A list containing zero or one :class:`Issue`.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"n": "x"}, {"n": "y"}])
        >>> issues = check_type(expr, Field(name="n", type="integer"), engine=e, table_name="t")
        >>> issues[0].code
        'schema.type'
    """
    if not field.type:
        return []
    allowed = _FRICTIONLESS_TO_PANDAS.get(field.type)
    if allowed is None or len(allowed) == 0:
        # Unknown type OR "any" — nothing to check at the dtype level.
        return []
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    actual = str(col.dtype)
    if actual in allowed:
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
    """Flag values that are not in the declared ``constraints.enum``.

    Null values are skipped (handled by :func:`check_required`).

    Args:
        expr: Engine-native table expression.
        field: The field to check.
        engine: The engine that produced ``expr``.
        table_name: Logical table name.

    Returns:
        Per-row :class:`Issue` records (capped at :data:`MAX_ROW_ISSUES`).

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": "a"}, {"x": "z"}])
        >>> f = Field(name="x", type="string", constraints=Constraints(enum=["a", "b"]))
        >>> issues = check_enum(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.enum'
    """
    if not field.constraints or not field.constraints.enum:
        return []
    allowed = list(field.constraints.enum)
    allowed_set = set(allowed)
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    # Drop nulls so the membership check doesn't fire schema.required noise.
    non_null = col.dropna()
    bad_mask = ~non_null.isin(allowed_set)
    bad_rows = _row_value_pairs(non_null, bad_mask)
    if not bad_rows:
        return []
    issues: list[Issue] = []
    allowed_str = ", ".join(repr(v) for v in allowed)
    for row, value in bad_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.enum",
                message=(f"{table_name}.{field.name} row {row}: value {value!r} not in enum [{allowed_str}]"),
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Use one of: {', '.join(str(v) for v in allowed)}.",
            )
        )
    if len(bad_rows) > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.enum",
                message=(
                    f"{table_name}.{field.name}: {len(bad_rows)} values outside enum (showing first {MAX_ROW_ISSUES})"
                ),
                table=table_name,
                column=field.name,
                extra={"total_violations": len(bad_rows), "allowed": allowed},
            )
        )
    return issues


def _check_numeric_bound(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
    bound: Any,
    code: str,
    direction: str,
) -> list[Issue]:
    """Shared body for :func:`check_minimum` and :func:`check_maximum`.

    Args:
        expr: Engine-native table expression or pre-materialised frame.
        field: The :class:`~datagrove.spec.model.Field` to check.
        engine: The engine that produced ``expr`` (used for materialisation).
        table_name: Logical name of the table (populates ``Issue.table``).
        bound: Numeric bound from ``field.constraints``.
        code: One of ``"schema.minimum"`` / ``"schema.maximum"``.
        direction: Either ``"below"`` (minimum) or ``"above"`` (maximum).
    """
    if bound is None:
        return []
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    # Coerce to numeric so we can compare; non-numeric entries become NaN
    # and are excluded (they're a schema.type concern).
    numeric = pd.to_numeric(col, errors="coerce")
    if direction == "below":
        bad_mask = numeric < bound
        rel = "below minimum"
        fix_word = "above"
    else:
        bad_mask = numeric > bound
        rel = "above maximum"
        fix_word = "below"
    bad_mask = bad_mask.fillna(False)
    bad_rows = _row_value_pairs(col, bad_mask)
    if not bad_rows:
        return []
    severity = _bound_severity(field)
    issues: list[Issue] = []
    for row, value in bad_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=(f"{table_name}.{field.name} row {row}: value {value} {rel} {bound}"),
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Set {table_name}.{field.name} to a value {fix_word} {bound}.",
            )
        )
    if len(bad_rows) > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=(
                    f"{table_name}.{field.name}: {len(bad_rows)} values {rel} {bound} (showing first {MAX_ROW_ISSUES})"
                ),
                table=table_name,
                column=field.name,
                extra={"total_violations": len(bad_rows), "bound": bound},
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
    """Flag values strictly below ``field.constraints.minimum``.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": 5}, {"x": -1}])
        >>> f = Field(name="x", type="number", constraints=Constraints(minimum=0))
        >>> issues = check_minimum(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.minimum'
    """
    if not field.constraints:
        return []
    return _check_numeric_bound(
        expr,
        field,
        engine=engine,
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
    """Flag values strictly above ``field.constraints.maximum``.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": 5}, {"x": 999}])
        >>> f = Field(name="x", type="number", constraints=Constraints(maximum=100))
        >>> issues = check_maximum(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.maximum'
    """
    if not field.constraints:
        return []
    return _check_numeric_bound(
        expr,
        field,
        engine=engine,
        table_name=table_name,
        bound=field.constraints.maximum,
        code="schema.maximum",
        direction="above",
    )


def _check_length_bound(
    expr: TableExpr,
    field: Field,
    *,
    engine: Engine,
    table_name: str,
    bound: int | None,
    code: str,
    direction: str,
) -> list[Issue]:
    """Shared body for :func:`check_min_length` / :func:`check_max_length`.

    Args:
        expr: Engine-native table expression or pre-materialised frame.
        field: The :class:`~datagrove.spec.model.Field` to check.
        engine: The engine that produced ``expr`` (used for materialisation).
        table_name: Logical name of the table (populates ``Issue.table``).
        bound: Integer character-length bound from ``field.constraints``.
        code: One of ``"schema.min_length"`` / ``"schema.max_length"``.
        direction: Either ``"below"`` (min_length) or ``"above"`` (max_length).
    """
    if bound is None:
        return []
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    lengths = col.dropna().astype(str).str.len()
    if direction == "below":
        bad_mask = lengths < bound
        rel = f"shorter than min_length {bound}"
        fix_word = "at least"
    else:
        bad_mask = lengths > bound
        rel = f"longer than max_length {bound}"
        fix_word = "no more than"
    bad_rows = [(int(i), col.loc[i]) for i in _row_indices(bad_mask)]
    if not bad_rows:
        return []
    severity = _bound_severity(field)
    issues: list[Issue] = []
    for row, value in bad_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=(f"{table_name}.{field.name} row {row}: value {value!r} ({len(str(value))} chars) {rel}"),
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Use a value {fix_word} {bound} characters in {table_name}.{field.name}.",
            )
        )
    if len(bad_rows) > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=severity,
                category=Category.SCHEMA,
                code=code,
                message=(f"{table_name}.{field.name}: {len(bad_rows)} values {rel} (showing first {MAX_ROW_ISSUES})"),
                table=table_name,
                column=field.name,
                extra={"total_violations": len(bad_rows), "bound": bound},
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
    """Flag strings shorter than ``field.constraints.min_length``.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": "abc"}, {"x": "z"}])
        >>> f = Field(name="x", type="string", constraints=Constraints(min_length=2))
        >>> issues = check_min_length(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.min_length'
    """
    if not field.constraints:
        return []
    return _check_length_bound(
        expr,
        field,
        engine=engine,
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
    """Flag strings longer than ``field.constraints.max_length``.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": "abc"}, {"x": "abcdef"}])
        >>> f = Field(name="x", type="string", constraints=Constraints(max_length=4))
        >>> issues = check_max_length(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.max_length'
    """
    if not field.constraints:
        return []
    return _check_length_bound(
        expr,
        field,
        engine=engine,
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

    Uses :func:`re.fullmatch` so the pattern must match the entire
    value (Frictionless semantics). Null values are skipped.

    This is the regression site for the v0.3 ``~s.str.contains(...)``
    bool-of-Series bug — we iterate the boolean mask explicitly rather
    than relying on Python's truthiness of a Series.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": "abc"}, {"x": "@@@"}])
        >>> f = Field(name="x", type="string", constraints=Constraints(pattern=r"^[a-z]+$"))
        >>> issues = check_pattern(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.pattern'
    """
    if not field.constraints or not field.constraints.pattern:
        return []
    pattern = field.constraints.pattern
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return [
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.pattern",
                message=(f"{table_name}.{field.name}: invalid regex {pattern!r} in schema ({e})"),
                table=table_name,
                column=field.name,
                fix_hint=f"Fix the regex declared on {table_name}.{field.name}.",
            )
        ]
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    non_null = col.dropna().astype(str)
    # ``.items()`` is typed (idx: Hashable, value: Any). Coerce both
    # through Any so pyright accepts the int() conversion below — the
    # default RangeIndex makes every i an int at runtime.
    items: list[tuple[Any, Any]] = list(non_null.items())
    bad_rows = [(int(i), v) for i, v in items if regex.fullmatch(v) is None]
    if not bad_rows:
        return []
    issues: list[Issue] = []
    for row, value in bad_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.pattern",
                message=(f"{table_name}.{field.name} row {row}: value {value!r} does not match pattern {pattern!r}"),
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Make {table_name}.{field.name} match the regex {pattern!r}.",
            )
        )
    if len(bad_rows) > MAX_ROW_ISSUES:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                category=Category.SCHEMA,
                code="schema.pattern",
                message=(
                    f"{table_name}.{field.name}: {len(bad_rows)} values fail pattern "
                    f"{pattern!r} (showing first {MAX_ROW_ISSUES})"
                ),
                table=table_name,
                column=field.name,
                extra={"total_violations": len(bad_rows), "pattern": pattern},
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
    ``required`` constraint handles nulls).

    This is the regression site for the v0.3 ``_unique_constraint``
    bug (``if s.dropna().duplicated(): ...`` on a Series). We use
    ``.any()`` on the mask explicitly and enumerate offending values.

    Emits one summary Issue (with the duplicate count) plus per-row
    Issues for each duplicate (capped at :data:`MAX_ROW_ISSUES`).

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.spec.model import Field, Constraints
        >>> e = PandasEngine()
        >>> expr = e.from_records([{"x": 1}, {"x": 1}])
        >>> f = Field(name="x", type="integer", constraints=Constraints(unique=True))
        >>> issues = check_unique(expr, f, engine=e, table_name="t")
        >>> issues[0].code
        'schema.unique'
    """
    if not field.constraints or not field.constraints.unique:
        return []
    df = _materialise(engine, expr)
    col = _column_or_none(df, field.name)
    if col is None:
        return []
    non_null = col.dropna()
    duplicated_mask = non_null.duplicated(keep=False)
    # ``.any()`` returns a scalar bool — explicitly NOT ``if duplicated_mask:``
    # (the v0.3 bug). Pin this regression structurally.
    if not bool(duplicated_mask.any()):
        return []
    dup_rows = _row_value_pairs(non_null, duplicated_mask)
    duplicate_count = len(dup_rows)
    issues: list[Issue] = [
        Issue(
            severity=Severity.ERROR,
            category=Category.SCHEMA,
            code="schema.unique",
            message=f"{table_name}.{field.name}: {duplicate_count} duplicate values",
            table=table_name,
            column=field.name,
            fix_hint=f"Remove or de-duplicate values in {table_name}.{field.name}.",
            extra={"total_violations": duplicate_count},
        )
    ]
    for row, value in dup_rows[:MAX_ROW_ISSUES]:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                category=Category.SCHEMA,
                code="schema.unique",
                message=(f"{table_name}.{field.name} row {row}: duplicate value {value!r}"),
                table=table_name,
                column=field.name,
                row=row,
                fix_hint=f"Make {table_name}.{field.name} unique at row {row}.",
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

    The frame is materialised **once** (via :meth:`Engine.to_pandas`)
    and shared across every rule — the per-rule helpers accept either a
    ``TableExpr`` or an already-materialised pandas DataFrame so calling
    this orchestrator is strictly cheaper than calling each helper
    individually.

    Args:
        expr: Engine-native lazy table expression to validate.
        schema: Parsed Frictionless :class:`~datagrove.spec.model.Schema`.
        engine: The :class:`~datagrove.engines.base.Engine` that produced
            ``expr``. Used for materialisation.
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
    # Materialise once so every rule shares the same frame. Skip when
    # the caller hands us a DataFrame directly (test convenience).
    df = expr if isinstance(expr, pd.DataFrame) else engine.to_pandas(expr)
    for field in schema.fields:
        for rule in _RULE_ORDER:
            for issue in rule(df, field, engine=engine, table_name=table_name):
                report.add_issue(issue)
    return report
