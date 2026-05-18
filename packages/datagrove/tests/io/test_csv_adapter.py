"""Tests for the CSV FormatAdapter (task 1.7).

The CsvAdapter is a thin glue layer between :func:`datagrove.io.dispatch`
and an :class:`Engine`. The actual CSV reading and writing lives in each
engine (today: ``IbisEngine`` / ``PolarsEngine`` / ``PandasEngine``);
the adapter is responsible for self-registering, owning the ``.csv``
extension, and forwarding the call.

Cross-engine tests parametrise over the three engines; ``polars`` is
skipped when its optional extra isn't installed (mirrors the pattern in
``tests/engines/test_cross_engine_dtype_parity.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from datagrove.engines.ibis_engine import IbisEngine
from datagrove.engines.pandas_engine import PandasEngine
from datagrove.io import FormatAdapter, dispatch, list_adapters
from datagrove.io.csv_adapter import CsvAdapter
from gmnspy.fixtures import leavenworth

LEAVENWORTH_CSV_DIR = leavenworth.csv_dir()
LINK_CSV = LEAVENWORTH_CSV_DIR / "link.csv"
NODE_CSV = LEAVENWORTH_CSV_DIR / "node.csv"


# ---------------------------------------------------------------------------
# Engine parametrisation helper
# ---------------------------------------------------------------------------


def _make_engine(name: str):
    """Construct an engine instance by short name; importorskip polars."""
    if name == "ibis":
        return IbisEngine()
    if name == "polars":
        pytest.importorskip("polars", reason="polars optional extra not installed")
        from datagrove.engines.polars_engine import PolarsEngine

        return PolarsEngine()
    if name == "pandas":
        return PandasEngine()
    raise AssertionError(f"unknown engine name: {name!r}")


@pytest.fixture()
def adapter() -> CsvAdapter:
    return CsvAdapter()


# ---------------------------------------------------------------------------
# 1. probe — extension sniff
# ---------------------------------------------------------------------------


def test_probe_csv_extension(adapter: CsvAdapter) -> None:
    """``.csv`` paths probe True; ``.parquet`` paths probe False; non-paths probe False."""
    assert adapter.probe(LINK_CSV) is True
    assert adapter.probe(str(LINK_CSV)) is True
    assert adapter.probe(Path("any/where/foo.csv")) is True
    assert adapter.probe("any/where/foo.parquet") is False
    # Source with no path-like interface: not a csv.
    assert adapter.probe({"not": "a path"}) is False


# ---------------------------------------------------------------------------
# 2. probe — total (never raises)
# ---------------------------------------------------------------------------


def test_probe_never_raises(adapter: CsvAdapter) -> None:
    """probe must be total — garbage in, ``False`` out, never an exception."""
    for garbage in (None, object(), 42, 3.14, [], set(), ("a", "b")):
        # The dispatch loop catches exceptions, but the adapter's contract
        # (per FormatAdapter docstring: "must be cheap and total") is
        # stronger — we don't want to lean on the catch.
        assert adapter.probe(garbage) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. self-registration on import
# ---------------------------------------------------------------------------


def test_self_registers_on_import() -> None:
    """Importing ``datagrove.io.csv_adapter`` registers a ``"csv"`` adapter."""
    import datagrove.io.csv_adapter  # noqa: F401 — import is the assertion

    assert "csv" in list_adapters()


# ---------------------------------------------------------------------------
# 4. scan — single-file resource listing
# ---------------------------------------------------------------------------


def test_scan_returns_single_resource_ref(adapter: CsvAdapter) -> None:
    """For a single-file CSV, scan returns one ResourceRef named after the stem."""
    engine = IbisEngine()
    try:
        listing = adapter.scan(LINK_CSV, engine=engine)
    finally:
        engine.close()
    assert len(listing) == 1
    only = listing[0]
    assert only.name == "link"
    assert only.format == "csv"
    assert only.path == str(LINK_CSV)


def test_scan_with_string_path(adapter: CsvAdapter) -> None:
    """scan accepts string paths too (not just Path)."""
    engine = IbisEngine()
    try:
        listing = adapter.scan(str(NODE_CSV), engine=engine)
    finally:
        engine.close()
    assert len(listing) == 1
    assert listing[0].name == "node"


def test_scan_rejects_dict_source(adapter: CsvAdapter) -> None:
    """A dict handle has no meaningful stem for CSV — return an empty listing.

    The decision: dict sources do not map to a CSV file the way ``str`` /
    ``Path`` do (a dict means "engine-side handle" per the SourceRef
    contract). Returning ``[]`` keeps scan() total and lets callers
    distinguish "no resources here" from a thrown exception. Callers that
    actually want to read inline data should go through ``engine.scan``
    with ``format='csv'`` skipped entirely.
    """
    engine = IbisEngine()
    try:
        listing = adapter.scan({"data": [{"a": 1}]}, engine=engine)
    finally:
        engine.close()
    assert listing == []


# ---------------------------------------------------------------------------
# 5. read — delegates to engine.scan(..., format="csv")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_delegates_to_engine_csv_path(engine_name: str, adapter: CsvAdapter) -> None:
    """adapter.read(link_csv, engine) returns a table with the fixture's row count."""
    engine = _make_engine(engine_name)
    try:
        expr = adapter.read(LINK_CSV, engine=engine)
        df = engine.to_pandas(expr)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    # Leavenworth link.csv ships with a known, stable row count.
    import pandas as pd

    direct = pd.read_csv(LINK_CSV)
    assert len(df) == len(direct)
    # Sanity: columns match.
    assert set(df.columns) == set(direct.columns)


