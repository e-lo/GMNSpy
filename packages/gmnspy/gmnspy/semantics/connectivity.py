"""Network connectivity helpers built on :class:`gmnspy.indexes.GraphIndex`.

All entry points take a :class:`gmnspy.Network`, build (or reuse) a
graph index, and answer a connectivity question. The index is cached
on the network's ``metadata`` dict under ``_cached_graph_index`` so
repeat calls inside a session do not rebuild — see
:func:`_get_or_build_graph_index`.

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
    from gmnspy.indexes import GraphIndex
    from gmnspy.network import Network

__all__ = [
    "connected_components",
    "is_connected",
    "largest_component",
    "unreachable_from",
]

# The key under which we stash the built GraphIndex on Network.metadata.
# Lives at module scope so the scope module (task 3.10) can reuse it
# instead of building a parallel cache.
_GRAPH_INDEX_KEY = "_cached_graph_index"


def _get_or_build_graph_index(net: Network) -> GraphIndex:
    """Return a cached :class:`GraphIndex` or build + cache one.

    Building requires both the ``link`` and ``node`` tables; we let
    :class:`Network` raise :class:`gmnspy.NetworkError` on its own if
    either is missing.
    """
    cached = net.metadata.get(_GRAPH_INDEX_KEY)
    if cached is not None:
        return cached
    # Local import to keep the cold-import cost of `semantics` low —
    # callers who never touch connectivity don't pay for igraph.
    from gmnspy.indexes import GraphIndex

    index = GraphIndex.build(net.links, net.nodes)
    net.metadata[_GRAPH_INDEX_KEY] = index
    return index


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
    index = _get_or_build_graph_index(net)
    if len(index) == 0:
        return []
    # igraph returns positional indices; map back to node ids and sort.
    raw = index.graph.connected_components(mode="weak")
    comps = [{index.node_ids[p] for p in comp} for comp in raw]
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

    index = _get_or_build_graph_index(net)
    pos = index._pos.get(int(source_node_id))
    if pos is None:
        raise SemanticsError(
            f"source_node_id={source_node_id!r} not present in network.nodes (network has {len(index)} nodes)."
        )
    # igraph's `subcomponent` with mode="out" walks directed edges.
    reachable_positions = set(index.graph.subcomponent(pos, mode="out"))
    all_positions = set(range(len(index)))
    unreachable_positions = all_positions - reachable_positions
    return {index.node_ids[p] for p in unreachable_positions}
