"""Resolver tests against the committed rdu_i40 fixture (real I-40 interchanges)."""
from importlib import resources

import pandas as pd
import pytest

from gmnspy.select.intent import Facility, SelectionIntent
from gmnspy.select.resolve import resolve_frames


@pytest.fixture(scope="module")
def rdu():
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    links = pd.read_parquet(base.joinpath("link.parquet"))
    nodes = pd.read_parquet(base.joinpath("node.parquet"))
    return links, nodes


def _intent(direction, a, b):
    return SelectionIntent(
        facility=Facility(ref="I 40", direction=direction),
        from_anchor=a, to_anchor=b,
        utterance=f"I-40 {direction} between {a} and {b}",
    )


def test_resolves_eb_between_two_interchanges(rdu):
    links, nodes = rdu
    r = resolve_frames(_intent("EB", "South Miami Boulevard", "Airport Boulevard"), links, nodes)
    assert r.status == "resolved"
    assert r.link_ids, "expected a non-empty link path"
    # every selected link is an I-40 mainline motorway link
    sel = links[links.link_id.isin(r.link_ids)]
    assert (sel.facility_type == "motorway").all()
    assert sel["ref"].apply(lambda x: "40" in str(x)).all()
    # path endpoints match the resolved anchor nodes
    assert r.node_path[0] == r.from_match.node_id
    assert r.node_path[-1] == r.to_match.node_id
    # gore/merge rule: upstream=gore (off-ramp diverge), downstream=merge (on-ramp)
    assert r.from_match.kind == "gore"
    assert r.to_match.kind == "merge"


def test_direction_reverses_path(rdu):
    links, nodes = rdu
    eb = resolve_frames(_intent("EB", "South Miami Boulevard", "Airport Boulevard"), links, nodes)
    wb = resolve_frames(_intent("WB", "Airport Boulevard", "South Miami Boulevard"), links, nodes)
    assert eb.status == wb.status == "resolved"
    # opposite carriageways -> disjoint directed link sets
    assert set(eb.link_ids).isdisjoint(set(wb.link_ids))


def test_unknown_facility_not_found(rdu):
    links, nodes = rdu
    r = resolve_frames(_intent("EB", "South Miami Boulevard", "Airport Boulevard")
                       .__class__(facility=Facility(ref="I 999", direction="EB"),
                                  from_anchor="South Miami Boulevard", to_anchor="Airport Boulevard"),
                       links, nodes)
    assert r.status == "not_found"


def test_golden_eb_south_miami_to_airport(rdu):
    """Regression lock: exact resolved link path + gore/merge nodes."""
    links, nodes = rdu
    r = resolve_frames(_intent("EB", "South Miami Boulevard", "Airport Boulevard"), links, nodes)
    assert r.link_ids == [5021, 5019, 5018, 5016, 801, 267, 5015, 5010, 5011, 5009, 5008, 10201, 10200, 7262]
    assert r.from_match.node_id == 170505098 and r.from_match.kind == "gore"
    assert r.to_match.node_id == 195387716 and r.to_match.kind == "merge"


def test_unknown_anchor_is_not_resolved(rdu):
    links, nodes = rdu
    r = resolve_frames(_intent("EB", "Nonexistent Street XYZ", "Airport Boulevard"), links, nodes)
    assert r.status in {"not_found", "ambiguous"}
    assert r.from_match is None or r.from_match.node_id is None
