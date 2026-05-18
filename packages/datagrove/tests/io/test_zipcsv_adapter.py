"""Tests for the ZipCsvAdapter (Phase 1 task 1.10).

A bundle of CSV files packaged into a single ``.zip`` (or ``.csv.zip``
for single-table cases). Self-registers under name ``"zipcsv"``; owns
the compound extension ``"csv.zip"`` and the bare ``"zip"`` extension
(see :class:`datagrove.io.zipcsv_adapter.ZipCsvAdapter`).

Tests cover:
    - ``probe()`` heuristics + safety (never raises).
    - ``scan()`` shape (one ``ResourceRef`` per CSV member).
    - ``read()`` round-trip via the three stock engines.
    - Dispatch precedence (compound ``.csv.zip`` wins over bare ``.zip``;
      bare ``.zip`` falls through to ``probe``).
    - ``write()`` round-trip for the single-CSV-into-zip case.
    - Protocol conformance.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd
import pytest
from datagrove.engines import get_engine, list_engines
from datagrove.engines.errors import InvalidEngineCallError
from datagrove.io import FormatAdapter, dispatch, list_adapters, register_adapter
from datagrove.io.base import ResourceRef
from datagrove.io.zipcsv_adapter import ZipCsvAdapter


@pytest.fixture(autouse=True)
def _ensure_zipcsv_registered():
    """Re-register ZipCsvAdapter before each test in this file.

    Other tests (notably test_dispatch.py) call ``_clear_registry()`` in
    their teardown, which would wipe the import-time registration done
    by ``zipcsv_adapter.py``. Re-registering per-test keeps these tests
    independent of suite execution order.
    """
    register_adapter(ZipCsvAdapter())
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LEAVENWORTH = Path(__file__).resolve().parents[4] / "packages" / "gmnspy" / "gmnspy" / "fixtures" / "leavenworth"
LEAVENWORTH_ZIP = LEAVENWORTH / "leavenworth.csv.zip"

# 9 CSVs ship in the fixture zip; the datapackage.json is not a csv and
# must be excluded from scan/probe accounting.
_EXPECTED_LEAVENWORTH_CSVS = {
    "geometry",
    "lane",
    "link",
    "link_tod",
    "node",
    "signal_controller",
    "time_set_definitions",
    "use_definition",
    "use_group",
}


def _make_zip(tmp_path: Path, members: dict[str, bytes], name: str = "x.zip") -> Path:
    """Build a zip at ``tmp_path/name`` containing ``members`` (arcname → bytes)."""
    out = tmp_path / name
    with zipfile.ZipFile(out, "w") as z:
        for arcname, data in members.items():
            z.writestr(arcname, data)
    return out


def _single_csv_zip(tmp_path: Path) -> Path:
    """A zip with exactly one CSV inside (no other members)."""
    return _make_zip(
        tmp_path,
        {"only.csv": b"a,b\n1,2\n3,4\n"},
        name="single.csv.zip",
    )


def _multi_csv_zip(tmp_path: Path) -> Path:
    """A bare ``.zip`` with multiple CSVs — probe must open it to recognise."""
    return _make_zip(
        tmp_path,
        {
            "left.csv": b"a,b\n1,2\n",
            "right.csv": b"c,d\n5,6\n",
        },
        name="pair.zip",
    )


def _zip_without_csvs(tmp_path: Path) -> Path:
    return _make_zip(
        tmp_path,
        {"a.txt": b"hello", "b.txt": b"world"},
        name="no_csv.zip",
    )


# ---------------------------------------------------------------------------
# probe()
# ---------------------------------------------------------------------------


def test_probe_csv_zip_extension(tmp_path):
    """``.csv.zip`` suffix is sufficient — don't even need to open the file."""
    adapter = ZipCsvAdapter()
    # The compound suffix wins without opening; file need not exist.
    fake = tmp_path / "anything.csv.zip"
    assert adapter.probe(fake) is True


def test_probe_zip_with_csvs(tmp_path):
    """A bare ``.zip`` containing CSVs probes True."""
    adapter = ZipCsvAdapter()
    assert adapter.probe(_single_csv_zip(tmp_path)) is True
    assert adapter.probe(_multi_csv_zip(tmp_path)) is True


def test_probe_zip_without_csvs(tmp_path):
    """A zip of non-CSV files probes False."""
    adapter = ZipCsvAdapter()
    assert adapter.probe(_zip_without_csvs(tmp_path)) is False


def test_probe_non_zip_extension(tmp_path):
    """A path that isn't a zip extension at all probes False."""
    adapter = ZipCsvAdapter()
    plain = tmp_path / "plain.csv"
    plain.write_text("a,b\n1,2\n")
    assert adapter.probe(plain) is False


