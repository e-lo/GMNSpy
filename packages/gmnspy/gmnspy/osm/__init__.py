"""GMNS network construction from OpenStreetMap (optional ``[osm]`` extra).

The heavy ``build`` / ``query`` paths need ``requests`` (Overpass / Nominatim
access) and ``pyyaml`` (the tag-mapping data loader) — both pulled in by
``pip install 'gmnspy[osm]'``. The deep-link URL helpers in
:mod:`gmnspy.osm.edit` are pure string formatters with no external deps and
load freely without the ``[osm]`` extra, so the validation HTML viewer in
:mod:`gmnspy.reports` can surface "Edit in OSM" links without forcing the
``[osm]`` install on every consumer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Edit-URL helpers have no external deps — re-export eagerly so the
# reports package can use them without the [osm] extra.
from .edit import issue_osm_edit_url, osm_edit_url

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .build import build_network_from_osm, network_from_records

__all__ = [
    "build_network_from_osm",
    "issue_osm_edit_url",
    "network_from_records",
    "osm_edit_url",
]


def __getattr__(name: str):
    """Lazy-import the build/query entry points so they only need [osm] when actually called."""
    if name in {"build_network_from_osm", "network_from_records"}:
        try:
            import requests  # noqa: F401
            import yaml  # noqa: F401
        except ImportError as e:  # pragma: no cover - defensive
            raise ImportError(f"gmnspy.osm.{name} requires the [osm] extra: pip install 'gmnspy[osm]'") from e
        from . import build as _build

        return getattr(_build, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
