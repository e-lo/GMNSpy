# NL Providers (multi-provider LLM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Natural-language selection in the Workbench (and in `gmnspy select`) gains four providers: local Ollama (Qwen), Anthropic, OpenAI and Gemini. You pick a provider and model in the UI. Your API keys stay in the OS keyring (or env, or a labelled 0600 file when there is no keyring). Keys are managed through write-only UI and CLI paths and never appear in settings, API responses, history, SSE or logs.

**Architecture:**
- A new provider-neutral package, `gmnspy.llm`, contains:
  - types and errors;
  - one HTTP call path (`_http.request_json`, with httpx imported lazily);
  - four hand-rolled adapters behind `LLMProvider.complete()` / `list_models()`;
  - a structured-output helper (forced tool → validate → repair, with JSON mode for tool-less models);
  - a TOML model catalog;
  - a `SecretStore` (env → keyring → file) whose key slots are bound to the endpoint origin;
  - a `ProviderRegistry`.
- `gmnspy.select.parse.LLMParser` uses any provider with the unchanged selection tool schema. `ClaudeParser` becomes a back-compat subclass.
- The Workbench session builds its parser from settings plus the registry, and turns `LLMError` into `ActionError`.
- New non-recorded `/api/llm/*` routes handle key status, key writes and connection tests.
- The header gets a provider + model picker, and a "Language models" panel manages keys.

**Tech Stack:**
- Python 3.11, pydantic v2, httpx 0.28 (`MockTransport` in tests), jsonschema 4, keyring 24+ (macOS Keychain / Windows Credential Manager / Secret Service), FastAPI.
- Plain ES modules.
- pytest + `fastapi.testclient`, and `node --check`.

**Spec:** [2026-10-02-nl-providers-design.md](2026-10-02-nl-providers-design.md).

**Branch:** cut `feat/nl-providers` from `feat/workbench-p0`. After P0 merges, rebase it onto `refactor/v1.0`. It does not depend on P1a or P1b.

**Conventions:**
- Run commands from the repo root.
- Run tests with `uv run --all-extras pytest <path> -q`.
- Lint with `uv run ruff check packages scripts && uv run ruff format --check packages scripts`.
- Ruff enforces Google-style docstrings (`D`) on every public module-level function, class and method outside `tests/` and `__init__.py`. Every code block below already has them.
- Line length is 120.
- `__all__` lists are sorted the way ruff's `RUF022` expects: SCREAMING_CASE, then CamelCase, then lowercase.
- **Never put a real key in a test.** Tests use obviously fake strings. The fixtures in Task 0 and Task 4 stop any test from reaching the real network or the developer's keychain.

---

## Scope notes

- **In scope:**
  - the `gmnspy.llm` package and four adapters;
  - the catalog;
  - secrets, including `datagrove.io.credentials.system_keyring`;
  - the structured-output helper;
  - the registry;
  - widened settings (`select.provider` with the `claude` alias, `select.model`, `llm.*`);
  - the `SetSetting` secret guard and the 422 no-echo hardening;
  - `LLMParser`, `ClaudeParser` and `make_parser`;
  - session wiring with `parsed_by`;
  - the `/api/llm` routes;
  - the `gmnspy llm` CLI;
  - the header picker and the Language-models panel;
  - recorded contract fixtures, the record script and the live smoke marker;
  - docs.
- **Deferred:**
  - the P3 assistant (multi-turn chat, tool results, grounding);
  - streaming;
  - cost metering;
  - a per-launch auth token (P4, design Q4);
  - multiple named OpenAI-compatible endpoints (design Q5).
- **Overlap with P1b (Settings workspace):** this plan builds only the Language-models panel and the header picker. The panel's code lives in `llm.js`, and its DOM is a single `#llm-panel` container, so P1b can mount it as a Settings section and drop the floating panel. P1b's generic, schema-driven form will also list `llm.*`; P1b should hide that section in favour of this panel.

### Conflicts with the parallel P1a plan (Open/Import wizard)

| File | P1a change | This plan | How to merge |
|---|---|---|---|
| `gmnspy/config.py` | `AppSettings.approve_above_s` (plus `io.allowed_roots` enforcement) | `SelectSettings` rewritten; new `LLMEndpointSettings`/`OllamaSettings`/`LLMSettings`; `Settings.llm` field; `PROVIDER_ALIASES`; `__all__` | Different classes. In `class Settings` and `__all__` both add lines; keep both |
| `workbench/static/index.html` | header `#open-src`/`#open-go` → **Open / Import…** + **Recent** + jobs indicator | `#nl-picker` between `#utterance` and `#go`; `#llm-panel` after `#hist-panel` | Disjoint ranges. If P1a reflows the header, move the picker along with `#utterance`. Consider a second header row if the header gets crowded |
| `workbench/session.py` | jobs runner, `OpenNetwork` via jobs, `allowed_roots` | `__init__` kwargs `llm_transport`/`keyring`, `self.llm`, `parser()`, `reset_llm()`, `_do_select`, `_do_set_setting` | `__init__` is the only shared hunk; keep both sets of attributes |
| `workbench/server.py` | new routers | `llm_router` include | One line each |
| `workbench/static/js/main.js`, `app.css` | wizard/jobs wiring and styles | `llm.js` wiring and styles | Both append; keep both |
| `packages/gmnspy/pyproject.toml` | possibly `[osm]` tweaks | `[nl]` extra and wheel include | Disjoint lines; re-run `uv lock` after merging |

## File structure

| Path | Responsibility |
|---|---|
| `packages/datagrove/datagrove/io/credentials.py` (modify) | `system_keyring()`: is a real OS keyring backend usable? |
| `packages/gmnspy/gmnspy/llm/__init__.py` (new) | Public surface of the LLM layer |
| `packages/gmnspy/gmnspy/llm/types.py` (new) | `Tool`, `Message`, `ToolCall`, `CompletionRequest`, `Completion`, `LLMProvider` |
| `packages/gmnspy/gmnspy/llm/errors.py` (new) | `LLMError` hierarchy (user-facing, secret-free) |
| `packages/gmnspy/gmnspy/llm/catalog.py`, `models.toml` (new) | Maintained provider/model catalog plus the user overlay |
| `packages/gmnspy/gmnspy/llm/secrets.py` (new) | `KeySlot`, `SecretStore`, `redact`, `looks_like_secret`, `origin_of` |
| `packages/gmnspy/gmnspy/llm/_http.py` (new) | `request_json`: the one network path, with status → error mapping and scrubbing |
| `packages/gmnspy/gmnspy/llm/providers/{__init__,_base,anthropic,openai,gemini,ollama}.py` (new) | Adapters and the `ADAPTERS` map |
| `packages/gmnspy/gmnspy/llm/structured.py` (new) | `request_tool_call`: forced tool, validation, repair, JSON mode |
| `packages/gmnspy/gmnspy/llm/registry.py` (new) | `ProviderRegistry`, `build_registry`, `default_registry` |
| `packages/gmnspy/gmnspy/config.py` (modify) | Widened `SelectSettings`; `LLMSettings` |
| `packages/gmnspy/gmnspy/select/parse.py`, `select/__init__.py` (modify) | `LLMParser`, `ClaudeParser` alias, `make_parser`, `intent_from_payload` |
| `packages/gmnspy/gmnspy/cli/commands/select.py` (modify) | `--provider` from settings, `--model` |
| `packages/gmnspy/gmnspy/cli/commands/llm.py`, `cli/app.py` (new/modify) | `gmnspy llm {status,set-key,remove-key,test,models}` |
| `packages/gmnspy/gmnspy/workbench/actions.py` (modify) | `SetSetting` refuses key-shaped values |
| `packages/gmnspy/gmnspy/workbench/session.py`, `selection.py` (modify) | Registry, parser factory, `LLMError` → `ActionError`, `parsed_by` |
| `packages/gmnspy/gmnspy/workbench/routes/core.py` (modify) | 422 no longer echoes input values |
| `packages/gmnspy/gmnspy/workbench/routes/llm.py`, `server.py` (new/modify) | `/api/llm/*` |
| `packages/gmnspy/gmnspy/workbench/static/{index.html,app.css,js/api.js,js/llm.js,js/main.js}` (modify/new) | Picker and panel |
| `packages/gmnspy/pyproject.toml`, `uv.lock` (modify) | `[nl]` = jsonschema + httpx + keyring (drops `anthropic`); wheel includes `llm/*.toml` |
| `pyproject.toml` (root, modify) | `live_llm` pytest marker |
| `scripts/record_llm_fixtures.py` (new) | Re-record contract fixtures from live APIs (headers never written) |
| `packages/gmnspy/tests/conftest.py` (modify) | `FakeKeyring`, `FakeAPI`, `no_network`, autouse no-system-keyring |
| `packages/gmnspy/tests/fixtures/llm/*_select.json` (new) | Contract fixtures |
| `packages/gmnspy/tests/test_llm_*.py`, `test_workbench_llm_routes.py`, `test_cli_llm.py` (new) | Tests |
| `packages/gmnspy/docs/cookbook/workbench.md` (modify) | "Language models" section |

---

### Task 0: Branch, `live_llm` marker, shared LLM test fakes

**Files:**
- Modify: `pyproject.toml` (root)
- Modify: `packages/gmnspy/tests/conftest.py`

- [ ] **Step 1: Cut the branch**

```bash
git checkout feat/workbench-p0 && git checkout -b feat/nl-providers
```

- [ ] **Step 2: Register the marker.** In the root `pyproject.toml`, extend `[tool.pytest.ini_options].markers`:

```toml
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "perf: performance regression bench",
    "integration: cross-package integration",
    "live_llm: calls real LLM provider APIs; skipped unless GMNSPY_LIVE_LLM=anthropic,openai,gemini,ollama (any subset)",
]
```

- [ ] **Step 3: Add the fakes to `packages/gmnspy/tests/conftest.py`.** Add `import json` and `from typing import Any` to the stdlib imports at the top of the file, keeping them sorted (`conftest.py` already has `from __future__ import annotations`, so the `-> FakeAPI` annotation below needs no quotes). Then append:

```python
class FakeKeyring:
    """In-memory stand-in for the ``keyring`` module: tests never touch the real OS keychain."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.store.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.store[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        del self.store[(service_name, username)]


@pytest.fixture
def fake_keyring() -> FakeKeyring:
    """A fresh in-memory keyring."""
    return FakeKeyring()


class FakeAPI:
    """Canned JSON per ``(METHOD, path)`` behind an ``httpx.MockTransport``; every request is kept.

    ``add`` queues responses for a route; once one is left it repeats. ``raises`` makes the
    transport raise that exception instead (e.g. ``httpx.ConnectError("refused")``).
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, Any, dict[str, str], Exception | None]]] = {}
        self.requests: list[Any] = []

    def add(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raises: Exception | None = None,
    ) -> FakeAPI:
        self.routes.setdefault((method.upper(), path), []).append((status, body, headers or {}, raises))
        return self

    def transport(self) -> Any:
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            queue = self.routes.get((request.method, request.url.path))
            if not queue:
                return httpx.Response(599, json={"error": f"no fake route for {request.method} {request.url.path}"})
            status, body, headers, raises = queue.pop(0) if len(queue) > 1 else queue[0]
            if raises is not None:
                raise raises
            return httpx.Response(status, json=body, headers=headers)

        return httpx.MockTransport(handler)

    def body(self, index: int = -1) -> dict[str, Any]:
        """The JSON body of a recorded request (default: the last one)."""
        return json.loads(self.requests[index].content)


@pytest.fixture
def fake_api() -> FakeAPI:
    """A fresh fake provider API."""
    return FakeAPI()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if code under test opens a real HTTP connection (LLM tests use ``fake_api``)."""
    httpx = pytest.importorskip("httpx")

    def refuse(self: Any, request: Any) -> Any:
        raise AssertionError(f"real network call in a test: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
```

- [ ] **Step 4: Confirm the suite still collects and passes**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session.py packages/gmnspy/tests/test_config.py -q`
Expected: `38 passed`, with no marker errors under `--strict-markers`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml packages/gmnspy/tests/conftest.py
git commit -m "test(gmnspy): live_llm marker + FakeKeyring/FakeAPI/no_network fixtures for LLM tests"
```

---

### Task 1: `datagrove.io.credentials.system_keyring()`

**Files:**
- Modify: `packages/datagrove/datagrove/io/credentials.py`
- Test: `packages/datagrove/tests/io/test_credentials.py` (append)

- [ ] **Step 1: Append the failing tests**

```python


# ---------------------------------------------------------------------------
# system_keyring(): is a real OS keyring backend usable?
# ---------------------------------------------------------------------------


def _fake_keyring_module(priority: float) -> types.ModuleType:
    module = types.ModuleType("keyring")
    backend = types.SimpleNamespace(priority=priority)
    module.get_keyring = lambda: backend  # type: ignore[attr-defined]
    return module


def test_system_keyring_none_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    from datagrove.io.credentials import system_keyring

    monkeypatch.setitem(sys.modules, "keyring", None)
    assert system_keyring() is None


def test_system_keyring_none_for_fail_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from datagrove.io.credentials import system_keyring

    monkeypatch.setitem(sys.modules, "keyring", _fake_keyring_module(0))
    assert system_keyring() is None


def test_system_keyring_returns_module_for_real_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from datagrove.io.credentials import system_keyring

    module = _fake_keyring_module(5)
    monkeypatch.setitem(sys.modules, "keyring", module)
    assert system_keyring() is module


def test_system_keyring_none_when_backend_lookup_breaks(monkeypatch: pytest.MonkeyPatch) -> None:
    from datagrove.io.credentials import system_keyring

    module = types.ModuleType("keyring")

    def boom() -> Any:
        raise RuntimeError("secret service not running")

    module.get_keyring = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", module)
    assert system_keyring() is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/datagrove/tests/io/test_credentials.py -q -k system_keyring`
Expected: `4 failed`, each with `ImportError: cannot import name 'system_keyring'`.

- [ ] **Step 3: Implement.** In `credentials.py`, change `__all__ = ["resolve_credentials"]` to `__all__ = ["resolve_credentials", "system_keyring"]`, add `from typing import Any, Final` (replacing `from typing import Final`), and add this function after `resolve_credentials`:

```python
def system_keyring() -> Any | None:
    """Return the ``keyring`` module when a real OS keyring backend is active, else ``None``.

    ``None`` when the optional ``keyring`` package is missing (or disabled with
    ``sys.modules['keyring'] = None``), or when its active backend is the
    fail/null backend (priority <= 0: headless CI, containers, WSL without a
    secret service). Callers use this one answer to decide whether secrets can
    be stored in a keyring at all.
    """
    try:
        import keyring  # type: ignore[import-not-found]
    except ImportError:
        return None
    if keyring is None:  # type: ignore[unreachable]
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # boundary: a broken backend configuration means "no usable keyring", never a crash
        return None
    if getattr(backend, "priority", 0) <= 0:
        return None
    return keyring
```

- [ ] **Step 4: Run the file**

Run: `uv run --all-extras pytest packages/datagrove/tests/io/test_credentials.py -q`
Expected: `19 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/datagrove/datagrove/io/credentials.py packages/datagrove/tests/io/test_credentials.py
git commit -m "feat(datagrove): system_keyring() — one answer to 'is a real OS keyring usable?'"
```

---

### Task 2: `gmnspy.llm` types and errors

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/__init__.py`, `types.py`, `errors.py`
- Test: `packages/gmnspy/tests/test_llm_types.py`

- [ ] **Step 1: Write the failing tests** in `packages/gmnspy/tests/test_llm_types.py`

```python
"""Tests for gmnspy.llm.types and gmnspy.llm.errors."""

import dataclasses

