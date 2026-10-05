"""Ollama ``/api/chat`` adapter: local models (e.g. Qwen), no key.

A model without tool support answers HTTP 400 "... does not support tools", which
:mod:`gmnspy.llm._http` maps to :class:`~gmnspy.llm.errors.ToolsUnsupported`. Then
:mod:`gmnspy.llm.structured` retries the same model in JSON mode, where ``json_schema``
becomes Ollama's native ``format`` constraint.
"""

from __future__ import annotations

from typing import Any

from ..types import Completion, CompletionRequest
from ._base import HTTPProvider
from .openai import chat_messages, function_tools, parse_function_calls

__all__ = ["OllamaProvider"]


class OllamaProvider(HTTPProvider):
    """``POST {base_url}/api/chat`` (non-streaming). Ollama cannot force a tool; the repair loop covers that."""

    name = "ollama"
    label = "Ollama"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one chat turn; ``message.tool_calls`` become :class:`~gmnspy.llm.types.ToolCall`."""
        body: dict[str, Any] = {
            "model": request.model,
            "messages": chat_messages(request),
            "stream": False,
            "options": {"num_predict": request.max_tokens},
        }
        if request.tools:
            body["tools"] = function_tools(request)
        if request.json_schema is not None:
            body["format"] = request.json_schema
        if request.temperature is not None:
            body["options"]["temperature"] = request.temperature
        data = self._call("POST", "/api/chat", body)
        try:
            message = data["message"]
            calls, leftover = parse_function_calls(message.get("tool_calls"))
        except (KeyError, TypeError, AttributeError) as exc:
            raise self._bad_shape(exc) from None
        text = "\n".join(part for part in (message.get("content") or "", leftover) if part)
        return Completion(
            tool_calls=calls,
            text=text,
            stop_reason=data.get("done_reason"),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    def list_models(self) -> list[str]:
        """Installed model tags (``GET /api/tags``)."""
        data = self._call("GET", "/api/tags")
        try:
            return [m["name"] for m in data["models"]]
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise self._bad_shape(exc) from None