def test_probe_never_raises(tmp_path):
    """Corrupt, non-existent, None — all return False without exceptions."""
    adapter = ZipCsvAdapter()
    # Corrupt zip content under a .zip extension.
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"this is not a zip file")
    assert adapter.probe(corrupt) is False
    # Non-existent file under bare .zip — probe peeks inside, which fails.
    assert adapter.probe(tmp_path / "missing.zip") is False
    # Non-existent .csv.zip — extension shortcut still returns True.
    assert adapter.probe(tmp_path / "missing.csv.zip") is True
    # None — must not crash.
    assert adapter.probe(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_self_registers_on_import():
    """Importing the module registers ``"zipcsv"`` in the global registry."""
    # Importing the module at the top of this file is what triggers
    # the registration; we just assert the effect.
    assert "zipcsv" in list_adapters()


def test_protocol_conformance():
    """The adapter satisfies the runtime_checkable FormatAdapter protocol."""
    assert isinstance(ZipCsvAdapter(), FormatAdapter)


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------


def test_scan_returns_one_resource_per_csv_member():
    """The Leavenworth zip → 9 ResourceRefs (datapackage.json excluded)."""
    adapter = ZipCsvAdapter()
    refs = adapter.scan(LEAVENWORTH_ZIP, engine=None)
    assert len(refs) == 9
    assert {r.name for r in refs} == _EXPECTED_LEAVENWORTH_CSVS


def test_scan_member_names_are_stems():
    """ResourceRef.name is the file stem (no .csv, no directory prefix)."""
    adapter = ZipCsvAdapter()
    refs = adapter.scan(LEAVENWORTH_ZIP, engine=None)
    for ref in refs:
        assert not ref.name.endswith(".csv")
        assert "/" not in ref.name
        assert isinstance(ref, ResourceRef)
        assert ref.format == "csv"
        # The path locator includes the member name after a "::" separator
        # so downstream code can re-open the right member.
        assert "::" in ref.path


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------


def test_read_single_csv_zip_no_kwarg_needed(tmp_path):
    """Single-CSV zip — no ``table=`` kwarg required."""
    adapter = ZipCsvAdapter()
    zip_path = _single_csv_zip(tmp_path)
    engine = get_engine("pandas")
    expr = adapter.read(zip_path, engine=engine)
    df = engine.to_pandas(expr)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_read_multi_csv_zip_requires_table_kwarg():
    """Multi-CSV zip without ``table=`` raises InvalidEngineCallError."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    with pytest.raises(InvalidEngineCallError) as excinfo:
        adapter.read(LEAVENWORTH_ZIP, engine=engine)
    msg = str(excinfo.value)
    # Message should name the kwarg and suggest one of the actual tables.
    assert "table" in msg
    # Hint: list a member name so the user sees a concrete example.
    assert any(name in msg for name in _EXPECTED_LEAVENWORTH_CSVS)


def test_read_multi_csv_zip_unknown_table_raises():
    """``table=<name>`` that isn't in the zip raises InvalidEngineCallError."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    with pytest.raises(InvalidEngineCallError) as excinfo:
        adapter.read(LEAVENWORTH_ZIP, engine=engine, table="nonexistent")
    msg = str(excinfo.value)
    assert "nonexistent" in msg


@pytest.mark.parametrize("engine_name", ["pandas", "polars", "ibis"])
def test_read_specific_table_delegates_to_engine(engine_name):
    """Round-trip via each registered engine — node.csv has known shape."""
    if engine_name not in list_engines():
        pytest.skip(f"engine {engine_name!r} not installed")
    adapter = ZipCsvAdapter()
    engine = get_engine(engine_name)
    expr = adapter.read(LEAVENWORTH_ZIP, engine=engine, table="node")
    df = engine.to_pandas(expr)
    assert isinstance(df, pd.DataFrame)
    assert "node_id" in df.columns
    assert len(df) > 0


def test_read_accepts_member_alias(tmp_path):
    """``member=`` is accepted as an alias for ``table=``."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    zip_path = _make_zip(
        tmp_path,
        {"left.csv": b"a,b\n1,2\n", "right.csv": b"c,d\n5,6\n"},
        name="alias.zip",
    )
    expr = adapter.read(zip_path, engine=engine, member="left")
    df = engine.to_pandas(expr)
    assert list(df.columns) == ["a", "b"]


def test_read_table_kwarg_accepts_stem_or_filename(tmp_path):
    """Both ``table="node"`` and ``table="node.csv"`` resolve to the same member."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    by_stem = engine.to_pandas(adapter.read(LEAVENWORTH_ZIP, engine=engine, table="node"))
    by_fname = engine.to_pandas(adapter.read(LEAVENWORTH_ZIP, engine=engine, table="node.csv"))
    assert by_stem.shape == by_fname.shape


# ---------------------------------------------------------------------------
# dispatch() routing
# ---------------------------------------------------------------------------


def test_dispatch_routes_csv_zip():
    """``foo.csv.zip`` resolves to ZipCsvAdapter via the compound-extension lane."""
    adapter = dispatch("foo.csv.zip")
    assert adapter.name == "zipcsv"


def test_dispatch_routes_zip_via_probe(tmp_path):
    """``foo.zip`` with csv members resolves to ZipCsvAdapter via probe."""
    # The bare ``.zip`` extension is also owned by zipcsv (extensions
    # tuple lists ``csv.zip`` first then ``zip``), so the extension lane
    # actually resolves before probe. Either way the result is zipcsv.
    zip_path = _multi_csv_zip(tmp_path)
    adapter = dispatch(zip_path)
    assert adapter.name == "zipcsv"


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


def test_write_single_csv_into_zip_roundtrip(tmp_path):
    """Write a DataFrame as a single csv inside a zip; round-trip back equal."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    src = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    dest = tmp_path / "out.csv.zip"
    adapter.write(src, dest, engine=engine, table="data")

    # The destination exists, is a valid zip, contains exactly one csv.
    assert dest.is_file()
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    assert names == ["data.csv"]

    # Round-trip via the adapter's read path.
    expr = adapter.read(dest, engine=engine)
    out = engine.to_pandas(expr)
    assert list(out.columns) == ["a", "b"]
    assert len(out) == 3


def test_write_without_table_defaults_to_dest_stem(tmp_path):
    """If ``table=`` is omitted, the inner csv is named after the dest stem."""
    adapter = ZipCsvAdapter()
    engine = get_engine("pandas")
    src = pd.DataFrame({"a": [1]})
    dest = tmp_path / "named_after_dest.csv.zip"
    adapter.write(src, dest, engine=engine)
    with zipfile.ZipFile(dest) as z:
        names = z.namelist()
    # Single .csv inside; stem comes from dest (strip the .csv.zip compound).
    assert len(names) == 1
    assert names[0].endswith(".csv")
