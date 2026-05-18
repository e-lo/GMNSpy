"""Stub-implementation tests — verify the placeholders raise with the right message."""

from __future__ import annotations

import pytest
from datagrove.engines.ibis_engine import IbisEngine


def test_ibis_stub_methods_raise_with_task_id():
    e = IbisEngine()
    for call in (
        lambda: e.scan("x"),
        lambda: e.materialize(None),
        lambda: e.to_pandas(None),
        lambda: e.to_polars(None),
        lambda: e.write(None, "x", "csv"),
    ):
        with pytest.raises(NotImplementedError) as excinfo:
            call()
        assert "1.3" in str(excinfo.value)


def test_polars_stub_methods_raise_with_task_id():
    pytest.importorskip("polars", reason="polars optional extra not installed")
    from datagrove.engines.polars_engine import PolarsEngine

    e = PolarsEngine()
    for call in (
        lambda: e.scan("x"),
        lambda: e.materialize(None),
        lambda: e.to_pandas(None),
        lambda: e.to_polars(None),
        lambda: e.write(None, "x", "csv"),
    ):
        with pytest.raises(NotImplementedError) as excinfo:
            call()
        assert "1.4" in str(excinfo.value)


def test_pandas_stub_methods_raise_with_task_id():
    pytest.importorskip("pandas", reason="pandas optional extra not installed")
    from datagrove.engines.pandas_engine import PandasEngine

    e = PandasEngine()
    for call in (
        lambda: e.scan("x"),
        lambda: e.materialize(None),
        lambda: e.to_pandas(None),
        lambda: e.to_polars(None),
        lambda: e.write(None, "x", "csv"),
    ):
        with pytest.raises(NotImplementedError) as excinfo:
            call()
        assert "1.5" in str(excinfo.value)


def test_polars_stub_importable_unconditionally():
    # Importing the stub module itself should never require polars to be installed.
    from datagrove.engines import polars_engine  # noqa: F401


def test_pandas_stub_importable_unconditionally():
    from datagrove.engines import pandas_engine  # noqa: F401