import pytest
from gmnspy.llm.errors import InvalidKey, LLMError, MissingKey, RateLimited
from gmnspy.llm.types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall


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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_types.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/types.py`**

```python
"""Provider-neutral request/response types for tool-calling LLMs.

Every adapter in :mod:`gmnspy.llm.providers` maps a :class:`CompletionRequest` onto its
provider's wire format and maps the reply back to a :class:`Completion`. Nothing here
knows about any one provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = ["Completion", "CompletionRequest", "LLMProvider", "Message", "Tool", "ToolCall"]


@dataclass(frozen=True)
class Tool:
    """A tool the model may call: a name, a description, and a plain JSON-schema input."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One plain-text conversation turn."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ToolCall:
    """A tool call the model made: the tool name and its parsed JSON-object arguments."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class CompletionRequest:
    """One provider-neutral completion request.

    ``force_tool`` names a tool the model must call (providers that cannot force one ignore it).
    ``json_schema`` asks for a bare JSON reply instead of a tool call: adapters with a native JSON
    mode (Ollama's ``format``) use it, the others rely on the instructions in ``system``.
    """

    model: str
    messages: tuple[Message, ...]
    system: str = ""
    tools: tuple[Tool, ...] = ()
    force_tool: str | None = None
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 1024


@dataclass(frozen=True)
class Completion:
    """A provider-neutral reply: tool calls and/or text, plus token counts when reported."""

    tool_calls: tuple[ToolCall, ...] = ()
    text: str = ""
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """The one interface every adapter implements."""

    name: str
    label: str

    def complete(self, request: CompletionRequest) -> Completion:
        """Run one completion; raise :class:`~gmnspy.llm.errors.LLMError` on any provider failure."""
        ...

    def list_models(self) -> list[str]:
        """Model ids this endpoint serves for this key (an authenticated call that spends no tokens)."""
        ...
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/llm/errors.py`**

```python
"""User-facing, secret-free LLM provider errors.

Every message is written for the person at the keyboard and is safe to show in the
browser, record in history, and log: adapters build them from status codes and
*scrubbed* provider detail (:func:`gmnspy.llm.secrets.redact`), never from request headers.
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
```

- [ ] **Step 5: Create `packages/gmnspy/gmnspy/llm/__init__.py`** (the first version; Task 11 completes it)

```python
"""Provider-neutral LLM layer for gmnspy's natural-language features (see ``registry`` for the entry point)."""

from .errors import (
    BadRequest,
    BadResponse,
    InvalidKey,
    LLMError,
    MissingKey,
    ModelNotFound,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    ToolsUnsupported,
)
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall

__all__ = [
    "BadRequest",
    "BadResponse",
    "Completion",
    "CompletionRequest",
    "InvalidKey",
    "LLMError",
    "LLMProvider",
    "Message",
    "MissingKey",
    "ModelNotFound",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimited",
    "Tool",
    "ToolCall",
    "ToolsUnsupported",
]
```

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_types.py -q`
Expected: `4 passed`.

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/llm packages/gmnspy/tests/test_llm_types.py
git commit -m "feat(gmnspy.llm): provider-neutral request/response types and secret-free error hierarchy"
```

---

### Task 3: Model catalog (`models.toml`) and loader

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/models.toml`, `packages/gmnspy/gmnspy/llm/catalog.py`
- Modify: `packages/gmnspy/pyproject.toml` (wheel include)
- Test: `packages/gmnspy/tests/test_llm_catalog.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for gmnspy.llm.catalog — the maintained provider/model catalog."""

import pytest
from gmnspy.llm.catalog import CATALOG_OVERLAY, load_catalog


def test_packaged_catalog_has_the_four_providers_in_order():
    cat = load_catalog()
    assert cat.names() == ["anthropic", "openai", "gemini", "ollama"]
    assert cat["ollama"].kind == "local" and cat["anthropic"].kind == "remote"
    assert cat["anthropic"].key_env == ("GMNSPY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")


def test_anthropic_models_are_the_current_ids():
    anthropic = load_catalog()["anthropic"]
    assert [m.id for m in anthropic.models] == ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5-5"]
    assert [m.tier for m in anthropic.models] == ["fast", "balanced", "best"]
    assert anthropic.default_model == "claude-sonnet-5"


def test_every_default_model_is_listed_and_every_model_has_a_label():
    for info in load_catalog().providers.values():
        assert info.model(info.default_model) is not None, info.name
        assert all(m.label for m in info.models)


def test_user_overlay_adds_and_relabels_but_cannot_move_keys(tmp_path):
    (tmp_path / CATALOG_OVERLAY).write_text(
        "[openai]\n"
        'default_model = "my-model"\n'
        'base_url = "https://evil.example/v1"\n'
        'key_env = ["EVIL"]\n'
        "[[openai.models]]\n"
        'id = "my-model"\n'
        'label = "Mine"\n'
        'tier = "fast"\n'
        "[mystery]\n"
        'label = "No adapter"\n'
    )
    cat = load_catalog(tmp_path)
    openai = cat["openai"]
    assert openai.default_model == "my-model" and openai.model("my-model").label == "Mine"
    assert openai.base_url == "https://api.openai.com/v1" and openai.key_env == (
        "GMNSPY_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    )
    assert "mystery" not in cat.names()


def test_unknown_provider_and_bad_entries_raise(tmp_path):
    with pytest.raises(KeyError, match="unknown LLM provider 'mistral'"):
        load_catalog()["mistral"]
    (tmp_path / CATALOG_OVERLAY).write_text('[[anthropic.models]]\nlabel = "no id"\n')
    with pytest.raises(ValueError, match="every model needs an id"):
        load_catalog(tmp_path)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_catalog.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.catalog'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/models.toml`**

```toml
# Maintained catalog of the LLM providers and models the Workbench offers for its
# natural-language features. Edit freely. A user overlay at
# <user config dir>/llm_models.toml (same shape) may add or relabel models and change
# a provider's label/default_model; it can NOT change base_url, key_env or kind
# (those decide where API keys are sent).
#
# Per provider:
#   label          display name
#   kind           "remote" (needs an API key) | "local" (no key; Ollama)
#   base_url       the official endpoint; a key is only ever sent to the endpoint it was entered for
#   key_env        env vars checked, in order, before the OS keyring (official endpoint only)
#   default_model  used when select.model is unset
# Per model: id (sent to the API), label, tier (fast | balanced | best), tools (tool calling).
#
# VERIFY: OpenAI, Gemini and Ollama model ids are editable starting points, not
# checked against the provider docs. `gmnspy llm test <provider>` lists every catalog
# id the live endpoint does not serve; fix this file before each release.

[anthropic]
label = "Anthropic"
kind = "remote"
base_url = "https://api.anthropic.com"
key_env = ["GMNSPY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"]
default_model = "claude-sonnet-5"

[[anthropic.models]]
id = "claude-haiku-4-5-20251001"
label = "Haiku 4.5"
tier = "fast"
tools = true

[[anthropic.models]]
id = "claude-sonnet-5"
label = "Sonnet 5"
tier = "balanced"
tools = true

[[anthropic.models]]
id = "claude-opus-5-5"
label = "Opus 5.5"
tier = "best"
tools = true

[openai]
label = "OpenAI"
kind = "remote"
base_url = "https://api.openai.com/v1"
key_env = ["GMNSPY_OPENAI_API_KEY", "OPENAI_API_KEY"]
default_model = "gpt-4.1-mini"

# VERIFY against https://platform.openai.com/docs/models
[[openai.models]]
id = "gpt-4.1-mini"
label = "GPT-4.1 mini"
tier = "fast"
tools = true

# VERIFY
[[openai.models]]
id = "gpt-4.1"
label = "GPT-4.1"
tier = "balanced"
tools = true

# VERIFY
[[openai.models]]
id = "gpt-5"
label = "GPT-5"
tier = "best"
tools = true

[gemini]
label = "Gemini"
kind = "remote"
base_url = "https://generativelanguage.googleapis.com/v1beta"
key_env = ["GMNSPY_GEMINI_API_KEY", "GEMINI_API_KEY"]
default_model = "gemini-2.5-flash"

# VERIFY against https://ai.google.dev/gemini-api/docs/models
[[gemini.models]]
id = "gemini-2.5-flash-lite"
label = "Gemini 2.5 Flash-Lite"
tier = "fast"
tools = true

# VERIFY
[[gemini.models]]
id = "gemini-2.5-flash"
label = "Gemini 2.5 Flash"
tier = "balanced"
tools = true

# VERIFY
[[gemini.models]]
id = "gemini-2.5-pro"
label = "Gemini 2.5 Pro"
tier = "best"
tools = true

[ollama]
label = "Ollama (local)"
kind = "local"
base_url = "http://localhost:11434"
key_env = []
default_model = "qwen3:8b"

# Ollama's installed models are discovered at run time (GET /api/tags). These entries
# only label known tags and power the "ollama pull <id>" hint. VERIFY tags at
# https://ollama.com/library before release.
[[ollama.models]]
id = "qwen3:8b"
label = "Qwen 3 8B"
tier = "balanced"
tools = true

[[ollama.models]]
id = "qwen2.5:7b"
label = "Qwen 2.5 7B"
tier = "fast"
tools = true
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/llm/catalog.py`**

```python
"""The maintained LLM provider/model catalog (``models.toml``), plus an optional user overlay.

The overlay (``<user config dir>/llm_models.toml``, same shape) may add or relabel models
and change a provider's ``label``/``default_model``. It cannot change ``base_url``,
``key_env`` or ``kind``: those decide where keys are sent, so they stay in packaged data.
A provider without an adapter in :mod:`gmnspy.llm.providers` is ignored.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

__all__ = ["CATALOG_OVERLAY", "Catalog", "ModelInfo", "ProviderInfo", "load_catalog"]

#: File name of the user overlay, next to the user ``config.toml``.
CATALOG_OVERLAY = "llm_models.toml"
#: Provider keys an overlay may set; anything else in the overlay is ignored.
_OVERLAY_KEYS = frozenset({"label", "default_model"})
#: Providers the packaged catalog may define (one adapter each).
_KNOWN = ("anthropic", "openai", "gemini", "ollama")

Tier = Literal["fast", "balanced", "best"]


@dataclass(frozen=True)
class ModelInfo:
    """One catalog model."""

    id: str
    label: str
    tier: Tier | None = None
    tools: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy for the API."""
        return {"id": self.id, "label": self.label, "tier": self.tier, "tools": self.tools}


@dataclass(frozen=True)
class ProviderInfo:
    """One catalog provider."""

    name: str
    label: str
    kind: Literal["remote", "local"]
    base_url: str
    key_env: tuple[str, ...]
    default_model: str
    models: tuple[ModelInfo, ...]

    def model(self, model_id: str) -> ModelInfo | None:
        """The catalog entry for ``model_id``, if there is one."""
        return next((m for m in self.models if m.id == model_id), None)


@dataclass(frozen=True)
class Catalog:
    """Providers keyed by name, in file order."""

    providers: dict[str, ProviderInfo]

    def __getitem__(self, name: str) -> ProviderInfo:
        """The provider called ``name`` (the ``KeyError`` lists the known ones)."""
        try:
            return self.providers[name]
        except KeyError:
            raise KeyError(f"unknown LLM provider {name!r}; known: {', '.join(self.providers)}") from None

    def names(self) -> list[str]:
        """Provider names in catalog order."""
        return list(self.providers)


def load_catalog(user_dir: str | Path | None = None) -> Catalog:
    """Load the packaged catalog, overlaid with ``<user_dir>/llm_models.toml`` when that file exists."""
    raw = tomllib.loads(resources.files("gmnspy.llm").joinpath("models.toml").read_text(encoding="utf-8"))
    if user_dir is not None and (overlay := Path(user_dir) / CATALOG_OVERLAY).is_file():
        raw = _apply_overlay(raw, tomllib.loads(overlay.read_text(encoding="utf-8")))
    return Catalog({name: _provider(name, body) for name, body in raw.items() if name in _KNOWN})


def _apply_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = {name: dict(body) for name, body in base.items()}
    for name, body in overlay.items():
        if name not in out:
            continue  # no adapter could serve a provider the packaged catalog doesn't define
        merged = out[name]
        merged.update({key: value for key, value in body.items() if key in _OVERLAY_KEYS})
        models = {m["id"]: dict(m) for m in merged.get("models", [])}
        for model in body.get("models", []):
            if "id" not in model:
                raise ValueError(f"LLM catalog overlay: every model needs an id (provider {name!r})")
            models[model["id"]] = {**models.get(model["id"], {}), **model}
        merged["models"] = list(models.values())
    return out


def _provider(name: str, body: dict[str, Any]) -> ProviderInfo:
    try:
        kind = body["kind"]
        if kind not in ("remote", "local"):
            raise ValueError(f"kind must be 'remote' or 'local', not {kind!r}")
        return ProviderInfo(
            name=name,
            label=str(body["label"]),
            kind=kind,
            base_url=str(body["base_url"]).rstrip("/"),
            key_env=tuple(body.get("key_env", ())),
            default_model=str(body["default_model"]),
            models=tuple(
                ModelInfo(
                    id=str(m["id"]),
                    label=str(m.get("label", m["id"])),
                    tier=m.get("tier"),
                    tools=bool(m.get("tools", True)),
                )
                for m in body.get("models", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"LLM catalog: provider {name!r} has a missing or bad field: {exc}") from None
```

- [ ] **Step 5: Ship the data file.** In `packages/gmnspy/pyproject.toml`, under `[tool.hatch.build.targets.wheel].include`, add these lines after the workbench static entries:

```toml
    # Maintained LLM provider/model catalog (gmnspy.llm).
    "gmnspy/llm/*.toml",
```

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_catalog.py -q`
Expected: `5 passed`.

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/models.toml packages/gmnspy/gmnspy/llm/catalog.py packages/gmnspy/pyproject.toml packages/gmnspy/tests/test_llm_catalog.py
git commit -m "feat(gmnspy.llm): maintained provider/model catalog (models.toml) with a key-safe user overlay"
```

---

### Task 4: `SecretStore`: env → keyring → 0600 file, origin-bound key slots

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/secrets.py`
- Modify: `packages/gmnspy/tests/conftest.py` (autouse: no system keyring)
- Test: `packages/gmnspy/tests/test_llm_secrets.py`

- [ ] **Step 1: Add the autouse guard to `packages/gmnspy/tests/conftest.py`** (append)

```python
@pytest.fixture(autouse=True)
def _no_system_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test reach the developer's real keychain: ``keyring="auto"`` resolves to "none".

    Tests that need a keyring pass ``fake_keyring`` explicitly.
    """
    monkeypatch.setattr("gmnspy.llm.secrets.system_keyring", lambda: None)
```

- [ ] **Step 2: Write the failing tests** in `packages/gmnspy/tests/test_llm_secrets.py`

```python
"""Tests for gmnspy.llm.secrets — write-only API-key storage."""

import stat
import sys

import pytest
from gmnspy.llm.errors import MissingKey
from gmnspy.llm.secrets import (
    KEYRING_SERVICE,
    KeySlot,
    SecretStore,
    SecretStoreError,
    looks_like_secret,
    origin_of,
    redact,
)

ENV_NAMES = {"openai": ("GMNSPY_OPENAI_API_KEY", "OPENAI_API_KEY")}
OPENAI = KeySlot("openai")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def _store(tmp_path, keyring=None, environ=None):
    return SecretStore(config_dir=tmp_path, environ=environ or {}, env_names=ENV_NAMES, keyring=keyring)


def test_env_beats_keyring_and_gmnspy_name_comes_first(tmp_path, fake_keyring):
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "from-ring")
    env = {"OPENAI_API_KEY": "standard", "GMNSPY_OPENAI_API_KEY": "ours"}
    assert _store(tmp_path, fake_keyring, env).lookup(OPENAI) == ("ours", "env")
    assert _store(tmp_path, fake_keyring, {"OPENAI_API_KEY": "standard"}).lookup(OPENAI) == ("standard", "env")
    assert _store(tmp_path, fake_keyring).lookup(OPENAI) == ("from-ring", "keyring")


def test_origin_slot_never_uses_env(tmp_path):
    custom = KeySlot("openai", "https://llm.example.org")
    store = _store(tmp_path, environ={"OPENAI_API_KEY": "standard"})
    assert custom.name == "openai@https://llm.example.org"
    assert store.lookup(custom) is None
    with pytest.raises(MissingKey, match=r"for https://llm\.example\.org"):
        store.get(custom, "OpenAI")


def test_missing_key_message_names_the_env_vars(tmp_path):
    with pytest.raises(MissingKey, match=r"OpenAI: no API key is configured.*GMNSPY_OPENAI_API_KEY / OPENAI_API_KEY"):
        _store(tmp_path).get(OPENAI, "OpenAI")


def test_set_in_keyring_status_and_remove(tmp_path, fake_keyring):
    store = _store(tmp_path, fake_keyring)
    assert store.set(OPENAI, "  sk-test-key  ") == "keyring"
    assert fake_keyring.store[(KEYRING_SERVICE, "openai")] == "sk-test-key"
    assert store.status(OPENAI) == {"configured": True, "source": "keyring"}
    assert store.remove(OPENAI) == ["keyring"]
    assert store.status(OPENAI) == {"configured": False, "source": None}


def test_keyring_backend_requires_a_keyring_and_file_requires_none(tmp_path, fake_keyring):
    with pytest.raises(SecretStoreError, match="no OS keyring is available"):
        _store(tmp_path).set(OPENAI, "k1")
    with pytest.raises(SecretStoreError, match="keys are not written to the plain-text file"):
        _store(tmp_path, fake_keyring).set(OPENAI, "k1", backend="file")


@posix_only
def test_file_fallback_is_0600_round_trips_and_removes(tmp_path):
    store = _store(tmp_path)
    assert store.set(KeySlot("openai", "https://x.example"), "k-file", backend="file") == "file"
    assert stat.S_IMODE(store.file_path.stat().st_mode) == 0o600
    assert "PLAIN TEXT" in store.file_path.read_text()
    assert store.lookup(KeySlot("openai", "https://x.example")) == ("k-file", "file")
    assert store.remove(KeySlot("openai", "https://x.example")) == ["file"]
    assert not store.file_path.exists()


@posix_only
def test_loose_file_permissions_are_refused(tmp_path):
    store = _store(tmp_path)
    store.set(OPENAI, "k-file", backend="file")
    store.file_path.chmod(0o644)
    with pytest.raises(SecretStoreError, match="chmod 600"):
        store.lookup(OPENAI)
    with pytest.raises(MissingKey, match="chmod 600"):
        store.get(OPENAI, "OpenAI")


def test_blank_or_spaced_keys_rejected(tmp_path, fake_keyring):
    store = _store(tmp_path, fake_keyring)
    for bad in ("", "   ", "two words"):
        with pytest.raises(SecretStoreError, match="cannot be empty"):
            store.set(OPENAI, bad)


def test_broken_keyring_read_is_no_key_and_write_error_hides_detail(tmp_path):
    class Broken:
        def get_password(self, *a):
            raise RuntimeError("locked")

        def set_password(self, *a):
            raise RuntimeError("secret sk-ant-api03-SHOULDNOTAPPEARabcdefghij")

        def delete_password(self, *a):
            raise RuntimeError("locked")

    store = _store(tmp_path, Broken())
    assert store.lookup(OPENAI) is None
    with pytest.raises(SecretStoreError) as info:
        store.set(OPENAI, "k1")
    assert "SHOULDNOTAPPEAR" not in str(info.value) and "RuntimeError" in str(info.value)


def test_redact_and_looks_like_secret():
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz0123"
    assert redact(f"bad key {key}", key) == "bad key [redacted]"
    assert (
        redact("Incorrect API key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX given") == "Incorrect API key [redacted] given"
    )
    assert looks_like_secret({"a": ["x", "AIzaSyA-abcdefghijklmnopqrstuvwxyz012"]})
    assert not looks_like_secret("task-abcdefghijklmnopqrstuvwxyz")  # 'sk-' inside a word is not a key
    assert not looks_like_secret("claude-sonnet-5") and not looks_like_secret(42)
    assert origin_of("HTTPS://API.Example.org:8443/v1/x") == "https://api.example.org:8443"


def test_repr_never_shows_keys(tmp_path, fake_keyring):
    store = _store(tmp_path, fake_keyring)
    store.set(OPENAI, "sk-test-repr-check")
    assert "sk-test" not in repr(store)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_secrets.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.secrets'`. Every other gmnspy test module also errors in the autouse fixture, with `ModuleNotFoundError`, until Step 4 exists.

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/llm/secrets.py`**

```python
"""Write-only API-key storage for LLM providers: env → OS keyring → (last resort) a 0600 file.

From the Workbench's point of view keys are write-only. This module stores, resolves and
deletes them and reports *where* one was found. No API route, Action, history entry,
log line or SSE event ever carries a key value.

A key is bound to the endpoint it was entered for (:class:`KeySlot`). The provider's
official endpoint uses the plain provider slot (``"openai"``); a ``base_url`` override
gets its own slot named for its origin (``"openai@https://llm.example.org"``), with no
env fallback. Pointing a provider at a new URL therefore never sends an existing key there.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from datagrove.io.credentials import system_keyring

from gmnspy.config import dumps_toml

from .errors import MissingKey

__all__ = [
    "KEYRING_SERVICE",
    "SECRETS_FILE",
    "KeySlot",
    "KeyringLike",
    "SecretStore",
    "SecretStoreError",
    "looks_like_secret",
    "origin_of",
    "redact",
]

#: Keyring service name for every gmnspy LLM key (one entry per :attr:`KeySlot.name`).
KEYRING_SERVICE = "gmnspy-llm"
#: Last-resort plain-text key file, kept in the user config dir (never the project dir).
SECRETS_FILE = "secrets.toml"

Source = Literal["env", "keyring", "file"]
Backend = Literal["keyring", "file"]

#: Key-shaped text: Anthropic ``sk-ant-…``, OpenAI ``sk-…``, Google ``AIza…``, 20+ chars after the prefix.
_KEY_SHAPE = re.compile(r"(?<![A-Za-z0-9_-])(?:sk-ant-|sk-|AIza)[A-Za-z0-9_-]{20,}")
_FILE_HEADER = (
    "# gmnspy LLM API keys in PLAIN TEXT, used only because no OS keyring was available.\n"
    "# Keep this file private (mode 0600). Remove a key with: gmnspy llm remove-key <provider>\n"
)


class SecretStoreError(ValueError):
    """A key could not be stored, read or removed. The message is user-facing and secret-free."""


class KeyringLike(Protocol):
    """The three ``keyring`` functions the store uses (tests pass an in-memory fake)."""

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return the stored secret, or ``None``."""
        ...

    def set_password(self, service_name: str, username: str, password: str) -> None:
        """Store ``password``."""
        ...

    def delete_password(self, service_name: str, username: str) -> None:
        """Delete the stored secret."""
        ...


def origin_of(url: str) -> str:
    """``scheme://host[:port]`` of ``url``, lowercased: what a key slot is bound to."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def redact(text: str, *secrets: str) -> str:
    """Replace each of ``secrets``, and anything key-shaped, in ``text`` with ``[redacted]``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return _KEY_SHAPE.sub("[redacted]", text)


def looks_like_secret(value: Any) -> bool:
    """Whether ``value`` (or any string nested in it) looks like an API key."""
    if isinstance(value, str):
        return bool(_KEY_SHAPE.search(value))
    if isinstance(value, Mapping):
        return any(looks_like_secret(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(looks_like_secret(v) for v in value)
    return False


@dataclass(frozen=True)
class KeySlot:
    """Where a key lives: a provider plus, for a non-official endpoint, that endpoint's origin."""

    provider: str
    origin: str | None = None

    @property
    def name(self) -> str:
        """The keyring username / file key: ``"openai"`` or ``"openai@https://host"``."""
        return self.provider if self.origin is None else f"{self.provider}@{self.origin}"


class SecretStore:
    """Resolve, store and delete LLM API keys. Only :meth:`get` ever returns a key."""

    def __init__(
        self,
        *,
        config_dir: str | Path,
        environ: Mapping[str, str],
        env_names: Mapping[str, Sequence[str]],
        keyring: KeyringLike | Literal["auto"] | None = "auto",
    ) -> None:
        """``keyring="auto"`` uses the OS keyring when one is usable; ``None`` disables it; tests pass a fake."""
        self.config_dir = Path(config_dir)
        self._environ = environ
        self._env_names = {name: tuple(names) for name, names in env_names.items()}
        self._keyring_arg = keyring
        self._keyring: KeyringLike | None = None
        self._keyring_resolved = False

    def __repr__(self) -> str:
        """Location and backend only."""
        return f"SecretStore(config_dir={str(self.config_dir)!r}, keyring={self.keyring_available})"

    @property
    def file_path(self) -> Path:
        """The last-resort plain-text key file."""
        return self.config_dir / SECRETS_FILE

    @property
    def keyring(self) -> KeyringLike | None:
        """The keyring in use (resolved once), or ``None``."""
        if not self._keyring_resolved:
            self._keyring = system_keyring() if isinstance(self._keyring_arg, str) else self._keyring_arg
            self._keyring_resolved = True
        return self._keyring

    @property
    def keyring_available(self) -> bool:
        """Whether keys can be stored in an OS keyring."""
        return self.keyring is not None

    def env_names(self, provider: str) -> tuple[str, ...]:
        """Env vars checked, in order, for ``provider``'s official-endpoint key."""
        return self._env_names.get(provider, ())

    def lookup(self, slot: KeySlot) -> tuple[str, Source] | None:
        """``(key, source)`` for ``slot``, or ``None``; raises :class:`SecretStoreError` for an unsafe key file."""
        if slot.origin is None:
            for name in self.env_names(slot.provider):
                if value := self._environ.get(name, "").strip():
                    return value, "env"
        if (ring := self.keyring) is not None:
            try:
                stored = ring.get_password(KEYRING_SERVICE, slot.name)
            except Exception:  # boundary: a locked or broken backend means "no key here", as in datagrove's cascade
                stored = None
            if stored:
                return stored, "keyring"
        if stored := self._read_file().get(slot.name):
            return stored, "file"
        return None

    def get(self, slot: KeySlot, label: str) -> str:
        """The key for ``slot``; raises :class:`~gmnspy.llm.errors.MissingKey` saying how to add one."""
        try:
            found = self.lookup(slot)
        except SecretStoreError as exc:
            raise MissingKey(slot.provider, f"{label}: {exc}") from None
        if found is not None:
            return found[0]
        if slot.origin is not None:
            raise MissingKey(
                slot.provider,
                f"{label}: no API key is configured for {slot.origin}. Keys are bound to the endpoint they were "
                "entered for; add one for this endpoint in Settings → Language models.",
            )
        env = " / ".join(self.env_names(slot.provider))
        hint = f", or set {env}" if env else ""
        raise MissingKey(
            slot.provider, f"{label}: no API key is configured. Add one in Settings → Language models{hint}."
        )

    def status(self, slot: KeySlot) -> dict[str, Any]:
        """``{"configured": bool, "source": "env" | "keyring" | "file" | None}``: never the key itself."""
        found = self.lookup(slot)
        return {"configured": found is not None, "source": found[1] if found else None}

    def set(self, slot: KeySlot, key: str, *, backend: Backend = "keyring") -> Source:
        """Store ``key`` for ``slot`` and return where it went."""
        key = key.strip()
        if not key or any(ch.isspace() for ch in key):
            raise SecretStoreError("an API key cannot be empty or contain spaces")
        if backend == "keyring":
            ring = self.keyring
            if ring is None:
                raise SecretStoreError(
                    "no OS keyring is available; store the key in the plain-text file instead, "
                    "or set it as an environment variable"
                )
            try:
                ring.set_password(KEYRING_SERVICE, slot.name, key)
            except Exception as exc:  # boundary: report the failure by type only; its text could echo the key
                raise SecretStoreError(f"the OS keyring refused the key ({type(exc).__name__})") from None
            return "keyring"
        if self.keyring is not None:
            raise SecretStoreError("an OS keyring is available, so keys are not written to the plain-text file")
        data = self._read_file()
        data[slot.name] = key
        self._write_file(data)
        return "file"

    def remove(self, slot: KeySlot) -> list[Source]:
        """Delete ``slot``'s key from the keyring and the file; return where it was removed from."""
        removed: list[Source] = []
        if (ring := self.keyring) is not None:
            try:
                if ring.get_password(KEYRING_SERVICE, slot.name):
                    ring.delete_password(KEYRING_SERVICE, slot.name)
                    removed.append("keyring")
            except Exception as exc:  # boundary: as in set()
                raise SecretStoreError(f"the OS keyring could not delete the key ({type(exc).__name__})") from None
        data = self._read_file()
        if slot.name in data:
            del data[slot.name]
            self._write_file(data)
            removed.append("file")
        return removed

    # ------------------------------------------------------------------ plain-text file

    def _read_file(self) -> dict[str, str]:
        path = self.file_path
        if not path.is_file():
            return {}
        if sys.platform != "win32" and path.stat().st_mode & 0o077:
            raise SecretStoreError(f"{path} is readable by other users; run: chmod 600 {path}")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            raise SecretStoreError(f"{path} is not valid TOML; fix or delete it") from None
        keys = data.get("keys", {})
        return {str(k): str(v) for k, v in keys.items()} if isinstance(keys, dict) else {}

    def _write_file(self, data: dict[str, str]) -> None:
        path = self.file_path
        if not data:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # 0600 from birth: never briefly world-readable
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_FILE_HEADER + dumps_toml({"keys": data}))
        os.replace(tmp, path)
