"""Tiny generic Frictionless data package — datagrove's own doctest fixture.

Bundled inside the datagrove wheel — no download needed. Used by
datagrove's doctests so the engine surface can demonstrate itself
without importing any *domain* package (notably gmnspy). The shape is
deliberately non-transportation (books / authors / venues) to make the
composition boundary visible: a developer reading
``datagrove.Package.from_source.__doc__`` should see that datagrove is a
generic engine, not a GMNS tool.

What's in it
------------
- 3 tables: ``author`` (5 rows), ``venue`` (4 rows), ``book`` (10 rows).
- 2 foreign-key relationships: ``book.author_id -> author.id`` and
  ``book.venue_id -> venue.id`` — exercises the FK validator without
  any GMNS-specific resolution rules.
- 1 WKT geometry column on ``venue.geometry`` (EPSG:4326 POINTs at
  real bookstores around the world) — exercises the spatial-scope view
  helpers (``from_bbox``, ``from_polygon``, ``from_geometry_buffer``).
- ~1 MB total across CSV + Parquet + DuckDB variants (most of that is
  the duckdb file's fixed-size header — the actual row payload is tiny).

Three storage variants
----------------------
All variants hold the **same data**; they exist so format adapters can
roundtrip and assert equality.

- :func:`csv_dir`       — one CSV per table (most readable on disk)
- :func:`parquet_dir`   — one Parquet per table (smallest + fastest)
- :func:`duckdb_path`   — single-file DuckDB database (lets the
  :class:`~datagrove.io.DuckdbAdapter` doctests exercise scan / read
  against a real on-disk file).

Plus :data:`DATAPACKAGE` for the Frictionless ``datapackage.json``
manifest and :data:`ROOT` for the on-disk parent directory.

Why a separate fixture (not the downstream Leavenworth one)
-----------------------------------------------------------
``gmnspy.fixtures.leavenworth`` is a GMNS network, owned by the
downstream gmnspy package. datagrove has a hard architectural
boundary against importing the downstream package (enforced by
import-linter contract "datagrove must not depend on gmnspy"), so
datagrove's own doctests need their own bundled data. This fixture
is that data — small, generic, with no transportation semantics.

Quick use
---------

.. code-block:: python

    from datagrove.fixtures import sample
    from datagrove import read

    print(sample.summary())             # prints what's in the fixture
    pkg = read(sample.csv_dir())        # returns a datagrove.Package
    pkg["book"].count()                 # -> 10
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "DATAPACKAGE",
    "ROOT",
    "csv_dir",
    "datapackage_path",
    "duckdb_path",
    "parquet_dir",
    "summary",
]

ROOT = Path(__file__).parent
DATAPACKAGE = ROOT / "datapackage.json"

# Static metadata about the bundled fixture. Update whenever the
# fixture is regenerated.
_FIXTURE_INFO = {
    "name": "datagrove-sample-books",
    "description": "Generic 3-table books fixture (author + venue + book) with FKs and WKT geometry",
    "tables": {
        "author": 5,
        "venue": 4,
        "book": 10,
    },
    "foreign_keys": [
        "book.author_id -> author.id",
        "book.venue_id -> venue.id",
    ],
}


def csv_dir() -> Path:
    """Directory containing the canonical CSV form of the fixture."""
    return ROOT / "csv"


def parquet_dir() -> Path:
    """Directory containing the per-table Parquet form of the fixture."""
    return ROOT / "parquet"


def duckdb_path() -> Path:
    """Path to the single-file DuckDB form of the fixture."""
    return ROOT / "sample.duckdb"


def datapackage_path() -> Path:
    """Path to the fixture's ``datapackage.json`` (the resolved Frictionless spec).

    Convenience alias for :data:`DATAPACKAGE` — exists so the
    documented form ``sample.datapackage_path()`` works without
    callers having to know whether to use the function or the
    constant. Both return the same path.

    Examples:
        >>> from datagrove.fixtures import sample
        >>> sample.datapackage_path() == sample.DATAPACKAGE
        True
    """
    return DATAPACKAGE


def summary() -> str:
    """Return a human-readable multi-line description of the fixture.

    Useful in interactive sessions where ``print(sample)`` only shows
    the module path. Call ``sample.summary()`` instead to see what's
    actually in the fixture without opening the README.

    Examples:
        >>> from datagrove.fixtures import sample
        >>> print(sample.summary())              # doctest: +ELLIPSIS
        datagrove sample fixture — books / authors / venues
        ...
    """
    lines = [
        "datagrove sample fixture — books / authors / venues",
        f"  name        : {_FIXTURE_INFO['name']}",
        f"  description : {_FIXTURE_INFO['description']}",
        "  tables      :",
    ]
    for name, count in _FIXTURE_INFO["tables"].items():
        lines.append(f"    {name:<10} {count:>3} rows")
    lines.append("  foreign keys:")
    for fk in _FIXTURE_INFO["foreign_keys"]:
        lines.append(f"    {fk}")
    lines.extend(
        [
            "",
            "Storage variants (all hold the same data):",
            f"  csv_dir()           -> {csv_dir()}",
            f"  parquet_dir()       -> {parquet_dir()}",
            f"  duckdb_path()       -> {duckdb_path()}",
            f"  datapackage_path()  -> {datapackage_path()}",
        ]
    )
    return "\n".join(lines)
