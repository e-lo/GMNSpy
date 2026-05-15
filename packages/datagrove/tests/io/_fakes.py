"""Shared mock adapters for io/ tests.

Kept minimal: just enough surface to satisfy the runtime_checkable
``FormatAdapter`` protocol and let dispatcher tests assert routing.
"""

from __future__ import annotations

from typing import Any

from datagrove.io.base import ResourceListing, ResourceRef, SourceRef


class _BaseFake:
    """Minimal scaffolding all fakes share."""

    name: str = ""
    extensions: tuple[str, ...] = ()
    schemes: tuple[str, ...] = ()
    probe_returns: bool = False

    def probe(self, source: SourceRef) -> bool:
        return self.probe_returns

    def read(
        self,
        source: SourceRef,
        engine: Any,
        schema: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        return ("read", self.name, str(source))

    def write(
        self,
        expr: Any,
        dest: SourceRef,
        engine: Any,
        **kwargs: Any,
    ) -> None:
        return None

    def scan(self, source: SourceRef, engine: Any) -> ResourceListing:
        return [ResourceRef(name=self.name, path=str(source), format=self.name)]


class FakeCsvAdapter(_BaseFake):
    name = "csv"
    extensions = ("csv",)
    schemes = ()


class FakeParquetAdapter(_BaseFake):
    name = "parquet"
    extensions = ("parquet",)
    schemes = ()


class FakeDuckdbAdapter(_BaseFake):
    name = "duckdb"
    extensions = ("duckdb",)
    schemes = ("duckdb",)


class FakeZipCsvAdapter(_BaseFake):
    name = "zipcsv"
    extensions = ("csv.zip",)
    schemes = ()


class FuzzyAdapter(_BaseFake):
    """Adapter that only resolves via ``probe()``.

    Returns True for any source whose string form starts with
    ``"magic://"`` — used to verify the probe-chain fallback.
    """

    name = "fuzzy"
    extensions = ()
    schemes = ()

    def probe(self, source: SourceRef) -> bool:
        return str(source).startswith("magic://")
