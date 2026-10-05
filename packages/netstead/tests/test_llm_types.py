"""Tests for netstead.llm.types and netstead.llm.errors."""

import dataclasses

import pytest
from netstead.llm.errors import InvalidKey, LLMError, MissingKey, RateLimited
from netstead.llm.types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall


def test_request_is_frozen_with_neutral_defaults():
    req = CompletionRequest(model="m", messages=(Message("user", "hi"),))
    assert (req.system, req.tools, req.force_tool, req.json_schema, req.max_tokens) == ("", (), None, None, 1024)
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.model = "other"  # type: ignore[misc]


def test_completion_defaults_and_tool_call():
    done = Completion(tool_calls=(ToolCall("t", {"a": 1}),))
    assert done.text == "" and done.tool_calls[0].arguments == {"a": 1} and done.input_tokens is None


def test_llm_provider_protocol_is_structural():
    class Dummy:
        name = "dummy"
        label = "Dummy"

        def complete(self, request):
            return Completion(text="ok")

        def list_models(self):
            return ["m"]

    assert isinstance(Dummy(), LLMProvider)
    assert Tool("t", "d", {"type": "object"}).input_schema == {"type": "object"}


def test_errors_carry_provider_and_message():
    exc = RateLimited("gemini", "Gemini rate limit", retry_after_s=20.0)
    assert isinstance(exc, LLMError) and exc.provider == "gemini" and exc.retry_after_s == 20.0
    assert str(MissingKey("openai", "OpenAI: no API key")) == "OpenAI: no API key"
    assert issubclass(InvalidKey, LLMError)