```

- [ ] **Step 5: Run the tests, plus one unrelated module to prove the autouse fixture is harmless**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_secrets.py packages/gmnspy/tests/test_config.py -q`
Expected: `27 passed` (11 + 16).

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/secrets.py packages/gmnspy/tests/test_llm_secrets.py packages/gmnspy/tests/conftest.py
git commit -m "feat(gmnspy.llm): write-only SecretStore (env -> keyring -> 0600 file) with origin-bound key slots"
```

---

### Task 5: The one HTTP path (`_http.request_json`), the adapter base, and the Anthropic adapter

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/_http.py`, `packages/gmnspy/gmnspy/llm/providers/__init__.py`, `providers/_base.py`, `providers/anthropic.py`
- Test: `packages/gmnspy/tests/test_llm_anthropic.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Anthropic adapter and the shared HTTP call path (gmnspy.llm._http)."""

import httpx
import pytest
from gmnspy.llm.errors import (
    BadRequest,
    BadResponse,
    InvalidKey,
    ModelNotFound,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
)
from gmnspy.llm.providers.anthropic import API_VERSION, AnthropicProvider
from gmnspy.llm.types import CompletionRequest, Message, Tool

pytestmark = pytest.mark.usefixtures("no_network")

KEY = "sk-ant-api03-TESTKEYabcdefghijklmnopqrst"
TOOL = Tool("emit", "Emit a thing.", {"type": "object", "properties": {"x": {"type": "integer"}}})
REQUEST = CompletionRequest(
    model="claude-sonnet-5",
    messages=(Message("user", "hi"),),
    system="sys",
    tools=(TOOL,),
    force_tool="emit",
    max_tokens=256,
)
REPLY = {
    "content": [{"type": "text", "text": "Sure."}, {"type": "tool_use", "id": "t1", "name": "emit", "input": {"x": 3}}],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 11, "output_tokens": 7},
}


def _provider(fake_api, **kw):
    return AnthropicProvider(api_key=KEY, transport=fake_api.transport(), **kw)


def test_request_shape_and_reply_parsing(fake_api):
    fake_api.add("POST", "/v1/messages", body=REPLY)
    done = _provider(fake_api).complete(REQUEST)
    req = fake_api.requests[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages" and KEY not in str(req.url)
    assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"] == API_VERSION
    assert fake_api.body() == {
        "model": "claude-sonnet-5",
        "max_tokens": 256,
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "emit", "description": "Emit a thing.", "input_schema": TOOL.input_schema}],
        "tool_choice": {"type": "tool", "name": "emit"},
    }
    assert done.tool_calls[0].name == "emit" and done.tool_calls[0].arguments == {"x": 3}
    assert (done.text, done.stop_reason, done.input_tokens, done.output_tokens) == ("Sure.", "tool_use", 11, 7)


def test_list_models(fake_api):
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}, {"id": "claude-haiku-4-5-20251001"}]})
    assert _provider(fake_api).list_models() == ["claude-sonnet-5", "claude-haiku-4-5-20251001"]


@pytest.mark.parametrize(
    ("status", "error", "match"),
    [
        (401, InvalidKey, r"Anthropic rejected the API key \(HTTP 401\)"),
        (403, InvalidKey, r"\(HTTP 403\)"),
        (404, ModelNotFound, "not found.*no such model"),
        (400, BadRequest, "rejected the request.*no such model"),
        (529, ProviderUnavailable, r"unavailable \(HTTP 529\)"),
    ],
)
def test_status_codes_map_to_typed_errors(fake_api, status, error, match):
    fake_api.add("POST", "/v1/messages", status=status, body={"type": "error", "error": {"message": "no such model"}})
    with pytest.raises(error, match=match):
        _provider(fake_api).complete(REQUEST)


def test_rate_limit_carries_retry_after(fake_api):
    fake_api.add("POST", "/v1/messages", status=429, headers={"retry-after": "20"}, body={"error": {"message": "slow"}})
    with pytest.raises(RateLimited, match="retry in 20 s") as info:
        _provider(fake_api).complete(REQUEST)
    assert info.value.retry_after_s == 20.0


def test_timeouts_and_connection_errors(fake_api):
    fake_api.add("POST", "/v1/messages", raises=httpx.ReadTimeout("slow"))
    fake_api.add("POST", "/v1/messages", raises=httpx.ConnectError("refused"))
    provider = _provider(fake_api, timeout_s=5)
    with pytest.raises(ProviderTimeout, match="did not answer within 5 s"):
        provider.complete(REQUEST)
    with pytest.raises(
        ProviderUnavailable, match=r"could not reach Anthropic at https://api\.anthropic\.com \(ConnectError\)"
    ):
        provider.complete(REQUEST)


def test_key_is_scrubbed_from_provider_detail(fake_api):
    detail = f"bad header {KEY} and sk-ant-api03-OTHERKEYabcdefghijklmnop"
    fake_api.add("POST", "/v1/messages", status=400, body={"error": {"message": detail}})
    with pytest.raises(BadRequest) as info:
        _provider(fake_api).complete(REQUEST)
    message = str(info.value)
    assert "TESTKEY" not in message and "OTHERKEY" not in message and "[redacted]" in message


def test_unexpected_shape_is_bad_response(fake_api):
    fake_api.add("POST", "/v1/messages", body={"nope": 1})
    with pytest.raises(BadResponse, match="unexpected reply"):
        _provider(fake_api).complete(REQUEST)


def test_repr_has_no_key(fake_api):
    text = repr(_provider(fake_api))
    assert KEY not in text and "api.anthropic.com" in text
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_anthropic.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.providers'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/_http.py`**

```python
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
        raise ProviderUnavailable(
            provider, f"could not reach {label} at {origin_of(url)} ({type(exc).__name__})."
        ) from None
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
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/llm/providers/_base.py`**

```python
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
```

- [ ] **Step 5: Create `packages/gmnspy/gmnspy/llm/providers/anthropic.py`**

```python
"""Anthropic Messages API adapter (tool use), hand-rolled over httpx."""

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
        """Run one Messages call; tool-use blocks become :class:`~gmnspy.llm.types.ToolCall`."""
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if request.system:
            body["system"] = request.system
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
```

- [ ] **Step 6: Create `packages/gmnspy/gmnspy/llm/providers/__init__.py`** (Tasks 6–8 add one entry each)

```python
"""Hand-rolled ``httpx`` adapters, one per provider, each implementing :class:`~gmnspy.llm.types.LLMProvider`."""

from ._base import HTTPProvider
from .anthropic import AnthropicProvider

#: Provider name -> adapter class. A catalog provider without an adapter is never offered.
ADAPTERS: dict[str, type[HTTPProvider]] = {
    "anthropic": AnthropicProvider,
}

__all__ = ["ADAPTERS", "AnthropicProvider", "HTTPProvider"]
```

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_anthropic.py -q`
Expected: `12 passed`.

- [ ] **Step 8: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/_http.py packages/gmnspy/gmnspy/llm/providers packages/gmnspy/tests/test_llm_anthropic.py
git commit -m "feat(gmnspy.llm): one scrubbed HTTP call path + hand-rolled Anthropic Messages adapter"
```

---

### Task 6: OpenAI (and OpenAI-compatible) Chat Completions adapter

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/providers/openai.py`
- Modify: `packages/gmnspy/gmnspy/llm/providers/__init__.py`
- Test: `packages/gmnspy/tests/test_llm_openai.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the OpenAI Chat Completions adapter."""

import pytest
from gmnspy.llm.errors import InvalidKey
from gmnspy.llm.providers.openai import OpenAIProvider
from gmnspy.llm.types import CompletionRequest, Message, Tool

pytestmark = pytest.mark.usefixtures("no_network")

KEY = "sk-proj-TESTKEYabcdefghijklmnopqrstuvwx"
TOOL = Tool("emit", "Emit a thing.", {"type": "object", "properties": {"x": {"type": "integer"}}})
REQUEST = CompletionRequest(
    model="gpt-4.1-mini",
    messages=(Message("user", "hi"), Message("assistant", "prev"), Message("user", "again")),
    system="sys",
    tools=(TOOL,),
    force_tool="emit",
)


def _reply(arguments: str, content=None):
    call = {"id": "c1", "type": "function", "function": {"name": "emit", "arguments": arguments}}
    message = {"role": "assistant", "content": content, "tool_calls": [call]}
    return {
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": message}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 5},
    }


def _provider(fake_api, **kw):
    return OpenAIProvider(api_key=KEY, transport=fake_api.transport(), **kw)


def test_request_shape_and_parsing(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply('{"x": 3}'))
    done = _provider(fake_api).complete(REQUEST)
    req = fake_api.requests[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert fake_api.body() == {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "prev"},
            {"role": "user", "content": "again"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "emit", "description": "Emit a thing.", "parameters": TOOL.input_schema},
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "emit"}},
    }
    assert done.tool_calls[0].arguments == {"x": 3}
    assert (done.stop_reason, done.input_tokens, done.output_tokens) == ("tool_calls", 20, 5)


def test_unparseable_arguments_come_back_as_text(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply('{"x": 3'))
    done = _provider(fake_api).complete(REQUEST)
    assert done.tool_calls == () and done.text == '{"x": 3'


def test_compatible_endpoint_via_base_url(fake_api):
    fake_api.add("POST", "/v1/chat/completions", body=_reply("{}"))
    _provider(fake_api, base_url="http://localhost:1234/v1/").complete(REQUEST)
    assert str(fake_api.requests[0].url) == "http://localhost:1234/v1/chat/completions"


def test_list_models(fake_api):
    fake_api.add("GET", "/v1/models", body={"object": "list", "data": [{"id": "gpt-4.1-mini"}, {"id": "gpt-4.1"}]})
    assert _provider(fake_api).list_models() == ["gpt-4.1-mini", "gpt-4.1"]


def test_invalid_key_message_omits_provider_detail(fake_api):
    body = {"error": {"message": "Incorrect API key provided: sk-proj-****uvwx."}}
    fake_api.add("POST", "/v1/chat/completions", status=401, body=body)
    with pytest.raises(InvalidKey) as info:
        _provider(fake_api).complete(REQUEST)
    assert "Incorrect" not in str(info.value)
    assert str(info.value).startswith("OpenAI rejected the API key (HTTP 401)")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_openai.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.providers.openai'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/providers/openai.py`**

```python
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
    """``messages`` with the system prompt as the leading ``system`` turn."""
    system = [{"role": "system", "content": request.system}] if request.system else []
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
```

- [ ] **Step 4: Register it.** In `providers/__init__.py`, add `from .openai import OpenAIProvider`, add `"openai": OpenAIProvider,` to `ADAPTERS`, and add `"OpenAIProvider"` to `__all__` (kept sorted).

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_openai.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/providers packages/gmnspy/tests/test_llm_openai.py
git commit -m "feat(gmnspy.llm): OpenAI Chat Completions adapter (also OpenAI-compatible endpoints)"
```

---

### Task 7: Gemini `generateContent` adapter

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/providers/gemini.py`
- Modify: `packages/gmnspy/gmnspy/llm/providers/__init__.py`
- Test: `packages/gmnspy/tests/test_llm_gemini.py`

> **Verify at implementation time:** check the current Gemini API reference for `FunctionDeclaration.parametersJsonSchema`, which takes full JSON Schema. If it isn't available, put `parameters` in its place, together with a sanitiser that turns the free-form `conditions` object into `{"type": "object", "properties": {}}`, because the OpenAPI-subset `parameters` field rejects property-less objects. Then update the `test_request_shape_and_parsing` expectation and re-record the contract fixture (Task 17).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Gemini generateContent adapter."""

import pytest
from gmnspy.llm.errors import BadResponse
from gmnspy.llm.providers.gemini import GeminiProvider
from gmnspy.llm.types import CompletionRequest, Message, Tool

pytestmark = pytest.mark.usefixtures("no_network")

KEY = "AIzaSyTESTKEYabcdefghijklmnopqrstuvw"
TOOL = Tool("emit", "Emit a thing.", {"type": "object", "properties": {"x": {"type": "integer"}}})
REQUEST = CompletionRequest(
    model="gemini-2.5-flash",
    messages=(Message("user", "hi"), Message("assistant", "prev")),
    system="sys",
    tools=(TOOL,),
    force_tool="emit",
    max_tokens=200,
)
PATH = "/v1beta/models/gemini-2.5-flash:generateContent"
REPLY = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"functionCall": {"name": "emit", "args": {"x": 3}}}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 4},
}


def _provider(fake_api):
    return GeminiProvider(api_key=KEY, transport=fake_api.transport())


def test_key_travels_in_a_header_never_the_url(fake_api):
    fake_api.add("POST", PATH, body=REPLY)
    _provider(fake_api).complete(REQUEST)
    req = fake_api.requests[0]
    assert req.headers["x-goog-api-key"] == KEY
    assert "key=" not in str(req.url) and KEY not in str(req.url)


def test_request_shape_and_parsing(fake_api):
    fake_api.add("POST", PATH, body=REPLY)
    done = _provider(fake_api).complete(REQUEST)
    assert fake_api.body() == {
        "contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "model", "parts": [{"text": "prev"}]},
        ],
        "generationConfig": {"maxOutputTokens": 200},
        "systemInstruction": {"parts": [{"text": "sys"}]},
        "tools": [
            {
                "functionDeclarations": [
                    {"name": "emit", "description": "Emit a thing.", "parametersJsonSchema": TOOL.input_schema}
                ]
            }
        ],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["emit"]}},
    }
    assert done.tool_calls[0].arguments == {"x": 3}
    assert (done.stop_reason, done.input_tokens, done.output_tokens) == ("STOP", 30, 4)


def test_text_reply(fake_api):
    fake_api.add("POST", PATH, body={"candidates": [{"content": {"parts": [{"text": '{"x": 1}'}]}}]})
    done = _provider(fake_api).complete(REQUEST)
    assert done.tool_calls == () and done.text == '{"x": 1}'


