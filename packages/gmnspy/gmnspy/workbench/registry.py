"""Open-network registry: one :class:`NetworkHandle` bundle per loaded network.

A handle bundles components (``roadway`` today; ``transit`` is reserved for the
GTFS feed in phase P6) and carries a ``version`` that every mutation bumps.
Derived artifacts (pandas frames, binary map buffers) are cached per version,
so a mutation invalidates them, unlike the old viz app's permanent caches.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from gmnspy import Network

__all__ = ["COMPONENTS", "Component", "NetworkHandle", "NetworkRegistry", "default_label"]

Component = Literal["roadway", "transit"]
COMPONENTS: tuple[Component, ...] = ("roadway", "transit")

#: Other canonical GMNS tables exposed in the data-table view when present (kept lazy).
_EXTRA_TABLES = ("lanes", "segments", "segment_lanes", "zones", "movements", "link_tod")
#: Directory/file stems too generic to name a network by.
_GENERIC_NAMES = {"csv", "parquet", "duckdb", "zip", "data", "network", ""}


def default_label(source: str) -> str:
    """A human label for ``source``: its stem, or its parent's name when the stem is generic."""
    p = Path(str(source).rstrip("/"))
    for candidate in (p.stem, p.parent.name):
        if candidate not in _GENERIC_NAMES:
            return candidate
    return "network"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "network"


def _as_pandas(table: Any) -> pd.DataFrame:
    return table.to_pandas() if hasattr(table, "to_pandas") else table.execute()


def _extra_tables(net: Network) -> dict[str, Any]:
    """Additional GMNS tables the network carries, kept lazy (best-effort), keyed by singular name."""
    out: dict[str, Any] = {}
    for accessor in _EXTRA_TABLES:
        try:
            tbl = getattr(net, accessor)
            if tbl is not None and tbl.count() > 0:
                out[accessor[:-1] if accessor.endswith("s") else accessor] = tbl
        except (AttributeError, KeyError, ValueError, FileNotFoundError):
            continue
    return out


@dataclass
class NetworkHandle:
    """A loaded network bundle plus its per-version derived-data cache."""

    id: str
    label: str
    source: str
    roadway: Network
    transit: Any | None = None
    version: int = 0
    lineage: list[str] = field(default_factory=list)
    _cache: dict[tuple[str, int], Any] = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def cached(self, key: str, build: Callable[[], Any]) -> Any:
        """Return ``build()`` memoised for the current version."""
        with self._lock:
            slot = (key, self.version)
            if slot not in self._cache:
                self._cache[slot] = build()
            return self._cache[slot]

    def bump(self) -> int:
        """Mark the network mutated: increment ``version`` and drop every cached artifact."""
        with self._lock:
            self.version += 1
            self._cache.clear()
            return self.version

    def links_df(self) -> pd.DataFrame:
        """The roadway ``link`` table as pandas (cached per version)."""
        return self.cached("links_df", lambda: _as_pandas(self.roadway.links))

    def nodes_df(self) -> pd.DataFrame:
        """The roadway ``node`` table as pandas (cached per version)."""
        return self.cached("nodes_df", lambda: _as_pandas(self.roadway.nodes))

    def node_xy(self) -> dict[Any, tuple[float, float]]:
        """``node_id -> (lon, lat)`` for anchor placement (cached per version)."""
        return self.cached(
            "node_xy", lambda: {r.node_id: (float(r.x_coord), float(r.y_coord)) for r in self.nodes_df().itertuples()}
        )

    def tables(self) -> dict[str, Any]:
        """Grid-browsable tables: eager ``link``/``node`` frames plus lazy extras."""
        return self.cached(
            "tables", lambda: {"link": self.links_df(), "node": self.nodes_df(), **_extra_tables(self.roadway)}
        )

    def summary(self) -> dict[str, Any]:
        """JSON-safe description for the session state."""
        return {
            "id": self.id,
            "label": self.label,
            "source": self.source,
            "version": self.version,
            "components": [c for c in COMPONENTS if getattr(self, c) is not None],
            "links": len(self.links_df()),
            "nodes": len(self.nodes_df()),
            "lineage": list(self.lineage),
        }


class NetworkRegistry:
    """Ordered collection of open :class:`NetworkHandle` objects keyed by id."""

    def __init__(self) -> None:
        """Start empty."""
        self._handles: dict[str, NetworkHandle] = {}

    def add(self, net: Network, *, source: str, label: str | None = None, net_id: str | None = None) -> NetworkHandle:
        """Register ``net`` under a unique id derived from ``net_id``/``label``/``source``."""
        derived = default_label(source)
        base = _slug(net_id or label or derived)
        hid, n = base, 2
        while hid in self._handles:
            hid, n = f"{base}-{n}", n + 1
        # an explicit label is kept; a derived one falls back to the unique id on collision
        handle = NetworkHandle(id=hid, label=label or (derived if hid == base else hid), source=source, roadway=net)
        self._handles[hid] = handle
        return handle

    def get(self, net_id: str) -> NetworkHandle:
        """Return the handle for ``net_id`` or raise ``KeyError("unknown network ...")``."""
        try:
            return self._handles[net_id]
        except KeyError:
            raise KeyError(f"unknown network {net_id!r}") from None

    def remove(self, net_id: str) -> None:
        """Forget ``net_id`` (``KeyError`` if unknown)."""
        self.get(net_id)
        del self._handles[net_id]

    def ids(self) -> list[str]:
        """Handle ids in insertion order."""
        return list(self._handles)

    def __iter__(self) -> Iterator[NetworkHandle]:
        """Iterate handles in insertion order."""
        return iter(list(self._handles.values()))

    def __len__(self) -> int:
        """Number of open networks."""
        return len(self._handles)
