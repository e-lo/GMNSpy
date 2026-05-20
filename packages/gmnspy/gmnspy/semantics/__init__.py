"""GMNS-domain semantics — connectivity, geometry assembly, TOD resolution.

Three loosely-coupled submodules, one concern each:

* :mod:`gmnspy.semantics.connectivity` — :func:`is_connected`,
  :func:`connected_components`, :func:`largest_component`,
  :func:`unreachable_from`. Built on :class:`gmnspy.indexes.GraphIndex`;
  the index is cached on ``Network.metadata`` so repeat calls don't
  rebuild.
* :mod:`gmnspy.semantics.geometry` — :func:`assemble_link_geometry`
  resolves ``link.geometry`` / ``link.geometry_id`` / node-endpoint
  fallback and stamps each row with its source.
* :mod:`gmnspy.semantics.tod` — :func:`resolve_link_attrs_at` overlays
  ``link_tod`` overrides for a given time period;
  :func:`tod_coverage` audits which periods have TOD data.

All three materialise through pyarrow (via the underlying engine's
``to_pandas`` then ``pa.Table.from_pandas``) — consistent with
:mod:`gmnspy.indexes` and chosen for legibility over an ibis-only API
that would require an ibis-backed engine.
"""

from .connectivity import (
    connected_components,
    is_connected,
    largest_component,
    unreachable_from,
)
from .errors import SemanticsError
from .geometry import GeometrySource, assemble_link_geometry
from .tod import resolve_link_attrs_at, tod_coverage

__all__ = [
    "GeometrySource",
    "SemanticsError",
    "assemble_link_geometry",
    "connected_components",
    "is_connected",
    "largest_component",
    "resolve_link_attrs_at",
    "tod_coverage",
    "unreachable_from",
]
