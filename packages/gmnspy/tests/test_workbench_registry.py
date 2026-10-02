"""Tests for the workbench network registry."""

import pytest
from gmnspy import Network
from gmnspy.workbench.registry import NetworkRegistry, default_label


@pytest.fixture(scope="module")
def net(rdu_source):
    return Network.from_source(rdu_source)


def test_default_label_skips_generic_dir_names():
    assert default_label("/x/rdu_i40/parquet") == "rdu_i40"
    assert default_label("/x/leavenworth.csv.zip") == "leavenworth.csv"
    assert default_label("") == "network"


def test_add_assigns_unique_slug_ids(net, rdu_source):
    reg = NetworkRegistry()
    a = reg.add(net, source=rdu_source)
    b = reg.add(net, source=rdu_source)
    assert (a.id, b.id) == ("rdu-i40", "rdu-i40-2")
    assert (a.label, b.label) == ("rdu_i40", "rdu-i40-2")
    assert reg.ids() == ["rdu-i40", "rdu-i40-2"]


def test_get_unknown_raises_keyerror_with_message():
    with pytest.raises(KeyError, match="unknown network 'nope'"):
        NetworkRegistry().get("nope")


def test_handle_frames_summary_and_transit_slot(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source, label="RDU")
    assert len(h.links_df()) == 178 and len(h.nodes_df()) == 143
    assert set(h.tables()) >= {"link", "node"}
    s = h.summary()
    assert s["label"] == "RDU" and s["components"] == ["roadway"] and s["version"] == 0 and s["lineage"] == []
    assert h.transit is None


def test_cache_is_keyed_by_version(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source)
    calls = []
    h.cached("k", lambda: calls.append(1) or "v1")
    h.cached("k", lambda: calls.append(1) or "v1")
    assert calls == [1]
    assert h.bump() == 1
    assert h.cached("k", lambda: "v2") == "v2"


def test_remove(net, rdu_source):
    reg = NetworkRegistry()
    h = reg.add(net, source=rdu_source)
    reg.remove(h.id)
    assert len(reg) == 0
