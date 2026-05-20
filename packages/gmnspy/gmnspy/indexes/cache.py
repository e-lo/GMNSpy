"""Sidecar parquet cache for built indexes.

Cache layout — ``{source.parent}/_gmnspy_indexes/{network.stem}.{kind}.{hash[:8]}.parquet``.
Indexes are content-addressed: a single-byte edit to the source link/node
tables produces a new content hash, a new cache filename, and a fresh
re-build. Stale sidecars linger until ``gmnspy index drop`` (Phase 4).

Format: a single-row pyarrow table with a ``payload`` binary column
holding the pickled index. Parquet (not raw pickle) so the sidecar fits
the broader sidecar story (``_gmnspy_meta.json``, ``_history.parquet``).
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

__all__ = ["cache_path", "load_cached", "save_cached"]


def cache_path(network_source: str, index_kind: str, content_hash: str) -> Path:
    """Compute the sidecar parquet path for an index cached against a network.

    Args:
        network_source: Filesystem path / URI of the network the index describes.
        index_kind: Short label (``"spatial"``, ``"graph"``).
        content_hash: Hex digest of the underlying table content (see
            :func:`datagrove.validation.hash_table`). Only the first 8
            characters land in the filename.

    Examples:
        >>> from gmnspy.indexes import cache_path
        >>> cache_path("/tmp/net.duckdb", "spatial", "abcdef1234").name
        'net.spatial.abcdef12.parquet'
    """
    src = Path(network_source)
    return src.parent / "_gmnspy_indexes" / f"{src.stem}.{index_kind}.{content_hash[:8]}.parquet"


def save_cached(path: Path, obj: Any) -> None:
    """Pickle ``obj`` into a single-row parquet at ``path`` (parent dir auto-created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"payload": [pickle.dumps(obj)]}), path)


def load_cached(path: Path) -> Any | None:
    """Load a previously cached object, or ``None`` if ``path`` is missing.

    A missing or unreadable cache is treated as a miss; callers fall
    back to rebuild. Corrupt sidecars are not eagerly deleted — the
    orchestrator surfaces a warning so a maintainer can triage.
    """
    if not path.is_file():
        return None
    return pickle.loads(pq.read_table(path).column("payload")[0].as_py())
