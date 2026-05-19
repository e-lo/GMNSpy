"""Tests for the runtime_checkable FormatAdapter protocol."""

from __future__ import annotations

from typing import Any

from datagrove.io import FormatAdapter
from datagrove.io.base import ResourceListing, ResourceRef, SourceRef


class FakeCsvAdapter:
    """Full stub satisfying every member of FormatAdapter."""

    name = "csv"
    extensions = ("csv",)
    schemes: tuple[str, ...] = ()

    def probe(self, source: SourceRef) -> bool:
        return True

    def read(
        self,
        source: SourceRef,
        engine: Any,
        schema: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        return ("read", str(source))

    def write(self, expr: Any, dest: SourceRef, engine: Any, **kwargs: Any) -> None:
        return None

    def scan(self, source: SourceRef, engine: Any) -> ResourceListing:
        return [ResourceRef(name="csv", path=str(source), format="csv")]


class MissingReadAdapter:
    """Stub deliberately missing ``read`` to verify protocol rejection."""

    name = "broken"
    extensions = ("broken",)
    schemes: tuple[str, ...] = ()

    def probe(self, source: SourceRef) -> bool:
        return False

    def write(self, expr: Any, dest: SourceRef, engine: Any, **kwargs: Any) -> None:
        return None

    def scan(self, source: SourceRef, engine: Any) -> ResourceListing:
        return []


def test_full_stub_satisfies_protocol() -> None:
    assert isinstance(FakeCsvAdapter(), FormatAdapter)


def test_missing_method_fails_protocol_check() -> None:
    assert not isinstance(MissingReadAdapter(), FormatAdapter)


def test_every_registered_adapter_scan_accepts_engine_none() -> None:
    """I8: ``FormatAdapter.scan(source, engine=None)`` must work for every adapter.

    The Protocol declares ``engine`` optional; locks that in here so a
    future adapter that forgets the default trips this test instead of
    surfacing as a TypeError at the first scan-without-an-engine call.
    """
    import inspect

    from datagrove.io import _REGISTRY

    for name, adapter in _REGISTRY.items():
        sig = inspect.signature(adapter.scan)
        engine_param = sig.parameters.get("engine")
        assert engine_param is not None, f"{name} adapter scan has no 'engine' parameter"
        assert engine_param.default is None, (
            f"{name} adapter scan's 'engine' parameter must default to None (got default={engine_param.default!r})"
        )
