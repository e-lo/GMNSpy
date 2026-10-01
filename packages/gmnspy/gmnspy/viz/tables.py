"""Server-side paged / sorted / filtered access to GMNS tables for the viewer.

The data-table exploration view browses the underlying GMNS tables (``link``,
``node``, …) beside the map. Paging, sorting and filtering happen here, on the
server, so the browser only ever holds one page — the same philosophy as the
binary network payload in :mod:`gmnspy.viz.buffers`.

The filter language (``[{"col", "op", "val"}, ...]``) is a small JSON predicate
spec, **never raw SQL**, compiled to column masks. It validates column and op
names (no injection surface) and maps cleanly onto the engine-agnostic datagrove
``Table.filter`` the day the viewer is handed a lazy ``Network`` instead of
materialized frames.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["table_list_entry", "table_schema", "page_table", "FilterError",
           "GEOM_COLS", "MAX_LIMIT"]

#: WKT geometry columns are huge; excluded from grid payloads (shown on the map).
GEOM_COLS = {"geometry", "geom", "wkt"}
#: Server-side cap on a single page.
MAX_LIMIT = 500

_OPS = {
    "eq": lambda s, v: s == v,
    "ne": lambda s, v: s != v,
    "lt": lambda s, v: s < v,
    "lte": lambda s, v: s <= v,
    "gt": lambda s, v: s > v,
    "gte": lambda s, v: s >= v,
    "in": lambda s, v: s.isin(v if isinstance(v, (list, tuple, set)) else [v]),
    "contains": lambda s, v: s.astype("string").str.contains(str(v), case=False, na=False),
    "isnull": lambda s, v: s.isna(),
    "notnull": lambda s, v: s.notna(),
}


class FilterError(ValueError):
    """An invalid filter spec (unknown column or operator)."""


def _scalar(v: Any) -> Any:
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return getattr(v, "item", lambda: v)()


def _column_kind(s: pd.Series) -> str:
    if s.name in GEOM_COLS:
        return "geom"
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_numeric_dtype(s):
        return "num"
    return "str"


def primary_key(name: str, columns: list[str]) -> str | None:
    """Best-effort primary key: ``<table>_id`` if present, else first ``*_id``."""
    cand = f"{name}_id"
    if cand in columns:
        return cand
    return next((c for c in columns if c.endswith("_id")), None)


def table_list_entry(name: str, df: pd.DataFrame) -> dict:
    return {"name": name, "rows": int(len(df)), "columns": list(df.columns)}


def table_schema(name: str, df: pd.DataFrame) -> dict:
    cols = [{"name": c, "dtype": str(df[c].dtype), "kind": _column_kind(df[c])} for c in df.columns]
    return {"name": name, "rows": int(len(df)), "primary_key": primary_key(name, list(df.columns)),
            "columns": cols}


def _apply_filter(df: pd.DataFrame, spec: list[dict]) -> pd.DataFrame:
    for cond in spec:
        col, op = cond.get("col"), cond.get("op")
        if col not in df.columns:
            raise FilterError(f"unknown column {col!r}")
        if op not in _OPS:
            raise FilterError(f"unknown operator {op!r}")
        df = df[_OPS[op](df[col], cond.get("val"))]
    return df


def page_table(df: pd.DataFrame, *, offset: int = 0, limit: int = 100, sort: str | None = None,
               direction: str = "asc", filter_spec: list[dict] | None = None,
               ids: list | None = None, pk: str | None = None) -> dict:
    """Return one page of ``df`` as compact column/row arrays (geometry excluded).

    Raises:
        FilterError: unknown filter column/operator, or unknown sort column.
    """
    if ids and pk and pk in df.columns:
        df = df[df[pk].isin(ids)]
    if filter_spec:
        df = _apply_filter(df, filter_spec)
    total = int(len(df))
    if sort:
        if sort not in df.columns:
            raise FilterError(f"unknown sort column {sort!r}")
        df = df.sort_values(sort, ascending=(direction != "desc"), kind="stable")
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    page = df.iloc[offset:offset + limit]
    cols = [c for c in page.columns if c not in GEOM_COLS]
    rows = [[_scalar(v) for v in rec] for rec in page[cols].itertuples(index=False, name=None)]
    return {"columns": cols, "rows": rows, "total": total, "offset": offset, "limit": limit}
