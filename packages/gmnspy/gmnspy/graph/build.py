"""Build a compact in-memory routing graph from a GMNS network.

The graph is a Compressed Sparse Row (CSR) matrix of generalized cost. It is
built from the ``node`` and ``link`` tables of any :class:`NetworkSource`, holds
its node-id mapping and an edge->link_id mapping, and is meant to be built once
per session and reused for many queries (connectivity, isochrones, shortest
paths). Rebuilding is cheap (~seconds even for a metro network), so there is no
persistent cache or staleness tracking by default.
"""

from __future__ import annotations

import ast
import logging

import numpy as np
import pandas as pd

from .source import NetworkSource, as_source

logger = logging.getLogger(__name__)


def _require_extras():
    try:
        import scipy.sparse  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without extras
        raise ImportError(
            "gmnspy graph features require the optional 'graph' extra. Install with: pip install 'gmnspy[graph]'"
        ) from exc


def _expr_names(expr: str) -> set:
    """Identifier names referenced by a Python expression (for column pruning)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _to_float_array(values) -> np.ndarray:
    return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype="float64", na_value=np.nan)


class ShortestPathResult:
    """Result of a one-to-one shortest path query."""

    def __init__(self, source, target, cost, nodes, links):
        self.source = source
        self.target = target
        self.cost = cost
        self.nodes = nodes
        self.links = links

    @property
    def reachable(self) -> bool:
        return np.isfinite(self.cost)

    def __repr__(self) -> str:
        return (
            f"ShortestPathResult(source={self.source!r}, target={self.target!r}, "
            f"cost={self.cost}, n_links={len(self.links)})"
        )


class GMNSGraph:
    """An in-memory CSR routing graph derived from a GMNS network."""

    def __init__(self, *, node_index, coords, csr, edge_link_id, meta):
        self.node_index = node_index  # pd.Index, position == graph node index
        self.node_ids = node_index.to_numpy()
        self.coords = coords  # (n, 2) float array, NaN where unknown
        self.csr = csr
        self.edge_link_id = edge_link_id  # aligned with csr.data slots
        self.meta = meta
        self._source = None  # retained for lazy geometry access in viz
        self._reverse_csr = None
        self._kdtree = None
        self._kdtree_index = None  # graph indices that the kdtree covers

    # -- construction --------------------------------------------------------

    @classmethod
    def build(
        cls,
        source: NetworkSource | dict | str,
        cost: str,
        barrier: str | None = None,
        directed: None | bool | str = None,
        mode: str = "node",
        *,
        node_id_col: str = "node_id",
        from_col: str = "from_node_id",
        to_col: str = "to_node_id",
        link_id_col: str = "link_id",
        x_col: str = "x_coord",
        y_col: str = "y_coord",
    ) -> GMNSGraph:
        """Build a routing graph.

        Args:
            source: A NetworkSource, a ``{table: DataFrame}`` dict, a DuckDB
                connection, or a path (``.duckdb`` file or directory of
                Parquet/CSV).
            cost: Build-time expression over link columns giving the generalized
                cost / edge weight (e.g. ``"length / free_speed"``). May also be a
                bare column name.
            barrier: Optional boolean expression over link columns; matching links
                are removed from the graph (e.g. ``"lts > 2"``).
            directed: ``None`` uses a per-link ``directed`` column if present else
                treats every link row as a one-way edge; ``True``/``False`` forces
                all links one-way/two-way; a string names a boolean column.
            mode: ``"node"`` (default). ``"edge"`` (movement expansion for turn
                penalties) is reserved for a later release.
        """
        _require_extras()
        if mode == "edge":
            raise NotImplementedError(
                "mode='edge' (movement/turn-penalty expansion) is planned but not yet implemented; use mode='node'."
            )
        if mode != "node":
            raise ValueError(f"Unknown mode {mode!r}; expected 'node' or 'edge'.")

        src = as_source(source)

        # Pull only the link columns the build actually needs (column pruning).
        needed = {from_col, to_col, link_id_col} | _expr_names(cost)
        if barrier is not None:
            needed |= _expr_names(barrier)
        if directed is None:
            needed.add("directed")
        elif isinstance(directed, str):
            needed.add(directed)

        link_tbl = src.table("link", sorted(needed))
        if link_tbl is None:
            raise ValueError("Source has no 'link' table; cannot build a graph.")
        link = link_tbl.to_pandas()

        for col in (from_col, to_col):
            if col not in link.columns:
                raise ValueError(f"link table is missing required column {col!r}.")

        # Cost and barrier are evaluated over the link columns.
        try:
            weight = _to_float_array(link.eval(cost) if not _is_bare_column(cost, link) else link[cost])
        except Exception as exc:
            raise ValueError(f"Could not evaluate cost expression {cost!r}: {exc}") from exc

        keep = np.ones(len(link), dtype=bool)
        if barrier is not None:
            try:
                barrier_mask = pd.Series(link.eval(barrier)).fillna(False).to_numpy(dtype=bool)
            except Exception as exc:
                raise ValueError(f"Could not evaluate barrier expression {barrier!r}: {exc}") from exc
            keep &= ~barrier_mask

        keep &= np.isfinite(weight)

        # Directedness per link row (True == one-way from->to).
        is_directed = cls._resolve_directed(link, directed)

        # Node-id universe: node table first, then any endpoints only seen on links.
        node_ids, coords, nodes_only_in_links = cls._build_node_universe(
            src, link, from_col, to_col, node_id_col, x_col, y_col
        )
        node_index = pd.Index(node_ids)

        from_idx = node_index.get_indexer(link[from_col].to_numpy())
        to_idx = node_index.get_indexer(link[to_col].to_numpy())
        # get_indexer returns -1 for unknown; the universe includes all endpoints
        # so this should not happen, but guard anyway.
        keep &= (from_idx >= 0) & (to_idx >= 0)

        link_ids = (link[link_id_col] if link_id_col in link.columns else pd.Series(link.index)).to_numpy()

        u = from_idx[keep]
        v = to_idx[keep]
        w = weight[keep]
        lid = link_ids[keep]
        directed_keep = is_directed[keep]

        if np.any(w < 0):
            raise ValueError(
                "Negative edge costs are not supported (Dijkstra requires "
                "non-negative weights). Check the cost expression."
            )

        # Add reverse edges for two-way links.
        rev = ~directed_keep
        U = np.concatenate([u, v[rev]])
        V = np.concatenate([v, u[rev]])
        W = np.concatenate([w, w[rev]])
        LID = np.concatenate([lid, lid[rev]])

        n = len(node_index)
        csr, edge_link_id = cls._assemble_csr(U, V, W, LID, n)

        meta = {
            "mode": mode,
            "cost": cost,
            "barrier": barrier,
            "directed": directed,
            "n_nodes": n,
            "n_edges": int(csr.nnz),
            "nodes_only_in_links": list(nodes_only_in_links),
        }
        logger.info("Built GMNSGraph: %d nodes, %d edges (mode=%s)", n, csr.nnz, mode)
        graph = cls(node_index=node_index, coords=coords, csr=csr, edge_link_id=edge_link_id, meta=meta)
        graph._source = src
        return graph

    @staticmethod
    def _resolve_directed(link: pd.DataFrame, directed) -> np.ndarray:
        n = len(link)
        if directed is None:
            if "directed" in link.columns:
                return pd.Series(link["directed"]).fillna(True).to_numpy(dtype=bool)
            return np.ones(n, dtype=bool)
        if isinstance(directed, str):
            if directed not in link.columns:
                raise ValueError(f"directed column {directed!r} not found in link table.")
            return pd.Series(link[directed]).fillna(True).to_numpy(dtype=bool)
        return np.full(n, bool(directed))

    @staticmethod
    def _build_node_universe(src, link, from_col, to_col, node_id_col, x_col, y_col):
        node_tbl = src.table("node", [node_id_col, x_col, y_col])
        endpoints = pd.unique(pd.concat([link[from_col], link[to_col]], ignore_index=True))
        if node_tbl is None:
            # No node table: derive nodes purely from link endpoints.
            coords = np.full((len(endpoints), 2), np.nan, dtype="float64")
            return endpoints, coords, list(endpoints.tolist())

        node = node_tbl.to_pandas()
        declared = node[node_id_col].to_numpy()
        declared_set = set(declared.tolist())
        extra = [e for e in endpoints.tolist() if e not in declared_set]
        node_ids = np.concatenate([declared.astype(object), np.array(extra, dtype=object)]) if extra else declared
        coords = np.full((len(node_ids), 2), np.nan, dtype="float64")
        if x_col in node.columns and y_col in node.columns:
            coords[: len(declared), 0] = _to_float_array(node[x_col])
            coords[: len(declared), 1] = _to_float_array(node[y_col])
        return node_ids, coords, extra

    @staticmethod
    def _assemble_csr(U, V, W, LID, n):
        from scipy.sparse import csr_array

        order = np.argsort(U, kind="stable")
        U = U[order]
        V = V[order].astype(np.int32, copy=False)
        W = W[order].astype("float64", copy=False)
        LID = LID[order]
        counts = np.bincount(U, minlength=n)
        indptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(counts, out=indptr[1:])
        csr = csr_array((W, V, indptr), shape=(n, n))
        return csr, LID

    # -- accessors -----------------------------------------------------------

    def index_of(self, node_id) -> int:
        i = self.node_index.get_indexer([node_id])[0]
        if i < 0:
            raise KeyError(f"node_id {node_id!r} is not in the graph.")
        return int(i)

    def node_at(self, index: int):
        return self.node_ids[index]

    @property
    def reverse_csr(self):
        if self._reverse_csr is None:
            self._reverse_csr = self.csr.T.tocsr()
        return self._reverse_csr

    def link_between(self, u_idx: int, v_idx: int):
        """The (min-cost) link_id of the edge from graph index ``u_idx`` to ``v_idx``."""
        start, end = self.csr.indptr[u_idx], self.csr.indptr[u_idx + 1]
        cols = self.csr.indices[start:end]
        hits = np.nonzero(cols == v_idx)[0]
        if len(hits) == 0:
            return None
        best = hits[np.argmin(self.csr.data[start:end][hits])]
        return self.edge_link_id[start + best]

    # -- queries (delegated to sibling modules) ------------------------------

    def connectivity(self, connection: str = "weak"):
        from .connectivity import connectivity

        return connectivity(self, connection=connection)

    def isochrone(self, source_node, cutoff: float):
        from .paths import isochrone

        return isochrone(self, source_node, cutoff)

    def shortest_path(self, source_node, target_node) -> ShortestPathResult:
        from .paths import shortest_path

        return shortest_path(self, source_node, target_node)

    def snap(self, x: float, y: float):
        from .paths import snap

        return snap(self, x, y)

    def to_geodataframe(self, **kwargs):
        from .viz import to_geodataframe

        return to_geodataframe(self, **kwargs)

    @property
    def nbytes(self) -> int:
        """Exact in-memory size of the graph's backing arrays, in bytes.

        Covers the CSR (``data``/``indices``/``indptr``), the edge->link_id map,
        node coordinates, and the node-id array. This is deterministic and
        independent of process noise, so it is the preferred memory metric for
        benchmarking how the graph scales.
        """
        arrays = [
            self.csr.data,
            self.csr.indices,
            self.csr.indptr,
            self.coords,
            np.asarray(self.edge_link_id),
            np.asarray(self.node_ids),
        ]
        return int(sum(a.nbytes for a in arrays))

    def __repr__(self) -> str:
        return f"GMNSGraph(nodes={self.meta['n_nodes']}, edges={self.meta['n_edges']}, mode={self.meta['mode']!r})"


def _is_bare_column(expr: str, df: pd.DataFrame) -> bool:
    return expr in df.columns
