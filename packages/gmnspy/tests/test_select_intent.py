"""Tests for gmnspy.select.intent — the structured SelectionIntent value type."""

import pytest
from gmnspy.select.errors import IntentError
from gmnspy.select.intent import Facility, SelectionIntent


def test_valid_intent_with_ref_and_direction():
    intent = SelectionIntent(
        facility=Facility(ref="I 40", direction="EB"),
        from_anchor="South Miami Boulevard",
        to_anchor="Airport Boulevard",
        utterance="I-40 EB between South Miami Blvd and Airport Blvd",
    )
    assert intent.facility.ref == "I 40"
    assert intent.facility.direction == "EB"
    assert intent.from_anchor == "South Miami Boulevard"


def test_facility_requires_ref_or_name():
    with pytest.raises(IntentError):
        SelectionIntent(facility=Facility(), from_anchor="A", to_anchor="B")


def test_invalid_direction_rejected():
    with pytest.raises(IntentError):
        SelectionIntent(
            facility=Facility(ref="I 40", direction="EASTBOUND"),
            from_anchor="A",
            to_anchor="B",
        )


def test_blank_anchor_rejected():
    with pytest.raises(IntentError):
        SelectionIntent(facility=Facility(name="Main St"), from_anchor="  ", to_anchor="B")


def test_direction_optional():
    intent = SelectionIntent(facility=Facility(name="Main Street"), from_anchor="1st Ave", to_anchor="5th Ave")
    assert intent.facility.direction is None
