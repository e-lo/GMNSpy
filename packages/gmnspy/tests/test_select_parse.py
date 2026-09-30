"""Tests for gmnspy.select.parse — utterance -> SelectionIntent."""
from gmnspy.select.parse import StubParser, ClaudeParser
from gmnspy.select.intent import SelectionIntent


def test_stub_parses_route_direction_between():
    intent = StubParser().parse("I-40 EB between South Miami Blvd and Airport Blvd")
    assert isinstance(intent, SelectionIntent)
    assert intent.facility.ref == "I 40"
    assert intent.facility.direction == "EB"
    assert intent.from_anchor == "South Miami Blvd"
    assert intent.to_anchor == "Airport Blvd"


def test_stub_parses_eastbound_word_and_strips_exits():
    intent = StubParser().parse("I-40 eastbound between Harrison Avenue and NC 54 exits")
    assert intent.facility.direction == "EB"
    assert intent.from_anchor == "Harrison Avenue"
    assert intent.to_anchor == "NC 54"


def test_stub_surface_street_no_direction():
    intent = StubParser().parse("Main Street between 1st Ave and 5th Ave")
    assert intent.facility.name == "Main Street"
    assert intent.facility.ref is None
    assert intent.facility.direction is None


def test_stub_from_to_grammar():
    intent = StubParser().parse("I-40 EB from Davis Drive to Aviation Parkway")
    assert intent.facility.ref == "I 40" and intent.facility.direction == "EB"
    assert intent.from_anchor == "Davis Drive" and intent.to_anchor == "Aviation Parkway"


def test_stub_bare_facility_is_whole_selection():
    intent = StubParser().parse("Electra Ave")
    assert intent.facility.name == "Electra Ave"
    assert intent.from_anchor is None and intent.to_anchor is None


def test_claude_parser_reads_tool_use_input():
    class _Block:
        type = "tool_use"
        name = "emit_selection_intent"
        input = {"facility": {"ref": "I 40", "direction": "EB"},
                 "from_anchor": "A Street", "to_anchor": "B Street"}

    class _Resp:
        content = [_Block()]

    class _Messages:
        def create(self, **kwargs):
            return _Resp()

    class FakeClient:
        messages = _Messages()

    intent = ClaudeParser(client=FakeClient()).parse("I-40 EB between A Street and B Street")
    assert intent.facility.ref == "I 40"
    assert intent.facility.direction == "EB"
    assert intent.from_anchor == "A Street"
    assert intent.utterance == "I-40 EB between A Street and B Street"