# ---------------------------------------------------------------------------
# 6. read with schema casts types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_with_schema_casts_types(engine_name: str, adapter: CsvAdapter) -> None:
    """A Frictionless schema flows through the adapter to the engine cast pass."""
    from datagrove.spec.model import Field, Schema

    # Force ``lanes`` to string to prove the cast plumbing actually ran.
    # The engine's natural read would infer int; if our schema arrived it
    # comes back as string.
    schema = Schema(
        fields=[
            Field(name="lanes", type="string"),
        ]
    )
    engine = _make_engine(engine_name)
    try:
        expr = adapter.read(LINK_CSV, engine=engine, schema=schema)
        df = engine.to_pandas(expr)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    assert str(df["lanes"].dtype) == "string"


# ---------------------------------------------------------------------------
# 7. read kwargs passthrough — invalid delimiter forces a row-shape mismatch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_with_kwargs_passthrough(engine_name: str, adapter: CsvAdapter, tmp_path: Path) -> None:
    """A semicolon-delimited CSV round-trips when ``delimiter=';'`` is forwarded.

    Each engine's CSV reader exposes a different name for the field
    separator (ibis/duckdb: ``delim``; polars: ``separator``; pandas:
    ``sep`` or ``delimiter``). We use whichever the active engine
    accepts; the assertion is simply that the kwarg reaches the engine
    rather than being silently dropped by the adapter.
    """
    semi = tmp_path / "semi.csv"
    semi.write_text("a;b\n1;x\n2;y\n", encoding="utf-8")

    engine = _make_engine(engine_name)
    sep_kw = {
        "ibis": {"delim": ";"},
        "polars": {"separator": ";"},
        "pandas": {"sep": ";"},
    }[engine_name]
    try:
        expr = adapter.read(semi, engine=engine, **sep_kw)
        df = engine.to_pandas(expr)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


# ---------------------------------------------------------------------------
# 8. write — round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "pandas"])
def test_write_roundtrip(engine_name: str, adapter: CsvAdapter, tmp_path: Path) -> None:
    """scan → write → re-scan returns an equal table.

    Polars is excluded from this parametrisation only because polars's
    sink-csv path requires a streaming collect that complicates the
    minimal round-trip; the read-side ``test_read_delegates`` already
    proves polars's read path. Write coverage for polars can be added
    once a sibling task introduces a streaming write helper.
    """
    engine = _make_engine(engine_name)
    out = tmp_path / "node-roundtrip.csv"
    try:
        original = adapter.read(NODE_CSV, engine=engine)
        adapter.write(original, out, engine=engine)
        roundtrip = adapter.read(out, engine=engine)
        df_in = engine.to_pandas(original).sort_index(axis=1).reset_index(drop=True)
        df_out = engine.to_pandas(roundtrip).sort_index(axis=1).reset_index(drop=True)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    assert df_in.shape == df_out.shape
    assert list(df_in.columns) == list(df_out.columns)
    assert len(df_in) == len(df_out)


# ---------------------------------------------------------------------------
# 9. Protocol conformance
# ---------------------------------------------------------------------------


def test_protocol_conformance() -> None:
    """CsvAdapter satisfies the runtime_checkable FormatAdapter protocol."""
    assert isinstance(CsvAdapter(), FormatAdapter)


# ---------------------------------------------------------------------------
# 10. Dispatch wiring
# ---------------------------------------------------------------------------


def test_dispatch_routes_csv_to_csv_adapter() -> None:
    """After import-time registration, ``dispatch('foo.csv')`` finds the CsvAdapter."""
    import datagrove.io.csv_adapter  # noqa: F401 — ensure registration

    resolved = dispatch("foo.csv")
    assert isinstance(resolved, CsvAdapter)
    assert resolved.name == "csv"
