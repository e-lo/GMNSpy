"""The one HTTP call path every adapter uses: JSON in, JSON out, errors typed and scrubbed.

``httpx`` (the ``[nl]`` extra) is imported lazily, so ``gmnspy.llm`` imports without it.
Request headers carry the key, so they never appear in any error. Provider error text
goes through :func:`~gmnspy.llm.secrets.redact` and is truncated. Exceptions are raised
``from None`` so httpx request objects (which hold the headers) aren't chained into tracebacks.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import (
    BadRequest,
    BadResponse,
    InvalidKey,
    LLMError,
    ModelNotFound,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    ToolsUnsupported,
)
from .secrets import origin_of, redact

__all__ = ["DETAIL_MAX_CHARS", "request_json"]

#: Longest provider error detail passed on to the user.
DETAIL_MAX_CHARS = 300


def request_json(
    method: str,
    url: str,
    *,
    provider: str,
    label: str,
    timeout_s: float,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    transport: Any = None,
    secret: str = "",
) -> Any:
    """Send one JSON request and return the decoded reply, or raise a typed :class:`~gmnspy.llm.errors.LLMError`.

    Args:
        method: HTTP method.
        url: Full URL. Never carries a key: keys travel in ``headers``.
        provider: Provider name, recorded on the error.
        label: Provider display name used in messages.
        timeout_s: Whole-request timeout in seconds.
        headers: Request headers, including auth.
        body: JSON body.
        params: Query parameters (never secrets).
        transport: Optional ``httpx`` transport (tests pass an ``httpx.MockTransport``).
        secret: The key in use; scrubbed from any provider error text.

    Returns:
        The decoded JSON reply.
    """
    try:
        import httpx
    except ImportError:
        raise ProviderUnavailable(
            provider, f"{label}: natural-language providers need the [nl] extra: pip install 'gmnspy[nl]'"
        ) from None
    try:
        with httpx.Client(timeout=timeout_s, transport=transport) as client:
            response = client.request(method, url, headers=headers, json=body, params=params)
    except httpx.TimeoutException:
        raise ProviderTimeout(
            provider,
            f"{label} did not answer within {timeout_s:g} s; try again, or raise the timeout in "
            "Settings → Language models.",
        ) from None
    except httpx.TransportError as exc:
        try:
            where = origin_of(url)
        except ValueError:
            where = "the configured endpoint"
        raise ProviderUnavailable(provider, f"could not reach {label} at {where} ({type(exc).__name__}).") from None
    if response.status_code >= 400:
        raise _status_error(response, provider=provider, label=label, secret=secret)
    try:
        return response.json()
    except ValueError:
        raise BadResponse(
            provider, f"{label} returned a reply that is not JSON (HTTP {response.status_code})."
        ) from None


def _status_error(response: Any, *, provider: str, label: str, secret: str) -> LLMError:
    code = response.status_code
    detail = _detail(response, secret)
    suffix = f": {detail}" if detail else ""
    if code in (401, 403):  # no provider detail here: some providers echo part of the rejected key
        return InvalidKey(
            provider, f"{label} rejected the API key (HTTP {code}). Replace it in Settings → Language models."
        )
    if code == 404:
        return ModelNotFound(provider, f"{label}: model or endpoint not found (HTTP 404){suffix}")
    if code == 408:
        return ProviderTimeout(provider, f"{label} timed out (HTTP 408); try again.")
    if code == 429:
        retry = _retry_after(response.headers.get("retry-after"))
        hint = f"retry in {retry:g} s" if retry is not None else "wait a moment and retry"
        return RateLimited(provider, f"{label} rate limit or quota reached (HTTP 429); {hint}.", retry)
    if code >= 500:
        return ProviderUnavailable(provider, f"{label} is unavailable (HTTP {code}){suffix}")
    if "does not support tools" in detail:
        return ToolsUnsupported(provider, f"{label}: this model does not support tool calling{suffix}")
    return BadRequest(provider, f"{label} rejected the request (HTTP {code}){suffix}")


def _detail(response: Any, secret: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text
    else:
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            text = str(error.get("message", ""))
        elif isinstance(error, str):
            text = error
        else:
            text = json.dumps(payload)
    return redact(" ".join(text.split()), secret)[:DETAIL_MAX_CHARS]


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # an HTTP-date: not worth parsing for a hint
