"""GMNS geometry on load — read the config encoding, convert geometry columns to WKB.

Canonical in-memory geometry is **WKB bytes** (geometry ADR, 2026-10-01). GMNS
declares the on-disk encoding in its ``config`` table via ``geometry_field_format``
+ ``crs`` (both typed ``any`` in the spec); packages that omit a config — most
CSV networks — default to ``WKT`` / ``EPSG:4326``. On load gmnspy converts any
WKT geometry column on the geometry-bearing tables to WKB exactly once (via
:func:`datagrove.dataset.geometry.encode_wkb`, which is idempotent on an already-
binary column), so every downstream consumer sees a single encoding regardless
of whether the source was CSV (WKT) or GeoParquet (WKB).

datagrove owns the *encoding mechanics*; this module owns the *GMNS policy* —
which tables carry geometry and what the config defaults are.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datagrove.dataset.geometry import WKT, decode_wkt, encode_wkb

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package

__all__ = [
    "DEFAULT_CRS",
    "convert_geometry_to_wkb",
    "decode_geometry_to_wkt",
    "geometry_encoding",
]

#: CRS assumed when a GMNS package declares none (gmnspy stays lon/lat-centric).
DEFAULT_CRS = "EPSG:4326"

#: GMNS tables that carry a ``geometry`` (WKT/WKB LINESTRING) column. ``link``
#: holds inline geometry; the ``geometry`` table holds shared geometries keyed
#: by ``geometry_id``.
_GEOMETRY_TABLES = ("link", "geometry")


def geometry_encoding(package: Package) -> tuple[str, str]:
    """Return ``(geometry_field_format, crs)`` from the GMNS ``config`` table.

    Reads the one-row ``config`` table when present (osm/overture importers stamp
    it; see :mod:`gmnspy._network_build`). Falls back to the GMNS-friendly
    defaults ``("WKT", "EPSG:4326")`` when there is no config or the fields are
    absent — the common case for a hand-authored CSV package.
    """
    fmt: str = WKT
    crs: str = DEFAULT_CRS
    config = package.tables.get("config")
    if config is not None:
        rows = config.expr.to_pyarrow().to_pylist()
        if rows:
            fmt = rows[0].get("geometry_field_format") or fmt
            crs = rows[0].get("crs") or crs
    return fmt, crs


def convert_geometry_to_wkb(package: Package) -> None:
    """Re-encode WKT geometry columns on the geometry-bearing tables as WKB, in place.

    Mutates ``package.tables`` so ``link.geometry`` and the ``geometry`` table's
    ``geometry`` column become WKB bytes. A no-op on tables without a geometry
    column and on columns already binary, so it is safe to call on any package
    (CSV or GeoParquet) and more than once.
    """
    for name in _GEOMETRY_TABLES:
        table = package.tables.get(name)
        if table is not None and "geometry" in table.columns():
            package.tables[name] = encode_wkb(table, column="geometry")


def decode_geometry_to_wkt(package: Package) -> None:
    """Render WKB geometry columns back to WKT in place — the inverse for CSV export.

    GMNS CSV must carry WKT text (geometry ADR: WKT on disk for CSV, WKB for
    Parquet). Callers writing a CSV container decode a throwaway copy of the
    package so the in-memory tables stay canonical WKB. A no-op on tables without
    a geometry column and on columns already text.
    """
    for name in _GEOMETRY_TABLES:
        table = package.tables.get(name)
        if table is not None and "geometry" in table.columns():
            package.tables[name] = decode_wkt(table, column="geometry")
