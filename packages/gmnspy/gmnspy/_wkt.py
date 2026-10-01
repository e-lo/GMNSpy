"""Tiny, dependency-free WKT ``LINESTRING`` parser.

Lives at the package root (not under ``gmnspy.map``) so low-level consumers like
``gmnspy.viz`` and ``gmnspy.select`` can parse link geometry without importing the
optional-extra ``gmnspy.map`` module — keeping the ``cli`` → ``map`` import
boundary (enforced by import-linter) intact. ``shapely`` is a heavy C-extension
dep to drag in just for coordinate extraction, so this stays hand-rolled.
"""

from __future__ import annotations

import re

#: Matches each ``x y`` coordinate pair inside a WKT geometry string.
_WKT_POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")


def _parse_linestring_points(wkt: str) -> list[tuple[float, float]]:
    """Parse a ``LINESTRING (x y, x y, ...)`` WKT to a list of ``(lon, lat)``.

    Accepts a leading ``LINESTRING`` / ``LINESTRING M`` / ``LINESTRING Z`` token
    (case-insensitive) and any surrounding whitespace. Returns an empty list when
    the input is not a string or no coordinates parse.
    """
    if not isinstance(wkt, str):
        return []
    return [(float(x), float(y)) for x, y in _WKT_POINT_RE.findall(wkt)]
