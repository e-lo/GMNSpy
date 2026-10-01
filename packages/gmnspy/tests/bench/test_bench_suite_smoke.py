"""End-to-end smoke of the benchmark suite (Layer A macro runner).

Marked ``perf`` so the bench workflow discovers it and the fast test job can
deselect it with ``-m "not perf"``. It runs the real suite on the small
bundled fixture with minimal repeats — fast, and it proves the create /
selection / viz-pack paths wire together and that the count co-assertion holds
(a "fast" run that dropped rows must fail, not pass).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.perf


def test_run_suite_small_fixture_shape_and_counts():
    suite = pytest.importorskip("gmnspy.bench.suite")
    pytest.importorskip("gmnspy.select")  # selection needs the [nl] extra

    doc = suite.run_suite(sizes=("S",), repeats=1, warm_repeats=2)

    assert doc["schema_version"] == "1"
    assert "env" in doc and "versions" in doc["env"]

    operations = {r["operation"] for r in doc["results"]}
    assert {"network_create", "selection", "viz_pack"} <= operations

    creates = [r for r in doc["results"] if r["operation"] == "network_create"]
    assert creates, "expected at least one network_create result"
    for record in creates:
        # Correctness co-assertion: counts must match the fixture's expected.
        assert record["counts"]["ok"] is True

    packs = [r for r in doc["results"] if r["operation"] == "viz_pack"]
    assert packs and packs[0]["payload_bytes"] > 0