def test_blocked_prompt_is_bad_response(fake_api):
    fake_api.add("POST", PATH, body={"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(BadResponse, match=r"Gemini blocked the request \(SAFETY\)"):
        _provider(fake_api).complete(REQUEST)


def test_list_models_filters_and_strips_prefix(fake_api):
    fake_api.add(
        "GET",
        "/v1beta/models",
        body={
            "models": [
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]
        },
    )
    assert _provider(fake_api).list_models() == ["gemini-2.5-flash"]
    assert fake_api.requests[0].url.params["pageSize"] == "1000"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_gemini.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.providers.gemini'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/providers/gemini.py`**

```python
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
        """Run one generateContent call; ``functionCall`` parts become :class:`~gmnspy.llm.types.ToolCall`."""
        body: dict[str, Any] = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in request.messages
            ],
            "generationConfig": {"maxOutputTokens": request.max_tokens},
        }
        if request.system:
            body["systemInstruction"] = {"parts": [{"text": request.system}]}
        if request.tools:
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
        except (KeyError, TypeError, AttributeError) as exc:
            raise self._bad_shape(exc) from None
```

- [ ] **Step 4: Register it.** In `providers/__init__.py`, add `from .gemini import GeminiProvider`, add `"gemini": GeminiProvider,` to `ADAPTERS`, and add `"GeminiProvider"` to `__all__`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_gemini.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/providers packages/gmnspy/tests/test_llm_gemini.py
git commit -m "feat(gmnspy.llm): Gemini generateContent adapter (key in header, never the URL)"
```

---

### Task 8: Ollama `/api/chat` adapter

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/providers/ollama.py`
- Modify: `packages/gmnspy/gmnspy/llm/providers/__init__.py`
- Test: `packages/gmnspy/tests/test_llm_ollama.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Ollama /api/chat adapter."""

import httpx
import pytest
from gmnspy.llm.errors import ModelNotFound, ProviderUnavailable, ToolsUnsupported
from gmnspy.llm.providers.ollama import OllamaProvider
from gmnspy.llm.types import CompletionRequest, Message, Tool

pytestmark = pytest.mark.usefixtures("no_network")

TOOL = Tool("emit", "Emit a thing.", {"type": "object", "properties": {"x": {"type": "integer"}}})
REQUEST = CompletionRequest(
    model="qwen3:8b", messages=(Message("user", "hi"),), system="sys", tools=(TOOL,), force_tool="emit", max_tokens=300
)
REPLY = {
    "model": "qwen3:8b",
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "emit", "arguments": {"x": 3}}}],
    },
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 40,
    "eval_count": 9,
}


def _provider(fake_api):
    return OllamaProvider(transport=fake_api.transport())


def test_request_shape_no_auth_and_parsing(fake_api):
    fake_api.add("POST", "/api/chat", body=REPLY)
    done = _provider(fake_api).complete(REQUEST)
    req = fake_api.requests[0]
    assert str(req.url) == "http://localhost:11434/api/chat" and "authorization" not in req.headers
    assert fake_api.body() == {
        "model": "qwen3:8b",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        "stream": False,
        "options": {"num_predict": 300},
        "tools": [
            {
                "type": "function",
                "function": {"name": "emit", "description": "Emit a thing.", "parameters": TOOL.input_schema},
            }
        ],
    }
    assert done.tool_calls[0].arguments == {"x": 3}
    assert (done.stop_reason, done.input_tokens, done.output_tokens) == ("stop", 40, 9)


def test_json_mode_uses_native_format(fake_api):
    fake_api.add("POST", "/api/chat", body={"message": {"role": "assistant", "content": '{"x": 1}'}, "done": True})
    json_request = CompletionRequest(model="gemma2", messages=(Message("user", "hi"),), json_schema=TOOL.input_schema)
    done = _provider(fake_api).complete(json_request)
    assert fake_api.body()["format"] == TOOL.input_schema and "tools" not in fake_api.body()
    assert done.text == '{"x": 1}'


def test_string_arguments_are_parsed(fake_api):
    reply = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "emit", "arguments": '{"x": 2}'}}],
        }
    }
    fake_api.add("POST", "/api/chat", body=reply)
    assert _provider(fake_api).complete(REQUEST).tool_calls[0].arguments == {"x": 2}


def test_model_without_tools_raises_tools_unsupported(fake_api):
    body = {"error": "registry.ollama.ai/library/gemma2:latest does not support tools"}
    fake_api.add("POST", "/api/chat", status=400, body=body)
    with pytest.raises(ToolsUnsupported, match="does not support tool calling"):
        _provider(fake_api).complete(REQUEST)


def test_missing_model_is_model_not_found(fake_api):
    fake_api.add("POST", "/api/chat", status=404, body={"error": 'model "qwen3:8b" not found, try pulling it first'})
    with pytest.raises(ModelNotFound, match="try pulling it first"):
        _provider(fake_api).complete(REQUEST)


def test_list_models_then_server_down(fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]})
    fake_api.add("GET", "/api/tags", raises=httpx.ConnectError("refused"))
    provider = _provider(fake_api)
    assert provider.list_models() == ["qwen3:8b", "llama3.2:3b"]
    with pytest.raises(ProviderUnavailable, match="could not reach Ollama at http://localhost:11434"):
        provider.list_models()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_ollama.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.providers.ollama'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/providers/ollama.py`**

```python
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
        except (KeyError, TypeError) as exc:
            raise self._bad_shape(exc) from None
```

- [ ] **Step 4: Finish the adapter map.** `packages/gmnspy/gmnspy/llm/providers/__init__.py` now reads:

```python
"""Hand-rolled ``httpx`` adapters, one per provider, each implementing :class:`~gmnspy.llm.types.LLMProvider`."""

from ._base import HTTPProvider
from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider

#: Provider name -> adapter class. A catalog provider without an adapter is never offered.
ADAPTERS: dict[str, type[HTTPProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}

__all__ = ["ADAPTERS", "AnthropicProvider", "GeminiProvider", "HTTPProvider", "OllamaProvider", "OpenAIProvider"]
```

- [ ] **Step 5: Run all adapter tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_anthropic.py packages/gmnspy/tests/test_llm_openai.py packages/gmnspy/tests/test_llm_gemini.py packages/gmnspy/tests/test_llm_ollama.py -q`
Expected: `28 passed` (12 + 5 + 5 + 6).

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/providers packages/gmnspy/tests/test_llm_ollama.py
git commit -m "feat(gmnspy.llm): Ollama /api/chat adapter (local, no key; native JSON format)"
```

---

### Task 9: Structured output: forced tool, validation, repair loop, JSON-mode fallback

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/structured.py`
- Test: `packages/gmnspy/tests/test_llm_structured.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for gmnspy.llm.structured — one validated tool call, repair loop, JSON-mode fallback."""

import pytest
from gmnspy.llm.errors import InvalidKey, ToolsUnsupported
from gmnspy.llm.structured import StructuredOutputError, request_tool_call
from gmnspy.llm.types import Completion, Tool, ToolCall

TOOL = Tool("emit", "Emit a count.", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})


class Scripted:
    """An LLMProvider that replays scripted Completions (or raises scripted errors) and keeps every request."""

    name = "scripted"
    label = "Scripted"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def list_models(self):
        return []


def _call(n):
    return Completion(tool_calls=(ToolCall("emit", {"n": n}),))


def test_forced_tool_first_try():
    provider = Scripted(_call(3))
    result = request_tool_call(provider, model="m", tool=TOOL, user="three", system="sys")
    assert (result.arguments, result.mode, result.attempts) == ({"n": 3}, "tools", 1)
    req = provider.requests[0]
    assert req.tools == (TOOL,) and req.force_tool == "emit" and req.system == "sys" and req.json_schema is None


def test_schema_error_is_repaired():
    provider = Scripted(_call("three"), _call(3))
    result = request_tool_call(provider, model="m", tool=TOOL, user="three")
    assert result.attempts == 2 and result.arguments == {"n": 3}
    second = provider.requests[1].messages
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert '"three"' in second[1].content
    assert "not usable: n: 'three' is not of type 'integer'" in second[2].content


def test_caller_validation_error_is_repaired():
    seen = []

    def validate(arguments):
        seen.append(arguments)
        if arguments["n"] < 0:
            raise ValueError("n must be positive")

    provider = Scripted(_call(-1), _call(2))
    assert request_tool_call(provider, model="m", tool=TOOL, user="x", validate=validate).arguments == {"n": 2}
    assert "n must be positive" in provider.requests[1].messages[-1].content and len(seen) == 2


def test_gives_up_after_the_repair_budget():
    provider = Scripted(_call("a"), _call("b"))
    with pytest.raises(StructuredOutputError, match="still invalid after 2 attempts"):
        request_tool_call(provider, model="m", tool=TOOL, user="x", max_repairs=1)
    assert len(provider.requests) == 2


def test_tools_unsupported_switches_to_json_mode_on_the_same_model():
    provider = Scripted(ToolsUnsupported("scripted", "no tools"), Completion(text='Here: ```json\n{"n": 4}\n```'))
    result = request_tool_call(provider, model="m", tool=TOOL, user="four", system="sys")
    assert (result.arguments, result.mode) == ({"n": 4}, "json")
    json_request = provider.requests[1]
    assert json_request.model == "m" and json_request.tools == () and json_request.json_schema == TOOL.input_schema
    assert json_request.system.startswith("sys\n\nReply with ONLY one JSON object")
    assert '"required": ["n"]' in json_request.system


def test_text_reply_in_tools_mode_is_accepted_and_nulls_dropped():
    provider = Scripted(Completion(text='{"n": 5, "note": null}'))
    assert request_tool_call(provider, model="m", tool=TOOL, user="x").arguments == {"n": 5}


def test_provider_errors_are_not_retried():
    provider = Scripted(InvalidKey("scripted", "bad key"), _call(1))
    with pytest.raises(InvalidKey):
        request_tool_call(provider, model="m", tool=TOOL, user="x")
    assert len(provider.requests) == 1


def test_json_mode_from_the_start():
    provider = Scripted(Completion(text='{"n": 6}'))
    result = request_tool_call(provider, model="m", tool=TOOL, user="x", json_mode=True)
    assert result.mode == "json" and provider.requests[0].json_schema == TOOL.input_schema
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_structured.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.structured'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/structured.py`**

```python
"""Get one validated tool call out of any provider, with a bounded repair loop.

PRD §15(e): when the model's output fails validation, re-prompt with the error instead of
surfacing a raw failure. Models without tool calling get the same tool as a "reply with
JSON only" instruction (JSON mode) on the *same* provider and model, never another provider.
Provider failures (:class:`~gmnspy.llm.errors.LLMError`: keys, rate limits, timeouts) are
never retried here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .errors import ToolsUnsupported
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool

__all__ = ["JSON_MODE_INSTRUCTIONS", "REPAIR_PROMPT", "StructuredOutputError", "ToolResult", "request_tool_call"]

Mode = Literal["tools", "json"]

#: Appended to the system prompt in JSON mode.
JSON_MODE_INSTRUCTIONS = (
    "Reply with ONLY one JSON object, with no prose and no code fences, that is valid input for the tool "
    "{name!r} ({description}). Its JSON schema:\n{schema}"
)
#: The user turn that asks the model to fix its previous reply.
REPAIR_PROMPT = "Your previous reply was not usable: {error}\nTry again: {how}"


class StructuredOutputError(ValueError):
    """The model never produced a valid tool call within the repair budget."""


@dataclass(frozen=True)
class ToolResult:
    """Validated tool arguments, the mode that produced them, and how many calls it took."""

    arguments: dict[str, Any]
    mode: Mode
    attempts: int


def request_tool_call(
    provider: LLMProvider,
    *,
    model: str,
    tool: Tool,
    user: str,
    system: str = "",
    validate: Callable[[dict[str, Any]], object] | None = None,
    json_mode: bool = False,
    max_repairs: int = 1,
    max_tokens: int = 1024,
) -> ToolResult:
    """Ask ``provider`` to call ``tool`` for ``user``; validate, and repair until valid or out of budget.

    Args:
        provider: Any :class:`~gmnspy.llm.types.LLMProvider`.
        model: Model id.
        tool: The tool the model must call. Its ``input_schema`` is enforced with jsonschema.
        user: The user's text.
        system: System prompt.
        validate: Extra check on the arguments; raise ``ValueError`` to trigger a repair.
        json_mode: Start in JSON mode (for models known to lack tool calling).
        max_repairs: Extra calls allowed after an invalid reply.
        max_tokens: Output token cap per call.

    Returns:
        The validated arguments, the mode used, and the number of calls made.

    Raises:
        StructuredOutputError: Still invalid after ``max_repairs`` repairs.
    """
    mode: Mode = "json" if json_mode else "tools"
    messages = [Message("user", user)]
    error = ""
    for attempt in range(1, max_repairs + 2):
        completion, mode = _complete(provider, model, tool, system, tuple(messages), mode, max_tokens)
        try:
            arguments = _arguments(completion, tool, mode)
            _check_schema(arguments, tool.input_schema)
            if validate is not None:
                validate(arguments)
        except ValueError as exc:
            error = str(exc)
            how = (
                f"call {tool.name} with corrected arguments."
                if mode == "tools"
                else "reply with only the corrected JSON object."
            )
            messages += [
                Message("assistant", _echo(completion)),
                Message("user", REPAIR_PROMPT.format(error=error, how=how)),
            ]
            continue
        return ToolResult(arguments, mode, attempt)
    raise StructuredOutputError(f"the model's reply was still invalid after {max_repairs + 1} attempts: {error}")


def _complete(
    provider: LLMProvider,
    model: str,
    tool: Tool,
    system: str,
    messages: tuple[Message, ...],
    mode: Mode,
    max_tokens: int,
) -> tuple[Completion, Mode]:
    if mode == "tools":
        request = CompletionRequest(
            model=model, messages=messages, system=system, tools=(tool,), force_tool=tool.name, max_tokens=max_tokens
        )
        try:
            return provider.complete(request), "tools"
        except ToolsUnsupported:
            pass  # same provider, same model, JSON mode instead: a change of mode, never of provider
    instructions = JSON_MODE_INSTRUCTIONS.format(
        name=tool.name, description=tool.description, schema=json.dumps(tool.input_schema)
    )
    request = CompletionRequest(
        model=model,
        messages=messages,
        system=f"{system}\n\n{instructions}".strip(),
        json_schema=tool.input_schema,
        max_tokens=max_tokens,
    )
    return provider.complete(request), "json"


def _arguments(completion: Completion, tool: Tool, mode: Mode) -> dict[str, Any]:
    for call in completion.tool_calls:
        if call.name == tool.name:
            return _drop_nulls(dict(call.arguments))
    if completion.tool_calls:
        raise ValueError(f"the model called {completion.tool_calls[0].name!r}, not {tool.name!r}")
    parsed = _json_object(completion.text)
    if parsed is None:
        raise ValueError(
            f"the model did not call {tool.name!r}" if mode == "tools" else "the reply was not a JSON object"
        )
    return _drop_nulls(parsed)


def _json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _drop_nulls(value: Any) -> Any:
    """Treat ``null`` as "absent": several providers emit explicit nulls for unused optional fields."""
    if isinstance(value, dict):
        return {key: _drop_nulls(item) for key, item in value.items() if item is not None}
    return value


def _check_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator  # the [nl] extra; lazy so gmnspy.llm imports without it
    from jsonschema.exceptions import best_match

    error = best_match(Draft202012Validator(schema).iter_errors(arguments))
    if error is not None:
        where = "/".join(str(part) for part in error.absolute_path) or "(top level)"
        raise ValueError(f"{where}: {error.message}")


def _echo(completion: Completion) -> str:
    if completion.tool_calls:
        call = completion.tool_calls[0]
        return f"(called {call.name} with {json.dumps(call.arguments)})"
    return completion.text[:2000] or "(empty reply)"
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_structured.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/structured.py packages/gmnspy/tests/test_llm_structured.py
git commit -m "feat(gmnspy.llm): request_tool_call — forced tool, schema check, repair loop, JSON-mode fallback"
```

---

### Task 10: Settings — widen `select.provider`, add `llm.*` endpoints, refuse key-shaped values

**Files:**
- Modify: `packages/gmnspy/gmnspy/config.py`
- Modify: `packages/gmnspy/gmnspy/workbench/actions.py` (`SetSetting` guard)
- Modify: `packages/gmnspy/gmnspy/workbench/routes/core.py` (422 without input values)
- Test: `packages/gmnspy/tests/test_config.py`, `test_workbench_actions.py`, `test_workbench_server.py`

- [ ] **Step 1: Update and add the failing tests.**

In `packages/gmnspy/tests/test_config.py`, update `test_precedence_user_project_env_session`. The env still says `"claude"`, and the expected value becomes `"anthropic"`:

```python
    assert (s.viz.basemap, s.app.host, s.select.provider, s.app.port) == ("esri", "0.0.0.0", "anthropic", 9004)
```

Replace `test_save_setting_project_scope_keeps_other_keys` with:

```python
def test_save_setting_project_scope_keeps_other_keys(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text('[viz]\nbasemap = "esri"\n')
    save_setting("select.provider", "claude", scope="project", project_dir=tmp_path, environ=isolated_env)
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert (s.viz.basemap, s.select.provider) == ("esri", "anthropic")
    assert 'provider = "anthropic"' in (tmp_path / "gmnspy.toml").read_text()  # the alias is stored under its new name
```

Append:

```python


def test_select_provider_claude_alias_new_providers_and_model_default(tmp_path, isolated_env):
    for given, stored in (("claude", "anthropic"), ("openai", "openai"), ("gemini", "gemini"), ("ollama", "ollama")):
        s = load_settings(project_dir=tmp_path, environ=isolated_env, overrides={"select.provider": given}).settings
        assert s.select.provider == stored
    assert load_settings(project_dir=tmp_path, environ=isolated_env).settings.select.model is None


def test_llm_section_defaults_env_and_base_url_validation(tmp_path, isolated_env):
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert (s.llm.ollama.base_url, s.llm.ollama.timeout_s) == ("http://localhost:11434", 120.0)
    assert (s.llm.openai.base_url, s.llm.openai.timeout_s) == (None, 60.0)
    env = {
        **isolated_env,
        "GMNSPY_LLM__OLLAMA__BASE_URL": "http://gpu-box:11434/",
        "GMNSPY_LLM__OPENAI__TIMEOUT_S": "30",
    }
    s = load_settings(project_dir=tmp_path, environ=env).settings
    assert (s.llm.ollama.base_url, s.llm.openai.timeout_s) == ("http://gpu-box:11434", 30.0)
    with pytest.raises(SettingsError, match="base_url must be an http"):
        load_settings(project_dir=tmp_path, environ=isolated_env, overrides={"llm.openai.base_url": "ftp://x"})
    with pytest.raises(SettingsError):  # there is no place for a key in settings
        load_settings(project_dir=tmp_path, environ=isolated_env, overrides={"llm.openai.api_key": "nope"})
```

Append to `packages/gmnspy/tests/test_workbench_actions.py`:

```python


def test_set_setting_refuses_key_shaped_values():
    with pytest.raises(ValidationError, match="looks like an API key"):
        SetSetting(key="select.model", value="sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    nested = {
        "type": "set_setting",
        "key": "llm",
        "value": {"openai": {"base_url": "AIzaSyA-abcdefghijklmnopqrstuvwxyz012"}},
    }
    with pytest.raises(ValidationError, match="looks like an API key"):
        parse_action(nested)
    assert SetSetting(key="select.model", value="claude-sonnet-5").value == "claude-sonnet-5"
```

Append to `packages/gmnspy/tests/test_workbench_server.py`:

```python


def test_invalid_action_422_never_echoes_values(client):
    key = "sk-ant-api03-ECHOCHECKabcdefghijklmnop"
    r = client.post("/api/actions", json={"type": "set_setting", "key": "select.model", "value": key})
    assert r.status_code == 422 and "ECHOCHECK" not in r.text
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py packages/gmnspy/tests/test_workbench_actions.py packages/gmnspy/tests/test_workbench_server.py -q`
Expected: 6 failures.
- The alias tests fail with `Input should be 'stub' or 'claude'`.
- The `llm` test fails with `Extra inputs are not permitted`.
- The `SetSetting` test fails with `DID NOT RAISE`.
- The 422 test fails because the key is echoed in `input`.

- [ ] **Step 3: Edit `packages/gmnspy/gmnspy/config.py`.**

In the module docstring, replace the last paragraph with:

```python
Secrets never live here: credentials stay in env/keyring/netrc via
:mod:`datagrove.io.credentials`, and LLM API keys in :mod:`gmnspy.llm.secrets`.
``credentials.keyring_hosts`` only names hosts; ``llm.*`` only holds endpoints.
```

Make the imports read:

```python
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
```

Replace `__all__` with:

```python
__all__ = [
    "PROVIDER_ALIASES",
    "LLMEndpointSettings",
    "LLMSettings",
    "LoadedSettings",
    "OllamaSettings",
    "Settings",
    "SettingsError",
    "dumps_toml",
    "get_value",
    "load_settings",
    "project_config_path",
    "save_setting",
    "user_config_path",
]
```

After `PROJECT_FILE = "gmnspy.toml"`, add:

```python
#: Old ``select.provider`` names, still accepted and stored under the new name, so existing files keep working.
PROVIDER_ALIASES = {"claude": "anthropic"}
```

Replace `class SelectSettings` with the following, which also adds the three LLM endpoint classes:

```python
class SelectSettings(_Section):
    """Natural-language selection: which provider parses utterances, and with which model.

    ``model=None`` means the provider's catalog default (:mod:`gmnspy.llm.catalog`).
    """

    provider: Literal["stub", "anthropic", "openai", "gemini", "ollama"] = "stub"
    model: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _alias(cls, value: Any) -> Any:
        return PROVIDER_ALIASES.get(value, value) if isinstance(value, str) else value


class LLMEndpointSettings(_Section):
    """One LLM provider's endpoint. ``base_url=None`` is the official endpoint. Never a key."""

    base_url: str | None = None
    timeout_s: float = Field(default=60.0, gt=0, le=600)

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("base_url must be an http(s) URL, e.g. https://llm.example.org/v1")
        return value.rstrip("/")


class OllamaSettings(LLMEndpointSettings):
    """The Ollama server (local by default; a non-local URL means utterances leave this machine)."""

    base_url: str | None = "http://localhost:11434"
    timeout_s: float = Field(default=120.0, gt=0, le=600)


class LLMSettings(_Section):
    """Language-model endpoints. API keys never live in settings (see :mod:`gmnspy.llm.secrets`)."""

    anthropic: LLMEndpointSettings = Field(default_factory=LLMEndpointSettings)
    openai: LLMEndpointSettings = Field(default_factory=LLMEndpointSettings)
    gemini: LLMEndpointSettings = Field(default_factory=LLMEndpointSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
```

In `class Settings`, add this field directly after `select`:

```python
    llm: LLMSettings = Field(default_factory=LLMSettings)
```

- [ ] **Step 4: Guard `SetSetting` in `packages/gmnspy/gmnspy/workbench/actions.py`.** Add `from gmnspy.llm.secrets import looks_like_secret` below `from pydantic import ...`. Then replace the `SetSetting` class with:

```python
class SetSetting(_Action):
    """Change a setting (dotted key) for this session, or persist it to the user/project file.

    Refuses API-key-shaped values *at validation*, before anything is recorded: keys are set
    through the write-only ``/api/llm/keys`` route (or ``gmnspy llm set-key``), never as settings.
    """

    type: Literal["set_setting"] = "set_setting"
    mutates: ClassVar[bool] = True
    key: str
    value: Any = None
    scope: Literal["session", "user", "project"] = "session"

    @model_validator(mode="after")
    def _no_secrets(self) -> SetSetting:
        if looks_like_secret(self.value):
            raise ValueError(
                "that value looks like an API key; set keys in Settings → Language models (they are never settings)"
            )
        return self
```

- [ ] **Step 5: Stop 422 responses echoing input.** In `packages/gmnspy/gmnspy/workbench/routes/core.py`, inside `actions()`, change the `detail` line to:

```python
            detail = exc.errors(include_url=False, include_context=False, include_input=False)
```

- [ ] **Step 6: Run the affected suites**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py packages/gmnspy/tests/test_workbench_actions.py packages/gmnspy/tests/test_workbench_server.py packages/gmnspy/tests/test_cli_workbench.py packages/gmnspy/tests/test_workbench_session.py -q`
Expected: `84 passed` (18 + 10 + 23 + 11 + 22; `test_workbench_server.py` collects 23 items because some of its tests are parametrized). The existing `--provider gpt` / `value="gpt"` rejections still fail validation as before.

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/config.py packages/gmnspy/gmnspy/workbench/actions.py packages/gmnspy/gmnspy/workbench/routes/core.py packages/gmnspy/tests/test_config.py packages/gmnspy/tests/test_workbench_actions.py packages/gmnspy/tests/test_workbench_server.py
git commit -m "feat(gmnspy): select.provider gains anthropic/openai/gemini/ollama (claude alias), llm.* endpoints; key-shaped settings refused"
```

---

### Task 11: `ProviderRegistry`: adapters from settings + keys, status, models, connection tests

**Files:**
- Create: `packages/gmnspy/gmnspy/llm/registry.py`
- Modify: `packages/gmnspy/gmnspy/llm/__init__.py` (final public surface)
- Test: `packages/gmnspy/tests/test_llm_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for gmnspy.llm.registry — adapters from settings + keys, status, models, connection tests."""

import pytest
from gmnspy.config import load_settings
from gmnspy.llm.errors import MissingKey
from gmnspy.llm.registry import build_registry, is_local_url
from gmnspy.llm.secrets import KEYRING_SERVICE

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture
def make(tmp_path, isolated_env, fake_keyring, fake_api):
    def _make(overrides=None, environ=None):
        env = {**isolated_env, **(environ or {})}
        settings = load_settings(project_dir=tmp_path, environ=env, overrides=overrides).settings
        return build_registry(settings, environ=env, keyring=fake_keyring, transport=fake_api.transport())

    return _make


def test_status_rows_report_configuration_never_keys(make, fake_keyring, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}]})
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "sk-ant-secret-value")
    rows = {r["provider"]: r for r in make().status()}
    assert list(rows) == ["anthropic", "openai", "gemini", "ollama"]
    assert (rows["anthropic"]["configured"], rows["anthropic"]["source"], rows["anthropic"]["usable"]) == (
        True,
        "keyring",
        True,
    )
    assert (rows["openai"]["configured"], rows["openai"]["usable"], rows["openai"]["local"]) == (False, False, False)
    assert (rows["ollama"]["usable"], rows["ollama"]["models"], rows["ollama"]["local"]) == (True, 1, True)
    assert rows["gemini"]["default_model"] == "gemini-2.5-flash"
    assert "sk-ant-secret-value" not in repr(rows)


def test_env_key_status(make):
    reg = make(environ={"GEMINI_API_KEY": "AIza-from-env"})
    assert reg.secrets.status(reg.slot("gemini")) == {"configured": True, "source": "env"}


def test_ollama_running_without_models_is_not_usable(make, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": []})
    row = next(r for r in make().status() if r["provider"] == "ollama")
    assert row["usable"] is False and "ollama pull qwen3:8b" in row["error"]


def test_base_url_override_gets_its_own_key_slot(make, fake_keyring):
    reg = make(
        overrides={"llm.openai.base_url": "https://llm.example.org/v1"}, environ={"OPENAI_API_KEY": "sk-official"}
    )
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "sk-official-in-ring")
    assert reg.slot("openai").name == "openai@https://llm.example.org"
    with pytest.raises(MissingKey, match=r"for https://llm\.example\.org"):
        reg.provider("openai")  # neither the env key nor the official keyring key may go to a new host
    fake_keyring.set_password(KEYRING_SERVICE, "openai@https://llm.example.org", "custom-key")
    provider = reg.provider("openai")
    assert provider.base_url == "https://llm.example.org/v1" and "custom-key" not in repr(provider)


def test_official_url_spelled_out_is_still_the_official_slot(make):
    assert make(overrides={"llm.openai.base_url": "https://API.openai.com/v1/"}).slot("openai").name == "openai"


def test_provider_uses_endpoint_settings(make, fake_keyring):
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    reg = make(overrides={"llm.anthropic.timeout_s": 7})
    assert reg.provider("anthropic").timeout_s == 7
    assert reg.provider("ollama").base_url == "http://localhost:11434"


def test_models_catalog_and_discovered(make, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}, {"name": "phi4:14b"}]})
    reg = make()
    assert [m["id"] for m in reg.models("anthropic")] == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-opus-5-5",
    ]
    assert reg.models("ollama") == [
        {"id": "qwen3:8b", "label": "Qwen 3 8B", "tier": "balanced", "tools": True, "installed": True},
        {"id": "phi4:14b", "label": "phi4:14b", "tier": None, "tools": None, "installed": True},
    ]


def test_connection_test_reports_catalog_drift_and_missing_model(make, fake_keyring, fake_api):
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}]})
    reg = make()
    ok = reg.test("anthropic")
    assert ok["ok"] and ok["models_served"] == 1
    assert ok["catalog_missing"] == ["claude-haiku-4-5-20251001", "claude-opus-5-5"]
    bad_model = reg.test("anthropic", "claude-nope")
    assert (bad_model["ok"], bad_model["error_type"]) == (False, "ModelNotFound")


def test_connection_test_failures_are_reported_not_raised(make, fake_keyring, fake_api):
    reg = make()
    assert reg.test("openai") == {
        "provider": "openai",
        "ok": False,
        "error_type": "MissingKey",
        "message": "OpenAI: no API key is configured. Add one in Settings → Language models, "
        "or set GMNSPY_OPENAI_API_KEY / OPENAI_API_KEY.",
    }
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("GET", "/v1/models", status=401, body={"error": {"message": "invalid x-api-key"}})
    result = reg.test("anthropic")
    assert (result["ok"], result["error_type"]) == (False, "InvalidKey")


def test_is_local_url():
    assert is_local_url("http://localhost:11434") and is_local_url("http://[::1]:8000/v1")
    assert not is_local_url("http://gpu-box:11434") and not is_local_url("https://api.openai.com/v1")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_registry.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.llm.registry'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/llm/registry.py`**

```python
"""ProviderRegistry: adapters built from settings + stored keys, and what is usable right now.

The Workbench routes, the session's parser and the ``gmnspy llm`` CLI all go through this.
It hands out key *status* (configured / source), never key values. The only code that reads
a key is :meth:`ProviderRegistry.provider`, which hands it straight to an adapter.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from gmnspy.config import LLMSettings, Settings, load_settings, user_config_path

from .catalog import Catalog, ProviderInfo, load_catalog
from .errors import LLMError
from .providers import ADAPTERS
from .secrets import KeyringLike, KeySlot, SecretStore, SecretStoreError, origin_of
from .types import LLMProvider

__all__ = ["PROBE_TIMEOUT_S", "ProviderRegistry", "build_registry", "default_registry", "is_local_url"]

#: Status probes of a local server (Ollama) must not stall the UI.
PROBE_TIMEOUT_S = 1.5
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_local_url(url: str) -> bool:
    """Whether ``url`` points at this machine, so requests to it stay local."""
    return (urlsplit(url).hostname or "").lower() in _LOCAL_HOSTS


class ProviderRegistry:
    """Build provider adapters with their keys, and report status, models and connection tests."""

    def __init__(self, settings: LLMSettings, secrets: SecretStore, catalog: Catalog, *, transport: Any = None) -> None:
        """Bind endpoint settings, the key store, the catalog, and an optional ``httpx`` transport (tests)."""
        self.settings = settings
        self.secrets = secrets
        self.catalog = catalog
        self._transport = transport

    def names(self) -> list[str]:
        """Providers with both a catalog entry and an adapter, in catalog order."""
        return [name for name in self.catalog.names() if name in ADAPTERS]

    def base_url(self, name: str) -> str:
        """The effective endpoint for ``name``: the settings override, else the catalog's official URL."""
        override = getattr(self.settings, name).base_url
        return (override or self.catalog[name].base_url).rstrip("/")

    def slot(self, name: str) -> KeySlot:
        """The key slot for ``name``'s *effective* endpoint; a non-official origin gets its own slot."""
        here = origin_of(self.base_url(name))
        return KeySlot(name, None if here == origin_of(self.catalog[name].base_url) else here)

    def provider(self, name: str, *, timeout_s: float | None = None) -> LLMProvider:
        """An adapter for ``name`` holding its key; raises :class:`~gmnspy.llm.errors.MissingKey` if there is none."""
        info = self.catalog[name]
        key = "" if info.kind == "local" else self.secrets.get(self.slot(name), info.label)
        return ADAPTERS[name](
            api_key=key,
            base_url=self.base_url(name),
            timeout_s=timeout_s or getattr(self.settings, name).timeout_s,
            transport=self._transport,
        )

    def status(self) -> list[dict[str, Any]]:
        """One row per provider: configured / source / usable / error / models. Never a key value."""
        return [self._status(name) for name in self.names()]

    def _status(self, name: str) -> dict[str, Any]:
        info = self.catalog[name]
        base = self.base_url(name)
        row: dict[str, Any] = {
            "provider": name,
            "label": info.label,
            "kind": info.kind,
            "base_url": base,
            "local": is_local_url(base),
            "default_model": info.default_model,
            "configured": False,
            "source": None,
            "usable": False,
            "error": None,
            "models": None,
        }
        if info.kind == "local":
            try:
                installed = self.provider(name, timeout_s=PROBE_TIMEOUT_S).list_models()
            except LLMError as exc:
                row["error"] = str(exc)
                return row
            row.update(configured=True, usable=bool(installed), models=len(installed))
            if not installed:
                row["error"] = f"{info.label} is running but has no models; run: ollama pull {info.default_model}"
            return row
        try:
            row.update(self.secrets.status(self.slot(name)))
        except SecretStoreError as exc:
            row["error"] = str(exc)
        row["usable"] = row["configured"]
        return row

    def models(self, name: str) -> list[dict[str, Any]]:
        """Models to offer: the catalog for remote providers; the installed models for local ones."""
        info = self.catalog[name]
        if info.kind == "remote":
            return [m.to_dict() for m in info.models]
        installed = self.provider(name, timeout_s=PROBE_TIMEOUT_S).list_models()
        return [{**_describe(info, model_id), "installed": True} for model_id in installed]

    def test(self, name: str, model: str | None = None) -> dict[str, Any]:
        """An authenticated, token-free call (list models). Failures are reported in the result, not raised."""
        info = self.catalog[name]
        started = time.perf_counter()
        try:
            served = self.provider(name).list_models()
        except LLMError as exc:
            return {"provider": name, "ok": False, "error_type": type(exc).__name__, "message": str(exc)}
        result: dict[str, Any] = {
            "provider": name,
            "ok": True,
            "error_type": None,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "models_served": len(served),
            "catalog_missing": [m.id for m in info.models if m.id not in served] if info.kind == "remote" else [],
            "message": f"{info.label}: connected ({len(served)} models available).",
        }
        if model and model not in served:
            result.update(
                ok=False,
                error_type="ModelNotFound",
                message=f"{info.label}: connected, but model {model!r} is not available here.",
            )
        return result


def _describe(info: ProviderInfo, model_id: str) -> dict[str, Any]:
    known = info.model(model_id)
    return known.to_dict() if known else {"id": model_id, "label": model_id, "tier": None, "tools": None}


def build_registry(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    keyring: KeyringLike | Literal["auto"] | None = "auto",
    transport: Any = None,
) -> ProviderRegistry:
    """A registry for ``settings``: the catalog (plus user overlay) and key store live in the user config dir."""
    env = os.environ if environ is None else environ
    user_dir = user_config_path(env).parent
    catalog = load_catalog(user_dir)
    secrets = SecretStore(
        config_dir=user_dir,
        environ=env,
        env_names={name: info.key_env for name, info in catalog.providers.items()},
        keyring=keyring,
    )
    return ProviderRegistry(settings.llm, secrets, catalog, transport=transport)


def default_registry() -> ProviderRegistry:
    """A registry from the current process's layered settings and environment."""
    return build_registry(load_settings().settings)
```

- [ ] **Step 4: Complete `packages/gmnspy/gmnspy/llm/__init__.py`**

```python
"""Provider-neutral LLM layer for gmnspy's natural-language features.

* :mod:`~gmnspy.llm.types`: :class:`CompletionRequest` / :class:`Completion` and the
  :class:`LLMProvider` protocol every adapter implements.
* :mod:`~gmnspy.llm.providers`: hand-rolled ``httpx`` adapters (anthropic, openai, gemini, ollama).
* :mod:`~gmnspy.llm.structured`: one validated tool call, with a repair loop and JSON mode.
* :mod:`~gmnspy.llm.catalog`: the maintained provider/model catalog (``models.toml``).
* :mod:`~gmnspy.llm.secrets`: write-only API-key storage (env → keyring → 0600 file).
* :mod:`~gmnspy.llm.registry`: :class:`ProviderRegistry`, the entry point.

``httpx``, ``jsonschema`` and ``keyring`` (the ``[nl]`` extra) are imported lazily, so
importing this package never requires them.
"""

from .catalog import Catalog, ModelInfo, ProviderInfo, load_catalog
from .errors import (
    BadRequest,
    BadResponse,
    InvalidKey,
    LLMError,
    MissingKey,
    ModelNotFound,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    ToolsUnsupported,
)
from .registry import ProviderRegistry, build_registry, default_registry, is_local_url
from .secrets import KeySlot, SecretStore, SecretStoreError, looks_like_secret, redact
from .structured import StructuredOutputError, ToolResult, request_tool_call
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall

__all__ = [
    "BadRequest",
    "BadResponse",
    "Catalog",
    "Completion",
    "CompletionRequest",
    "InvalidKey",
    "KeySlot",
    "LLMError",
    "LLMProvider",
    "Message",
    "MissingKey",
    "ModelInfo",
    "ModelNotFound",
    "ProviderInfo",
    "ProviderRegistry",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimited",
    "SecretStore",
    "SecretStoreError",
    "StructuredOutputError",
    "Tool",
    "ToolCall",
    "ToolResult",
    "ToolsUnsupported",
    "build_registry",
    "default_registry",
    "is_local_url",
    "load_catalog",
    "looks_like_secret",
    "redact",
    "request_tool_call",
]
```

- [ ] **Step 5: Run every LLM test so far**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_*.py -q`
Expected: `66 passed` (types 4, catalog 5, secrets 11, anthropic 12, openai 5, gemini 5, ollama 6, structured 8, registry 10). Also run `uv run lint-imports`, and expect all contracts kept.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/llm/registry.py packages/gmnspy/gmnspy/llm/__init__.py packages/gmnspy/tests/test_llm_registry.py
git commit -m "feat(gmnspy.llm): ProviderRegistry — adapters from settings + keys, status, models, connection tests"
```

---

### Task 12: `LLMParser`, `ClaudeParser` alias, `make_parser`; CLI flags; the `[nl]` extra

**Files:**
- Modify: `packages/gmnspy/gmnspy/select/parse.py` (full replacement below), `select/__init__.py`
- Modify: `packages/gmnspy/gmnspy/cli/commands/select.py`, `cli/commands/workbench.py`, `cli/commands/viz.py`
- Modify: `packages/gmnspy/pyproject.toml`, `uv.lock`
- Test: `packages/gmnspy/tests/test_select_parse.py`, `test_select_cli.py`, `test_cli_workbench.py`

- [ ] **Step 1: Update the failing tests.**

In `packages/gmnspy/tests/test_select_parse.py`, replace the imports and the old `test_claude_parser_reads_tool_use_input`. The new top of the file is:

```python
"""Tests for gmnspy.select.parse — utterance -> SelectionIntent."""

import pytest
from gmnspy.config import load_settings
from gmnspy.llm import build_registry
from gmnspy.llm.providers.anthropic import AnthropicProvider
from gmnspy.llm.secrets import KEYRING_SERVICE
from gmnspy.select.errors import IntentError
from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import SELECTION_TOOL, ClaudeParser, LLMParser, StubParser, make_parser

pytestmark = pytest.mark.usefixtures("no_network")

UTTER = "I-40 EB between A Street and B Street"


def _anthropic_reply(payload):
    return {
        "content": [{"type": "tool_use", "id": "t", "name": "emit_selection_intent", "input": payload}],
        "stop_reason": "tool_use",
    }
```

Keep the five `test_stub_*` tests unchanged. Delete `test_claude_parser_reads_tool_use_input` and append:

```python
def test_claude_parser_is_llm_parser_over_anthropic(fake_api):
    payload = {"facility": {"ref": "I 40", "direction": "EB"}, "from_anchor": "A Street", "to_anchor": "B Street"}
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply(payload))
    parser = ClaudeParser(provider=AnthropicProvider(api_key="k", transport=fake_api.transport()))
    intent = parser.parse(UTTER)
    assert isinstance(parser, LLMParser) and parser.model == "claude-sonnet-5"
    assert (intent.facility.ref, intent.facility.direction, intent.from_anchor, intent.utterance) == (
        "I 40",
        "EB",
        "A Street",
        UTTER,
    )
    body = fake_api.body()
    assert body["tools"][0]["input_schema"] == SELECTION_TOOL.input_schema
    assert body["tool_choice"] == {"type": "tool", "name": "emit_selection_intent"}
    assert parser.describe() == {"provider": "anthropic", "model": "claude-sonnet-5", "mode": "tools"}


def test_llm_parser_repairs_an_intent_error_then_succeeds(fake_api):
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"modes": ["drive"]}))
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"facility": {"name": "Main Street"}}))
    provider = AnthropicProvider(api_key="k", transport=fake_api.transport())
    intent = LLMParser(provider, "claude-haiku-4-5-20251001").parse("Main Street")
    assert intent.facility.name == "Main Street" and len(fake_api.requests) == 2
    assert "selection requires one of" in fake_api.body()["messages"][-1]["content"]


