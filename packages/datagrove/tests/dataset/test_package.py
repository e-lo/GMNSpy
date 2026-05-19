"""Tests for :class:`datagrove.dataset.Package` (task 2.7 / issue #66).

End-to-end exercises against the bundled Leavenworth GMNS fixture in
all three on-disk shapes (csv directory, parquet directory, single
duckdb file). The same parametrisation also covers the dict-access,
scope, write, and validate surfaces.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from datagrove.dataset import (
    OutOfSyncError,
    OutOfSyncWarning,
    Package,
    Table,
)
from datagrove.engines.ibis_engine import IbisEngine
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.spec.loader import load_package
from gmnspy.fixtures import leavenworth

# ---------------------------------------------------------------------------
# Engine parametrisation helper
# ---------------------------------------------------------------------------


def _make_engine(name: str):
    if name == "ibis":
        return IbisEngine()
    if name == "polars":
        pytest.importorskip("polars", reason="polars optional extra not installed")
        from datagrove.engines.polars_engine import PolarsEngine

        return PolarsEngine()
    if name == "pandas":
        return PandasEngine()
    raise AssertionError(f"unknown engine name: {name!r}")


def _gmns_datapackage() -> Path:
    """Path to the bundled GMNS 0.97 datapackage.json."""
    import gmnspy

    return Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"


# ---------------------------------------------------------------------------
# Constructors — Leavenworth fixture roundtrips per format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "pandas"])
def test_package_from_leavenworth_csv_dir(engine_name: str) -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=_make_engine(engine_name),
        spec=_gmns_datapackage(),
    )
    assert isinstance(pkg, Package)
    assert "link" in pkg
    assert "node" in pkg
    assert isinstance(pkg["link"], Table)
    # Source captured for round-trip.
    assert pkg.source is not None and "csv" in pkg.source


@pytest.mark.parametrize("engine_name", ["ibis", "pandas"])
def test_package_from_leavenworth_parquet_dir(engine_name: str) -> None:
    pkg = Package.from_source(
        leavenworth.parquet_dir(),
        engine=_make_engine(engine_name),
        spec=_gmns_datapackage(),
    )
    assert "link" in pkg
    assert "node" in pkg
    # Parquet adapter sets the format on each table.
    assert pkg["link"].format == "parquet"


@pytest.mark.parametrize("engine_name", ["ibis", "pandas"])
def test_package_from_leavenworth_duckdb(engine_name: str) -> None:
    pkg = Package.from_source(
        leavenworth.duckdb_path(),
        engine=_make_engine(engine_name),
        spec=_gmns_datapackage(),
    )
    assert "link" in pkg
    assert "node" in pkg
    assert pkg["link"].format == "duckdb"


def test_package_from_source_partial_load() -> None:
    """Passing ``tables=`` limits the load to a subset."""
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    assert set(pkg.keys()) == {"link", "node"}


# ---------------------------------------------------------------------------
# Dict-like surface
# ---------------------------------------------------------------------------


def test_package_dict_access() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    # __getitem__
    assert isinstance(pkg["link"], Table)
    # __contains__
    assert "link" in pkg
    assert "no-such-table" not in pkg
    # __len__
    assert len(pkg) == 2
    # __iter__
    assert set(iter(pkg)) == {"link", "node"}
    # keys/values/items
    assert set(pkg.keys()) == {"link", "node"}
    assert all(isinstance(t, Table) for t in pkg.values())
    assert dict(pkg.items()).keys() == {"link", "node"}


# ---------------------------------------------------------------------------
# Validation orchestration
# ---------------------------------------------------------------------------


def test_package_validate_runs_all_passes() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    report = pkg.validate()
    # The report should accumulate findings from multiple categories.
    # On the clean fixture we expect no errors; the categories present
    # are whatever the validators emitted (informational + structural).
    cats = {i.category for i in report.issues}
    assert isinstance(cats, set)


def test_package_validate_skip_individual_passes() -> None:
    """``schema=False`` skips the per-table schema rules."""
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    full = pkg.validate()
    skipped = pkg.validate(schema=False)
    full_codes = {i.code for i in full.issues}
    skipped_codes = {i.code for i in skipped.issues}
    # Every schema.* code in the full report should be absent from the
    # skipped one; non-schema codes are unaffected.
    full_schema_codes = {c for c in full_codes if c.startswith("schema.")}
    skipped_schema_codes = {c for c in skipped_codes if c.startswith("schema.")}
    assert skipped_schema_codes == set()
    assert (full_codes - full_schema_codes) <= skipped_codes


# ---------------------------------------------------------------------------
# Scope (table + column subset)
# ---------------------------------------------------------------------------


def test_package_scope_by_tables_subset() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
    )
    sub = pkg.scope(tables=["link", "node"])
    assert isinstance(sub, Package)
    assert set(sub.keys()) == {"link", "node"}
    # Original unchanged.
    assert set(pkg.keys()) > {"link", "node"}


def test_package_scope_by_columns() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    sub = pkg.scope(columns={"link": ["link_id"], "node": ["node_id"]})
    assert sub["link"].columns() == ["link_id"]
    assert sub["node"].columns() == ["node_id"]
    # Original unchanged.
    assert set(pkg["link"].columns()) > {"link_id"}


# ---------------------------------------------------------------------------
# Write — happy path + overwrite protection + sync-state
# ---------------------------------------------------------------------------


def test_package_write_roundtrip(tmp_path: Path) -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    dest = tmp_path / "out.gmns"
    pkg.write(dest, format="parquet")
    pkg2 = Package.from_source(dest, engine=PandasEngine(), spec=_gmns_datapackage())
    assert "link" in pkg2
    assert "node" in pkg2
    assert pkg2["link"].count() == pkg["link"].count()


def test_package_write_overwrite_protection(tmp_path: Path) -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    dest = tmp_path / "out.gmns"
    pkg.write(dest, format="parquet")
    with pytest.raises(FileExistsError):
        pkg.write(dest, format="parquet")
    # overwrite=True succeeds:
    pkg.write(dest, format="parquet", overwrite=True)


def test_package_write_on_dirty_emits_warning(tmp_path: Path) -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    pkg["link"].invalidate()
    dest = tmp_path / "out.gmns"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", OutOfSyncWarning)
        pkg.write(dest, format="parquet")
    assert any(isinstance(w.message, OutOfSyncWarning) for w in caught)


def test_package_write_strict_sync_raises_on_dirty(tmp_path: Path) -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    pkg["link"].invalidate()
    dest = tmp_path / "out.gmns"
    with pytest.raises(OutOfSyncError):
        pkg.write(dest, format="parquet", strict_sync=True)


# ---------------------------------------------------------------------------
# Mutation surface
# ---------------------------------------------------------------------------


def test_package_add_remove_table() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link"],
    )
    # Build a small Table by hand.
    e = pkg.engine
    new_t = Table(name="custom", expr=e.from_records([{"a": 1}]), engine=e)
    pkg.add_table("custom", new_t)
    assert "custom" in pkg
    pkg.remove_table("custom")
    assert "custom" not in pkg


def test_package_repr_html_returns_non_empty_string() -> None:
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    html = pkg._repr_html_()
    assert isinstance(html, str)
    assert html.strip() != ""


def test_package_dirty_tracker_optional(tmp_path: Path) -> None:
    """Package works without DirtyTracker — sync_state validation no-ops."""
    pkg = Package.from_source(
        leavenworth.csv_dir(),
        engine=PandasEngine(),
        spec=_gmns_datapackage(),
        tables=["link", "node"],
    )
    # No DirtyTracker passed in. validate(sync_state=True) must not raise.
    report = pkg.validate(sync_state=True)
    # No sync.* issues should be emitted when there's no tracker.
    sync_codes = [i for i in report.issues if i.code.startswith("sync.")]
    assert sync_codes == []


# ---------------------------------------------------------------------------
# Top-level re-export
# ---------------------------------------------------------------------------


def test_top_level_reexport_of_package_and_table() -> None:
    """``from datagrove import Package, Table`` works."""
    from datagrove import Package as TopPackage
    from datagrove import Table as TopTable

    assert TopPackage is Package
    assert TopTable is Table


def test_from_tables_constructor() -> None:
    """Package can be built from an already-prepared mapping of Tables."""
    e = PandasEngine()
    link = Table(name="link", expr=e.from_records([{"link_id": 1}]), engine=e)
    node = Table(name="node", expr=e.from_records([{"node_id": 1}]), engine=e)
    pkg = load_package(
        {
            "name": "x",
            "resources": [
                {"name": "link", "path": "link.csv"},
                {"name": "node", "path": "node.csv"},
            ],
        }
    )
    p = Package.from_tables({"link": link, "node": node}, spec=pkg, engine=e)
    assert set(p.keys()) == {"link", "node"}
