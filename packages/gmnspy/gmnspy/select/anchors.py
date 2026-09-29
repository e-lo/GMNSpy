"""Resolve an anchor (cross-street / interchange name) to a mainline node.

Method B (topological, no new GMNS attributes). For a limited-access facility,
an anchor resolves to a mainline node via the *gore/merge* rule:

* the upstream (``from``) anchor -> the **off-ramp diverge (gore)** node, and
* the downstream (``to``) anchor -> the **on-ramp merge** node,

both on the requested-direction carriageway. Surface arterials resolve to a
directly-incident named node. Anchors match on both ``name`` and ``ref``.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass

from ._support import bounded_bfs, is_link_class, norm_name, norm_ref
from .result import AnchorMatch

__all__ = ["Interchanges", "classify_interchanges", "resolve_anchor"]

_MAX_RAMP_HOPS = 8


@dataclass
class Interchanges:
    """Mainline attach nodes on the requested carriageway, by ramp orientation."""

    gore: set   # off-ramp diverge nodes (traffic leaves mainline here)
    merge: set  # on-ramp merge nodes (traffic joins mainline here)


def classify_interchanges(links, directed_nodes: set, mainline_nodes: set) -> Interchanges:
    """Find gore (off-ramp) and merge (on-ramp) nodes on the directed carriageway.

    A ramp (``*_link``) that departs the carriageway (``from_node`` on the
    directed mainline, ``to_node`` off the mainline) marks its ``from_node`` a
    gore node. A ramp that joins the carriageway marks its ``to_node`` a merge
    node.
    """
    gore, merge = set(), set()
    for _, r in links.iterrows():
        if not is_link_class(r["facility_type"]):
            continue
        f, t = r["from_node_id"], r["to_node_id"]
        if f in directed_nodes and t not in mainline_nodes:
            gore.add(f)
        if t in directed_nodes and f not in mainline_nodes:
            merge.add(t)
    return Interchanges(gore=gore, merge=merge)


def _surface_links(links, anchor: str):
    """Links whose name OR ref matches the anchor (excluding motorway/ramps)."""
    a_name = norm_name(anchor)
    a_ref = norm_ref(anchor)
    name_hit = links["name"].apply(lambda n: bool(a_name) and a_name == norm_name(n))
    ref_hit = links["ref"].apply(lambda r: bool(a_ref & norm_ref(r)))
    surf = links[name_hit | ref_hit]
    return surf[~surf["facility_type"].isin(["motorway", "motorway_link"])]


def _ramp_adjacency(links, surface_link_ids: set) -> dict:
    """Undirected adjacency over ramp/connector links + the anchor's own links."""
    adj = collections.defaultdict(list)
    for _, r in links.iterrows():
        if is_link_class(r["facility_type"]) or r["link_id"] in surface_link_ids:
            adj[r["from_node_id"]].append(r["to_node_id"])
            adj[r["to_node_id"]].append(r["from_node_id"])
    return adj


def resolve_anchor(anchor: str, role: str, links, interchanges: Interchanges) -> AnchorMatch:
    """Resolve ``anchor`` to a mainline node for ``role`` in {"from","to"}.

    ``from`` targets gore (off-ramp diverge) nodes; ``to`` targets merge
    (on-ramp) nodes. Nearest match wins; the rest are ranked candidates
    (ambiguity signal for the caller).
    """
    targets = interchanges.gore if role == "from" else interchanges.merge
    kind = "gore" if role == "from" else "merge"
    detail_kind = "off-ramp diverge" if role == "from" else "on-ramp merge"

    surf = _surface_links(links, anchor)
    if surf.empty:
        return AnchorMatch(anchor, None, [], 0.0, "unresolved", "anchor street not found")

    seeds = set(surf["from_node_id"]) | set(surf["to_node_id"])
    adj = _ramp_adjacency(links, set(surf["link_id"]))
    reached = bounded_bfs(adj, seeds, targets, _MAX_RAMP_HOPS)
    if not reached:
        return AnchorMatch(anchor, None, [], 0.0, "unresolved",
                           f"no ramp path to a {detail_kind} node on the carriageway")

    reached.sort(key=lambda x: x[1])
    best_node, hops = reached[0]
    candidates = [n for n, _ in reached[1:]]
    confidence = 1.0 / (1 + hops)
    return AnchorMatch(anchor, best_node, candidates, confidence, kind,
                       f"{detail_kind} node, {hops} ramp hop(s)")