def test_llm_parser_gives_up_as_intent_error(fake_api):
    fake_api.add("POST", "/v1/messages", body=_anthropic_reply({"modes": ["drive"]}))
    with pytest.raises(IntentError, match="still invalid after 2 attempts"):
        LLMParser(AnthropicProvider(api_key="k", transport=fake_api.transport()), "m").parse("drive links")


def test_make_parser_stub_default_model_and_explicit_model(tmp_path, isolated_env, fake_keyring, fake_api):
    def parser_for(overrides):
        settings = load_settings(project_dir=tmp_path, environ=isolated_env, overrides=overrides).settings
        registry = build_registry(settings, environ=isolated_env, keyring=fake_keyring, transport=fake_api.transport())
        return make_parser(settings.select, registry)

    stub = parser_for({})
    assert isinstance(stub, StubParser) and stub.describe() == {"provider": "stub", "model": None, "mode": "pattern"}
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "sk-test")
    assert parser_for({"select.provider": "openai"}).model == "gpt-4.1-mini"
    assert parser_for({"select.provider": "openai", "select.model": "gpt-4.1"}).model == "gpt-4.1"
```

Append to `packages/gmnspy/tests/test_select_cli.py`:

```python


def test_cli_unknown_provider_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    res = _run(["select", "Main Street", "dummy", "--provider", "gpt"])
    assert res.exit_code == 2 and "invalid settings" in res.output


