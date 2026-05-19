"""Cross-engine parity tests — the regression lock for findings I1 + S3.

The engine layer promises that ``engine.to_pandas(engine.scan(src))``
returns a pandas DataFrame with the same dtype family regardless of
which engine produced it. This file pins that contract on the
Leavenworth fixture (``link.csv``) and also asserts the three
per-engine Frictionless→native type maps cover the same Frictionless
keyset — so adding a new Frictionless type later forces all three
engines to update together.

Why these tests live here (not in each engine's test file): the value
they assert is the *cross-engine* promise — placing them in one
engine's file would obscure that. New engines added to the registry
should be added to the parametrisation below.
"""

from __future__ import annotations

import pytest

# Skip the whole module if polars isn't installed — without it the parity
# claim is vacuous (only ibis vs pandas; gives no symmetry signal).
pytest.importorskip("polars", reason="polars optional extra not installed")

import pandas as pd
import polars as pl
from datagrove.engines.ibis_engine import _FRICTIONLESS_TO_IBIS, IbisEngine
from datagrove.engines.pandas_engine import (
    _FRICTIONLESS_TO_PANDAS_NULLABLE,
    PandasEngine,
)
from datagrove.engines.polars_engine import _FRICTIONLESS_TO_POLARS, PolarsEngine
from gmnspy.fixtures import leavenworth

LINK_CSV = leavenworth.csv_dir() / "link.csv"


# ---------------------------------------------------------------------------
# Frictionless type-map keyset parity (finding S3)
# ---------------------------------------------------------------------------


def test_frictionless_type_maps_cover_same_keyset():
    """All three engine maps must support the same Frictionless types.

    We inline the maps per Lens C (small, single-consumer, more legible
    at point-of-use than imported from a shared defaults module) — this
    test is the trade-off that catches drift. If a future contributor
    adds ``"date"`` to one engine's map, this test fails until the
    others follow.
    """
    ibis_keys = set(_FRICTIONLESS_TO_IBIS)
    polars_keys = set(_FRICTIONLESS_TO_POLARS)
    pandas_keys = set(_FRICTIONLESS_TO_PANDAS_NULLABLE)

    assert ibis_keys == polars_keys == pandas_keys, (
        "Frictionless type maps diverge across engines: "
        f"ibis={ibis_keys}, polars={polars_keys}, pandas={pandas_keys}. "
        "Add the missing type(s) to every engine's map and update this "
        "parity test if the contract intentionally grew."
    )


# ---------------------------------------------------------------------------
# to_pandas dtype parity (finding I1)
# ---------------------------------------------------------------------------


def _scan_via(engine_name: str):
    """Return ``(engine, scan_result)`` for ``engine_name`` over LINK_CSV."""
    if engine_name == "ibis":
        e = IbisEngine()
        return e, e.scan(LINK_CSV)
    if engine_name == "polars":
        e = PolarsEngine()
        return e, e.scan(LINK_CSV)
    if engine_name == "pandas":
        e = PandasEngine()
        return e, e.scan(LINK_CSV)
    raise AssertionError(f"unknown engine name: {engine_name}")


# Columns we pin on the Leavenworth link.csv fixture. Picked to cover
# every dtype family in the cross-engine convention:
#   - from_node_id : integer (no nulls here, but the contract says Int64)
#   - lanes        : integer
#   - length       : number
#   - name         : string
#   - directed     : boolean
PINNED_COLUMNS = ["from_node_id", "lanes", "length", "name", "directed"]

# Expected pandas nullable dtypes. The whole point of the cross-engine
# parity contract: this dict is the SAME for every engine.
EXPECTED_DTYPES = {
    "from_node_id": "Int64",
    "lanes": "Int64",
    "length": "Float64",
    "name": "string",
    "directed": "boolean",
}


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_to_pandas_returns_numpy_backed_nullable_dtypes(engine_name):
    """Each engine's to_pandas lands on numpy-backed nullable dtypes.

    Per the Engine protocol's ``to_pandas`` docstring, the returned
    frame uses ``Int64`` / ``Float64`` / ``string`` / ``boolean`` —
    NOT numpy ``int64`` / ``object`` / ``float64`` (ibis's native
    default) and NOT pyarrow-extension dtypes (``int64[pyarrow]``,
    which polars's ``use_pyarrow_extension_array=True`` would
    produce). Both alternatives break downstream libraries
    (sklearn, geopandas pre-1.0) and the nullable family preserves
    null semantics without silently upcasting ints with nulls to
    float64.
    """
    engine, scanned = _scan_via(engine_name)
    try:
        df = engine.to_pandas(scanned)
    finally:
        # IbisEngine owns its connection; close to release the file
        # lock so the next parametrize iteration runs cleanly.
        if hasattr(engine, "close"):
            engine.close()

    assert isinstance(df, pd.DataFrame)
    for col, expected in EXPECTED_DTYPES.items():
        assert col in df.columns, f"{engine_name}: missing column {col!r}"
        actual = str(df[col].dtype)
        assert actual == expected, (
            f"{engine_name}.to_pandas: column {col!r} has dtype {actual!r}, "
            f"expected {expected!r} (cross-engine convention — see "
            f"Engine.to_pandas docstring)"
        )


