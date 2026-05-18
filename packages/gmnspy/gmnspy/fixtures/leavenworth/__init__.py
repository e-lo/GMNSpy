"""Tiny example GMNS network for Leavenworth, WA. See README.md for provenance."""

from pathlib import Path

ROOT = Path(__file__).parent
DATAPACKAGE = ROOT / "datapackage.json"


def csv_dir() -> Path:
    """Directory containing the canonical CSV form of the fixture."""
    return ROOT / "csv"


def parquet_dir() -> Path:
    """Directory containing the per-table Parquet form of the fixture."""
    return ROOT / "parquet"


def duckdb_path() -> Path:
    """Path to the single-file DuckDB form of the fixture."""
    return ROOT / "leavenworth.duckdb"


def zip_path() -> Path:
    """Path to the zipped-CSV form of the fixture."""
    return ROOT / "leavenworth.csv.zip"


# Once gmnspy.read() and the Network class land (Phase 3) a load() shortcut
# returning a fully-typed Network will live here.