def test_cli_missing_key_exits_1_with_how_to(tmp_path, monkeypatch):
    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    for name in ("GMNSPY_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    res = _run(["select", "Main Street", "dummy", "--provider", "openai"])
    assert res.exit_code == 1 and "OpenAI: no API key is configured" in res.output
```

Append to `packages/gmnspy/tests/test_cli_workbench.py`:

```python


def test_app_provider_alias_and_model_flag(served):
    result = runner.invoke(app, ["app", "--provider", "claude", "--model", "claude-haiku-4-5-20251001"])
    assert result.exit_code == 0, result.output
    select = served[0].settings.select
    assert (select.provider, select.model) == ("anthropic", "claude-haiku-4-5-20251001")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_select_parse.py packages/gmnspy/tests/test_select_cli.py packages/gmnspy/tests/test_cli_workbench.py -q`
Expected:
- `test_select_parse.py` fails to collect with `ImportError: cannot import name 'SELECTION_TOOL'`;
- the two new CLI tests fail (the old `--provider` code calls `StubParser`);
- `--model` fails with `No such option: --model`.

- [ ] **Step 3: Replace `packages/gmnspy/gmnspy/select/parse.py` entirely**

```python
"""Parse a natural-language utterance into a SelectionIntent.

Provider-agnostic seam:

* :class:`StubParser`: deterministic and offline. It parses the constrained grammar
  ``<facility> [direction] between <A> and <B>``, and is used in tests and when no
  provider is configured.
* :class:`LLMParser`: any :class:`~gmnspy.llm.types.LLMProvider` (Anthropic, OpenAI,
  Gemini, Ollama) with the one provider-neutral selection tool (:data:`INTENT_TOOL`).
  The model returns a structured intent, never ids. Invalid output is repaired once,
  then reported as an :class:`~gmnspy.select.errors.IntentError`. Provider failures
  (keys, rate limits, timeouts) raise :class:`~gmnspy.llm.errors.LLMError`.
* :class:`ClaudeParser`: the back-compat name for an :class:`LLMParser` over Anthropic.
* :func:`make_parser`: the parser that ``select.provider`` / ``select.model`` describe.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from gmnspy.llm.structured import StructuredOutputError, request_tool_call
from gmnspy.llm.types import LLMProvider, Tool

from .errors import IntentError
from .intent import Facility, SelectionIntent

if TYPE_CHECKING:
    from gmnspy.config import SelectSettings
    from gmnspy.llm.registry import ProviderRegistry

__all__ = [
    "INTENT_TOOL",
    "SELECTION_TOOL",
    "SYSTEM_PROMPT",
    "ClaudeParser",
    "LLMParser",
    "Parser",
    "StubParser",
    "intent_from_payload",
    "make_parser",
]

_DIR_WORDS = {
    "eb": "EB",
    "eastbound": "EB",
    "wb": "WB",
    "westbound": "WB",
    "nb": "NB",
    "northbound": "NB",
    "sb": "SB",
    "southbound": "SB",
}
# route ref like "I-40", "US 1", "NC 54", "SR-147"
_REF_RE = re.compile(r"^(?:I|US|SR|NC|CR|SH|CA|TX)[-\s]?\d+$", re.IGNORECASE)


@runtime_checkable
class Parser(Protocol):
    """Protocol for utterance -> SelectionIntent parsers."""

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse an utterance into a validated :class:`SelectionIntent`."""
        ...


def _facility_from_text(text: str) -> Facility:
    """Interpret the facility phrase as a route ref or a street name."""
    stripped = text.strip()
    if _REF_RE.match(stripped):
        ref = re.sub(r"[-\s]+", " ", stripped).upper()  # "I-40" -> "I 40"
        return Facility(ref=ref)
    return Facility(name=stripped)


class StubParser:
    """Deterministic parser for the constrained grammar (offline/testing)."""

    def describe(self) -> dict[str, Any]:
        """Who parses: recorded on each selection as ``parsed_by``."""
        return {"provider": "stub", "model": None, "mode": "pattern"}

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse the constrained grammar into a :class:`SelectionIntent`."""
        text = utterance.strip()
        # optional segment: "<facility> [dir] between A and B" OR "... from A to B";
        # with no segment clause the whole facility is selected.
        m = re.search(r"\b(?:between|from)\b(.*)\b(?:and|to)\b(.*)$", text, re.IGNORECASE)
        if m:
            head = text[: m.start()].strip()
            from_anchor = self._clean_anchor(m.group(1))
            to_anchor = self._clean_anchor(m.group(2))
        else:
            head, from_anchor, to_anchor = text, None, None

        direction = None
        tokens = head.split()
        if tokens and tokens[-1].lower() in _DIR_WORDS:
            direction = _DIR_WORDS[tokens[-1].lower()]
            head = " ".join(tokens[:-1]).strip()
        if not head or not re.search(r"[a-zA-Z0-9]", head):  # no letters/digits: e.g. "???" isn't a facility
            raise IntentError(f"could not find a facility in {utterance!r}")

        facility = _facility_from_text(head)
        return SelectionIntent(
            facility=Facility(ref=facility.ref, name=facility.name, direction=direction),
            from_anchor=from_anchor,
            to_anchor=to_anchor,
            utterance=utterance,
        )

    @staticmethod
    def _clean_anchor(text: str) -> str:
        cleaned = re.sub(r"\b(exits?|interchanges?|ramps?)\b", "", text, flags=re.IGNORECASE)
        return cleaned.strip(" ,.")


#: Provider-neutral tool schema constraining the model to emit a SelectionIntent.
#: Mirrors a ProjectCard roadway facility selection (see gmnspy.select.intent).
INTENT_TOOL: dict[str, Any] = {
    "name": "emit_selection_intent",
    "description": (
        "Return the structured roadway selection the user described. Choose ONE primary "
        "selector: a facility (by name and/or ref), select_all, or explicit link_ids. Add "
        "from_anchor/to_anchor ONLY when the user wants a segment between two points; omit "
        "them to select the whole facility. Use conditions for attribute filters (e.g. "
        '"where there are 2 lanes" -> {"lanes": [2]}). Never invent link or node ids '
        "unless the user gave them explicitly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "facility": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Route number e.g. 'I 40', 'NC 54'."},
                    "name": {"type": "string", "description": "Street/road name, e.g. 'North Harrison Ave'."},
                    "direction": {"type": "string", "enum": ["EB", "WB", "NB", "SB"]},
                },
            },
            "from_anchor": {"type": "string", "description": "Upstream cross-street/interchange (segment start)."},
            "to_anchor": {"type": "string", "description": "Downstream cross-street/interchange (segment end)."},
            "select_all": {"type": "boolean", "description": "Select every link (then narrowed by conditions/modes)."},
            "link_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Explicit link ids, only if the user gave them.",
            },
            "modes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "e.g. ['drive','bike','walk','transit'].",
            },
            "conditions": {
                "type": "object",
                "description": 'Attribute AND-filters, {column: value | [values]}, e.g. {"lanes": [2,3]}.',
            },
        },
    },
}

#: :data:`INTENT_TOOL` as a :class:`~gmnspy.llm.types.Tool`: byte-identical for every provider.
SELECTION_TOOL = Tool(INTENT_TOOL["name"], INTENT_TOOL["description"], INTENT_TOOL["input_schema"])

#: The system prompt every provider gets; the tool schema carries the detail.
SYSTEM_PROMPT = (
    "You turn a transportation modeller's request into a roadway selection on a GMNS network. "
    "Call emit_selection_intent exactly once. Copy street names, route numbers and cross-street "
    "anchors as the user wrote them; never invent link or node ids."
)


def intent_from_payload(payload: dict[str, Any], utterance: str) -> SelectionIntent:
    """Build a validated :class:`SelectionIntent` from tool arguments (raises :class:`IntentError`)."""
    fac = payload.get("facility") or {}
    facility = (
        Facility(ref=fac.get("ref"), name=fac.get("name"), direction=fac.get("direction"))
        if (fac.get("ref") or fac.get("name"))
        else None
    )
    return SelectionIntent(
        facility=facility,
        from_anchor=payload.get("from_anchor"),
        to_anchor=payload.get("to_anchor"),
        select_all=bool(payload.get("select_all", False)),
        link_ids=payload.get("link_ids"),
        modes=payload.get("modes"),
        conditions=payload.get("conditions") or {},
        utterance=utterance,
    )


class LLMParser:
    """Parse with any :class:`~gmnspy.llm.types.LLMProvider` through the shared selection tool."""

    def __init__(self, provider: LLMProvider, model: str, *, json_mode: bool = False, max_repairs: int = 1) -> None:
        """Bind a provider adapter and a model id (``json_mode`` for models known to lack tool calling)."""
        self.provider = provider
        self.model = model
        self._json_mode = json_mode
        self._max_repairs = max_repairs
        self.last_mode: str | None = None

    def describe(self) -> dict[str, Any]:
        """Which provider, model and mode parse (no secrets): recorded on each selection as ``parsed_by``."""
        return {"provider": self.provider.name, "model": self.model, "mode": self.last_mode}

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse via a forced tool call (or JSON mode); provider failures raise :class:`~gmnspy.llm.errors.LLMError`."""
        try:
            result = request_tool_call(
                self.provider,
                model=self.model,
                tool=SELECTION_TOOL,
                user=utterance,
                system=SYSTEM_PROMPT,
                validate=lambda arguments: intent_from_payload(arguments, utterance),
                json_mode=self._json_mode,
                max_repairs=self._max_repairs,
            )
        except StructuredOutputError as exc:
            raise IntentError(str(exc)) from exc
        self.last_mode = result.mode
        return intent_from_payload(result.arguments, utterance)


class ClaudeParser(LLMParser):
    """Back-compat name: an :class:`LLMParser` over the Anthropic adapter (key from the secret store)."""

    def __init__(self, *, model: str = "claude-sonnet-5", provider: LLMProvider | None = None) -> None:
        """Use ``provider`` if given, else the Anthropic adapter from the current settings and keys."""
        if provider is None:
            from gmnspy.llm.registry import default_registry

            provider = default_registry().provider("anthropic")
        super().__init__(provider, model)


def make_parser(select: SelectSettings, registry: ProviderRegistry) -> Parser:
    """The parser that ``select.provider`` / ``select.model`` describe (``model=None`` means the catalog default).

    Raises :class:`~gmnspy.llm.errors.MissingKey` when a remote provider has no key.
    """
    if select.provider == "stub":
        return StubParser()
    model = select.model or registry.catalog[select.provider].default_model
    return LLMParser(registry.provider(select.provider), model)
```

- [ ] **Step 4: Export the new names.** In `packages/gmnspy/gmnspy/select/__init__.py`, change the parse import to `from .parse import ClaudeParser, LLMParser, Parser, StubParser, make_parser` and replace `__all__` with:

```python
__all__ = [
    "DIRECTIONS",
    "AnchorMatch",
    "ClaudeParser",
    "Facility",
    "LLMParser",
    "Parser",
    "SelectionIntent",
    "SelectionResult",
    "StubParser",
    "make_parser",
    "resolve",
    "resolve_frames",
    "to_fragment",
    "to_projectcard",
    "validate_fragment",
]
```

- [ ] **Step 5: `gmnspy select` takes `--provider`/`--model` from settings.** In `packages/gmnspy/gmnspy/cli/commands/select.py`:

Replace the import `from ...select.parse import ClaudeParser, StubParser` with `from ...select.parse import make_parser`. Then add these two lines directly above `from ...select.emit import to_fragment`, so the relative imports stay sorted:

```python
from ...config import SettingsError, load_settings
from ...llm import LLMError, build_registry
```

Add `from typing import Any` to the stdlib imports. Then add this helper above `register`:

```python
def _make_parser(provider: str | None, model: str | None) -> Any:
    """The parser for ``--provider``/``--model`` over the layered settings (exit 2: bad settings; 1: no key)."""
    overrides = {k: v for k, v in {"select.provider": provider, "select.model": model}.items() if v is not None}
    try:
        settings = load_settings(overrides=overrides).settings
        return make_parser(settings.select, build_registry(settings))
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    except LLMError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
```

In `select(...)`, replace the `provider` option with these two options:

```python
        provider: str = typer.Option(
            None, "--provider", help="Parser: stub | anthropic | openai | gemini | ollama (default: settings)."
        ),
        model: str = typer.Option(None, "--model", help="Model id (default: settings, else the catalog default)."),
```

Then replace the two lines `parser = ClaudeParser() if provider == "claude" else StubParser()` / `intent = parser.parse(utterance)` with:

```python
        parser = _make_parser(provider, model)
        try:
            intent = parser.parse(utterance)
        except LLMError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
```

In `select_serve(...)` and in `cli/commands/viz.py`, change the `--provider` help text to `"NL parser: stub | anthropic | openai | gemini | ollama (default: settings)."`.

- [ ] **Step 6: `gmnspy app --model`.** In `packages/gmnspy/gmnspy/cli/commands/workbench.py`:
- add `model: str | None = None,` to `run_workbench`'s keyword arguments, after `provider`;
- replace the `flags = {...}` line with:

```python
    flags = {
        "select.provider": provider,
        "select.model": model,
        "viz.basemap": basemap,
        "app.host": host,
        "app.port": port,
    }
```

- in `app_cmd`, replace the `--provider` option with these two options:

```python
        provider: str = typer.Option(
            None, "--provider", help="NL parser: stub | anthropic | openai | gemini | ollama (default: settings)."
        ),
        model: str = typer.Option(None, "--model", help="NL model id (default: settings, else the catalog default)."),
```

- pass `model=model` to `run_workbench`.

- [ ] **Step 7: Swap the `[nl]` extra and relock.** In `packages/gmnspy/pyproject.toml`, replace the `nl = [...]` block with:

```toml
nl = [
    # Natural-language features (gmnspy.select, gmnspy.llm). httpx drives the
    # hand-rolled provider adapters (Anthropic, OpenAI and compatible, Gemini,
    # Ollama; no vendor SDKs); jsonschema validates tool-call output and the
    # emitted selection fragment; keyring stores API keys in the OS keychain.
    # The StubParser + resolver need none of these. Requires [graph] for path search.
    "jsonschema>=4.0",
    "httpx>=0.27",
    "keyring>=24",
]
```

Run: `uv lock`
Expected: the lock resolves. `git diff --stat uv.lock` shows `keyring` (and its `jaraco.*` deps) added for gmnspy. If nothing else requires `anthropic`, it disappears from the lock.

- [ ] **Step 8: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_select_parse.py packages/gmnspy/tests/test_select_cli.py packages/gmnspy/tests/test_cli_workbench.py packages/gmnspy/tests/test_select_webapp.py packages/gmnspy/tests/test_viz_server.py -q`
Expected: all pass. `test_select_parse.py` contributes 9, `test_select_cli.py` 4, and `test_cli_workbench.py` 12. The deprecated `select/webapp.py` and `viz/server.py` still construct `ClaudeParser()` only for `provider == "claude"`, which their tests never use.

- [ ] **Step 9: Commit**

```bash
git add packages/gmnspy/gmnspy/select packages/gmnspy/gmnspy/cli/commands packages/gmnspy/pyproject.toml uv.lock packages/gmnspy/tests/test_select_parse.py packages/gmnspy/tests/test_select_cli.py packages/gmnspy/tests/test_cli_workbench.py
git commit -m "feat(gmnspy.select): LLMParser over any provider (ClaudeParser kept as alias), make_parser, --model; [nl] drops the anthropic SDK"
```

---

### Task 13: Session wiring: registry, parser factory, `LLMError` → `ActionError`, `parsed_by`

**Files:**
- Modify: `packages/gmnspy/gmnspy/workbench/session.py`, `packages/gmnspy/gmnspy/workbench/selection.py`
- Test: `packages/gmnspy/tests/test_workbench_session.py` (append)

- [ ] **Step 1: Append the failing tests**

```python


ANTHROPIC_SELECT_REPLY = {
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "emit_selection_intent",
            "input": {
                "facility": {"ref": "I 40", "direction": "EB"},
                "from_anchor": "South Miami Boulevard",
                "to_anchor": "Airport Boulevard",
            },
        }
    ],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 700, "output_tokens": 60},
}


@pytest.fixture
def llm_session(tmp_path, isolated_env, rdu_source, fake_keyring, fake_api, no_network):
    s = Session(project_dir=tmp_path, environ=isolated_env, keyring=fake_keyring, llm_transport=fake_api.transport())
    s.dispatch(OpenNetwork(source=rdu_source))
    return s


def _anthropic_key(session):
    session.llm.secrets.set(session.llm.slot("anthropic"), "sk-ant-test-0000")


def test_select_with_anthropic_records_parsed_by(llm_session, fake_api):
    fake_api.add("POST", "/v1/messages", body=ANTHROPIC_SELECT_REPLY)
    _anthropic_key(llm_session)
    llm_session.dispatch(SetSetting(key="select.provider", value="anthropic"))
    sel = llm_session.dispatch(Select(utterance=UTTERANCE))
    assert sel["status"] == "resolved"
    assert sel["parsed_by"] == {"provider": "anthropic", "model": "claude-sonnet-5", "mode": "tools"}
    assert fake_api.body()["model"] == "claude-sonnet-5"


def test_missing_key_is_an_action_error_not_a_no_match(llm_session):
    llm_session.dispatch(SetSetting(key="select.provider", value="openai"))
    with pytest.raises(ActionError, match="OpenAI: no API key is configured"):
        llm_session.dispatch(Select(utterance=UTTERANCE))
    assert llm_session.history[-1].ok is False


def test_rate_limit_is_an_action_error(llm_session, fake_api):
    fake_api.add("POST", "/v1/messages", status=429, headers={"retry-after": "7"}, body={"error": {"message": "slow"}})
    _anthropic_key(llm_session)
    llm_session.dispatch(SetSetting(key="select.provider", value="anthropic"))
    with pytest.raises(ActionError, match="retry in 7 s"):
        llm_session.dispatch(Select(utterance=UTTERANCE))


def test_invalid_model_output_is_a_no_match_selection(llm_session, fake_api):
    bad = {"content": [{"type": "tool_use", "id": "t", "name": "emit_selection_intent", "input": {"modes": ["drive"]}}]}
    fake_api.add("POST", "/v1/messages", body=bad)
    _anthropic_key(llm_session)
    llm_session.dispatch(SetSetting(key="select.provider", value="anthropic"))
    sel = llm_session.dispatch(Select(utterance=UTTERANCE))
    assert sel["status"] == "not_found" and sel["diagnostics"][0].startswith("could not parse")
    assert sel["parsed_by"]["provider"] == "anthropic" and len(fake_api.requests) == 2  # one repair, then give up


def test_llm_and_select_settings_rebuild_the_parser(llm_session):
    _anthropic_key(llm_session)
    llm_session.dispatch(SetSetting(key="select.provider", value="anthropic"))
    first = llm_session.parser()
    llm_session.dispatch(SetSetting(key="select.model", value="claude-haiku-4-5-20251001"))
    second = llm_session.parser()
    assert second is not first and second.model == "claude-haiku-4-5-20251001"
    llm_session.dispatch(SetSetting(key="llm.anthropic.timeout_s", value=5))
    assert llm_session.parser().provider.timeout_s == 5


def test_stub_selection_reports_parsed_by_stub(opened):
    sel = opened.dispatch(Select(utterance=UTTERANCE))
    assert sel["parsed_by"] == {"provider": "stub", "model": None, "mode": "pattern"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session.py -q`
Expected: 6 failures or errors: `TypeError: Session.__init__() got an unexpected keyword argument 'keyring'` for the `llm_session` tests, and `KeyError: 'parsed_by'` for the stub test.

- [ ] **Step 3: Edit `packages/gmnspy/gmnspy/workbench/selection.py`.** Change `selection_payload` and `unparsed_payload` to accept `parsed_by` and include it:

```python
def selection_payload(
    handle: NetworkHandle, result: Any, *, utterance: str | None = None, parsed_by: dict[str, Any] | None = None
) -> dict[str, Any]:
    """JSON-safe selection: status, link ids, located anchors, fragment, diagnostics, and who parsed it."""
```

Add `"parsed_by": parsed_by,` as the last key of the returned dict. Then:

```python
def unparsed_payload(
    handle: NetworkHandle, utterance: str, error: Exception, *, parsed_by: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A ``not_found`` selection for an utterance the parser could not read."""
```

Add `"parsed_by": parsed_by,` as the last key of its returned dict too.

- [ ] **Step 4: Edit `packages/gmnspy/gmnspy/workbench/session.py`.**

Add `from gmnspy.llm import LLMError, ProviderRegistry, build_registry` directly after the `from gmnspy.config import ...` line, and replace `from gmnspy.select.parse import ClaudeParser, StubParser` with `from gmnspy.select.parse import make_parser`.

Replace the `__init__` signature and body with:

```python
    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        parser: Any = None,
        environ: Mapping[str, str] | None = None,
        llm_transport: Any = None,
        keyring: Any = "auto",
    ) -> None:
        """Load settings (raises :class:`~gmnspy.config.SettingsError` on bad config) and start empty.

        ``llm_transport`` (an ``httpx`` transport) and ``keyring`` (``"auto"``, ``None`` or a
        keyring-like object) exist for tests and embedding; the defaults use the network and OS keyring.
        """
        self.project_dir = project_dir
        self._environ = environ
        self._overrides: dict[str, Any] = dict(overrides or {})
        self.loaded: LoadedSettings = load_settings(project_dir=project_dir, overrides=self._overrides, environ=environ)
        self._llm_transport = llm_transport
        self._keyring = keyring
        self.llm: ProviderRegistry = self._build_llm()
        self.registry = NetworkRegistry()
        self.events = EventBus()
        self.active: str | None = None
        self.selection: dict[str, Any] | None = None
        self.style: dict[str, Any] = copy.deepcopy(DEFAULT_STYLE)
        self.history: list[HistoryEntry] = []
        self._injected_parser = parser
        self._parser = parser
        self._lock = threading.RLock()
```

Replace `parser()` with the following, which adds `reset_llm()` and `_build_llm()` next to it:

```python
    def parser(self) -> Any:
        """The NL parser for ``select.provider``/``select.model`` (built lazily; an injected parser wins).

        Raises :class:`~gmnspy.llm.errors.MissingKey` when the chosen provider has no key.
        """
        if self._parser is None:
            self._parser = make_parser(self.settings.select, self.llm)
        return self._parser

    def reset_llm(self) -> None:
        """Rebuild the provider registry and drop the cached parser (after a key or endpoint change)."""
        with self._lock:
            self.llm = self._build_llm()
            if self._injected_parser is None:
                self._parser = None

    def _build_llm(self) -> ProviderRegistry:
        return build_registry(
            self.settings, environ=self._environ, keyring=self._keyring, transport=self._llm_transport
        )
```

In `_do_select`, replace the `if action.utterance is not None: ... else: ...` block and the two lines after it with:

```python
        if action.utterance is not None:
            try:
                parser = self.parser()
                intent = parser.parse(action.utterance)
            except LLMError as exc:  # missing/invalid key, rate limit, timeout: the user must act, so it's an error
                raise ActionError(str(exc)) from None
            except Exception as exc:  # any other parse failure is a normal "could not parse" selection
                self.selection = unparsed_payload(handle, action.utterance, exc, parsed_by=_parser_info(self._parser))
                return self.selection
            parsed_by = _parser_info(parser)
        else:
            intent = SelectionIntent(link_ids=list(action.link_ids or []))
            parsed_by = None
        result = resolve_frames(intent, handle.links_df(), handle.nodes_df())
        self.selection = selection_payload(handle, result, utterance=action.utterance, parsed_by=parsed_by)
        return self.selection
```

In `_do_set_setting`, replace the two lines that reset the parser for `select.` keys with:

```python
        if action.key.split(".", 1)[0] in ("select", "llm"):
            self.reset_llm()  # parser and adapters rebuild from the new provider/model/endpoint on next use
```

At the end of the module, add:

```python
def _parser_info(parser: Any) -> dict[str, Any] | None:
    """``parser.describe()`` when it has one: provider/model/mode, never secrets."""
    if parser is None:
        return None
    if hasattr(parser, "describe"):
        return parser.describe()
    return {"provider": type(parser).__name__, "model": None, "mode": None}
```

- [ ] **Step 5: Run the session, server and static suites**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session.py packages/gmnspy/tests/test_workbench_server.py packages/gmnspy/tests/test_workbench_network_routes.py -q`
Expected: all pass, with `test_workbench_session.py` at `28 passed` within the run.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/session.py packages/gmnspy/gmnspy/workbench/selection.py packages/gmnspy/tests/test_workbench_session.py
git commit -m "feat(workbench): parser from settings + ProviderRegistry; provider errors are ActionErrors; selections record parsed_by"
```

---

### Task 14: `/api/llm` routes: status, write-only keys, models, connection test (plus the canary test)

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/routes/llm.py`
- Modify: `packages/gmnspy/gmnspy/workbench/server.py`
- Test: `packages/gmnspy/tests/test_workbench_llm_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the /api/llm routes: status only, write-only keys, guards, and the canary (no key ever leaks)."""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from gmnspy.llm.secrets import KEYRING_SERVICE
from gmnspy.workbench import Session, build_app

pytestmark = pytest.mark.usefixtures("no_network")

SECRETS = {"X-GMNSpy-Secrets": "1"}
KEY = "sk-ant-api03-ROUTEKEYabcdefghijklmnop"
UTTERANCE = "I-40 EB between South Miami Boulevard and Airport Boulevard"
ROW_KEYS = {
    "provider", "label", "kind", "base_url", "local", "default_model",
    "configured", "source", "usable", "error", "models",
}  # fmt: skip
TOOL_REPLY = {
    "content": [
        {
            "type": "tool_use",
            "id": "t",
            "name": "emit_selection_intent",
            "input": {
                "facility": {"ref": "I 40", "direction": "EB"},
                "from_anchor": "South Miami Boulevard",
                "to_anchor": "Airport Boulevard",
            },
        }
    ],
    "stop_reason": "tool_use",
}


@pytest.fixture
def session(tmp_path, isolated_env, fake_keyring, fake_api):
    return Session(project_dir=tmp_path, environ=isolated_env, keyring=fake_keyring, llm_transport=fake_api.transport())


@pytest.fixture
def client(session):
    return TestClient(build_app(session))


def test_providers_status_shape_has_no_key_fields(client, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}]})
    data = client.get("/api/llm/providers").json()
    assert [r["provider"] for r in data["providers"]] == ["anthropic", "openai", "gemini", "ollama"]
    assert all(set(row) == ROW_KEYS for row in data["providers"])
    ollama = data["providers"][-1]
    assert (ollama["usable"], ollama["local"]) == (True, True)
    assert (data["keyring"], data["key_writes"], data["selected"]) == (True, True, {"provider": "stub", "model": None})


def test_put_key_stores_in_keyring_and_returns_status_only(client, fake_keyring):
    r = client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    assert r.status_code == 200 and "ROUTEKEY" not in r.text
    assert fake_keyring.store[(KEYRING_SERVICE, "anthropic")] == KEY
    row = r.json()["providers"][0]
    assert (row["configured"], row["source"], row["usable"]) == (True, "keyring", True)


def test_key_writes_need_the_secrets_header(client):
    assert client.put("/api/llm/keys/anthropic", json={"key": KEY}).status_code == 403
    assert client.delete("/api/llm/keys/anthropic").status_code == 403
    assert client.post("/api/llm/test", json={"provider": "anthropic"}).status_code == 403


def test_cross_origin_key_write_is_rejected_by_the_middleware(client):
    r = client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers={**SECRETS, "origin": "http://evil.example"})
    assert r.status_code == 403 and "Cross-origin" in r.text


def test_bad_key_bodies_are_422_without_echo(client):
    short = client.put("/api/llm/keys/anthropic", json={"key": "abc1234"}, headers=SECRETS)
    extra = client.put("/api/llm/keys/anthropic", json={"key": KEY, "note": 1}, headers=SECRETS)
    assert (short.status_code, extra.status_code) == (422, 422)
    assert "abc1234" not in short.text and "ROUTEKEY" not in extra.text


def test_local_provider_takes_no_key_and_unknown_is_404(client):
    assert client.put("/api/llm/keys/ollama", json={"key": KEY}, headers=SECRETS).status_code == 400
    assert client.put("/api/llm/keys/mistral", json={"key": KEY}, headers=SECRETS).status_code == 404


def test_delete_key(client, fake_keyring):
    client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    r = client.delete("/api/llm/keys/anthropic", headers=SECRETS)
    assert r.status_code == 200 and r.json()["providers"][0]["configured"] is False and fake_keyring.store == {}


def test_connection_test_reports_catalog_drift(client, fake_api):
    client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}]})
    result = client.post("/api/llm/test", json={"provider": "anthropic"}, headers=SECRETS).json()
    assert result["ok"] and result["catalog_missing"] == ["claude-haiku-4-5-20251001", "claude-opus-5-5"]


def test_connection_test_invalid_key(client, fake_api):
    client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    fake_api.add("GET", "/v1/models", status=401, body={"error": {"message": "invalid x-api-key"}})
    result = client.post("/api/llm/test", json={"provider": "anthropic"}, headers=SECRETS).json()
    assert (result["ok"], result["error_type"]) == (False, "InvalidKey")


def test_exposed_bind_refuses_key_writes(tmp_path, isolated_env, fake_keyring, fake_api):
    exposed = Session(
        project_dir=tmp_path,
        environ=isolated_env,
        overrides={"app.host": "0.0.0.0"},
        keyring=fake_keyring,
        llm_transport=fake_api.transport(),
    )
    client = TestClient(build_app(exposed))
    r = client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    assert r.status_code == 403 and "gmnspy llm set-key" in r.text and fake_keyring.store == {}
    assert client.get("/api/llm/providers").json()["key_writes"] is False


def test_models_route(client, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}]})
    assert [m["id"] for m in client.get("/api/llm/models", params={"provider": "anthropic"}).json()["models"]] == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-opus-5-5",
    ]
    assert client.get("/api/llm/models", params={"provider": "ollama"}).json()["models"][0]["label"] == "Qwen 3 8B"
    assert client.get("/api/llm/models", params={"provider": "mistral"}).status_code == 404


def test_key_change_publishes_a_status_only_event_and_resets_the_parser(session, client, monkeypatch):
    published = []
    monkeypatch.setattr(session.events, "publish", published.append)
    session._parser = object()
    client.put("/api/llm/keys/anthropic", json={"key": KEY}, headers=SECRETS)
    (event,) = [e for e in published if e["type"] == "llm"]
    assert "ROUTEKEY" not in json.dumps(event) and session._parser is None


def test_canary_key_never_leaves_the_secret_store(
    session, client, fake_api, rdu_source, isolated_env, caplog, monkeypatch
):
    canary = "sk-ant-api03-CANARYabcdefghijklmnopqrst"
    fake_api.add("POST", "/v1/messages", body=TOOL_REPLY)
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}]})
    published = []
    real_publish = session.events.publish
    monkeypatch.setattr(
        session.events, "publish", lambda e: (published.append(json.dumps(e, default=str)), real_publish(e))
    )
    caplog.set_level(logging.DEBUG)
    seen = []

    def call(method, url, **kw):
        response = client.request(method, url, **kw)
        seen.append(response.text)
        return response

    assert call("PUT", "/api/llm/keys/anthropic", json={"key": canary}, headers=SECRETS).status_code == 200
    call("POST", "/api/actions", json={"type": "open_network", "source": rdu_source})
    call(
        "POST",
        "/api/actions",
        json={"type": "set_setting", "key": "select.provider", "value": "anthropic", "scope": "user"},
    )
    assert call("POST", "/api/actions", json={"type": "select", "utterance": UTTERANCE}).json()["ok"]
    call("POST", "/api/llm/test", json={"provider": "anthropic"}, headers=SECRETS)
    for url in (
        "/api/llm/providers",
        "/api/settings",
        "/api/state",
        "/api/history",
        "/api/llm/models?provider=anthropic",
    ):
        call("GET", url)
    with client.stream("GET", "/api/events", params={"max_events": 1}) as r:
        seen.append(r.read().decode())
    files = [p.read_text(errors="replace") for p in Path(isolated_env["GMNSPY_CONFIG_DIR"]).rglob("*") if p.is_file()]
    haystack = "\n".join([*seen, *published, caplog.text, *files])
    assert "CANARY" not in haystack
    sent = [r for r in fake_api.requests if r.headers.get("x-api-key") == canary]
    assert sent and all(r.url.host == "api.anthropic.com" for r in sent)  # it reached the provider, and only there
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_llm_routes.py -q`
Expected: `13 failed`. Every `/api/llm/...` request is a 404 until the router exists.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/routes/llm.py`**

```python
"""Language-model routes: provider status, write-only key management, model lists, connection tests.

None of these are Actions: a key cannot be recorded or replayed without recording the key.
A key write leaves only a status-only ``llm`` SSE event and a log line naming the provider
and the store, never the key. No route returns a key; status is ``{provider, configured, source}``.

On top of the server's Host/Origin guard, key writes and connection tests need a loopback
bind and an ``X-GMNSpy-Secrets: 1`` header. A cross-origin page cannot send that custom
header without a CORS preflight, and this server never approves one.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from gmnspy.llm import LLMError, SecretStoreError

from ..session import Session

__all__ = ["SECRETS_HEADER", "llm_router"]

logger = logging.getLogger(__name__)

#: Header every key write and connection test must carry (forces a CORS preflight on any cross-origin page).
SECRETS_HEADER = "X-GMNSpy-Secrets"


class _KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SecretStr = Field(min_length=8, max_length=512)
    backend: Literal["keyring", "file"] = "keyring"


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

    def known(provider: str) -> str:
        if provider not in session.llm.names():
            raise HTTPException(404, f"unknown provider {provider!r}")
        return provider

    def snapshot() -> dict[str, Any]:
        select = session.settings.select
        return {
            "providers": session.llm.status(),
            "keyring": session.llm.secrets.keyring_available,
            "secrets_file": str(session.llm.secrets.file_path),
            "selected": {"provider": select.provider, "model": select.model},
            "key_writes": allow_key_writes,
        }

    def changed(provider: str, verb: str, where: str) -> dict[str, Any]:
        logger.info("llm key %s for %s (%s)", verb, provider, where)  # the provider and store only, never the key
        session.reset_llm()
        state = snapshot()
        session.events.publish({"type": "llm", **state})
        return state

    @router.get("/providers")
    def providers() -> dict[str, Any]:
        return snapshot()

    @router.get("/models")
    def models(provider: str) -> dict[str, Any]:
        known(provider)
        try:
            return {"provider": provider, "models": session.llm.models(provider)}
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from None

    @router.put("/keys/{provider}", dependencies=[Depends(guard)])
    def set_key(provider: str, body: dict = Body(...)) -> dict[str, Any]:  # noqa: B008  (FastAPI Body default)
        info = session.llm.catalog[known(provider)]
        if info.kind == "local":
            raise HTTPException(400, f"{info.label} needs no API key")
        try:
            parsed = _KeyBody.model_validate(body)
        except ValidationError:
            # A hand-written detail: FastAPI's default 422 body would echo the submitted key back.
            raise HTTPException(
                422, 'send {"key": "...", "backend": "keyring" | "file"}; a key is 8-512 characters'
            ) from None
        try:
            source = session.llm.secrets.set(
                session.llm.slot(provider), parsed.key.get_secret_value(), backend=parsed.backend
            )
        except SecretStoreError as exc:
            raise HTTPException(400, str(exc)) from None
        return changed(provider, "set", source)

    @router.delete("/keys/{provider}", dependencies=[Depends(guard)])
    def remove_key(provider: str) -> dict[str, Any]:
        known(provider)
        try:
            removed = session.llm.secrets.remove(session.llm.slot(provider))
        except SecretStoreError as exc:
            raise HTTPException(400, str(exc)) from None
        return changed(provider, "removed", ", ".join(removed) or "nothing stored")

    @router.post("/test", dependencies=[Depends(guard)])
    def check_connection(body: dict = Body(...)) -> dict[str, Any]:  # noqa: B008  (FastAPI Body default)
        try:
            parsed = _TestBody.model_validate(body)
        except ValidationError:
            raise HTTPException(422, 'send {"provider": "...", "model": "..." | null}') from None
        return session.llm.test(known(parsed.provider), parsed.model)

    return router
```

- [ ] **Step 4: Mount it.** In `packages/gmnspy/gmnspy/workbench/server.py`, add `from .routes.llm import llm_router` next to the other route imports. After `app.include_router(network_router(session))`, add:

```python
    # Key writes are refused on an exposed bind: there is no auth beyond the loopback guard (design T10).
    app.include_router(llm_router(session, allow_key_writes=is_loopback_host(session.settings.app.host)))
```

- [ ] **Step 5: Run the route tests, then the whole workbench suite**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_llm_routes.py -q`
Expected: `13 passed`.

Run: `uv run --all-extras pytest packages/gmnspy/tests -q -k workbench`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/routes/llm.py packages/gmnspy/gmnspy/workbench/server.py packages/gmnspy/tests/test_workbench_llm_routes.py
git commit -m "feat(workbench): /api/llm — provider status, write-only key routes (loopback + header guard), tests; canary test"
```

---

### Task 15: `gmnspy llm` CLI: status, set-key (hidden prompt), remove-key, test, models

**Files:**
- Create: `packages/gmnspy/gmnspy/cli/commands/llm.py`
- Modify: `packages/gmnspy/gmnspy/cli/app.py`
- Test: `packages/gmnspy/tests/test_cli_llm.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for `gmnspy llm`: key status, set, remove, test and models from the terminal."""

import json

import httpx
import pytest
from gmnspy.cli.app import app
from gmnspy.llm.secrets import KEYRING_SERVICE
from typer.testing import CliRunner

pytestmark = pytest.mark.usefixtures("no_network")

KEY = "sk-test-cli-abcdefghijklmnopqrstuvwxyz"
KEY_ENV = (
    "GMNSPY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "GMNSPY_OPENAI_API_KEY",
    "OPENAI_API_KEY", "GMNSPY_GEMINI_API_KEY", "GEMINI_API_KEY",
)  # fmt: skip
runner = CliRunner()


@pytest.fixture
def ring(tmp_path, monkeypatch, fake_keyring, fake_api):
    """Isolated config dir and env, the fake keyring as the 'system' one, and the fake API as the network."""
    import gmnspy.llm

    monkeypatch.setenv("GMNSPY_CONFIG_DIR", str(tmp_path / "user"))
    monkeypatch.chdir(tmp_path)
    for name in KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("gmnspy.llm.secrets.system_keyring", lambda: fake_keyring)
    real = gmnspy.llm.build_registry
    monkeypatch.setattr(
        gmnspy.llm, "build_registry", lambda settings, **kw: real(settings, transport=fake_api.transport(), **kw)
    )
    return fake_keyring


def _llm(*args, input=None):
    return runner.invoke(app, ["llm", *args], input=input)


def test_status_json_lists_providers(ring, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}]})
    result = _llm("status", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [r["provider"] for r in data["providers"]] == ["anthropic", "openai", "gemini", "ollama"]
    assert data["keyring"] is True and data["providers"][-1]["usable"] is True


def test_set_key_prompts_hidden_and_never_echoes(ring):
    result = _llm("set-key", "openai", input=KEY + "\n")
    assert result.exit_code == 0, result.output
    assert "stored the OpenAI key in the keyring" in result.output and KEY not in result.output
    assert ring.store[(KEYRING_SERVICE, "openai")] == KEY


def test_set_key_from_stdin(ring):
    assert _llm("set-key", "anthropic", "--stdin", input=KEY + "\n").exit_code == 0
    assert ring.store[(KEYRING_SERVICE, "anthropic")] == KEY


def test_remove_key(ring):
    _llm("set-key", "gemini", input=KEY + "\n")
    result = _llm("remove-key", "gemini")
    assert result.exit_code == 0 and "removed the Gemini key from: keyring" in result.output and ring.store == {}


def test_local_provider_needs_no_key_and_unknown_provider_exits_2(ring):
    local = _llm("set-key", "ollama", input="x\n")
    unknown = _llm("test", "mistral")
    assert (local.exit_code, unknown.exit_code) == (2, 2)
    assert "needs no API key" in local.output and "unknown provider 'mistral'" in unknown.output


def test_test_exit_codes(ring, fake_api):
    ring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}]})
    ok = _llm("test", "anthropic")
    missing = _llm("test", "openai")
    assert ok.exit_code == 0 and "Anthropic: connected (1 models available)." in ok.output
    assert "catalog ids not served here" in ok.output
    assert missing.exit_code == 1 and "OpenAI: no API key is configured" in missing.output


def test_models_lists_the_catalog(ring):
    result = _llm("models", "anthropic")
    assert result.exit_code == 0 and "claude-haiku-4-5-20251001" in result.output and "fast" in result.output


def test_status_text_shows_source_not_key(ring, fake_api):
    ring.set_password(KEYRING_SERVICE, "openai", KEY)
    fake_api.add("GET", "/api/tags", raises=httpx.ConnectError("refused"))
    result = _llm("status")
    assert result.exit_code == 0 and "key set (keyring)" in result.output and KEY not in result.output
    assert "could not reach Ollama" in result.output
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_llm.py -q`
Expected: 8 failures, `No such command 'llm'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/cli/commands/llm.py`**

```python
"""``gmnspy llm``: language-model providers for the natural-language features.

Status, setting and removing API keys, connection tests and model lists, from the
terminal. Keys are read from a hidden prompt (or stdin with ``--stdin``), never from a
command-line argument, so they stay out of shell history and ``ps``. This is also how to
manage keys when the Workbench is bound to a non-local address, since its key routes
refuse writes then.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

__all__ = ["register"]


def _registry() -> Any:
    from gmnspy.config import SettingsError, load_settings
    from gmnspy.llm import build_registry

    try:
        settings = load_settings().settings
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    return build_registry(settings)


def _known(registry: Any, provider: str) -> Any:
    if provider not in registry.names():
        typer.echo(f"error: unknown provider {provider!r}; choose one of: {', '.join(registry.names())}", err=True)
        raise typer.Exit(2)
    return registry.catalog[provider]


def _remote(registry: Any, provider: str) -> Any:
    info = _known(registry, provider)
    if info.kind == "local":
        typer.echo(f"error: {info.label} needs no API key", err=True)
        raise typer.Exit(2)
    return info


def _status_line(row: dict[str, Any]) -> str:
    if row["kind"] == "local":
        state = f"running, {row['models']} model(s)" if row["usable"] else (row["error"] or "not reachable")
    else:
        state = row["error"] or (f"key set ({row['source']})" if row["configured"] else "no key")
    return f"{'*' if row['usable'] else '-'} {row['label']:<16} {state}  [{row['base_url']}]"


def register(app: typer.Typer) -> None:
    """Register the ``llm`` sub-app on ``app``."""
    llm_app = typer.Typer(no_args_is_help=True, help="Language-model providers for natural-language features.")
    app.add_typer(llm_app, name="llm")

    @llm_app.command(name="status")
    def status(json_out: bool = typer.Option(False, "--json", help="Emit JSON on stdout.")) -> None:
        """Show which providers are usable and where each key comes from (never the key)."""
        registry = _registry()
        rows = registry.status()
        if json_out:
            typer.echo(json.dumps({"providers": rows, "keyring": registry.secrets.keyring_available}, indent=2))
            return
        for row in rows:
            typer.echo(_status_line(row))
        store = registry.secrets
        where = "OS keyring" if store.keyring_available else f"no OS keyring; --file uses {store.file_path}"
        typer.echo(f"key storage: {where}")

    @llm_app.command(name="set-key")
    def set_key(
        provider: str = typer.Argument(..., help="anthropic | openai | gemini"),
        file: bool = typer.Option(False, "--file", help="Store in the plain-text 0600 file (only when no OS keyring)."),
        stdin: bool = typer.Option(False, "--stdin", help="Read the key from stdin instead of a hidden prompt."),
    ) -> None:
        """Store an API key for PROVIDER's endpoint: prompted and hidden, never an argument."""
        from gmnspy.llm import SecretStoreError

        registry = _registry()
        info = _remote(registry, provider)
        key = sys.stdin.readline() if stdin else typer.prompt(f"{info.label} API key", hide_input=True)
        try:
            source = registry.secrets.set(registry.slot(provider), key, backend="file" if file else "keyring")
        except SecretStoreError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"stored the {info.label} key in the {source}")

    @llm_app.command(name="remove-key")
    def remove_key(provider: str = typer.Argument(..., help="anthropic | openai | gemini")) -> None:
        """Delete PROVIDER's stored key (keyring and file). Env vars are yours to unset."""
        from gmnspy.llm import SecretStoreError

        registry = _registry()
        info = _remote(registry, provider)
        slot = registry.slot(provider)
        try:
            removed = registry.secrets.remove(slot)
            still = registry.secrets.status(slot)["source"]
        except SecretStoreError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        typer.echo(
            f"removed the {info.label} key from: {', '.join(removed)}" if removed else f"no stored {info.label} key"
        )
        if still == "env":
            typer.echo(f"note: a {info.label} key is still set in the environment")

    @llm_app.command(name="test")
    def test_connection(
        provider: str = typer.Argument(..., help="anthropic | openai | gemini | ollama"),
        model: str = typer.Option(None, "--model", help="Also check that this model is served."),
    ) -> None:
        """Make an authenticated call that spends no tokens (list models); exit 1 on failure."""
        registry = _registry()
        _known(registry, provider)
        result = registry.test(provider, model)
        typer.echo(result["message"])
        if result.get("catalog_missing"):
            typer.echo(f"catalog ids not served here (check models.toml): {', '.join(result['catalog_missing'])}")
        if not result["ok"]:
            raise typer.Exit(1)

    @llm_app.command(name="models")
    def models(provider: str = typer.Argument(..., help="anthropic | openai | gemini | ollama")) -> None:
        """List the models offered for PROVIDER: the catalog, or the installed models for Ollama."""
        from gmnspy.llm import LLMError

        registry = _registry()
        _known(registry, provider)
        try:
            rows = registry.models(provider)
        except LLMError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        for row in rows:
            typer.echo(f"{row['id']:<32} {row['label']:<24} {row['tier'] or '-':<9} tools={row['tools']}")
