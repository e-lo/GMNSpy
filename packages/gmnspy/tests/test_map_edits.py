"""Tests for :mod:`gmnspy.map.edits` — edit-log Phase 1.

The edit log is the bridge from the interactive viewer (which collects
proposed fixes per user click) to the Python world (which applies them
deterministically and saves). The format is intentionally simple — a
``list[Edit]`` per session, YAML on disk, PK-indexed so it survives row
reordering.
"""

from __future__ import annotations

import pandas as pd
import pytest
from datagrove.engines.pandas_engine import PandasEngine
from gmnspy import Network
from gmnspy.map.edits import Edit, EditLog, apply_edits, dump_edit_log, load_edit_log


@pytest.fixture
def tiny_net(tmp_path) -> Network:
    """Small network with a known free_speed column we can test edits against."""
    link = pd.DataFrame(
        {
            "link_id": [1, 2, 3],
            "from_node_id": [1, 2, 3],
            "to_node_id": [2, 3, 1],
            "directed": [True, True, True],
            "length": [100.0, 200.0, 150.0],
            "free_speed": [40.0, 35.0, None],
        }
    )
    node = pd.DataFrame(
        {
            "node_id": [1, 2, 3],
            "x_coord": [-120.6, -120.5, -120.4],
            "y_coord": [47.5, 47.6, 47.7],
        }
    )
    csv = tmp_path / "n"
    csv.mkdir()
    link.to_csv(csv / "link.csv", index=False)
    node.to_csv(csv / "node.csv", index=False)
    return Network.from_source(csv, engine=PandasEngine())


# ---------------------------------------------------------------------------
# Edit + EditLog data types
# ---------------------------------------------------------------------------


def test_edit_carries_pk_not_positional_row():
    """An Edit is identified by its primary-key dict, not by a positional row.

    Positional row indices aren't stable across re-runs (re-orders,
    deletes, partial loads). PKs survive.
    """
    e = Edit(
        id="e1",
        kind="fix",
        table="link",
        pk={"link_id": 42},
        column="free_speed",
        from_value=None,
        to_value=25,
    )
    assert e.pk == {"link_id": 42}
    assert e.kind == "fix"


def test_edit_log_is_serialisable_roundtrip_via_yaml(tmp_path):
    """An EditLog round-trips through YAML on disk unchanged."""
    log = EditLog(
        source="./tiny",
        spec_version="0.97",
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 3},
                column="free_speed",
                from_value=None,
                to_value=25,
                reason="schema.required",
                issue_id="i0",
            )
        ],
    )
    path = tmp_path / "edits.yaml"
    dump_edit_log(log, path)
    loaded = load_edit_log(path)
    assert loaded.source == log.source
    assert loaded.spec_version == "0.97"
    assert len(loaded.edits) == 1
    assert loaded.edits[0].pk == {"link_id": 3}
    assert loaded.edits[0].to_value == 25


def test_load_edit_log_rejects_unknown_schema_version(tmp_path):
    """A future schema bump should be a loud error, not silent misparse."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("edit_log:\n  schema_version: '99'\n  edits: []\n")
    with pytest.raises(ValueError, match="schema_version"):
        load_edit_log(bad)


# ---------------------------------------------------------------------------
# apply_edits — the deterministic replay path
# ---------------------------------------------------------------------------


def test_apply_edits_applies_a_simple_value_fix(tiny_net):
    """A fix that sets link[link_id=3].free_speed from null → 25 succeeds and mutates."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 3},
                column="free_speed",
                from_value=None,
                to_value=25,
            )
        ]
    )
    result = apply_edits(tiny_net, log)
    assert len(result.applied) == 1
    assert not result.skipped
    df = result.net.links.to_pandas()
    new_val = df[df["link_id"] == 3]["free_speed"].iloc[0]
    assert new_val == 25


def test_apply_edits_skips_when_pk_not_found(tiny_net):
    """A fix whose PK doesn't exist in the table is skipped with a reason."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 9999},
                column="free_speed",
                from_value=None,
                to_value=25,
            )
        ]
    )
    result = apply_edits(tiny_net, log)
    assert not result.applied
    assert len(result.skipped) == 1
    assert "pk" in result.skipped[0].reason.lower() or "found" in result.skipped[0].reason.lower()


def test_apply_edits_skips_on_value_drift(tiny_net):
    """If from_value doesn't match the table's current value, skip + report."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 1},
                column="free_speed",
                from_value=99,  # actual is 40
                to_value=25,
            )
        ]
    )
    result = apply_edits(tiny_net, log)
    assert not result.applied
    assert len(result.skipped) == 1
    assert "drift" in result.skipped[0].reason.lower() or "match" in result.skipped[0].reason.lower()


def test_apply_edits_with_from_value_none_skips_strict_check(tiny_net):
    """``from_value=None`` is treated as 'don't check' (the most common JS-side case)."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 1},
                column="free_speed",
                from_value=None,
                to_value=25,
            )
        ]
    )
    result = apply_edits(tiny_net, log)
    # link_id=1 had free_speed=40; from_value=None means "don't enforce", so apply succeeds.
    assert len(result.applied) == 1
    df = result.net.links.to_pandas()
    assert df[df["link_id"] == 1]["free_speed"].iloc[0] == 25


def test_apply_edits_unknown_table_is_skipped(tiny_net):
    """An edit pointing at a table the network doesn't have is skipped, not crash."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="nonexistent_table",
                pk={"id": 1},
                column="x",
                from_value=None,
                to_value=1,
            )
        ]
    )
    result = apply_edits(tiny_net, log)
    assert not result.applied
    assert len(result.skipped) == 1


def test_apply_result_summary_includes_counts(tiny_net):
    """ApplyResult.summary() is human-readable, names applied + skipped counts."""
    log = EditLog(
        edits=[
            Edit(
                id="e1",
                kind="fix",
                table="link",
                pk={"link_id": 1},
                column="free_speed",
                from_value=None,
                to_value=25,
            ),
            Edit(
                id="e2",
                kind="fix",
                table="link",
                pk={"link_id": 9999},
                column="free_speed",
                from_value=None,
                to_value=25,
            ),
        ]
    )
    result = apply_edits(tiny_net, log)
    s = result.summary()
    assert "1" in s and "applied" in s.lower()
    assert "1" in s and "skipped" in s.lower()
