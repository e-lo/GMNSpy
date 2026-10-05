"""Tests for gmnspy.llm.structured — one validated tool call, repair loop, JSON-mode fallback."""

import pytest
from gmnspy.llm.errors import InvalidKey, ToolsUnsupported
from gmnspy.llm.structured import StructuredOutputError, request_tool_call
from gmnspy.llm.types import Completion, Tool, ToolCall

TOOL = Tool("emit", "Emit a count.", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})


class Scripted:
    """An LLMProvider that replays scripted Completions (or raises scripted errors) and keeps every request."""

    name = "scripted"
    label = "Scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def list_models(self):
        return []


def _call(n):
    return Completion(tool_calls=(ToolCall("emit", {"n": n}),))


def test_forced_tool_first_try():
    provider = Scripted(_call(3))
    result = request_tool_call(provider, model="m", tool=TOOL, user="three", system="sys")
    assert (result.arguments, result.mode, result.attempts) == ({"n": 3}, "tools", 1)
    req = provider.requests[0]
    assert req.tools == (TOOL,) and req.force_tool == "emit" and req.system == "sys" and req.json_schema is None


def test_schema_error_is_repaired():
    provider = Scripted(_call("three"), _call(3))
    result = request_tool_call(provider, model="m", tool=TOOL, user="three")
    assert result.attempts == 2 and result.arguments == {"n": 3}
    second = provider.requests[1].messages
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert '"three"' in second[1].content
    assert "not usable: n: 'three' is not of type 'integer'" in second[2].content


def test_caller_validation_error_is_repaired():
    seen = []

    def validate(arguments):
        seen.append(arguments)
        if arguments["n"] < 0:
            raise ValueError("n must be positive")

    provider = Scripted(_call(-1), _call(2))
    assert request_tool_call(provider, model="m", tool=TOOL, user="x", validate=validate).arguments == {"n": 2}
    assert "n must be positive" in provider.requests[1].messages[-1].content and len(seen) == 2


def test_gives_up_after_the_repair_budget():
    provider = Scripted(_call("a"), _call("b"))
    with pytest.raises(StructuredOutputError, match="still invalid after 2 attempts"):
        request_tool_call(provider, model="m", tool=TOOL, user="x", max_repairs=1)
    assert len(provider.requests) == 2


def test_tools_unsupported_switches_to_json_mode_on_the_same_model():
    provider = Scripted(ToolsUnsupported("scripted", "no tools"), Completion(text='Here: ```json\n{"n": 4}\n```'))
    result = request_tool_call(provider, model="m", tool=TOOL, user="four", system="sys")
    assert (result.arguments, result.mode) == ({"n": 4}, "json")
    json_request = provider.requests[1]
    assert json_request.model == "m" and json_request.tools == () and json_request.json_schema == TOOL.input_schema
    assert json_request.system.startswith("sys\n\nReply with ONLY one JSON object")
    assert '"required": ["n"]' in json_request.system


def test_text_reply_in_tools_mode_is_accepted_and_nulls_dropped():
    provider = Scripted(Completion(text='{"n": 5, "note": null}'))
    assert request_tool_call(provider, model="m", tool=TOOL, user="x").arguments == {"n": 5}


def test_provider_errors_are_not_retried():
    provider = Scripted(InvalidKey("scripted", "bad key"), _call(1))
    with pytest.raises(InvalidKey):
        request_tool_call(provider, model="m", tool=TOOL, user="x")
    assert len(provider.requests) == 1


def test_json_mode_from_the_start():
    provider = Scripted(Completion(text='{"n": 6}'))
    result = request_tool_call(provider, model="m", tool=TOOL, user="x", json_mode=True)
    assert result.mode == "json" and provider.requests[0].json_schema == TOOL.input_schema


def test_context_and_temperature_reach_every_call_and_json_mode_keeps_the_context():
    provider = Scripted(ToolsUnsupported("scripted", "no tools"), Completion(text='{"n": 1}'))
    request_tool_call(provider, model="m", tool=TOOL, user="x", system="sys", context="GUIDE", temperature=0.0)
    assert [r.context for r in provider.requests] == ["GUIDE", "GUIDE"]
    assert [r.temperature for r in provider.requests] == [0.0, 0.0]
    assert provider.requests[1].system.startswith("sys\n\nReply with ONLY one JSON object")