```

- [ ] **Step 4: Register it.** In `packages/gmnspy/gmnspy/cli/app.py`, add `llm` to the `from .commands import (...)` list, keeping it alphabetical (after `info`). Add `llm.register(gmnspy_app)` directly after `select.register(gmnspy_app)`.

- [ ] **Step 5: Run the tests, plus the CLI contract tests and import linter**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_llm.py packages/gmnspy/tests/test_documented_cli_contract.py packages/gmnspy/tests/test_cli.py -q && uv run lint-imports`
Expected: all pass (`test_cli_llm.py`: `8 passed`), and import-linter reports every contract kept. `gmnspy.cli` → `gmnspy.llm` is allowed.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/cli/commands/llm.py packages/gmnspy/gmnspy/cli/app.py packages/gmnspy/tests/test_cli_llm.py
git commit -m "feat(cli): gmnspy llm {status,set-key,remove-key,test,models} — hidden-prompt key entry, never argv"
```

---

### Task 16: Front end: header provider/model picker and the "Language models" panel

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/static/js/llm.js`
- Modify: `packages/gmnspy/gmnspy/workbench/static/index.html`, `app.css`, `js/api.js`, `js/main.js`
- Test: `packages/gmnspy/tests/test_workbench_static.py` (append)

> **Overlap note:** P1b builds the general Settings workspace. This task builds only the picker and one panel. `llm.js` renders into `#llm-panel`, so P1b can move that container into its Settings view and delete the floating-panel CSS. P1a reflows the header; keep `#nl-picker` immediately after `#utterance` when merging.

- [ ] **Step 1: Append the failing static tests**

```python


def test_llm_module_never_persists_or_stores_key_text():
    src = (JS_DIR / "llm.js").read_text()
    for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie", "./store.js"):
        assert banned not in src, f"llm.js must not use {banned}"


def test_header_has_the_llm_picker_and_panel():
    html = (STATIC_DIR / "index.html").read_text()
    for marker in ('id="nl-provider"', 'id="nl-model"', 'id="nl-dot"', 'id="nl-manage"', 'id="llm-panel"'):
        assert marker in html
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: 2 failures: `FileNotFoundError` for `llm.js`, and the missing `nl-provider` marker.

- [ ] **Step 3: Add `sendJSON` to `packages/gmnspy/gmnspy/workbench/static/js/api.js`.** Append after `dispatch`:

```js
// PUT/DELETE/POST for non-action routes (e.g. /api/llm). Extra headers carry X-GMNSpy-Secrets.
export async function sendJSON(method, path, body, headers = {}) {
  const init = { method, headers: { ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  return readJSON(await fetch(path, init));
}
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/static/js/llm.js`**

```js
// Language models: the header provider/model picker and the "Language models" panel.
// Keys are write-only. The browser sends a key once (PUT) and only ever reads back status:
// {provider, configured, source}. Key text never enters the store, browser storage, or a lasting DOM node.
// P1b's Settings workspace can mount #llm-panel as a section; until then it floats from "Models…".
import { dispatch, getJSON, sendJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";

export const PRIVACY =
  "Remote providers (Anthropic, OpenAI, Gemini) receive your utterance and the selection tool's schema " +
  "(GMNS field names such as lanes), never your network tables or files. Ollama runs on this machine, so " +
  "nothing leaves it unless its URL points elsewhere. Keys stay in your OS keychain and are only sent to " +
  "the provider they were entered for.";
const SECRETS = { "X-GMNSpy-Secrets": "1" };
const STUB = { provider: "stub", label: "Offline (pattern)", usable: true, local: true };

let llm = null;      // last /api/llm/providers snapshot: status only, never key values
let sources = {};    // /api/settings per-key sources, used to choose the SetSetting scope
let configPath = ""; // the user config.toml path, for the catalog-overlay hint

const providerRow = name => (llm ? llm.providers.find(p => p.provider === name) : null);
const panelOpen = () => $("llm-panel").classList.contains("open");

export function dotClass(p) {
  if (!p) return "off";
  if (p.usable) return p.local ? "ok local" : "ok";
  return p.configured ? "warn" : "off";
}

// Remember choices in the user file, unless a higher layer (project file, env var, or an earlier
// session override) already sets the key: a user-file write would be masked, so keep it per-session.
export const scopeFor = (key, srcs) => (["project", "env", "session"].includes(srcs[key]) ? "session" : "user");

export async function refreshLLM() {
  const [snap, settings] = await Promise.all([getJSON("/api/llm/providers"), getJSON("/api/settings")]);
  llm = snap;
  sources = settings.sources;
  configPath = settings.paths.user;
  await renderPicker();
  if (panelOpen()) await renderPanel();
}

export function onLLMEvent(ev) {
  llm = ev;
  renderPicker().catch(e => toast(e.message));
  if (panelOpen()) renderPanel().catch(e => toast(e.message));
}

// ------------------------------------------------------------------ header picker

async function renderPicker() {
  if (!llm) return;
  const { provider, model } = llm.selected;
  const options = [STUB, ...llm.providers.filter(p => p.usable)];
  const current = options.find(p => p.provider === provider);
  const html = options.map(
    p => `<option value="${esc(p.provider)}"${p.provider === provider ? " selected" : ""}>${esc(p.label)}</option>`,
  );
  if (!current) html.push(`<option value="${esc(provider)}" selected disabled>${esc(provider)} (not set up)</option>`);
  $("nl-provider").innerHTML = html.join("");
  $("nl-dot").className = `dot ${current ? dotClass(current) : "off"}`;
  $("nl-picker").title = PRIVACY;
  await renderModels(provider, model);
}

async function renderModels(provider, model) {
  const box = $("nl-model");
  const p = providerRow(provider);
  box.hidden = provider === "stub";
  if (provider === "stub" || !p || !p.usable) {
    box.innerHTML = "";
    box.disabled = true;
    return;
  }
  let models = [];
  try {
    models = (await getJSON(`/api/llm/models?provider=${encodeURIComponent(provider)}`)).models;
  } catch (e) {
    toast(e.message);
  }
  const chosen = model || p.default_model;
  const label = m => (m.tier ? `${m.label} · ${m.tier}` : m.label);
  const opts = models.map(m => `<option value="${esc(m.id)}"${m.id === chosen ? " selected" : ""}>${esc(label(m))}</option>`);
  if (chosen && !models.some(m => m.id === chosen)) opts.unshift(`<option value="${esc(chosen)}" selected>${esc(chosen)}</option>`);
  box.innerHTML = opts.join("");
  box.disabled = !opts.length;
}

async function choose(key, value) {
  const result = await dispatch({ type: "set_setting", key, value, scope: scopeFor(key, sources) });
  sources = { ...sources, [key]: result.source };
}

async function onProviderChange(provider) {
  try {
    await choose("select.provider", provider);
    if (provider !== "stub") {
      const p = providerRow(provider);
      const model = p ? p.default_model : null;
      await choose("select.model", model); // explicit, so history replays the same model
      llm.selected = { provider, model };
    } else {
      llm.selected = { ...llm.selected, provider };
    }
  } catch (e) {
    toast(e.message);
  }
  await renderPicker();
}

async function onModelChange(model) {
  try {
    await choose("select.model", model);
    llm.selected = { ...llm.selected, model };
  } catch (e) {
    toast(e.message);
  }
}

// ------------------------------------------------------------------ "Language models" panel

function storageNote() {
  if (!llm.key_writes) {
    return "Key changes are disabled because the Workbench is exposed to the network; use `gmnspy llm set-key` in a terminal.";
  }
  return llm.keyring
    ? "Keys are stored in your OS keychain (keyring)."
    : `No OS keychain is available. Keys can be kept in a plain-text file only you can read: ${llm.secrets_file}`;
}

function statusText(p) {
  if (p.kind === "local") return p.usable ? `running · ${p.models} model(s)` : p.error || "not reachable";
  if (p.error) return p.error;
  return p.configured ? `key set · ${p.source}` : "no key";
}

function actionsHTML(p) {
  if (p.kind === "local") return llm.key_writes ? '<button class="mini ghost" data-act="test">Test</button>' : "";
  if (!llm.key_writes) return "";
  const fromEnv = p.source === "env"; // env keys are managed in the shell, not here
  return [
    fromEnv ? "" : `<button class="mini" data-act="set">${p.configured ? "Replace" : "Set key"}</button>`,
    p.configured && !fromEnv ? '<button class="mini ghost" data-act="remove">Remove</button>' : "",
    p.configured ? '<button class="mini ghost" data-act="test">Test</button>' : "",
  ].join("");
}

function rowHTML(p) {
  const tag = p.local ? ' <span class="tag">local</span>' : "";
  return (
    `<tr data-provider="${esc(p.provider)}"><td><span class="dot ${dotClass(p)}"></span>${esc(p.label)}${tag}</td>` +
    `<td class="st">${esc(statusText(p))}</td><td class="acts">${actionsHTML(p)}</td></tr>` +
    '<tr class="keyrow" hidden><td colspan="3"></td></tr>'
  );
}

async function renderPanel() {
  if (!llm) return;
  $("llm-privacy").textContent = PRIVACY;
  $("llm-storage").textContent = storageNote();
  $("llm-providers").innerHTML = llm.providers.map(rowHTML).join("");
  const ollama = providerRow("ollama");
  if (ollama && document.activeElement !== $("llm-ollama-url")) $("llm-ollama-url").value = ollama.base_url;
  const select = $("llm-catalog-provider");
  if (!select.options.length) {
    select.innerHTML = llm.providers.map(p => `<option value="${esc(p.provider)}">${esc(p.label)}</option>`).join("");
  }
  $("llm-catalog-hint").textContent =
    `Add or relabel models in ${configPath.replace(/config\.toml$/, "llm_models.toml")} (same shape as models.toml).`;
  await renderCatalog(select.value);
}

async function renderCatalog(provider) {
  const table = $("llm-catalog");
  try {
    const { models } = await getJSON(`/api/llm/models?provider=${encodeURIComponent(provider)}`);
    const tools = m => (m.tools === null ? "?" : m.tools ? "yes" : "no");
    table.innerHTML =
      "<tr><th>Model id</th><th>Label</th><th>Tier</th><th>Tools</th></tr>" +
      models
        .map(m => `<tr><td><code>${esc(m.id)}</code></td><td>${esc(m.label)}</td><td>${esc(m.tier || "—")}</td><td>${tools(m)}</td></tr>`)
        .join("");
  } catch (e) {
    table.innerHTML = `<tr><td class="st fail">${esc(e.message)}</td></tr>`;
  }
}

function openKeyForm(tr) {
  const provider = tr.dataset.provider;
  const row = tr.nextElementSibling;
  const cell = row.firstElementChild;
  const fileOption = llm.keyring
    ? ""
    : '<label class="llm-note"><input type="checkbox" class="kfile"> Store in a plain-text file (no OS keychain available)</label>';
  cell.innerHTML =
    '<div class="row"><input type="password" class="kval grow" autocomplete="off" spellcheck="false" ' +
    `placeholder="Paste API key" aria-label="API key for ${esc(provider)}">` +
    '<button class="mini ksave">Save</button><button class="mini ghost kcancel">Cancel</button></div>' +
    fileOption;
  row.hidden = false;
  const input = cell.querySelector(".kval");
  const close = () => {
    input.value = "";
    cell.innerHTML = "";
    row.hidden = true;
  };
  const save = async () => {
    const key = input.value.trim();
    const file = cell.querySelector(".kfile");
    const backend = file && file.checked ? "file" : "keyring";
    close(); // clear and drop the field before the request is even sent
    if (!key) return;
    try {
      llm = await sendJSON("PUT", `/api/llm/keys/${encodeURIComponent(provider)}`, { key, backend }, SECRETS);
    } catch (e) {
      toast(e.message);
    }
    await renderPicker();
    await renderPanel();
  };
  cell.querySelector(".ksave").onclick = save;
  cell.querySelector(".kcancel").onclick = close;
  input.onkeydown = e => {
    if (e.key === "Enter") save();
    else if (e.key === "Escape") close();
  };
  input.focus();
}

async function removeKey(tr) {
  const p = providerRow(tr.dataset.provider);
  if (!confirm(`Remove the ${p.label} key from the ${p.source}?`)) return;
  try {
    llm = await sendJSON("DELETE", `/api/llm/keys/${encodeURIComponent(p.provider)}`, undefined, SECRETS);
  } catch (e) {
    toast(e.message);
  }
  await renderPicker();
  await renderPanel();
}

async function testProvider(tr) {
  const provider = tr.dataset.provider;
  const cell = tr.querySelector(".st");
  cell.textContent = "testing…";
  cell.className = "st";
  const model = llm.selected.provider === provider ? llm.selected.model : null;
  try {
    const r = await sendJSON("POST", "/api/llm/test", { provider, model }, SECRETS);
    const missing = r.catalog_missing && r.catalog_missing.length ? ` Not served here: ${r.catalog_missing.join(", ")}.` : "";
    cell.textContent = r.message + missing;
    cell.className = `st ${r.ok ? "ok" : "fail"}`;
    if (!r.ok) tr.querySelector(".dot").className = "dot warn";
  } catch (e) {
    cell.textContent = e.message;
    cell.className = "st fail";
  }
}

export function wireLLM() {
  $("nl-provider").onchange = e => onProviderChange(e.target.value);
  $("nl-model").onchange = e => onModelChange(e.target.value);
  $("nl-manage").onclick = () => {
    if ($("llm-panel").classList.toggle("open")) renderPanel().catch(e => toast(e.message));
  };
  $("llm-close").onclick = () => $("llm-panel").classList.remove("open");
  $("llm-providers").onclick = e => {
    const button = e.target.closest("button[data-act]");
    if (!button) return;
    const tr = button.closest("tr");
    ({ set: openKeyForm, remove: removeKey, test: testProvider })[button.dataset.act](tr);
  };
  $("llm-ollama-save").onclick = async () => {
    const value = $("llm-ollama-url").value.trim() || null; // empty = back to the default
    try {
      await dispatch({ type: "set_setting", key: "llm.ollama.base_url", value, scope: "user" });
      await refreshLLM();
    } catch (e) {
      toast(e.message);
    }
  };
  $("llm-catalog-provider").onchange = e => renderCatalog(e.target.value);
}
```

- [ ] **Step 5: Edit `packages/gmnspy/gmnspy/workbench/static/index.html`.** Insert this directly after the `<input id="utterance" … />` line:

```html
    <span id="nl-picker">
      <span id="nl-dot" class="dot off" aria-hidden="true"></span>
      <select id="nl-provider" aria-label="Language model provider"></select>
      <select id="nl-model" aria-label="Language model"></select>
      <button id="nl-manage" class="mini ghost" aria-label="Manage language models">Models…</button>
    </span>
```

Insert this directly after the closing `</div>` of `#hist-panel`:

```html
<div class="panel" id="llm-panel" role="dialog" aria-label="Language models">
  <h4>Language models</h4>
  <p class="llm-note" id="llm-privacy"></p>
  <p class="llm-note" id="llm-storage"></p>
  <table id="llm-providers"></table>
  <h4 style="margin-top:14px">Ollama server</h4>
  <div class="row"><input id="llm-ollama-url" class="grow" aria-label="Ollama URL" spellcheck="false" />
    <button class="mini" id="llm-ollama-save">Save</button></div>
  <h4 style="margin-top:14px">Model catalog</h4>
  <div class="row"><select id="llm-catalog-provider" aria-label="Catalog provider"></select></div>
  <table id="llm-catalog"></table>
  <p class="llm-note" id="llm-catalog-hint"></p>
  <div class="row"><button class="mini ghost" id="llm-close">Close</button></div>
</div>
```

- [ ] **Step 6: Append the styles to `packages/gmnspy/gmnspy/workbench/static/app.css`**

```css
  /* ---- language models: header picker + panel ---- */
  #nl-picker { display:flex; align-items:center; gap:6px; flex:none; }
  #nl-picker select { background:#0c0e12; color:var(--ink); border:1px solid var(--edge); border-radius:8px;
                      padding:7px 6px; max-width:160px; font-size:12.5px; }
  .dot.ok { background:var(--from); }
  .dot.ok.local { background:var(--hl); }
  .dot.warn { background:var(--accent); }
  .dot.off { background:#3a4150; }
  #llm-panel { position:fixed; top:60px; right:12px; width:min(580px, calc(100vw - 24px));
               max-height:calc(100vh - 120px); overflow:auto; z-index:6; }
  #llm-panel table { width:100%; border-collapse:collapse; margin:4px 0 8px; }
  #llm-panel th { text-align:left; color:var(--muted); font-weight:600; font-size:11px; padding:4px 6px; }
  #llm-panel td { padding:5px 6px; border-bottom:1px solid var(--edge); vertical-align:middle; font-size:12.5px; }
  #llm-panel td.acts { text-align:right; white-space:nowrap; }
  #llm-panel td.acts button { margin-left:4px; }
  #llm-panel input { background:#0c0e12; color:var(--ink); border:1px solid var(--edge); border-radius:6px; padding:5px 8px; }
  .llm-note { color:var(--muted); font-size:12px; margin:0 0 8px; }
  .tag { font-size:10.5px; padding:1px 6px; border-radius:999px; background:rgba(45,210,230,.15); color:var(--hl); }
  .st.ok { color:var(--from); }
  .st.fail { color:var(--to); }
```

- [ ] **Step 7: Wire it in `packages/gmnspy/gmnspy/workbench/static/js/main.js`.**

Add `import { onLLMEvent, refreshLLM, wireLLM } from "./llm.js";` after the `./history.js` import.

Add this function above `function wireMapButtons()`:

```js
function onHistory(entry) {
  showEntry(entry);
  const a = entry.action; // a set_setting from Python or another tab may change the provider/model/endpoint
  if (entry.ok && a.type === "set_setting" && /^(select|llm)(\.|$)/.test(a.key)) refreshLLM().catch(e => toast(e.message));
}
```

In `boot()`, make these three changes:
1. Change the first line to `wireStore(); wirePanels(); wireSide(); wireTable(); wireHeader(); wireHistory(); wireMapButtons(); wireLLM();`.
2. After `restoreViewMode();`, add `refreshLLM().catch(e => toast(e.message));`.
3. Change the `subscribe(...)` call to:

```js
      subscribe({ state: e => onState(e.state), history: e => onHistory(e.entry), navigate: onNavigate, llm: onLLMEvent });
```

- [ ] **Step 8: Run the static tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: `19 passed`:
- `test_index_loads_main_module` (1);
- per-module served (13, now including `llm.js`);
- import/export graph (1);
- element ids (1), where every `$("…")` id in `llm.js` exists in `index.html`;
- `node --check` (1);
- the two new tests (2).

- [ ] **Step 9: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/static packages/gmnspy/tests/test_workbench_static.py
git commit -m "feat(workbench-ui): provider/model picker in the header + Language models panel (write-only keys, test, Ollama URL, catalog)"
```

---

### Task 17: Recorded contract fixtures, the re-record script, and the opt-in live smoke test

**Files:**
- Create: `packages/gmnspy/tests/fixtures/llm/{anthropic,openai,gemini,ollama}_select.json`
- Create: `packages/gmnspy/tests/test_llm_contract.py`, `packages/gmnspy/tests/test_llm_live.py`
- Create: `scripts/record_llm_fixtures.py`

The fixtures start hand-authored from each API reference: they have the same shapes the adapter unit tests use, but are complete replies. `scripts/record_llm_fixtures.py` replaces each one with a real exchange once you have keys. It writes only the response JSON and the request's top-level body keys, never headers.

- [ ] **Step 1: Create the fixtures.**

`packages/gmnspy/tests/fixtures/llm/anthropic_select.json`:

```json
{
  "provider": "anthropic",
  "source": "Hand-authored from the Messages API reference (tool use). Re-record: uv run --all-extras python scripts/record_llm_fixtures.py anthropic",
  "model": "claude-haiku-4-5-20251001",
  "endpoint": "POST /v1/messages",
  "utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard",
  "request_keys": ["max_tokens", "messages", "model", "system", "tool_choice", "tools"],
  "response": {
    "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-4-5-20251001",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01A09q90qw90lq917835lq9",
        "name": "emit_selection_intent",
        "input": {
          "facility": {"ref": "I 40", "direction": "EB"},
          "from_anchor": "South Miami Boulevard",
          "to_anchor": "Airport Boulevard"
        }
      }
    ],
    "stop_reason": "tool_use",
    "stop_sequence": null,
    "usage": {"input_tokens": 742, "output_tokens": 78}
  },
  "expected": {"ref": "I 40", "direction": "EB", "from_anchor": "South Miami Boulevard", "to_anchor": "Airport Boulevard"}
}
```

`packages/gmnspy/tests/fixtures/llm/openai_select.json`:

```json
{
  "provider": "openai",
  "source": "Hand-authored from the Chat Completions reference (function calling). Re-record: uv run --all-extras python scripts/record_llm_fixtures.py openai",
  "model": "gpt-4.1-mini",
  "endpoint": "POST /v1/chat/completions",
  "utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard",
  "request_keys": ["messages", "model", "tool_choice", "tools"],
  "response": {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1759400000,
    "model": "gpt-4.1-mini",
    "choices": [
      {
        "index": 0,
        "message": {
          "role": "assistant",
          "content": null,
          "tool_calls": [
            {
              "id": "call_abc123",
              "type": "function",
              "function": {
                "name": "emit_selection_intent",
                "arguments": "{\"facility\": {\"ref\": \"I 40\", \"direction\": \"EB\"}, \"from_anchor\": \"South Miami Boulevard\", \"to_anchor\": \"Airport Boulevard\"}"
              }
            }
          ]
        },
        "finish_reason": "stop"
      }
    ],
    "usage": {"prompt_tokens": 512, "completion_tokens": 41, "total_tokens": 553}
  },
  "expected": {"ref": "I 40", "direction": "EB", "from_anchor": "South Miami Boulevard", "to_anchor": "Airport Boulevard"}
}
```

`packages/gmnspy/tests/fixtures/llm/gemini_select.json`:

```json
{
  "provider": "gemini",
  "source": "Hand-authored from the generateContent reference (function calling). Re-record: uv run --all-extras python scripts/record_llm_fixtures.py gemini",
  "model": "gemini-2.5-flash",
  "endpoint": "POST /v1beta/models/gemini-2.5-flash:generateContent",
  "utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard",
  "request_keys": ["contents", "generationConfig", "systemInstruction", "toolConfig", "tools"],
  "response": {
    "candidates": [
      {
        "content": {
          "role": "model",
          "parts": [
            {
              "functionCall": {
                "name": "emit_selection_intent",
                "args": {
                  "facility": {"ref": "I 40", "direction": "EB"},
                  "from_anchor": "South Miami Boulevard",
                  "to_anchor": "Airport Boulevard"
                }
              }
            }
          ]
        },
        "finishReason": "STOP",
        "index": 0
      }
    ],
    "usageMetadata": {"promptTokenCount": 498, "candidatesTokenCount": 33, "totalTokenCount": 531},
    "modelVersion": "gemini-2.5-flash"
  },
  "expected": {"ref": "I 40", "direction": "EB", "from_anchor": "South Miami Boulevard", "to_anchor": "Airport Boulevard"}
}
```

`packages/gmnspy/tests/fixtures/llm/ollama_select.json`:

```json
{
  "provider": "ollama",
  "source": "Hand-authored from the Ollama /api/chat reference (tool calling). Re-record: uv run --all-extras python scripts/record_llm_fixtures.py ollama",
  "model": "qwen3:8b",
  "endpoint": "POST /api/chat",
  "utterance": "I-40 EB between South Miami Boulevard and Airport Boulevard",
  "request_keys": ["messages", "model", "options", "stream", "tools"],
  "response": {
    "model": "qwen3:8b",
    "created_at": "2026-10-02T12:00:00.000000Z",
    "message": {
      "role": "assistant",
      "content": "",
      "tool_calls": [
        {
          "function": {
            "name": "emit_selection_intent",
            "arguments": {
              "facility": {"ref": "I 40", "direction": "EB"},
              "from_anchor": "South Miami Boulevard",
              "to_anchor": "Airport Boulevard"
            }
          }
        }
      ]
    },
    "done_reason": "stop",
    "done": true,
    "total_duration": 2512345678,
    "prompt_eval_count": 612,
    "eval_count": 54
  },
  "expected": {"ref": "I 40", "direction": "EB", "from_anchor": "South Miami Boulevard", "to_anchor": "Airport Boulevard"}
}
```

- [ ] **Step 2: Create `packages/gmnspy/tests/test_llm_contract.py`**

```python
"""Contract tests: recorded provider replies, through the real adapters and LLMParser.

Each fixture under tests/fixtures/llm/ holds one provider exchange (response JSON plus the request's
top-level body keys). Re-record with scripts/record_llm_fixtures.py when an API changes.
"""

import json
from pathlib import Path

import pytest
from gmnspy.llm.providers import ADAPTERS
from gmnspy.select.parse import LLMParser

pytestmark = pytest.mark.usefixtures("no_network")

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "llm").glob("*_select.json"))


