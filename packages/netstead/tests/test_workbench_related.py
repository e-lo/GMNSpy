"""Tests for the workbench's foreign-key relations (read from the GMNS spec, never hard-coded)."""

import json

import pytest
from netstead.fixtures import leavenworth
from netstead.workbench import Session
from netstead.workbench.related import relation_graph


@pytest.fixture(scope="module")
def lw(tmp_path_factory):
    """The Leavenworth handle: link, node, lane, link_tod."""
    tmp = tmp_path_factory.mktemp("rel")
    src = str(leavenworth.parquet_dir())
    env = {"NETSTEAD_CONFIG_DIR": str(tmp / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([src])}
    s = Session(project_dir=tmp, environ=env)
    s.dispatch({"type": "open_network", "source": src})
    return s.registry.get("leavenworth")


@pytest.fixture(scope="module")
def graph(lw):
    return relation_graph(lw.roadway.spec, lw.tables())


def test_foreign_keys_come_from_the_spec(graph):
    fks = {(f.table, f.column, f.ref_table, f.ref_column) for f in graph.fks}
    assert {
        ("link", "from_node_id", "node", "node_id"),
        ("link", "to_node_id", "node", "node_id"),
        ("lane", "link_id", "link", "link_id"),
        ("link_tod", "link_id", "link", "link_id"),
    } <= fks


def test_self_references_and_absent_tables_are_left_out(graph):
    assert all(f.table != f.ref_table for f in graph.fks)  # link.parent_link_id, node.parent_node_id
    assert not any(f.ref_table in {"geometry", "zone", "time_set_definitions"} for f in graph.fks)  # not browsable


def test_primary_keys_prefer_the_spec(graph):
    assert graph.pks == {"link": "link_id", "node": "node_id", "lane": "lane_id", "link_tod": "link_tod_id"}


def test_label_names_the_relation(graph):
    fk = next(f for f in graph.fks if f.table == "lane")
    assert fk.label == "lane.link_id → link"
