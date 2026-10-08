"""GMNS network construction from Overture Maps (optional ``[overture]`` extra).

Mirrors :mod:`netstead.osm`: a ``build_network_from_overture(area, ...)`` entry
point whose shape matches ``build_network_from_osm`` so sources are swappable.
The Overture **transportation** theme is native GeoParquet on cloud storage, so
the read path leans on DuckDB (``read_parquet`` + the spatial/httpfs extensions,
already shipped with corral's duckdb engine) — the only added dependency is
``pyyaml`` for the maintained mapping loader, pulled in by
``pip install 'netstead[overture]'``.

The heavy ``build`` / ``query`` paths are lazily imported (via ``__getattr__``)
so importing this package is cheap and the import-linter boundary stays static.
The flat local-snapshot folder layout (``segment.parquet`` + ``connector.parquet``)
is documented in :mod:`netstead.overture.layout`.

Attribution: Overture data is **ODbL**; derived products must credit
"© OpenStreetMap contributors, © Overture Maps Foundation"
(https://docs.overturemaps.org/attribution/). netstead reads Overture data; it
does not vendor or redistribute it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .build import build_network_from_overture

__all__ = ["build_network_from_overture"]


def __getattr__(name: str):
    """Lazy-import the build entry point so it only needs [overture] when called."""
    if name == "build_network_from_overture":
        try:
            import yaml  # noqa: F401
        except ImportError as e:  # pragma: no cover - defensive
            raise ImportError(
                f"netstead.overture.{name} requires the [overture] extra: pip install 'netstead[overture]'"
            ) from e
        from . import build as _build

        return getattr(_build, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