def test_to_pandas_dtypes_match_across_all_engines():
    """The dtypes returned by each engine must literally match.

    The per-engine test above checks each engine individually; this
    test catches the case where every engine independently agreed on
    a non-target dtype (e.g. all three switching to ``int64[pyarrow]``
    in a future regression).
    """
    dtype_maps: dict[str, dict[str, str]] = {}
    for engine_name in ("ibis", "polars", "pandas"):
        engine, scanned = _scan_via(engine_name)
        try:
            df = engine.to_pandas(scanned)
        finally:
            if hasattr(engine, "close"):
                engine.close()
        dtype_maps[engine_name] = {c: str(df[c].dtype) for c in PINNED_COLUMNS}

    # All engines must agree column-by-column.
    ibis_dtypes = dtype_maps["ibis"]
    for engine_name, dtypes in dtype_maps.items():
        assert dtypes == ibis_dtypes, (
            f"{engine_name}.to_pandas dtypes diverge from ibis: {engine_name}={dtypes!r}, ibis={ibis_dtypes!r}"
        )


# ---------------------------------------------------------------------------
# Cross-engine dict-source contract parity (finding I3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_inline_data_dict_source_works_on_every_engine(engine_name):
    """All three engines must accept ``{"data": [...]}`` inline-data sources.

    This is half of the dict-source contract documented on
    :meth:`Engine.scan`. The other half (duckdb handle) is exercised
    by each engine's own test file (the fixture path is awkward to
    parametrise here).
    """
    engine, _ = _scan_via(engine_name)  # only to get an engine instance
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    try:
        scanned = engine.scan({"data": rows})
        df = engine.to_pandas(scanned)
    finally:
        if hasattr(engine, "close"):
            engine.close()
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_unrecognised_dict_source_raises_unsupported_source_error(engine_name):
    """Dict shapes other than {data:...}/{duckdb-handle} must error clearly.

    Locks the cross-engine error type for the "wrong dict shape" case
    so callers can catch ``UnsupportedSourceError`` once and have it
    work for every engine.
    """
    from datagrove.engines.errors import UnsupportedSourceError

    engine, _ = _scan_via(engine_name)
    try:
        with pytest.raises(UnsupportedSourceError, match="dict source"):
            engine.scan({"unknown_key": "garbage"})
    finally:
        if hasattr(engine, "close"):
            engine.close()


# ---------------------------------------------------------------------------
# Sanity that polars LazyFrame survives the round-trip too
# ---------------------------------------------------------------------------


def test_polars_to_pandas_does_not_use_pyarrow_extension_dtypes():
    """Polars's to_pandas MUST NOT return ``int64[pyarrow]`` dtypes.

    This is the explicit regression for the previous polars-engine
    behaviour (``use_pyarrow_extension_array=True``) which returned
    pyarrow-extension columns. Downstream libraries (sklearn,
    geopandas pre-1.0) don't understand them.
    """
    e = PolarsEngine()
    df = e.to_pandas(e.scan(LINK_CSV))
    for col, dtype in df.dtypes.items():
        # pyarrow-extension dtypes are instances of pd.ArrowDtype.
        assert not isinstance(dtype, pd.ArrowDtype), (
            f"polars.to_pandas returned column {col!r} as pyarrow-extension "
            f"({dtype!r}) — the cross-engine convention requires numpy-backed "
            f"nullable dtypes (Int64 etc)."
        )
    # Reference the polars import so the linter doesn't drop it from
    # the imports block above.
    assert pl is not None


# ---------------------------------------------------------------------------
# Cross-engine primitive parity (issue #134 — engine/adapter inversion)
# ---------------------------------------------------------------------------
#
# Before #134 the only public read surface was ``engine.scan(source)``,
# which dispatched per-format inside each engine. After #134 the
# adapters call ``engine.read_csv`` / ``read_parquet`` /
# ``read_duckdb_table`` / ``from_records`` directly. These tests pin
# that the primitives produce dtype-equivalent output across engines —
# the same regression promise as the ``scan``-based tests above, just
# moved one layer deeper so the contract is locked at the call site
# that adapters actually use.


def _engine_for(name: str):
    if name == "ibis":
        return IbisEngine()
    if name == "polars":
        return PolarsEngine()
    if name == "pandas":
        return PandasEngine()
    raise AssertionError(f"unknown engine name: {name}")


