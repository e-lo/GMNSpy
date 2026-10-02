"""WKT <-> WKB geometry re-encoding on a :class:`~datagrove.dataset.table.Table`.

Canonical in-memory geometry is **WKB bytes** (geometry ADR, 2026-10-01):
spatial ops decode it on the fly, Parquet stores it directly (GeoParquet), and a
WKB blob column round-trips through Arrow cleanly (unlike duckdb's ``GEOMETRY``
type). This module owns the *mechanics* of that encoding; the domain layer
(gmnspy) decides which column is geometry and in which CRS, and calls these.

- :func:`encode_wkb` — WKT *string* column → WKB bytes, at ingest.
- :func:`decode_wkt` — WKB bytes column → WKT string, for CSV export.

Both compile to duckdb spatial builtins through ibis (``ST_GeomFromText`` /
``ST_AsWKB`` / ``ST_GeomFromWKB`` / ``ST_AsText``) — no shapely, no geopandas, no
pandas round-trip, and the op stays lazy on the duckdb backend. Each is
**idempotent by dtype**: :func:`encode_wkb` skips a column that is already binary
and :func:`decode_wkt` skips one that is already text, so loading GeoParquet
(already WKB) and CSV (WKT) both converge on WKB without the caller tracking
provenance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ibis.expr.datatypes as dt
from ibis import udf

# Reuse the cached spatial-extension loader and backend probe from the sibling
# scope module rather than duplicating them; ST_GeomFromText is also defined
# there, so we import it instead of re-registering the same builtin name.
from .view import _ensure_spatial, _ibis_backend_of
from .view import _st_geom_from_text as _geom_from_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .table import Table

__all__ = ["WKB", "WKT", "decode_wkt", "encode_wkb"]

#: Canonical values for the GMNS config ``geometry_field_format`` field.
WKT = "WKT"
WKB = "WKB"


@udf.scalar.builtin(name="ST_AsWKB")
def _as_wkb(geom: dt.binary) -> dt.binary:  # type: ignore[empty-body]
    """Serialize a duckdb GEOMETRY to its WKB byte string."""


@udf.scalar.builtin(name="ST_GeomFromWKB")
def _geom_from_wkb(wkb: dt.binary) -> dt.binary:  # type: ignore[empty-body]
    """Parse WKB bytes into a duckdb GEOMETRY."""


@udf.scalar.builtin(name="ST_AsText")
def _as_text(geom: dt.binary) -> str:  # type: ignore[empty-body]
    """Render a duckdb GEOMETRY as WKT text."""


def _spatial_expr(table: Table):
    """Return ``table``'s ibis expr with the duckdb spatial extension loaded.

    Uses the table's own duckdb backend when the expr is ibis-native (the ingest
    path); otherwise binds through the default duckdb backend that ``ibis``
    memtables resolve to. Either way the geometry op stays a lazy projection.
    """
    from datagrove.validation._ibis import to_ibis

    backend = _ibis_backend_of(table)
    if backend is not None:
        _ensure_spatial(backend)
        return table.expr
    expr = to_ibis(table.expr)
    _ensure_spatial(expr._find_backend(use_default=True))
    return expr


def encode_wkb(table: Table, column: str = "geometry") -> Table:
    """Return ``table`` with WKT string ``column`` re-encoded as WKB bytes.

    No-op when the column is absent or already binary (WKB) — so calling it on a
    GeoParquet-sourced table, or twice, is harmless. The conversion is a lazy
    ``ST_AsWKB(ST_GeomFromText(column))`` projection on the duckdb backend.
    """
    if column not in table.columns():
        return table
    if not table.expr[column].type().is_string():
        return table  # already binary → treated as WKB; idempotent
    expr = _spatial_expr(table)
    return table._derived(expr.mutate(**{column: _as_wkb(_geom_from_text(expr[column]))}))


def decode_wkt(table: Table, column: str = "geometry") -> Table:
    """Return ``table`` with WKB bytes ``column`` rendered back to WKT text.

    The inverse of :func:`encode_wkb`, for CSV export. No-op when the column is
    absent or already a string. Lazy ``ST_AsText(ST_GeomFromWKB(column))``.
    """
    if column not in table.columns():
        return table
    if not table.expr[column].type().is_binary():
        return table  # already text → nothing to decode
    expr = _spatial_expr(table)
    return table._derived(expr.mutate(**{column: _as_text(_geom_from_wkb(expr[column]))}))
