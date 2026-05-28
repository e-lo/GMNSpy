"""Shortest path, isochrone, and nearest-node queries on a :class:`GMNSGraph`."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .build import ShortestPathResult

_NO_PRED = -9999  # scipy.sparse.csgraph predecessor sentinel


class IsochroneResult:
    """Nodes (and links) reachable from a source within a generalized-cost budget."""

    def __init__(self, source, cutoff, nodes: pd.DataFrame, reachable_link_ids):
        self.source = source
        self.cutoff = cutoff
        self.nodes = nodes  # columns: node_id, cost
        self.reachable_link_ids = reachable_link_ids

    @property
    def reachable_node_ids(self):
        return self.nodes["node_id"].to_numpy()

    def __repr__(self) -> str:
        return (
            f"IsochroneResult(source={self.source!r}, cutoff={self.cutoff}, "
            f"n_nodes={len(self.nodes)}, n_links={len(self.reachable_link_ids)})"
        )


def isochrone(graph, source_node, cutoff: float) -> IsochroneResult:
    """Return the nodes (and links) reachable from ``source_node`` within ``cutoff`` cost."""
    from scipy.sparse.csgraph import dijkstra

    src = graph.index_of(source_node)
    dist = dijkstra(graph.csr, directed=True, indices=src, limit=cutoff)
    dist = np.asarray(dist).ravel()
    reachable = np.isfinite(dist)

    nodes = pd.DataFrame({"node_id": graph.node_ids[reachable], "cost": dist[reachable]})

    # A link is inside the isochrone when both endpoints are reachable within budget.
    within = reachable
    indptr, indices = graph.csr.indptr, graph.csr.indices
    link_ids = []
    for u in np.nonzero(within)[0]:
        start, end = indptr[u], indptr[u + 1]
        vs = indices[start:end]
        for offset, v in enumerate(vs):
            if within[v]:
                link_ids.append(graph.edge_link_id[start + offset])
    reachable_link_ids = pd.unique(np.array(link_ids, dtype=object)) if link_ids else np.array([], dtype=object)
    return IsochroneResult(source_node, cutoff, nodes, reachable_link_ids)


def shortest_path(graph, source_node, target_node) -> ShortestPathResult:
    """Return the least-cost path from ``source_node`` to ``target_node`` (Dijkstra)."""
    from scipy.sparse.csgraph import dijkstra

    src = graph.index_of(source_node)
    tgt = graph.index_of(target_node)
    dist, pred = dijkstra(graph.csr, directed=True, indices=src, return_predecessors=True)
    dist = np.asarray(dist).ravel()
    pred = np.asarray(pred).ravel()

    cost = float(dist[tgt])
    if not np.isfinite(cost):
        return ShortestPathResult(source_node, target_node, np.inf, [], [])

    path_idx = [tgt]
    cur = tgt
    while cur != src and cur >= 0:
        cur = int(pred[cur])
        if cur == _NO_PRED or cur < 0:
            break
        path_idx.append(cur)
    path_idx.reverse()

    nodes = [graph.node_at(i) for i in path_idx]
    links = [graph.link_between(path_idx[k], path_idx[k + 1]) for k in range(len(path_idx) - 1)]
    return ShortestPathResult(source_node, target_node, cost, nodes, links)


def snap(graph, x: float, y: float):
    """Return the node_id of the network node nearest to ``(x, y)``."""
    from scipy.spatial import cKDTree

    if graph._kdtree is None:
        finite = np.isfinite(graph.coords).all(axis=1)
        if not finite.any():
            raise ValueError("No node coordinates available for snapping.")
        graph._kdtree_index = np.nonzero(finite)[0]
        graph._kdtree = cKDTree(graph.coords[graph._kdtree_index])
    _, pos = graph._kdtree.query([x, y])
    return graph.node_at(graph._kdtree_index[int(pos)])
