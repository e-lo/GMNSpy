"""Network connectivity helpers built on :class:`gmnspy.graph.GMNSGraph`.

All entry points take a :class:`gmnspy.Network`, build (or reuse) a routing
graph, and answer a connectivity question. The graph is cached on the network's
``metadata`` dict under ``_cached_gmnsgraph`` so repeat calls inside a session
do not rebuild — see :func:`_get_or_build_graph`.

This module is part of unifying graph operations onto :mod:`gmnspy.graph`
(scipy CSR), replacing the previous :class:`gmnspy.indexes.GraphIndex` (igraph)
backend. The graph is built with ``keep_missing_cost=True`` so a link with a
missing ``length`` is still a topological connection (matching the old
null-length → unit-weight behaviour) rather than being dropped.

Examples:
    >>> from gmnspy import Network
    >>> from gmnspy.fixtures import leavenworth
    >>> from datagrove.engines.pandas_engine import PandasEngine
    >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
    >>> from gmnspy.semantics import is_connected
    >>> is_connected(net)
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from gmnspy.graph import GMNSGraph
    from gmnspy.network import Network

__all__ = [
    "connected_components",
    "is_connected",
    "largest_component",
    "unreachable_from",
]

# The key under which we stash the built GMNSGraph on Network.metadata. Distinct
# from scope's ``_cached_graph_index`` (still an igraph GraphIndex until scope
# migrates too), so the two backends can coexist during the transition.
_GRAPH_CACHE_KEY = "_cached_gmnsgraph"


def _get_or_build_graph(net: Network) -> GMNSGraph:
    """Return a cached :class:`GMNSGraph` or build + cache one.

    Building requires both the ``link`` and ``node`` tables; we let
    :class:`Network` raise :class:`gmnspy.NetworkError` on its own if either is
    missing.
    """
    cached = net.metadata.get(_GRAPH_CACHE_KEY)
    if cached is not None:
        return cached
    # Local import to keep the cold-import cost of `semantics` low — callers who
    # never touch connectivity don't pay for scipy.
    from gmnspy.graph import GMNSGraph

    graph = GMNSGraph.from_network(net, cost="length", keep_missing_cost=True)
    net.metadata[_GRAPH_CACHE_KEY] = graph
    return graph


def is_connected(net: Network) -> bool:
    """Return ``True`` iff the network has exactly one weakly-connected component.

    "Weakly connected" means we ignore link direction — a one-way pair
    of streets between two nodes counts as connected.

    Examples:
        >>> from gmnspy import Network
        >>> from gmnspy.fixtures import leavenworth
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
        >>> is_connected(net)
        True
    """
    return len(connected_components(net)) == 1


def connected_components(net: Network) -> list[set[int]]:
    """Return the network's weakly-connected components, largest first.

    Each component is a set of node_ids. Sorted by ``len`` descending
    so ``connected_components(net)[0]`` is always the largest. Empty
    networks return ``[]``.

    Examples:
        >>> from gmnspy import Network
        >>> from gmnspy.fixtures import leavenworth
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
        >>> comps = connected_components(net)
        >>> len(comps) >= 1
        True
        >>> all(len(comps[i]) >= len(comps[i + 1]) for i in range(len(comps) - 1))
        True
    """
    graph = _get_or_build_graph(net)
    if len(graph.node_ids) == 0:
        return []
    table = graph.connectivity(connection="weak").table
    comps = [set(group["node_id"].tolist()) for _, group in table.groupby("component", sort=False)]
    comps.sort(key=len, reverse=True)
    return comps


def largest_component(net: Network) -> set[int]:
    """Return the set of node_ids in the largest weakly-connected component.

    Empty networks return ``set()``.
    """
    comps = connected_components(net)
    return comps[0] if comps else set()


def unreachable_from(net: Network, source_node_id: int) -> set[int]:
    """Return node_ids that cannot be reached by **directed** traversal from ``source_node_id``.

    Unlike :func:`connected_components` (which ignores direction), this
    walks the directed graph: a node only counts as reachable if there
    is a directed path of one-way links from the source.

    A missing ``source_node_id`` raises :class:`SemanticsError` —
    callers should validate ids against ``net.nodes`` first when they
    can't guarantee membership.

    Examples:
        >>> from gmnspy import Network
        >>> from gmnspy.fixtures import leavenworth
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
        >>> # Pick any node, query — Leavenworth is bidirectional so the
        >>> # unreachable set is typically empty.
        >>> seed = next(iter(largest_component(net)))
        >>> isinstance(unreachable_from(net, seed), set)
        True
    """
    from gmnspy.semantics.errors import SemanticsError

    graph = _get_or_build_graph(net)
    if graph._index_or_none(int(source_node_id)) is None:
        raise SemanticsError(
            f"source_node_id={source_node_id!r} not present in network.nodes (network has {len(graph.node_ids)} nodes)."
        )
    reachable = {int(n) for n in graph.reachable_from(int(source_node_id))}
    return {int(n) for n in graph.node_ids} - reachable
