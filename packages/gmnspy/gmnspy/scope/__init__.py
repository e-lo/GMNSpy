"""Network-aware scope ops — BFS subgraph, network buffer, spatial buffer, zone, component.

Re-exports the public surface from :mod:`gmnspy.scope.scope`. The
single file holds all constructors + composition + apply because the
ops share an FK-pushdown pattern that reads more cleanly side-by-side
than spread across N files (project legibility priority).

Public surface:

* :class:`NetworkScope` — the immutable (link_ids, node_ids) value
  with composition methods (``union`` / ``intersect`` / ``subtract`` /
  ``buffer_network`` / ``buffer_spatial``) and :meth:`apply`.
* Constructors: :func:`from_nodes`, :func:`from_node`,
  :func:`from_link`, :func:`from_point`, :func:`connected_component`,
  :func:`from_zone`.
* :class:`NetworkScopeAccessor` — partial-applied accessor returned by
  :attr:`gmnspy.Network.scope` so the architecture-documented chain
  ``net.scope.from_nodes([1,2,3]).buffer_network("0.5mi")`` reads
  naturally.
* :class:`ScopeError` — typed exception (subclass of
  :class:`gmnspy.NetworkError`).
* :data:`AUTO_INDEX_THRESHOLD_DEFAULT` — node-count threshold above
  which auto-build emits an info log; override via env var
  ``GMNSPY_AUTO_INDEX_THRESHOLD``.
"""

from .accessor import NetworkScopeAccessor
from .errors import ScopeError
from .scope import (
    AUTO_INDEX_THRESHOLD_DEFAULT,
    NetworkScope,
    connected_component,
    from_link,
    from_node,
    from_nodes,
    from_point,
    from_zone,
)

__all__ = [
    "AUTO_INDEX_THRESHOLD_DEFAULT",
    "NetworkScope",
    "NetworkScopeAccessor",
    "ScopeError",
    "connected_component",
    "from_link",
    "from_node",
    "from_nodes",
    "from_point",
    "from_zone",
]
