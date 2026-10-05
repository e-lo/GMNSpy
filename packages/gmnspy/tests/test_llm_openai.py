"""Tests for the OpenAI Chat Completions adapter."""

from dataclasses import replace

import pytest
from gmnspy.llm.errors import InvalidKey
from gmnspy.llm.providers.openai import OpenAIProvider
from gmnspy.llm.types import CompletionRequest, Message, Tool

pytestmark = pytest.mark.usefixtures("no_network")

KEY = "sk-proj-TESTKEYabcdefghijklmnopqrstuvwx"
TOOL = Tool("emit", "Emit a thing.", {"type": "object", "properties": {"x": {"type": "integer"}}})
REQUEST = CompletionRequest(
    model="gpt-4.1-mini",
    messages=(Message("user", "hi"), Message("assistant", "prev"), Message("user", "again")),
    system="sys",
    tools=(TOOL,),
    force_tool="emit",
)


def _reply(arguments: str, content=None):
    call = {"id": "c1", "type": "function", "function": {"name": "emit", "arguments": arguments}}
    message = {"role": "assistant", "content": content, "tool_calls": [call]}
    return {
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5},
    }


def _provider(fake_api, **kw):
    return OpenAIProvider(api_key=KEY, transport=fake_api.transport(), **kw)


def test_request_shape_and_parsing(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply('{"x": 3}'))
    done = _provider(fake_api).complete(REQUEST)
    req = fake_api.requests[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert fake_api.body() == {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "prev"},
            {"role": "user", "content": "again"},
        ],
        "max_tokens": 1024,
        "tools": [
            {
                "type": "function",
                "function": {"name": "emit", "description": "Emit a thing.", "parameters": TOOL.input_schema},
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "emit"}},
    }
    assert done.tool_calls[0].arguments == {"x": 3}
    assert (done.stop_reason, done.input_tokens, done.output_tokens) == ("tool_calls", 20, 5)


def test_reasoning_tier_model_uses_max_completion_tokens(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply("{}"))
    _provider(fake_api).complete(replace(REQUEST, model="o3-mini"))
    body = fake_api.body()
    assert body["max_completion_tokens"] == 1024 and "max_tokens" not in body


def test_unparseable_arguments_come_back_as_text(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply('{"x": 3'))
    done = _provider(fake_api).complete(REQUEST)
    assert done.tool_calls == () and done.text == '{"x": 3'


def test_compatible_endpoint_via_base_url(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply("{}"))
    _provider(fake_api, base_url="http://localhost:1234/v1/").complete(REQUEST)
    assert str(fake_api.requests[0].url) == "http://localhost:1234/v1/chat/completions"


def test_list_models(fake_api):
    fake_api.add("GET", "/v1/models", body={"object": "list", "data": [{"id": "gpt-4.1-mini"}, {"id": "gpt-4.1"}]})
    assert _provider(fake_api).list_models() == ["gpt-4.1-mini", "gpt-4.1"]


def test_invalid_key_message_omits_provider_detail(fake_api):
    body = {"error": {"message": "Incorrect API key provided: sk-proj-****uvwx."}}
    fake_api.add("POST", "/v1/chat/completions", status=401, body=body)
    with pytest.raises(InvalidKey) as info:
        _provider(fake_api).complete(REQUEST)
    assert "Incorrect" not in str(info.value)
    assert str(info.value).startswith("OpenAI rejected the API key (HTTP 401)")


def test_context_leads_the_system_turn_and_temperature_is_sent(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply("{}"))
    _provider(fake_api).complete(replace(REQUEST, context="GUIDE", temperature=0.2))
    body = fake_api.body()
    assert body["messages"][0] == {"role": "system", "content": "GUIDE\n\nsys"} and body["temperature"] == 0.2
