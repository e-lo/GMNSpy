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
        msg = str(excinfo.value)
        assert "planned for task 1.3" in msg
        assert "not yet implemented" in msg


# Polars stub test removed in task 1.4: the engine is implemented now; its
# behavior lives in test_polars_engine.py.


def test_polars_stub_importable_unconditionally():
    # Importing the stub module itself should never require polars to be installed.
    from datagrove.engines import polars_engine  # noqa: F401


def test_pandas_stub_importable_unconditionally():
    from datagrove.engines import pandas_engine  # noqa: F401
