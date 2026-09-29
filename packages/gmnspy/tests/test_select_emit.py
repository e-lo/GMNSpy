"""Tests for gmnspy.select.emit — SelectionResult -> validated fragment dict."""
import pytest

from gmnspy.select.intent import Facility, SelectionIntent
from gmnspy.select.result import AnchorMatch, SelectionResult
from gmnspy.select.emit import to_fragment, to_projectcard, validate_fragment
from gmnspy.select.errors import SelectError


def _resolved():
    intent = SelectionIntent(
        facility=Facility(ref="I 40", direction="EB"),
        from_anchor="South Miami Boulevard",
        to_anchor="Airport Boulevard",
        utterance="I-40 EB between South Miami Blvd and Airport Blvd",
    )
    return SelectionResult(
        status="resolved",
        intent=intent,
        link_ids=[5019, 5018, 5016, 801],
        node_path=[170510751, 1, 2, 195394331],
        from_match=AnchorMatch("South Miami Boulevard", 170510751, [], 1.0, "gore", "off-ramp diverge"),
        to_match=AnchorMatch("Airport Boulevard", 195394331, [], 1.0, "merge", "on-ramp merge"),
        diagnostics=[],
    )


def test_fragment_uses_gmns_native_keys():
    frag = to_fragment(_resolved())
    assert frag["links"]["link_id"] == [5019, 5018, 5016, 801]
    assert frag["from"]["node_id"] == 170510751
    assert frag["to"]["node_id"] == 195394331
    assert "South Miami" in frag["notes"]


def test_fragment_validates_against_schema():
    frag = to_fragment(_resolved())
    validate_fragment(frag)  # must not raise


def test_projectcard_adapter_maps_keys():
    pc = to_projectcard(_resolved())
    assert pc["links"]["model_link_id"] == [5019, 5018, 5016, 801]
    assert pc["from"]["model_node_id"] == 170510751
    assert pc["to"]["model_node_id"] == 195394331


def test_emit_requires_resolved_status():
    r = _resolved()
    unresolved = SelectionResult(
        status="ambiguous", intent=r.intent, link_ids=[], node_path=[],
        from_match=None, to_match=None, diagnostics=["two candidates for Airport Boulevard"],
    )
    with pytest.raises(SelectError):
        to_fragment(unresolved)
