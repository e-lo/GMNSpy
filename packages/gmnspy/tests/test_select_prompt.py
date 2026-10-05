"""Tests for gmnspy.select.prompt — grounding vocabulary, examples, close-match hints."""

import pandas as pd
from gmnspy.select.intent import Facility, SelectionIntent
from gmnspy.select.parse import intent_from_payload, payload_from_intent
from gmnspy.select.prompt import PromptContext, close_match_hint, render_prompt, vocabulary_from_links


def test_render_prompt_keeps_stable_parts_first_and_per_call_parts_apart():
    context = PromptContext(assistant="GUIDE", project="NOTES", vocabulary=("I 40", "Page Road"), hint="HINT")
    stable, per_call = render_prompt(context, "SYSTEM")
    assert (
        stable == "SYSTEM\n\nGUIDE\n\nNOTES\n\nStreet names and route numbers in the active network:\nI 40\nPage Road"
    )
    assert per_call == "HINT"
    assert render_prompt(PromptContext(), "SYSTEM") == ("SYSTEM", "")


def test_vocabulary_is_most_frequent_refs_and_names(rdu_source):
    links = pd.read_parquet(f"{rdu_source}/link.parquet")
    vocabulary = vocabulary_from_links(links, 3)
    assert vocabulary == ("I 40", "Page Road", "Airport Boulevard")
    assert len(vocabulary_from_links(links, 500)) == len(set(vocabulary_from_links(links, 500)))


def test_close_match_hint_covers_facility_and_anchors_and_skips_known_names():
    vocabulary = ("I 40", "Airport Boulevard", "South Miami Boulevard", "Page Road")
    intent = SelectionIntent(facility=Facility(ref="I 40"), from_anchor="S Miami Blvd", to_anchor="Page Road")
    hint = close_match_hint(intent, vocabulary, 2)
    assert "'S Miami Blvd'. Closest names: South Miami Boulevard" in hint and "Page Road'" not in hint
    assert close_match_hint(SelectionIntent(facility=Facility(ref="I 40")), vocabulary, 2) == ""
    assert close_match_hint(intent, (), 2) == ""


def test_payload_round_trips_through_the_intent():
    payload = {
        "facility": {"name": "Main Street", "direction": "NB"},
        "from_anchor": "1st Ave",
        "to_anchor": "5th Ave",
        "conditions": {"lanes": [2]},
        "modes": ["drive"],
    }
    assert payload_from_intent(intent_from_payload(payload, "x")) == payload
