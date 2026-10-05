"""Shared plumbing for the HTTP adapters: key custody, ``repr`` hygiene, and the one call path."""

from __future__ import annotations

from typing import Any, ClassVar

from .._http import request_json
from ..errors import BadResponse
from ..types import Completion, CompletionRequest

__all__ = ["HTTPProvider"]


class HTTPProvider:
    """Base for adapters: holds the key privately and sends every request through :func:`request_json`."""

    name: str
    label: str
    DEFAULT_BASE_URL: ClassVar[str]

    def __init__(
        self, *, api_key: str = "", base_url: str | None = None, timeout_s: float = 60.0, transport: Any = None
    ) -> None:
        """Hold the key (never exposed), endpoint, timeout and an optional ``httpx`` transport (tests)."""
        self._key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    def __repr__(self) -> str:
        """Endpoint only: the key must never reach a traceback, a log or a debugger summary."""
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one completion (each adapter implements this)."""
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """Model ids the endpoint serves (each adapter implements this)."""
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {}

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None
    ) -> Any:
        return request_json(
            method,
            f"{self.base_url}{path}",
            provider=self.name,
            label=self.label,
            timeout_s=self.timeout_s,
            headers=self._headers(),
            body=body,
            params=params,
            transport=self._transport,
            secret=self._key,
        )

    def _bad_shape(self, exc: Exception) -> BadResponse:
        return BadResponse(self.name, f"{self.label} returned an unexpected reply ({type(exc).__name__}: {exc}).")
