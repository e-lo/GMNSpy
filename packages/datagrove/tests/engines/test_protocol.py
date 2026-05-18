"""Structural conformance tests for the Engine protocol."""

from __future__ import annotations

from typing import Any

from datagrove.engines import Engine


class FakeEngine:
    """Minimal in-test engine satisfying the full Engine protocol."""

    name: str = "fake"

    def scan(self, source, schema=None):
        return None

    def materialize(self, expr):
        return None

    def to_pandas(self, expr):
        return None

    def to_polars(self, expr):
        return None

    def write(self, expr, dest, fmt: str, **kwargs: Any) -> None:
        return None


class IncompleteEngine:
    """Missing ``scan`` — should NOT be recognised as an Engine."""

    name: str = "incomplete"

    def materialize(self, expr):
        return None

    def to_pandas(self, expr):
        return None

    def to_polars(self, expr):
        return None

    def write(self, expr, dest, fmt: str, **kwargs: Any) -> None:
        return None


def test_fake_engine_satisfies_protocol():
    assert isinstance(FakeEngine(), Engine)


def test_engine_missing_scan_fails_protocol_check():
    assert not isinstance(IncompleteEngine(), Engine)


def test_engine_protocol_runtime_checkable_class_object():
    # Defensive sanity: re-confirm instance check after mutation in other tests.
    assert isinstance(FakeEngine(), Engine)
