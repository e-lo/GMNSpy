"""User-facing, secret-free LLM provider errors.

Every message is written for the person at the keyboard and is safe to show in the
browser, record in history, and log: adapters build them from status codes and
*scrubbed* provider detail (:func:`netstead.llm.secrets.redact`), never from request headers.
"""

from __future__ import annotations

__all__ = [
    "BadRequest",
    "BadResponse",
    "InvalidKey",
    "LLMError",
    "MissingKey",
    "ModelNotFound",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimited",
    "ToolsUnsupported",
]


class LLMError(Exception):
    """A provider call failed. ``str(exc)`` is the user-facing message."""

    def __init__(self, provider: str, message: str) -> None:
        """Record which provider failed and the message to show."""
        super().__init__(message)
        self.provider = provider


class MissingKey(LLMError):
    """No API key is configured for the provider (or its endpoint)."""


class InvalidKey(LLMError):
    """The provider rejected the key (HTTP 401/403)."""


class RateLimited(LLMError):
    """The provider throttled the request or the quota is spent (HTTP 429)."""

    def __init__(self, provider: str, message: str, retry_after_s: float | None = None) -> None:
        """Also keep the provider's ``Retry-After`` hint when it sent one."""
        super().__init__(provider, message)
        self.retry_after_s = retry_after_s


class ProviderTimeout(LLMError):
    """The provider did not answer within the configured timeout."""


class ProviderUnavailable(LLMError):
    """The provider could not be reached, or answered with a server error (5xx)."""


class ModelNotFound(LLMError):
    """The model (or endpoint path) does not exist for this key/server (HTTP 404)."""


class BadRequest(LLMError):
    """The provider rejected the request for another reason (HTTP 4xx)."""


class BadResponse(LLMError):
    """The provider's reply was not the expected shape (or it blocked the request)."""


class ToolsUnsupported(LLMError):
    """The model cannot do tool calling; the caller may retry the same model in JSON mode."""
