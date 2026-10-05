"""Unit tests for benchmark result records + rendering (netstead.bench.report)."""

from __future__ import annotations

import csv
import io
import json

from netstead.bench import report


def _sample_results():
    return [
        report.BenchResult(
            operation="network_create",
            size="S",
            label="leavenworth:parquet",
            metrics={"median": 0.02, "min": 0.01},
            mem={"peak_rss_mb": 17.0, "frame_mb": 0.2},
            counts={"links": 339, "nodes": 121, "ok": True},
        ),
        report.BenchResult(
            operation="viz_pack",
            size="S",
            label="leavenworth",
            metrics={"seconds_min": 0.001},
            extra={"payload_bytes": 11936, "payload_breakdown": {"links": {"count": 339}}},
        ),
    ]


def test_to_record_hoists_metrics_and_extra():
    record = _sample_results()[1].to_record()
    assert record["operation"] == "viz_pack"
    assert record["seconds_min"] == 0.001
    assert record["payload_bytes"] == 11936
    assert record["payload_breakdown"] == {"links": {"count": 339}}


def test_env_block_has_required_keys():
    env = report.env_block(commit="deadbeef")
    for key in ("machine", "python", "os", "host", "versions", "commit", "timestamp"):
        assert key in env
    assert env["commit"] == "deadbeef"
    assert "netstead" in env["versions"]


def test_build_document_shape():
    doc = report.build_document(_sample_results(), env={"host": "ci"})
    assert doc["schema_version"] == report.SCHEMA_VERSION
    assert doc["env"] == {"host": "ci"}
    assert len(doc["results"]) == 2
    assert doc["results"][0]["operation"] == "network_create"


def test_render_json_round_trips():
    doc = report.build_document(_sample_results(), env={"host": "ci"})
    parsed = json.loads(report.render_json(doc))
    assert parsed["schema_version"] == report.SCHEMA_VERSION
    assert parsed["results"][0]["counts"]["links"] == 339


def test_render_csv_header_and_rows():
    doc = report.build_document(_sample_results(), env={"host": "ci"})
    text = report.render_csv(doc["results"])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    # Nested dicts are flattened to dotted columns.
    assert "counts.links" in rows[0]
    assert rows[0]["counts.links"] == "339"
    # Nested dicts are flattened to dotted columns, not exploded into one cell.
    assert rows[1]["payload_breakdown.links.count"] == "339"


def test_render_csv_empty_is_empty_string():
    assert report.render_csv([]) == ""


def test_render_markdown_has_tables_and_caveats():
    doc = report.build_document(_sample_results(), env=report.env_block())
    md = report.render_markdown(doc)
    assert "## network_create" in md
    assert "## viz_pack" in md
    assert "leavenworth:parquet" in md
    assert "## Caveats" in md
    assert "buffer manager" in md  # the DuckDB memory honesty caveat
    assert "_Environment:" in md
