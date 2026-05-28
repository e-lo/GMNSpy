"""GMNS network construction from OpenStreetMap (optional ``[osm]`` extra).

Install via ``pip install gmnspy[osm]`` to pull in ``requests`` (Overpass /
Nominatim access) and ``pyyaml`` (the tag-mapping data loader). The public
entry point is :func:`gmnspy.osm.build.build_network_from_osm`, re-exported
here once the build module lands.
"""

from __future__ import annotations

# Guard the optional [osm] extra up front so an import-time error is obvious
# and points the user at the install command. The actual requests/yaml usage
# lives in the submodules (query.py uses requests, tags.py uses yaml).
try:
    import requests  # noqa: F401
    import yaml  # noqa: F401
except ImportError as e:  # pragma: no cover - defensive
    raise ImportError("gmnspy.osm requires the [osm] extra: pip install 'gmnspy[osm]'") from e

from .build import build_network_from_osm, network_from_records

__all__ = ["build_network_from_osm", "network_from_records"]
