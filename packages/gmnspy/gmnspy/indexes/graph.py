"""igraph adjacency over GMNS link.from_node_id → link.to_node_id.

Edge weight = ``link.length`` (meters, per spec). ``directed=False``
links add the reverse edge with the same weight; ``directed=True``
links are honored as-is. The wrapper maps GMNS node ids ↔ igraph
positional vertex indices so callers never see the positions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import igraph as ig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Table

__all__ = ["GraphIndex"]


class GraphIndex:
    """igraph adjacency over (link.from_node_id, link.to_node_id), edge-weighted by link.length.

    Built lazily via :meth:`build`; cached to sidecar parquet keyed on
    the content hash of the source link table (see
    :func:`gmnspy.indexes.cache.cache_path`).

    Examples:
        >>> import pytest
        >>> _ = pytest.importorskip("igraph")
        >>> from gmnspy.indexes import GraphIndex
        >>> GraphIndex.__name__
        'GraphIndex'
    """

    __slots__ = ("_pos", "directed", "edges", "graph", "node_ids")

    def __init__(
        self,
        node_ids: list[int],
        edges: list[tuple[int, int, float]],
        *,
        directed: bool = True,
    ) -> None:
        """Hold node ids + edge tuples and build the underlying igraph."""
        self.node_ids: list[int] = list(node_ids)
        self._pos: dict[int, int] = {nid: i for i, nid in enumerate(self.node_ids)}
        self.edges: list[tuple[int, int, float]] = list(edges)
        self.directed = directed
        self.graph = self._build_graph()

    def __len__(self) -> int:
        """Number of nodes in the graph."""
        return len(self.node_ids)

    def _build_graph(self) -> ig.Graph:
        g = ig.Graph(n=len(self.node_ids), directed=self.directed)
        if self.edges:
            g.add_edges([(u, v) for (u, v, _w) in self.edges])
            g.es["weight"] = [w for (_, _, w) in self.edges]
        return g

    @classmethod
    def build(cls, links_table: Table, nodes_table: Table) -> GraphIndex:
        """Build a :class:`GraphIndex` over a link + node table pair.

        ``links_table`` must carry ``from_node_id``, ``to_node_id``,
        ``length``, and ``directed`` columns. ``nodes_table`` must
        carry ``node_id``. Edges referencing unknown nodes are dropped
        silently — run datagrove FK validation first for hard errors.

        Args:
            links_table: Lazy :class:`~datagrove.dataset.Table` over GMNS links.
            nodes_table: Lazy :class:`~datagrove.dataset.Table` over GMNS nodes.

        Returns:
            A fresh :class:`GraphIndex`.
        """
        nodes_arrow = _to_arrow(nodes_table)
        node_ids = [int(n) for n in nodes_arrow.column("node_id").to_pylist()]
        pos = {nid: i for i, nid in enumerate(node_ids)}

        links_arrow = _to_arrow(links_table)
        from_col = links_arrow.column("from_node_id").to_pylist()
        to_col = links_arrow.column("to_node_id").to_pylist()
        len_col = links_arrow.column("length").to_pylist()
        if "directed" in links_arrow.column_names:
            dir_col = links_arrow.column("directed").to_pylist()
        else:
            dir_col = [True] * len(from_col)

        edges: list[tuple[int, int, float]] = []
        for u, v, length, directed in zip(from_col, to_col, len_col, dir_col, strict=True):
            if u is None or v is None:
                continue
            u_pos = pos.get(int(u))
            v_pos = pos.get(int(v))
            if u_pos is None or v_pos is None:
                continue
            w = float(length) if length is not None else 1.0
            edges.append((u_pos, v_pos, w))
            if not _is_truthy(directed):
                edges.append((v_pos, u_pos, w))
        return cls(node_ids, edges, directed=True)

    def neighbors(self, node_id: int, *, hops: int = 1) -> set[int]:
        """Return node_ids within ``hops`` graph-distance of ``node_id`` (excludes the seed)."""
        pos = self._pos.get(int(node_id))
        if pos is None:
            return set()
        nbrs = self.graph.neighborhood(pos, order=hops, mode="all")
        out = {self.node_ids[p] for p in nbrs}
        out.discard(int(node_id))
        return out

    def shortest_path(self, source: int, target: int) -> list[int]:
        """Return the ordered node_ids on the shortest weighted path.

        Returns ``[source]`` if ``source == target``, ``[]`` if either
        is unknown or unreachable.
        """
        s = self._pos.get(int(source))
        t = self._pos.get(int(target))
        if s is None or t is None:
            return []
        if s == t:
            return [int(source)]
        weights = self.graph.es["weight"] if self.graph.ecount() else None
        paths = self.graph.get_shortest_paths(s, to=t, weights=weights, mode="out", output="vpath")
        if not paths or not paths[0]:
            return []
        return [self.node_ids[p] for p in paths[0]]

    def network_buffer(self, seed_node_ids: list[int], distance_m: float) -> set[int]:
        """Return all node_ids reachable within ``distance_m`` of any seed (Dijkstra)."""
        seeds = [self._pos[int(n)] for n in seed_node_ids if int(n) in self._pos]
        if not seeds:
            return set()
        weights = self.graph.es["weight"] if self.graph.ecount() else None
        dist_matrix = self.graph.distances(source=seeds, weights=weights, mode="out")
        reachable: set[int] = set()
        for row in dist_matrix:
            for j, d in enumerate(row):
                if d is not None and d <= distance_m:
                    reachable.add(self.node_ids[j])
        return reachable

    def connected_component(self, seed_node_id: int) -> set[int]:
        """Return node_ids in the same weakly-connected component as the seed."""
        pos = self._pos.get(int(seed_node_id))
        if pos is None:
            return set()
        for comp in self.graph.connected_components(mode="weak"):
            if pos in comp:
                return {self.node_ids[p] for p in comp}
        return set()

    def __getstate__(self) -> dict[str, Any]:
        """Pickle as plain Python types; rebuild the igraph on load."""
        return {"node_ids": self.node_ids, "edges": self.edges, "directed": self.directed}

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Rebuild the igraph from the pickled node-id + edge payload."""
        self.node_ids = list(state["node_ids"])
        self._pos = {nid: i for i, nid in enumerate(self.node_ids)}
        self.edges = list(state["edges"])
        self.directed = bool(state["directed"])
        self.graph = self._build_graph()


def _to_arrow(table: Table) -> Any:
    """Materialize a :class:`~datagrove.dataset.Table` to pyarrow."""
    import pyarrow as pa

    return pa.Table.from_pandas(table.to_pandas(), preserve_index=False)


def _is_truthy(value: Any) -> bool:
    """Accept GMNS's bool/int/string encodings for the link.directed column."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "1", "yes", "y"}
    return bool(value)
