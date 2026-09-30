"""ProjectCard-parity selection modes: all / whole-facility / conditions / ids."""
from importlib import resources

import pandas as pd
import pytest

from gmnspy.select.intent import Facility, SelectionIntent
from gmnspy.select.resolve import resolve_frames


@pytest.fixture(scope="module")
def rdu():
    base = resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet")
    return (pd.read_parquet(base.joinpath("link.parquet")),
            pd.read_parquet(base.joinpath("node.parquet")))


def test_select_all(rdu):
    links, nodes = rdu
    r = resolve_frames(SelectionIntent(select_all=True), links, nodes)
    assert r.status == "resolved"
    assert len(r.link_ids) == len(links)


def test_whole_facility_by_ref(rdu):
    links, nodes = rdu
    r = resolve_frames(SelectionIntent(facility=Facility(ref="I 40")), links, nodes)
    assert r.status == "resolved"
    sel = links[links.link_id.isin(r.link_ids)]
    assert (sel.facility_type == "motorway").all() and len(sel) > 10


def test_whole_facility_surface_street_by_name(rdu):
    links, nodes = rdu
    r = resolve_frames(SelectionIntent(facility=Facility(name="South Miami Boulevard")), links, nodes)
    assert r.status == "resolved"
    sel = links[links.link_id.isin(r.link_ids)]
    assert len(sel) > 0 and (sel.name == "South Miami Boulevard").all()


def test_facility_with_attribute_condition(rdu):
    links, nodes = rdu
    whole = resolve_frames(SelectionIntent(facility=Facility(ref="I 40")), links, nodes)
    four = resolve_frames(SelectionIntent(facility=Facility(ref="I 40"), conditions={"lanes": [4]}), links, nodes)
    assert four.status == "resolved"
    assert set(four.link_ids) < set(whole.link_ids)           # strict subset
    sel = links[links.link_id.isin(four.link_ids)]
    assert (sel.lanes == 4).all()


def test_condition_with_no_matches_is_not_found(rdu):
    links, nodes = rdu
    r = resolve_frames(SelectionIntent(facility=Facility(ref="I 40"), conditions={"lanes": [99]}), links, nodes)
    assert r.status == "not_found"


def test_explicit_link_ids(rdu):
    links, nodes = rdu
    ids = list(links.link_id.iloc[:5])
    r = resolve_frames(SelectionIntent(link_ids=ids), links, nodes)
    assert r.status == "resolved" and sorted(r.link_ids) == sorted(ids)


def test_freeway_segment_still_works(rdu):
    links, nodes = rdu
    r = resolve_frames(SelectionIntent(facility=Facility(ref="I 40", direction="EB"),
                                       from_anchor="South Miami Boulevard", to_anchor="Airport Boulevard"),
                       links, nodes)
    assert r.status == "resolved" and r.link_ids[0] == 5021
