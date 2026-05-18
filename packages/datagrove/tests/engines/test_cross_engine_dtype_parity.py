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
