"""OpenAI Chat Completions adapter; any OpenAI-compatible endpoint works through ``base_url``.

Chat Completions (not the Responses API) is the surface every "OpenAI-compatible" server
speaks: vLLM, LM Studio, OpenRouter, Groq, and both Gemini's and Ollama's compatibility layers.
The helpers here are shared with the Ollama adapter, which uses the same tool shape.
"""

from __future__ import annotations

import json
from typing import Any

from ..types import Completion, CompletionRequest, ToolCall
from ._base import HTTPProvider

__all__ = ["OpenAIProvider", "chat_messages", "function_tools", "parse_function_calls"]


def chat_messages(request: CompletionRequest) -> list[dict[str, str]]:
    """``messages`` with the system prompt (context + system) as the leading ``system`` turn."""
    text = request.full_system()
    system = [{"role": "system", "content": text}] if text else []
    return system + [{"role": m.role, "content": m.content} for m in request.messages]


def function_tools(request: CompletionRequest) -> list[dict[str, Any]]:
    """``tools`` in the OpenAI function shape (Ollama accepts the same)."""
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
        for t in request.tools
    ]


def parse_function_calls(raw_calls: list[dict[str, Any]] | None) -> tuple[tuple[ToolCall, ...], str]:
    """Tool calls from an OpenAI/Ollama message, plus any arguments that weren't a JSON object, as text.

    Unparseable arguments are handed back as text instead of raising, so the structured-output
    repair loop can show the model what went wrong.
    """
    calls: list[ToolCall] = []
    leftovers: list[str] = []
    for call in raw_calls or []:
        function = call["function"]
        raw = function.get("arguments")
        arguments = raw
        if isinstance(raw, str):
            try:
                arguments = json.loads(raw or "{}")
            except json.JSONDecodeError:
                arguments = None
        if isinstance(arguments, dict):
            calls.append(ToolCall(function["name"], arguments))
        else:
            leftovers.append(str(raw))
    return tuple(calls), "\n".join(leftovers)


class OpenAIProvider(HTTPProvider):
    """``POST {base_url}/chat/completions`` with function tools and a forced ``tool_choice``.

    Sends no ``max_tokens``/``max_completion_tokens``: compatible servers disagree on the
    name, and a forced tool call is short.
    """

    name = "openai"
    label = "OpenAI"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._key}"}

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one chat completion; function calls become :class:`~gmnspy.llm.types.ToolCall`."""
        body: dict[str, Any] = {"model": request.model, "messages": chat_messages(request)}
        if request.tools:
            body["tools"] = function_tools(request)
            if request.force_tool:
                body["tool_choice"] = {"type": "function", "function": {"name": request.force_tool}}
        if request.temperature is not None:
            body["temperature"] = request.temperature
        data = self._call("POST", "/chat/completions", body)
        try:
            choice = data["choices"][0]
            message = choice["message"]
            calls, leftover = parse_function_calls(message.get("tool_calls"))
            usage = data.get("usage") or {}
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise self._bad_shape(exc) from None
        text = "\n".join(part for part in (message.get("content") or "", leftover) if part)
        return Completion(
            tool_calls=calls,
            text=text,
            stop_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def list_models(self) -> list[str]:
        """Model ids this key can use (``GET /models``)."""
        data = self._call("GET", "/models")
        try:
            return [m["id"] for m in data["data"]]
        except (KeyError, TypeError) as exc:
            raise self._bad_shape(exc) from None
