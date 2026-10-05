"""Language-model routes: provider status, write-only key management, model lists, connection tests, Ollama pulls.

None of these are Actions: a key cannot be recorded or replayed without recording the key.
A key write leaves only a status-only ``llm`` SSE event and a log line naming the provider
and the store, never the key. No route returns a key; status is ``{provider, configured, source}``.

On top of the server's Host/Origin guard, key writes, connection tests and Ollama pulls need a
loopback bind and an ``X-Netstead-Secrets: 1`` header. A cross-origin page cannot send that custom
header without a CORS preflight, and this server never approves one.

An Ollama pull (``POST /api/llm/ollama/pull``) is a background job (``job`` events, Cancel in the
Jobs panel) but not an Action either: it changes neither a network nor a setting, so replaying a
session must not re-download gigabytes, and a model on disk outlives any one session's history
(the same reasoning as key writes). It is refused unless ``llm.ollama.base_url`` is on this machine:
the browser may only make *this* machine download, and only a plain library name
(:func:`~netstead.llm.providers.ollama.valid_model_name`), never a URL or another registry host.

Request bodies are typed ``Any`` and validated here, by hand: FastAPI's default 422 body
echoes the submitted input, which for a key route would be the key.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from netstead.llm import LLMError, ProviderRegistry, SecretStoreError
from netstead.llm.providers.ollama import MODEL_NAME_MAX, PullTracker, valid_model_name

from ..errors import ActionError
from ..jobs import Job, JobContext
from ..session import Session

__all__ = ["SECRETS_HEADER", "llm_router"]

logger = logging.getLogger(__name__)

#: Header every key write and connection test must carry (forces a CORS preflight on any cross-origin page).
SECRETS_HEADER = "X-Netstead-Secrets"


class _KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SecretStr = Field(min_length=8, max_length=512)


class _TestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str | None = None


class _PullBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=MODEL_NAME_MAX)


#: A pull streams many progress lines a second; publish a ``job`` event at most this often
#: (or when the stage changes / progress moves a whole percent). Every line is still a cancel checkpoint.
_PULL_EVENT_EVERY_S = 0.5


def llm_router(session: Session, *, allow_key_writes: bool) -> APIRouter:
    """Build the ``/api/llm`` router; ``allow_key_writes`` is False when the server is exposed beyond loopback."""
    router = APIRouter(prefix="/api/llm")

    def guard(request: Request) -> None:
        if not allow_key_writes:
            raise HTTPException(
                403,
                "API keys can only be managed when the Workbench is bound to this machine (127.0.0.1); "
                "use `netstead llm set-key` in a terminal.",
            )
        if request.headers.get(SECRETS_HEADER) != "1":
            raise HTTPException(403, f"missing {SECRETS_HEADER} header")

    def pull_guard(request: Request) -> None:
        if not allow_key_writes:
            raise HTTPException(
                403,
                "Models can only be pulled from the browser when the Workbench is bound to this machine "
                "(127.0.0.1); use `netstead llm pull` in a terminal.",
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
            "ollama_pull": {"allowed": allow_key_writes and reg.is_local("ollama"), "choices": reg.pull_choices()},
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

    @router.post("/ollama/pull", dependencies=[Depends(pull_guard)])
    def ollama_pull(body: Any = Body(None)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
        """Pull a model into the local Ollama as a background job; answers 202 with the job."""
        try:
            model = _PullBody.model_validate(body).model
        except ValidationError:
            raise HTTPException(422, f'send {{"model": "..."}}; at most {MODEL_NAME_MAX} characters') from None
        if not valid_model_name(model):
            raise HTTPException(422, "not an Ollama model name: use name[:tag] or namespace/name[:tag], e.g. qwen3:4b")
        reg = session.llm
        if not reg.is_local("ollama"):
            raise HTTPException(
                400,
                f"Ollama is configured at {reg.base_url('ollama')}, which is not this machine; the Workbench only "
                "pulls into a local Ollama. Run `ollama pull` on that server instead.",
            )
        running = any(
            j["kind"] == "ollama_pull" and j["status"] == "running" and j["label"] == _pull_label(model)
            for j in session.jobs.snapshots()
        )
        if running:
            raise HTTPException(409, f"{model} is already being pulled; see Jobs")
        job = session.jobs.submit(
            "ollama_pull", _pull_label(model), lambda ctx: _run_pull(reg, model, ctx), on_finish=pulled
        )
        return JSONResponse({"job": jsonable_encoder(session.jobs.snapshot(job))}, status_code=202)

    def pulled(job: Job) -> None:
        # The registry's pull already dropped its probe cache; publish fresh status so the picker
        # and the panel show the new model (or the reason it isn't there) without a reload.
        logger.info("ollama pull %s: %s", job.label, job.status)
        try:
            # A new model can change which installed model stands in for the default: rebuild the parser.
            session.reset_llm()
            session.events.publish({"type": "llm", **snapshot()})
        except Exception:  # boundary: a failed status refresh must not fail the finished job
            logger.exception("llm status refresh after %s failed", job.id)

    return router


def _pull_label(model: str) -> str:
    return f"Pull {model} (Ollama)"


def _run_pull(reg: ProviderRegistry, model: str, ctx: JobContext) -> dict[str, Any]:
    """Job body: stream the pull, publishing throttled progress; every line is a cancel checkpoint."""
    tracker = PullTracker()
    stream = reg.pull(model)
    last: tuple[str, float | None, float] = ("", None, 0.0)
    try:
        for event in stream:
            ctx.check()
            fraction = tracker.update(event)
            stage, now = tracker.stage, time.monotonic()
            moved = fraction is not None and (last[1] is None or fraction - last[1] >= 0.01)
            if stage != last[0] or moved or now - last[2] >= _PULL_EVENT_EVERY_S:
                ctx.stage(stage, progress=fraction)
                last = (stage, fraction, now)
    except LLMError as exc:
        raise ActionError(str(exc)) from None
    finally:
        stream.close()  # on cancel: closes the HTTP stream (Ollama stops) and drops the probe cache
    return {"model": model, "bytes": tracker.total}
