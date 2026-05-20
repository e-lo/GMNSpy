"""OPTIONAL EXTRA — network editing with atomic rollback + audit log.

Install via ``pip install gmnspy[clean]`` to pick up shapely + igraph.

Each op composes with :class:`datagrove.editing.Session`:

    >>> import pytest
    >>> _ = pytest.importorskip("shapely")
    >>> # (See packages/gmnspy/tests/test_clean.py for runnable examples.)

Ops in this release:

* :func:`simplify_geometry` — drop redundant vertices or Douglas-Peucker
  simplify.
* :func:`merge_close_nodes` — collapse near-duplicate node pairs;
  rewrite incident links.
* :func:`remove_orphans` — drop nodes with no incident links.
* :func:`recompute_lengths` — set ``link.length`` from geometry
  (planar by default; ``geodesic=True`` for WGS84 haversine).

Deferred for follow-up (filed as issues): ``split_link_at_node``,
``connect_disconnected_components``, ``snap_to_reference``.
"""

from .clean import (
    merge_close_nodes,
    recompute_lengths,
    remove_orphans,
    simplify_geometry,
)
from .errors import CleanError

__all__ = [
    "CleanError",
    "merge_close_nodes",
    "recompute_lengths",
    "remove_orphans",
    "simplify_geometry",
]
