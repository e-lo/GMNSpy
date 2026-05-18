"""Stub-implementation tests — verify the placeholders raise with the right message.

The ibis engine is no longer a stub (task 1.3 implemented it); its tests
live in ``test_ibis_engine.py``. Polars and pandas remain stubs until
tasks 1.4 / 1.5 ship.
"""

from __future__ import annotations

import pytest


# Polars stub test removed in task 1.4: the engine is implemented now; its
# behavior lives in test_polars_engine.py.


def test_polars_stub_importable_unconditionally():
    # Importing the stub module itself should never require polars to be installed.
    from datagrove.engines import polars_engine  # noqa: F401


def test_pandas_stub_importable_unconditionally():
    from datagrove.engines import pandas_engine  # noqa: F401
