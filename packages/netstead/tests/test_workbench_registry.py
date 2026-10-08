"""Tests for the workbench network registry."""

import threading

import pytest
from netstead import Network
from netstead.workbench.registry import NetworkRegistry, default_label


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


def test_slow_build_does_not_block_other_cached_reads(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source)
    h.cached("fast", lambda: "ready")
    building, release = threading.Event(), threading.Event()

    def slow():
        building.set()
        release.wait(5)
        return "slow"

    worker = threading.Thread(target=lambda: h.cached("slow", slow))
    worker.start()
    assert building.wait(5)
    try:
        assert h.cached("fast", lambda: "rebuilt") == "ready"  # not stuck behind the slow build
    finally:
        release.set()
        worker.join(5)
    assert h.cached("slow", lambda: "again") == "slow"


def test_artifact_built_across_a_bump_is_not_cached(net, rdu_source):
    h = NetworkRegistry().add(net, source=rdu_source)

    def build_then_mutate():
        h.bump()  # the network changes while this artifact is being built
        return "stale"

    assert h.cached("k", build_then_mutate) == "stale"
    assert h.cached("k", lambda: "fresh") == "fresh"


def test_remove(net, rdu_source):
    reg = NetworkRegistry()
    h = reg.add(net, source=rdu_source)
    reg.remove(h.id)
    assert len(reg) == 0


def test_derived_copy_is_copy_on_write(rdu_source):
    from corral.editing import Edit
    from corral.editing.apply import apply_edit
    from netstead import Network
    from netstead.workbench.registry import as_pandas, derived_copy

    base = Network.from_source(rdu_source)
    copy_ = derived_copy(base)
    first = int(as_pandas(base.links)["link_id"].iloc[0])
    payload = {"predicate": lambda t: t.link_id == first, "set": {"lanes": 9}}
    edit = Edit(op="update_rows", table="link", payload=payload)
    apply_edit(copy_, edit)
    lanes = lambda net: int(as_pandas(net.links).set_index("link_id").loc[first, "lanes"])  # noqa: E731
    assert lanes(copy_) == 9 and lanes(base) != 9
    assert copy_.dirty_tracker is None and copy_.spec_version == base.spec_version
    assert not base.links.dirty and copy_.links.dirty


def test_summary_reports_derived_from(rdu_source):
    from netstead import Network
    from netstead.workbench.registry import NetworkRegistry

    reg = NetworkRegistry()
    handle = reg.add(Network.from_source(rdu_source), source=rdu_source)
    assert handle.summary()["derived_from"] is None
    handle.derived_from = "base"
    assert handle.summary()["derived_from"] == "base"
