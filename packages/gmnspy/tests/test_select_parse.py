"""Tests for gmnspy.select.parse — utterance -> SelectionIntent."""

import pytest
from gmnspy.config import load_settings
from gmnspy.llm import build_registry
from gmnspy.llm.providers.anthropic import AnthropicProvider
from gmnspy.llm.secrets import KEYRING_SERVICE
from gmnspy.select.errors import IntentError
from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import SELECTION_TOOL, SYSTEM_PROMPT, ClaudeParser, LLMParser, StubParser, make_parser
from gmnspy.select.prompt import PromptContext

pytestmark = pytest.mark.usefixtures("no_network")

UTTER = "I-40 EB between A Street and B Street"


def _anthropic_reply(payload):
    return {
        "content": [{"type": "tool_use", "id": "t", "name": "emit_selection_intent", "input": payload}],
        "stop_reason": "tool_use",
    }


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


def test_claude_parser_is_llm_parser_over_anthropic(fake_api):
    payload = {"facility": {"ref": "I 40", "direction": "EB"}, "from_anchor": "A Street", "to_anchor": "B Street"}
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply(payload))
    parser = ClaudeParser(provider=AnthropicProvider(api_key="k", transport=fake_api.transport()))
    intent = parser.parse(UTTER)
    assert isinstance(parser, LLMParser) and parser.model == "claude-haiku-4-5-20251001"
    assert (intent.facility.ref, intent.facility.direction, intent.from_anchor, intent.utterance) == (
        "I 40",
        "EB",
        "A Street",
        UTTER,
    )
    body = fake_api.body()
    assert body["tools"][0]["input_schema"] == SELECTION_TOOL.input_schema
    assert body["tool_choice"] == {"type": "tool", "name": "emit_selection_intent"}
    assert parser.describe() == {"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "mode": "tools"}


def test_llm_parser_repairs_an_intent_error_then_succeeds(fake_api):
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"modes": ["drive"]}))
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"facility": {"name": "Main Street"}}))
    provider = AnthropicProvider(api_key="k", transport=fake_api.transport())
    intent = LLMParser(provider, "claude-haiku-4-5-20251001").parse("Main Street")
    assert intent.facility.name == "Main Street" and len(fake_api.requests) == 2
    assert "selection requires one of" in fake_api.body()["messages"][-1]["content"]


def test_llm_parser_gives_up_as_intent_error(fake_api):
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"modes": ["drive"]}))
    with pytest.raises(IntentError, match="still invalid after 2 attempts"):
        LLMParser(AnthropicProvider(api_key="k", transport=fake_api.transport()), "m").parse("drive links")


def test_make_parser_stub_default_model_and_explicit_model(tmp_path, isolated_env, fake_keyring, fake_api):
    def parser_for(overrides):
        settings = load_settings(project_dir=tmp_path, environ=isolated_env, overrides=overrides).settings
        registry = build_registry(settings, environ=isolated_env, keyring=fake_keyring, transport=fake_api.transport())
        return make_parser(settings.select, registry)

    stub = parser_for({})
    assert isinstance(stub, StubParser) and stub.describe() == {"provider": "stub", "model": None, "mode": "pattern"}
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "sk-test")
    assert parser_for({"select.provider": "openai"}).model == "gpt-4.1-mini"
    assert parser_for({"select.provider": "openai", "select.model": "gpt-4.1"}).model == "gpt-4.1"


def test_quality_settings_reach_the_request(tmp_path, isolated_env, fake_keyring, fake_api):
    overrides = {"select.provider": "anthropic", "llm.quality.max_repairs": 0, "llm.quality.temperature": 0.3}
    settings = load_settings(project_dir=tmp_path, environ=isolated_env, overrides=overrides).settings
    registry = build_registry(settings, environ=isolated_env, keyring=fake_keyring, transport=fake_api.transport())
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"modes": ["drive"]}))
    with pytest.raises(IntentError, match="after 1 attempts"):
        make_parser(settings.select, registry).parse("drive links")
    assert fake_api.body()["temperature"] == 0.3 and len(fake_api.requests) == 1


def test_prompt_context_is_a_cached_prefix_and_examples_are_per_call(fake_api):
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"facility": {"name": "Page Road"}}))
    context = PromptContext(
        assistant="GUIDE", vocabulary=("Page Road",), examples=(("I-40 EB", {"facility": {"ref": "I 40"}}),)
    )
    LLMParser(AnthropicProvider(api_key="k", transport=fake_api.transport()), "m").parse("Page Rd", context=context)
    cached, per_call = fake_api.body()["system"]
    assert cached["cache_control"] == {"type": "ephemeral"}
    assert cached["text"].startswith(SYSTEM_PROMPT) and "GUIDE" in cached["text"] and "Page Road" in cached["text"]
    assert per_call["text"].startswith("Earlier requests") and '{"facility": {"ref": "I 40"}}' in per_call["text"]
