"""Tests for the global adapter registry."""

from __future__ import annotations

import pytest
from datagrove.io import (
    AdapterNotAvailableError,
    _clear_registry,
    get_adapter,
    list_adapters,
    register_adapter,
)

from ._fakes import FakeCsvAdapter, FakeParquetAdapter


@pytest.fixture(autouse=True)
def _isolated_registry():
    _clear_registry()
    yield
    _clear_registry()


def test_empty_registry_after_clear() -> None:
    assert list_adapters() == []


def test_register_then_lookup() -> None:
    adapter = FakeCsvAdapter()
    register_adapter(adapter)
    assert list_adapters() == ["csv"]
    assert get_adapter("csv") is adapter


def test_re_register_overwrites_same_name() -> None:
    a1 = FakeCsvAdapter()
    a2 = FakeCsvAdapter()
    register_adapter(a1)
    register_adapter(a2)
    assert list_adapters() == ["csv"]
    assert get_adapter("csv") is a2


def test_get_unknown_adapter_raises() -> None:
    with pytest.raises(AdapterNotAvailableError):
        get_adapter("missing")


def test_registration_preserves_order() -> None:
    register_adapter(FakeCsvAdapter())
    register_adapter(FakeParquetAdapter())
    assert list_adapters() == ["csv", "parquet"]
