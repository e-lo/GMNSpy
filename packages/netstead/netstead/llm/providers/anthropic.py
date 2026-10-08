"""Anthropic Messages API adapter (tool use, prompt caching), hand-rolled over httpx."""

from __future__ import annotations

from typing import Any

from ..types import Completion, CompletionRequest, ToolCall
from ._base import HTTPProvider

__all__ = ["API_VERSION", "AnthropicProvider"]

#: Messages API version header. Bump deliberately, together with a contract-fixture re-record.
API_VERSION = "2023-06-01"


class AnthropicProvider(HTTPProvider):
    """``POST {base_url}/v1/messages`` with ``tools`` and a forced ``tool_choice``."""

    name = "anthropic"
    label = "Anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key, "anthropic-version": API_VERSION}

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one Messages call; tool-use blocks become :class:`~netstead.llm.types.ToolCall`."""
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.context:
            # The stable prefix gets a cache breakpoint (Anthropic prompt caching). Below the model's
            # minimum cacheable length the marker is simply ignored: no error, no saving.
            blocks = [{"type": "text", "text": request.context, "cache_control": {"type": "ephemeral"}}]
            if request.system:
                blocks.append({"type": "text", "text": request.system})
            body["system"] = blocks
        elif request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in request.tools
            ]
            if request.force_tool:
                body["tool_choice"] = {"type": "tool", "name": request.force_tool}
        data = self._call("POST", "/v1/messages", body)
        try:
            blocks = data["content"]
            calls = tuple(ToolCall(b["name"], dict(b["input"])) for b in blocks if b.get("type") == "tool_use")
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            usage = data.get("usage") or {}
        except (KeyError, TypeError, AttributeError) as exc:
            raise self._bad_shape(exc) from None
        return Completion(
            tool_calls=calls,
            text=text,
            stop_reason=data.get("stop_reason"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    def list_models(self) -> list[str]:
        """Model ids this key can use (``GET /v1/models``)."""
        data = self._call("GET", "/v1/models", params={"limit": 1000})
        try:
            return [m["id"] for m in data["data"]]
        except (KeyError, TypeError) as exc:
            raise self._bad_shape(exc) from None