def test_every_provider_has_a_fixture():
    assert {json.loads(p.read_text())["provider"] for p in FIXTURES} == set(ADAPTERS)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_recorded_reply_parses_to_the_expected_intent(path, fake_api):
    fixture = json.loads(path.read_text())
    method, endpoint = fixture["endpoint"].split(" ", 1)
    fake_api.add(method, endpoint, body=fixture["response"])
    adapter = ADAPTERS[fixture["provider"]](api_key="test-key", transport=fake_api.transport())
    intent = LLMParser(adapter, fixture["model"]).parse(fixture["utterance"])
    expected = fixture["expected"]
    got = (intent.facility.ref, intent.facility.direction, intent.from_anchor, intent.to_anchor)
    assert got == (expected["ref"], expected["direction"], expected["from_anchor"], expected["to_anchor"])
    assert sorted(fake_api.body()) == fixture["request_keys"]
```

- [ ] **Step 3: Create `packages/gmnspy/tests/test_llm_live.py`**

```python
"""Opt-in live smoke test: one real selection per provider, with your own keys / local Ollama.

    GMNSPY_LIVE_LLM=anthropic,ollama uv run --all-extras pytest packages/gmnspy/tests/test_llm_live.py -m live_llm

Keys come from the env or the OS keyring (this test deliberately uses the real keyring). Override a
model with GMNSPY_LIVE_<PROVIDER>_MODEL. CI never sets GMNSPY_LIVE_LLM, so these are always skipped there.
"""

import os

import pytest
from datagrove.io.credentials import system_keyring
from gmnspy.config import load_settings
from gmnspy.llm import build_registry
from gmnspy.select.parse import LLMParser

pytestmark = pytest.mark.live_llm

LIVE = {name.strip() for name in os.environ.get("GMNSPY_LIVE_LLM", "").split(",") if name.strip()}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "ollama"])
def test_live_selection_round_trip(provider):
    if provider not in LIVE:
        pytest.skip(f"set GMNSPY_LIVE_LLM={provider} to run")
    registry = build_registry(load_settings().settings, keyring=system_keyring())
    model = os.environ.get(f"GMNSPY_LIVE_{provider.upper()}_MODEL") or registry.catalog[provider].default_model
    parser = LLMParser(registry.provider(provider), model)
    intent = parser.parse("I-40 EB between South Miami Boulevard and Airport Boulevard")
    assert intent.facility is not None and intent.facility.direction == "EB"
    assert intent.from_anchor and intent.to_anchor
    assert parser.describe()["mode"] in ("tools", "json")
```

- [ ] **Step 4: Create `scripts/record_llm_fixtures.py`**

```python
"""Re-record the LLM contract fixtures from the live provider APIs.

    uv run --all-extras python scripts/record_llm_fixtures.py anthropic [openai gemini ollama]

Uses your configured keys (env or OS keyring) and each fixture's model and utterance. Writes only
the response JSON and the request's top-level body keys, NEVER headers, so no key reaches the repo.
Review the diff (and re-check "expected") before committing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from datagrove.io.credentials import system_keyring
from gmnspy.config import load_settings
from gmnspy.llm import build_registry
from gmnspy.select.parse import LLMParser

FIXTURES = Path(__file__).resolve().parents[1] / "packages" / "gmnspy" / "tests" / "fixtures" / "llm"


class _Recording(httpx.BaseTransport):
    """Pass requests to the network and keep the last exchange (request + decoded response)."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self.last: tuple[httpx.Request, httpx.Response] | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        live = self._inner.handle_request(request)
        live.read()
        copy = httpx.Response(live.status_code, headers={"content-type": "application/json"}, content=live.content)
        self.last = (request, copy)
        return copy


def record(provider: str) -> Path:
    path = FIXTURES / f"{provider}_select.json"
    fixture = json.loads(path.read_text())
    recorder = _Recording()
    registry = build_registry(load_settings().settings, keyring=system_keyring(), transport=recorder)
    LLMParser(registry.provider(provider), fixture["model"], max_repairs=0).parse(fixture["utterance"])
    if recorder.last is None:
        raise SystemExit(f"{provider}: no exchange was recorded")
    request, response = recorder.last
    fixture.update(
        source=f"Recorded from the live API by scripts/record_llm_fixtures.py ({provider}).",
        endpoint=f"{request.method} {request.url.path}",
        request_keys=sorted(json.loads(request.content)),
        response=response.json(),
    )
    path.write_text(json.dumps(fixture, indent=2) + "\n")
    return path


if __name__ == "__main__":
    for name in sys.argv[1:] or ["anthropic", "openai", "gemini", "ollama"]:
        print(f"recorded {record(name)}")
```

- [ ] **Step 5: Run the contract and live tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_llm_contract.py packages/gmnspy/tests/test_llm_live.py -q -rs`
Expected: `5 passed, 4 skipped`. The skip reasons read `set GMNSPY_LIVE_LLM=<provider> to run`.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/tests/fixtures/llm packages/gmnspy/tests/test_llm_contract.py packages/gmnspy/tests/test_llm_live.py scripts/record_llm_fixtures.py
git commit -m "test(gmnspy.llm): recorded-fixture contract tests per provider, re-record script, opt-in live_llm smoke"
```

---

### Task 18: Docs, full suite, catalog verification, end-to-end browser check

**Files:**
- Modify: `packages/gmnspy/docs/cookbook/workbench.md`
- Modify (only if verification finds drift): `packages/gmnspy/gmnspy/llm/models.toml`

- [ ] **Step 1: Update `packages/gmnspy/docs/cookbook/workbench.md`.**
- In the Quick start, change `--provider claude` to `--provider anthropic`.
- In the settings TOML example, change `provider = "claude"` to `provider = "anthropic"`.
- Then add this section directly before `## Every action is replayable`:

````markdown
## Language models (natural-language selection)

The utterance box can be read by one of these:
- an offline pattern parser (the default);
- a local model through [Ollama](https://ollama.com), for example Qwen;
- Anthropic, OpenAI or Gemini, with your own API key.

Pick the provider and model with the picker next to the utterance box. **Models…** opens the Language models panel, where you can set, replace, remove and test keys, point at another Ollama server, and browse the model catalog.

- **Keys are write-only.**
  - They are stored in your OS keychain (macOS Keychain, Windows Credential Manager, or Secret Service on Linux), or read from `GMNSPY_<PROVIDER>_API_KEY` or the provider's own variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`).
  - They are never written to `config.toml`, shown in the browser, recorded in the session history, or logged.
  - Without a keychain you can opt into a plain-text file that only you can read.
- **What is sent.** Remote providers receive your utterance and the selection tool's schema (GMNS field names such as `lanes`), never your network tables or files. Ollama keeps everything on your machine.
- **Keys are bound to their endpoint.** If you point a provider at a different `base_url`, for example an OpenAI-compatible server, it needs a key entered for that endpoint. Existing keys are never sent there.
- **Errors are explicit.** A missing or rejected key, a rate limit or a timeout shows as an error. The Workbench never quietly switches to another provider.

From a terminal (also the way to manage keys when the Workbench is bound to a non-local address):

```bash
uv run gmnspy llm status
uv run gmnspy llm set-key anthropic
uv run gmnspy llm test anthropic
uv run gmnspy llm models ollama
uv run gmnspy select "I-40 EB between South Miami Boulevard and Airport Boulevard" ./my-network --provider ollama --model qwen3:8b
```

```toml
# ~/.config/gmnspy/config.toml: endpoints and choices only, never keys
[select]
provider = "anthropic"
model = "claude-haiku-4-5-20251001"

[llm.ollama]
base_url = "http://localhost:11434"
```
````

- [ ] **Step 2: Run the full suite and lint**

Run: `uv run --all-extras pytest packages/datagrove/tests packages/gmnspy/tests -q && uv run ruff check packages scripts && uv run ruff format --check packages scripts && uv run lint-imports && uv run pyright packages/gmnspy/gmnspy/llm`
Expected:
- every test passes; the `live_llm` tests are skipped;
- both documented-contract tests pass on the new docs section (`--provider`, `--model` and `gmnspy llm …` all resolve);
- lint is clean, import-linter keeps all contracts, and pyright reports 0 errors in `gmnspy/llm`.

- [ ] **Step 3: Verify the catalog against the live providers (needs the user's keys; the user runs this or is asked first).**
- Run `uv run gmnspy llm test openai`, `uv run gmnspy llm test gemini` and `uv run gmnspy llm test anthropic`, each with a configured key.
- Expected: `… connected (N models available).` Any `catalog ids not served here: …` line names ids to fix in `models.toml`.
- Update `models.toml` and drop each `# VERIFY` comment that has now been checked.
- Re-record the fixtures with `uv run --all-extras python scripts/record_llm_fixtures.py`, then re-run Task 17 Step 5.
- If Gemini rejects `parametersJsonSchema`, apply the Task 7 fallback before re-recording.

- [ ] **Step 4: Check it end to end in the browser pane.** Add a second configuration to the uncommitted `.claude/launch.json` from P0 Task 12. It uses a scratch config dir, so the real `~/.config/gmnspy` is never touched:

```json
{
  "name": "workbench-llm",
  "runtimeExecutable": "env",
  "runtimeArgs": ["GMNSPY_CONFIG_DIR=/tmp/gmnspy-llm-e2e", "uv", "run", "--all-extras", "gmnspy", "app",
                  "packages/gmnspy/gmnspy/fixtures/rdu_i40/parquet", "--port", "8851"],
  "port": 8851
}
```

Start it with `preview_start` (`name: "workbench-llm"`), then check each item. Use `read_console_messages` for errors and screenshots for visuals.

1. The header shows the picker: a teal dot and **Offline (pattern)**, with the model select hidden. Hovering shows the privacy note. The console has no errors.
2. Click **Models…**. The panel lists Anthropic, OpenAI, Gemini and Ollama (local). The storage line reads "Keys are stored in your OS keychain (keyring)." The Ollama row shows `running · N model(s)` if Ollama is running, otherwise "could not reach Ollama at http://localhost:11434 (ConnectError)."
3. **Dummy key flow.** An agent must never type a real key; the user does that themselves.
   - On Anthropic, click **Set key** and enter the test value `sk-ant-dummy-e2e-0000000000`. The field clears at once, and the row reads `key set · keyring`. Anthropic now appears in the picker.
   - Click **Test**. The row reads "Anthropic rejected the API key (HTTP 401). …" in red, and the dot turns amber.
   - Choose Anthropic → **Haiku 4.5 · fast** in the picker. The history strip shows `app.do(SetSetting(key='select.model', value='claude-haiku-4-5-20251001', scope='user'))`. Then run `I-40 EB between South Miami Boulevard and Airport Boulevard`. A red toast shows the same 401 message, the history entry is marked failed, and no selection is drawn.
   - Click **Remove** and confirm. Anthropic leaves the picker, which shows "anthropic (not set up)".
4. **Ollama flow** (only if `ollama list` shows a Qwen model). Choose **Ollama (local)** and the Qwen model, then run the same utterance. The selection resolves. `curl -s localhost:8851/api/state` shows `"parsed_by": {"provider": "ollama", …, "mode": "tools"}`, or `"json"` for a model without tool support.
5. **No-leak checks from a terminal:**
   - `curl -s localhost:8851/api/llm/providers | grep -c dummy-e2e` prints `0`.
   - `curl -s -o /dev/null -w '%{http_code}' -XPUT localhost:8851/api/llm/keys/openai -H 'content-type: application/json' -d '{"key":"sk-test-e2e-0000000000"}'` prints `403` (no `X-GMNSpy-Secrets` header).
   - `grep -rc dummy-e2e /tmp/gmnspy-llm-e2e` finds nothing.

Stop the preview with `preview_stop`, then delete `/tmp/gmnspy-llm-e2e`. Record any defects as new failing tests or fixes before continuing.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/docs/cookbook/workbench.md packages/gmnspy/gmnspy/llm/models.toml packages/gmnspy/tests/fixtures/llm
git commit -m "docs(gmnspy): Language models in the Workbench (providers, write-only keys, privacy, CLI); verified catalog"
```

---

## Self-review notes (completed while writing)

- **Spec coverage (design doc → tasks):**
  - Provider interface and four adapters: Tasks 2, 5–8. Stub kept: Task 12.
  - `ClaudeParser` behind `LLMParser`, with an identical tool schema (`SELECTION_TOOL` ≡ `INTENT_TOOL`): Task 12.
  - Tool-less models (`ToolsUnsupported` → JSON mode; `format` for Ollama) and the repair loop: Tasks 8, 9.
  - Model catalog in data plus the key-safe overlay; Ollama discovery through `/api/tags`: Tasks 3, 11.
  - Secrets:
    - env → keyring → 0600 file;
    - `datagrove.system_keyring`;
    - origin-bound slots (T4);
    - `redact`/`looks_like_secret`;
    - the `SetSetting` guard and 422 no-echo (T5);
    - `repr` hygiene and the header-only Gemini key (T6);
    - scrubbed errors (T7);
    - file modes (T8);
    - exposed-bind refusal (T10);
    - hidden-prompt CLI (T13).
    - These land in Tasks 1, 4, 5, 7, 10, 14 and 15.
  - Non-recorded key routes with status-only responses, the SSE `llm` event and a log line: Task 14.
  - Settings: `select.provider` widened with the `claude` alias, `select.model`, `llm.*`: Task 10.
  - The picker: usable providers only, status dot, scope rule, recorded `SetSetting`. The panel: set/replace/remove/test, Ollama URL, catalog, privacy note. Task 16.
  - Errors become `ActionError`, with no provider fallback; bad output becomes a "could not parse" selection: Task 13.
  - Testing:
    - mocked HTTP per adapter (Tasks 5–8);
    - recorded contract fixtures plus the re-record script (Task 17);
    - the `live_llm` marker (Tasks 0, 17);
    - the canary no-leak test (Task 14);
    - `no_network` and no-system-keyring guards (Tasks 0, 4).
  - Docs: Task 18.
- **Type and name consistency:**
  - `ProviderRegistry.{names, base_url, slot, provider, status, models, test}` are used identically in Session (Task 13), routes (Task 14), CLI (Task 15) and tests.
  - `SecretStore.{lookup, get, status, set, remove, keyring_available, file_path}` are used identically in Tasks 4, 11, 14 and 15.
  - Every adapter takes `api_key/base_url/timeout_s/transport` (`HTTPProvider.__init__`), which `ProviderRegistry.provider` and the contract test rely on.
  - `describe()` exists on `StubParser` and `LLMParser`; Session's `_parser_info` tolerates injected parsers without it.
  - The JS imports in `llm.js` (`dispatch`, `getJSON`, `sendJSON`, `$`, `esc`, `toast`) all exist, which the static graph test enforces.
- **Test counts used in Expected lines:** types 4, catalog 5, secrets 11, anthropic 12 (including 5 parametrized), openai 5, gemini 5, ollama 6, structured 8, registry 10, routes 13, cli-llm 8, contract 5, live 4 skipped. Modified files: config 16→18, actions 9→10, server 22→23 (collected items, including parametrized cases), session 22→28, select_parse 6→9, select_cli 2→4, cli_workbench 11→12, static 16→19, datagrove credentials 15→19.
- **Validated before hand-off:** every code block and edit in this plan was applied to a scratch copy of `feat/workbench-p0` HEAD and checked there:
  - `ruff check` and `ruff format --check` are clean, with no reformatting needed;
  - pyright reports 0 errors in `gmnspy/llm`, `workbench/routes/llm.py`, `select/parse.py` and `cli/commands/llm.py` (the remaining pyright errors in `cli/commands/select.py:_emit` and `workbench/registry.py:node_xy` predate this plan);
  - import-linter keeps both contracts;
  - every per-task Expected count matches;
  - the full `packages/gmnspy/tests --doctest-modules packages/gmnspy/gmnspy` run plus `packages/datagrove/tests/io` gives `1270 passed, 6 skipped` (4 `live_llm`, 2 pre-existing);
  - the documented-contract tests pass with the Task 18 docs section;
  - `node --check` passes on `llm.js`.
- **Independently mergeable after P0:** nothing here depends on P1a/P1b. The conflict table at the top lists the shared files: `config.py`, `index.html`, `session.py`, `server.py`, `main.js`, `app.css`, `pyproject.toml`/`uv.lock`.
- **Known follow-ups:**
  - P4: a per-launch token gating `/api/actions` and `/api/llm/*` writes (design Q4).
  - P3: the assistant reuses `ProviderRegistry` and `request_tool_call`, extends `Message` with tool results, adds grounding behind a privacy-note update, and excludes `llm.*`/`select.*` from its `SetSetting` vocabulary.
  - P1b: mount `#llm-panel` in the Settings workspace and hide `llm.*` from the generic form.
  - Delete `select/webapp.py` and `viz/server.py` (P1); they are the last `ClaudeParser()` callers.
