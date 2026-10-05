"""Gemini ``generateContent`` adapter (function calling), hand-rolled over httpx.

The key goes in the ``x-goog-api-key`` header, never the ``?key=`` query string:
URLs are logged by httpx and appear in error messages, headers are not.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..errors import BadResponse
from ..types import Completion, CompletionRequest, ToolCall
from ._base import HTTPProvider

__all__ = ["GeminiProvider"]


class GeminiProvider(HTTPProvider):
    """``POST {base_url}/models/{model}:generateContent`` with function declarations (mode ``ANY``)."""

    name = "gemini"
    label = "Gemini"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key}

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one generateContent call; ``functionCall`` parts become :class:`~netstead.llm.types.ToolCall`."""
        body: dict[str, Any] = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in request.messages
            ],
            "generationConfig": {"maxOutputTokens": request.max_tokens},
        }
        if system := request.full_system():
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if request.temperature is not None:
            body["generationConfig"]["temperature"] = request.temperature
        if request.tools:
            # `parametersJsonSchema` takes a full JSON Schema object (vs. the older, narrower
            # `parameters` field) per the Gemini API reference for FunctionDeclaration, checked
            # 2026-10-05: https://ai.google.dev/api/caching#FunctionDeclaration
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {"name": t.name, "description": t.description, "parametersJsonSchema": t.input_schema}
                        for t in request.tools
                    ]
                }
            ]
            if request.force_tool:
                body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [request.force_tool]}
                }
        data = self._call("POST", f"/models/{quote(request.model, safe='')}:generateContent", body)
        if not data.get("candidates"):
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
            raise BadResponse(self.name, f"{self.label} blocked the request ({reason}).")
        try:
            candidate = data["candidates"][0]
            parts = (candidate.get("content") or {}).get("parts") or []
            calls = tuple(
                ToolCall(p["functionCall"]["name"], dict(p["functionCall"].get("args") or {}))
                for p in parts
                if "functionCall" in p
            )
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            usage = data.get("usageMetadata") or {}
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise self._bad_shape(exc) from None
        return Completion(
            tool_calls=calls,
            text=text,
            stop_reason=candidate.get("finishReason"),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    def list_models(self) -> list[str]:
        """Model ids that support ``generateContent`` (``GET /models``), without the ``models/`` prefix."""
        data = self._call("GET", "/models", params={"pageSize": 1000})
        try:
            return [
                m["name"].removeprefix("models/")
                for m in data["models"]
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise self._bad_shape(exc) from None