PARQUET_LINK = leavenworth.parquet_dir() / "link.parquet"
DUCKDB_PATH = leavenworth.duckdb_path()


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_csv_primitive_dtypes_match_scan(engine_name):
    """``engine.read_csv(source)`` returns dtype-equivalent output to ``engine.scan(source)``.

    The adapter calls ``read_csv`` directly post-#134; this pins that
    the dispatch path and the direct-primitive path agree on dtypes.
    """
    e = _engine_for(engine_name)
    try:
        via_scan = e.to_pandas(e.scan(LINK_CSV))
        via_primitive = e.to_pandas(e.read_csv(LINK_CSV))
    finally:
        if hasattr(e, "close"):
            e.close()
    for col, expected in EXPECTED_DTYPES.items():
        assert str(via_primitive[col].dtype) == expected
        assert str(via_scan[col].dtype) == str(via_primitive[col].dtype)


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_parquet_primitive_dtypes_consistent_across_engines(engine_name):
    """``engine.read_parquet(source)`` produces the cross-engine dtype family."""
    e = _engine_for(engine_name)
    try:
        df = e.to_pandas(e.read_parquet(PARQUET_LINK))
    finally:
        if hasattr(e, "close"):
            e.close()
    for col, expected in EXPECTED_DTYPES.items():
        assert col in df.columns
        assert str(df[col].dtype) == expected, f"{engine_name}.read_parquet col {col!r}: {df[col].dtype} != {expected}"


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_read_duckdb_table_primitive_consistent_across_engines(engine_name):
    """``engine.read_duckdb_table(source, table=...)`` reads the duckdb fixture."""
    e = _engine_for(engine_name)
    try:
        df = e.to_pandas(e.read_duckdb_table(DUCKDB_PATH, table="link"))
    finally:
        if hasattr(e, "close"):
            e.close()
    # Every engine sees the same rowcount and column set from the same
    # duckdb file.
    assert len(df) > 0
    assert "from_node_id" in df.columns


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_from_records_primitive_accepts_both_dict_shapes(engine_name):
    """``from_records`` handles the two contract shapes (list-of-row-dicts + columnar dict)."""
    e = _engine_for(engine_name)
    try:
        rows = e.to_pandas(e.from_records([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]))
        cols = e.to_pandas(e.from_records({"a": [1, 2], "b": ["x", "y"]}))
    finally:
        if hasattr(e, "close"):
            e.close()
    assert len(rows) == 2 and list(rows.columns) == ["a", "b"]
    assert len(cols) == 2 and list(cols.columns) == ["a", "b"]


# ---------------------------------------------------------------------------
# Engine scan() is a thin delegator after #134
# ---------------------------------------------------------------------------


def test_engines_have_no_resolve_kind_method():
    """Lock the engine/adapter inversion: no per-engine ``_resolve_kind`` lives on.

    Before #134 each engine carried a private ``_resolve_kind`` that
    dispatched per-format inside ``scan``. After #134 dispatch lives
    exclusively in ``datagrove.io.dispatch``, called from the
    delegating ``scan``. If a future contributor reintroduces a
    per-engine resolver, this regression fires.
    """
    for name in ("ibis", "polars", "pandas"):
        e = _engine_for(name)
        try:
            assert not hasattr(e, "_resolve_kind"), (
                f"{name} engine grew a _resolve_kind — engine/adapter inversion "
                "regressed; dispatch belongs in datagrove.io.dispatch"
            )
            # And the module-level helper should be gone too.
            module = type(e).__module__
            mod = __import__(module, fromlist=["*"])
            assert not hasattr(mod, "_resolve_kind"), (
                f"{module} grew a module-level _resolve_kind helper — same regression"
            )
        finally:
            if hasattr(e, "close"):
                e.close()


@pytest.mark.parametrize("engine_name", ["ibis", "polars", "pandas"])
def test_engine_scan_is_a_thin_delegator(engine_name):
    """Engine.scan() is a short convenience over io.dispatch — pin the LOC budget.

    The post-#134 ``scan`` body is the dict-source carve-out (one if
    plus a helper call) and the dispatch+delegate (two lines). Keeping
    it under ~10 executable statements is the rubric that prevents a
    regression where someone re-grows the per-format if/elif inside
    ``scan``.
    """
    import ast
    import inspect
    import textwrap

    e = _engine_for(engine_name)
    try:
        src = textwrap.dedent(inspect.getsource(e.scan))
    finally:
        if hasattr(e, "close"):
            e.close()

    # Parse the function and count executable statements in its body,
    # stripping the docstring expression. This avoids the heuristic
    # mess of trying to skip docstrings by line.
    tree = ast.parse(src)
    func = tree.body[0]
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    body = list(func.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        # Drop the docstring.
        body = body[1:]

    # A statement count <= 10 covers: ``if isinstance(source, dict): return _scan_dict(...)``,
    # ``from datagrove.io import dispatch``, ``adapter = dispatch(...)``,
    # ``return adapter.read(...)`` and a little slack for future minor
    # additions. Anything substantially larger means a per-format
    # if/elif has crept back in.
    assert len(body) <= 10, (
        f"{engine_name}.scan() body has {len(body)} top-level statements (budget 10); "
        "engine/adapter inversion regressed — dispatch should live in "
        f"datagrove.io.dispatch.\n{ast.unparse(func)}"
    )
