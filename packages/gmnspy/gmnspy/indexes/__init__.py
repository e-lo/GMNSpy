"""Spatial (STRtree) + graph (igraph) index build/cache/load.

Indexes are **opt-in** (per architecture §6.2): build them when the
caller knows they'll run network-aware scope ops repeatedly. The
auto-build heuristic (threshold-based) lives in :mod:`gmnspy.scope`
(task 3.10) — this package only ships the primitives.

Examples:
    >>> import pytest
    >>> _ = pytest.importorskip("shapely")
    >>> _ = pytest.importorskip("igraph")
    >>> from gmnspy.indexes import SpatialIndex, GraphIndex, build_indexes, cache_path
    >>> cache_path("/tmp/net.duckdb", "spatial", "deadbeefcafef00d").name
    'net.spatial.deadbeef.parquet'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cache import cache_path, load_cached, save_cached
from .graph import GraphIndex
from .spatial import SpatialIndex

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Table

__all__ = [
    "GraphIndex",
    "SpatialIndex",
    "build_indexes",
    "cache_path",
    "load_cached",
    "save_cached",
]


def build_indexes(
    *,
    links: Table,
    nodes: Table | None = None,
    spatial: bool = True,
    graph: bool = True,
) -> tuple[SpatialIndex | None, GraphIndex | None]:
    """Build both indexes from a links + nodes pair, returning ``(spatial, graph)``.

    Either flag can be ``False`` to skip the corresponding build.
    ``graph=True`` requires ``nodes``.

    Raises:
        ValueError: If ``graph=True`` but ``nodes`` is ``None``.

    Examples:
        >>> import pytest
        >>> _ = pytest.importorskip("shapely")
        >>> _ = pytest.importorskip("igraph")
        >>> build_indexes  # doctest: +ELLIPSIS
        <function build_indexes at ...>
    """
    if graph and nodes is None:
        raise ValueError("build_indexes(graph=True) requires a nodes Table")
    spatial_idx = SpatialIndex.build(links) if spatial else None
    graph_idx = GraphIndex.build(links, nodes) if (graph and nodes is not None) else None
    return spatial_idx, graph_idx
