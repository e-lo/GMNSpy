"""Language-model routes: provider status, write-only key management, model lists, connection tests.

None of these are Actions: a key cannot be recorded or replayed without recording the key.
A key write leaves only a status-only ``llm`` SSE event and a log line naming the provider
and the store, never the key. No route returns a key; status is ``{provider, configured, source}``.

On top of the server's Host/Origin guard, key writes and connection tests need a loopback
bind and an ``X-GMNSpy-Secrets: 1`` header. A cross-origin page cannot send that custom
header without a CORS preflight, and this server never approves one.

Request bodies are typed ``Any`` and validated here, by hand: FastAPI's default 422 body
echoes the submitted input, which for a key route would be the key.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from gmnspy.llm import LLMError, ProviderRegistry, SecretStoreError

from ..session import Session

__all__ = ["SECRETS_HEADER", "llm_router"]

logger = logging.getLogger(__name__)

#: Header every key write and connection test must carry (forces a CORS preflight on any cross-origin page).
SECRETS_HEADER = "X-GMNSpy-Secrets"


class _KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SecretStr = Field(min_length=8, max_length=512)


class _TestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str | None = None


def llm_router(session: Session, *, allow_key_writes: bool) -> APIRouter:
    """Build the ``/api/llm`` router; ``allow_key_writes`` is False when the server is exposed beyond loopback."""
    router = APIRouter(prefix="/api/llm")

    def guard(request: Request) -> None:
        if not allow_key_writes:
            raise HTTPException(
                403,
                "API keys can only be managed when the Workbench is bound to this machine (127.0.0.1); "
                "use `gmnspy llm set-key` in a terminal.",
            )
        if request.headers.get(SECRETS_HEADER) != "1":
            raise HTTPException(403, f"missing {SECRETS_HEADER} header")

    # Each handler reads ``session.llm`` once: a concurrent key write or setting change swaps the
    # registry (``Session.reset_llm``), and one response must not mix two registries.

    def known(reg: ProviderRegistry, provider: str) -> str:
        if provider not in reg.names():
            raise HTTPException(404, f"unknown provider {provider!r}")
        return provider

    def snapshot() -> dict[str, Any]:
        reg = session.llm
        select = session.settings.select
        return {
            "providers": reg.status(),
            "keyring": reg.secrets.keyring_available,
            "selected": {"provider": select.provider, "model": select.model},
            "key_writes": allow_key_writes,
        }

    def changed(provider: str, verb: str, where: str) -> dict[str, Any]:
        logger.info("llm key %s for %s (%s)", verb, provider, where)  # the provider and store only, never the key
        # A fresh registry (empty probe cache) and parser pick up the new key; the picker's next status shows it.
        session.reset_llm()
        state = snapshot()
        session.events.publish({"type": "llm", **state})
        return state

    @router.get("/providers")
    def providers() -> dict[str, Any]:
        """Status rows (never a key), whether a keyring is usable, the selected pair, and whether keys can be set."""
        return snapshot()

    @router.get("/models")
    def models(provider: str) -> dict[str, Any]:
        """Models to offer for ``provider``: the catalog (remote) or what is installed (local)."""
        reg = session.llm
        known(reg, provider)
        try:
            return {"provider": provider, "models": reg.models(provider)}
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from None

    @router.put("/keys/{provider}", dependencies=[Depends(guard)])
    def set_key(provider: str, body: Any = Body(None)) -> dict[str, Any]:  # noqa: B008  (FastAPI Body default)
        """Store ``provider``'s key in the OS keyring; answer with status only."""
        reg = session.llm
        info = reg.catalog[known(reg, provider)]
        if info.kind == "local":
            raise HTTPException(400, f"{info.label} needs no API key")
        try:
            parsed = _KeyBody.model_validate(body)
        except ValidationError:
            # A hand-written detail: the validation error would carry the submitted key.
            raise HTTPException(422, 'send {"key": "..."}; a key is 8-512 characters') from None
        try:
            source = reg.secrets.set(reg.slot(provider), parsed.key.get_secret_value())
        except SecretStoreError as exc:
            raise HTTPException(400, str(exc)) from None
        return changed(provider, "set", source)

    @router.delete("/keys/{provider}", dependencies=[Depends(guard)])
    def remove_key(provider: str) -> dict[str, Any]:
        """Delete ``provider``'s key from the OS keyring (env vars are the user's to unset)."""
        reg = session.llm
        known(reg, provider)
        try:
            removed = reg.secrets.remove(reg.slot(provider))
        except SecretStoreError as exc:
            raise HTTPException(400, str(exc)) from None
        return changed(provider, "removed", ", ".join(removed) or "nothing stored")

    @router.post("/test", dependencies=[Depends(guard)])
    def check_connection(body: Any = Body(None)) -> dict[str, Any]:  # noqa: B008  (FastAPI Body default)
        """An authenticated, token-free call to ``provider``; failures are reported in the result."""
        reg = session.llm
        try:
            parsed = _TestBody.model_validate(body)
        except ValidationError:
            raise HTTPException(422, 'send {"provider": "...", "model": "..." | null}') from None
        return reg.test(known(reg, parsed.provider), parsed.model)

    return router
