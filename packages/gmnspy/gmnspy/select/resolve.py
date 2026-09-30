"""Resolve a SelectionIntent to GMNS link/node ids against a network.

Pipeline (engine-agnostic; operates on materialized link/node frames):
  1. facility narrowing  — normalized-exact ref/name among mainline links
  2. direction filter     — link bearing within +-75 deg of the cardinal
  3. anchor resolution    — gore/merge rule (see :mod:`gmnspy.select.anchors`)
  4. path                 — shortest path along the directed carriageway
  5. validate + classify  — contiguity + status
"""
from __future__ import annotations

import collections

from . import anchors as _anchors
from ._support import (
    bearing_deg,
    dijkstra_links,
    is_link_class,
    link_length,
    matches_direction,
    norm_name,
    norm_ref,
    to_py,
)
from .intent import SelectionIntent
from .result import SelectionResult

__all__ = ["resolve_frames", "resolve"]

_MAINLINE_TYPES = ("motorway", "trunk")


def _node_coords(nodes):
    nx = dict(zip(nodes["node_id"], nodes["x_coord"]))
    ny = dict(zip(nodes["node_id"], nodes["y_coord"]))
    return nx, ny


def _facility_links(links, facility):
    """Mainline links whose normalized ref or name matches the facility."""
    if facility.ref:
        want = norm_ref(facility.ref)
        hit = links["ref"].apply(lambda r: bool(want & norm_ref(r)))
    else:
        want_name = norm_name(facility.name)
        hit = links["name"].apply(lambda n: bool(want_name) and want_name == norm_name(n))
    mainline = links[hit & links["facility_type"].isin(_MAINLINE_TYPES)]
    return mainline


def _filter_direction(mainline, direction, nx, ny):
    if direction is None:
        return mainline
    keep = [
        row["link_id"]
        for _, row in mainline.iterrows()
        if matches_direction(bearing_deg(nx, ny, row["from_node_id"], row["to_node_id"]), direction)
    ]
    return mainline[mainline["link_id"].isin(keep)]


def resolve_frames(intent: SelectionIntent, links, nodes) -> SelectionResult:
    """Resolve against materialized pandas link/node frames (the testable core)."""
    nx, ny = _node_coords(nodes)
    mainline = _facility_links(links, intent.facility)
    if mainline.empty:
        return SelectionResult("not_found", intent, diagnostics=[
            f"no mainline links matched facility ref/name {intent.facility.ref or intent.facility.name!r}"])

    directed = _filter_direction(mainline, intent.facility.direction, nx, ny)
    if directed.empty:
        return SelectionResult("not_found", intent, diagnostics=[
            f"facility found but no links in direction {intent.facility.direction!r}"])

    directed_nodes = set(directed["from_node_id"]) | set(directed["to_node_id"])
    mainline_nodes = set(mainline["from_node_id"]) | set(mainline["to_node_id"])
    interchanges = _anchors.classify_interchanges(links, directed_nodes, mainline_nodes)

    from_m = _anchors.resolve_anchor(intent.from_anchor, "from", links, interchanges)
    to_m = _anchors.resolve_anchor(intent.to_anchor, "to", links, interchanges)

    diags = [from_m.detail, to_m.detail]
    if from_m.node_id is None or to_m.node_id is None:
        return SelectionResult("not_found", intent, from_match=from_m, to_match=to_m, diagnostics=diags)

    # directed adjacency over the carriageway
    adj = collections.defaultdict(list)
    for _, r in directed.iterrows():
        adj[r["from_node_id"]].append((r["to_node_id"], link_length(nx, ny, r), r["link_id"]))
    path = dijkstra_links(adj, from_m.node_id, to_m.node_id)
    if path is None:
        return SelectionResult("not_found", intent, from_match=from_m, to_match=to_m,
                               diagnostics=diags + ["no directed path between resolved anchor nodes"])

    link_ids, node_path = path
    link_ids = [to_py(i) for i in link_ids]
    node_path = [to_py(n) for n in node_path]
    status = "resolved"
    if from_m.candidates or to_m.candidates:
        status = "ambiguous"
        diags.append("multiple interchange candidates; picked nearest (see candidates)")
    return SelectionResult(status, intent, link_ids=link_ids, node_path=node_path,
                           from_match=from_m, to_match=to_m, diagnostics=diags)


def resolve(intent: SelectionIntent, net) -> SelectionResult:
    """Resolve against a gmnspy Network (materializes link/node tables)."""
    def _pd(table):
        return table.to_pandas() if hasattr(table, "to_pandas") else table.execute()

    return resolve_frames(intent, _pd(net.links), _pd(net.nodes))
