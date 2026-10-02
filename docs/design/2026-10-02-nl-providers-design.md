# Multi-provider LLM support for the Workbench's natural-language features

Status: **proposed** · Date: 2026-10-02 · Owner: gmnspy · Phase: after P0, before P3 (independently mergeable)

Related: [Workbench design](2026-10-02-gmnspy-workbench-design.md) (core Action bus, §e assistant, §g settings) · [network-viewer PRD §15](2026-09-30-network-viewer-prd.md) (NL action schema) · [NL selection design](2026-09-23-nl-selection-design.md) · Plan: [2026-10-02-nl-providers-plan.md](2026-10-02-nl-providers-plan.md)

## Context

Today natural language means a single provider:
- `gmnspy.select.parse.ClaudeParser` wraps the `anthropic` SDK. It forces the `emit_selection_intent` tool, and its model defaults to `claude-sonnet-5`.
- `StubParser` is a regex grammar used offline and in tests.
- `Settings.select.provider` is `Literal["stub", "claude"]`. The key is whatever `anthropic.Anthropic()` finds in `ANTHROPIC_API_KEY`.
- There is no UI for keys, no way to choose a model, and no local option.

The user wants:
- Local models through **Ollama** (Qwen in particular), plus **Gemini**, **Anthropic** and **OpenAI** via API keys.
- Keys entered in the UI but never exposed. They are kept only in a local secret store.
- A per-use choice of provider and model (for example Haiku vs Sonnet), offered only for providers that are actually set up.

PRD §15 already requires the NL layer to stay provider-agnostic. Its action schema is plain JSON-schema tool definitions, and the LLM emits validated structured output, never ids or code. This design makes that real for the one NL feature that exists today (utterance → `SelectionIntent`). It also leaves the seam the P3 assistant will reuse.

## Goals

1. **One small provider interface** with four adapters (anthropic, openai, gemini, ollama), plus the stub. The selection tool schema is byte-identical across providers.
2. **Keys are write-only from the browser's point of view.** They are never in TOML, any API response, history, `to_python`, SSE, logs or error messages.
3. **Keys can be configured from the UX** ("Set key / Replace / Remove / Test connection"), and also from the CLI for headless or exposed-bind setups.
4. **Provider + model picker** at every NL entry point. It lists only usable providers, shows a status dot, and is remembered through the normal `SetSetting` action.
5. **Model catalog as maintained data** (`gmnspy/llm/models.toml`), with a user overlay file. Ollama models are discovered at runtime.
6. **Explicit, user-facing errors** for missing or invalid keys, rate limits, timeouts and unreachable servers. There is no silent fallback to another provider.
7. **Lean dependencies:** hand-rolled HTTP over `httpx`, no vendor SDKs (justified below).
8. **Offline tests:** mocked HTTP per adapter, recorded-fixture contract tests, and an opt-in live smoke marker.

## Non-goals

- The P3 chat assistant itself: multi-turn chat, tool results, Style/Filter/Navigate tools, draft-before-apply. This design only gives it the provider layer.
- Streaming responses. A selection is one short tool call, so latency is dominated by model time, not streaming.
- Cost metering or budgets. Token counts are captured in `Completion` for later use and are not surfaced.
- Azure OpenAI, Bedrock and Vertex auth flows (OAuth, SigV4, service accounts). OpenAI-*compatible* endpoints that use bearer keys (vLLM, LM Studio, OpenRouter, Groq) work through a `base_url` override.
- Sending network data (facility names, anchor vocabulary) as grounding. Selection keeps today's behaviour: the utterance plus the tool schema. Grounding arrives with the P3 assistant and its own privacy review.
- Per-launch auth tokens for the server. That mechanism belongs to P4's `--console` and is listed as an open question.

## Decisions at a glance

| Topic | Decision |
|---|---|
| HTTP | Hand-rolled adapters over `httpx` (in the `[nl]` extra). Drop `anthropic` from `[nl]`. |
| Interface | `LLMProvider.complete(CompletionRequest) -> Completion` and `list_models() -> list[str]` |
| Parser | `LLMParser(provider, model)` in `gmnspy.select.parse`. `ClaudeParser` is kept as a back-compat subclass. |
| Tool-less models | Automatic JSON mode (same provider, same model), validated with a bounded repair loop |
| Catalog | `gmnspy/llm/models.toml` plus `<user config dir>/llm_models.toml` overlay; Ollama comes from `GET /api/tags` |
| Key storage | env → OS keyring (service `gmnspy-llm`) → 0600 `secrets.toml` only when no keyring exists |
| Key binding | A key slot is bound to the endpoint origin it was entered for. Changing `base_url` never sends an existing key to a new host. |
| Key routes | `/api/llm/*`: not Actions, not recorded. Writes need a loopback bind plus the `X-GMNSpy-Secrets: 1` header. |
| Settings | `select.provider ∈ {stub, anthropic, openai, gemini, ollama}` (`claude` → `anthropic` alias); `select.model: str \| None`; new `llm.<provider>.{base_url, timeout_s}` |
| Picker choice | A recorded `SetSetting`, user scope by default, session scope when a project or env layer pins the key |
| Errors | `LLMError` subclasses become `ActionError` with an actionable message. An invalid model *output* still becomes a "could not parse" selection after repairs. |

## Architecture

```
gmnspy/llm/                         (new, provider-neutral; no gmnspy.select / workbench imports)
  types.py        Tool, Message, ToolCall, CompletionRequest, Completion, LLMProvider (Protocol)
  errors.py       LLMError → MissingKey, InvalidKey, RateLimited, ProviderTimeout, ProviderUnavailable,
                  ModelNotFound, BadRequest, BadResponse, ToolsUnsupported
  _http.py        request_json(): the ONE network call path (lazy httpx, status→error mapping, scrubbing)
  providers/      _base.HTTPProvider; anthropic.py, openai.py, gemini.py, ollama.py; ADAPTERS map
  structured.py   request_tool_call(): forced tool → validate → repair; JSON-mode fallback
  catalog.py      load_catalog(): models.toml + user overlay → Catalog/ProviderInfo/ModelInfo
  models.toml     maintained data
  secrets.py      KeySlot, SecretStore (env → keyring → file), redact(), looks_like_secret()
  registry.py     ProviderRegistry (provider(), status(), models(), test()), build_registry()

gmnspy/select/parse.py       LLMParser, ClaudeParser (alias), make_parser(select_settings, registry)
gmnspy/config.py             SelectSettings widened; LLMSettings section
gmnspy/workbench/session.py  Session.llm (registry), parser via make_parser, LLMError → ActionError, reset_llm()
gmnspy/workbench/routes/llm.py   /api/llm/{providers, models, keys/{p}, test}
gmnspy/workbench/static/js/llm.js  header picker + "Language models" panel
gmnspy/cli/commands/llm.py   gmnspy llm {status, set-key, remove-key, test, models}
datagrove/io/credentials.py  + system_keyring(): shared "is a real OS keyring usable?" check
```

Dependency direction: `gmnspy.llm` → `gmnspy.config` and `datagrove.io.credentials`. `gmnspy.select` → `gmnspy.llm`. `gmnspy.workbench` → both. `gmnspy.llm` imports nothing optional at module import time: `httpx`, `jsonschema` and `keyring` are imported lazily. So `import gmnspy.select` still works on a core install, and the `--doctest-modules` sweep stays green.

## Provider interface

```python
@dataclass(frozen=True)
class CompletionRequest:
    model: str
    messages: tuple[Message, ...]        # plain-text user/assistant turns
    system: str = ""
    tools: tuple[Tool, ...] = ()         # Tool(name, description, input_schema)  — plain JSON schema
    force_tool: str | None = None        # "must call this tool" where the provider supports it
    json_schema: dict | None = None      # JSON mode (native where supported: Ollama `format`)
    max_tokens: int = 1024

@dataclass(frozen=True)
class Completion:
    tool_calls: tuple[ToolCall, ...] = ()   # ToolCall(name, arguments: dict)
    text: str = ""
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

class LLMProvider(Protocol):
    name: str            # "anthropic" | "openai" | "gemini" | "ollama"
    label: str
    def complete(self, request: CompletionRequest) -> Completion: ...
    def list_models(self) -> list[str]: ...  # authenticated, token-free; powers "Test connection" + Ollama discovery
```

The brief sketched `complete_tools(messages, tools, model) -> ToolCalls`. This uses a request object instead, so later fields (temperature, P3's tool results) don't change every adapter's signature. It returns text as well as calls, which JSON mode needs.

**Messages are plain text on purpose.** The repair loop shows the model its previous attempt as an *assistant text* turn, not as a provider-specific tool-use/tool-result pair. That keeps every adapter to one simple mapping. P3 will add a `ToolResult` part when the assistant needs real multi-step tool loops.

## Adapters (wire mapping)

All four inherit `HTTPProvider`. It holds the key privately, overrides `__repr__` so the key never appears in tracebacks or debug output, and sends every request through `_http.request_json`.

| | Anthropic | OpenAI (+ compatible) | Gemini | Ollama |
|---|---|---|---|---|
| Default base | `https://api.anthropic.com` | `https://api.openai.com/v1` | `https://generativelanguage.googleapis.com/v1beta` | `http://localhost:11434` |
| Call | `POST /v1/messages` | `POST /chat/completions` | `POST /models/{model}:generateContent` | `POST /api/chat` (`stream:false`) |
| Auth header | `x-api-key` + `anthropic-version: 2023-06-01` | `Authorization: Bearer` | `x-goog-api-key` (**never** `?key=`: URLs get logged) | none |
| Tools | `tools[{name,description,input_schema}]` | `tools[{type:function,function:{name,description,parameters}}]` | `tools[{functionDeclarations[{name,description,parametersJsonSchema}]}]` | same shape as OpenAI |
| Force tool | `tool_choice{type:tool,name}` | `tool_choice{type:function,function:{name}}` | `toolConfig.functionCallingConfig{mode:ANY,allowedFunctionNames}` | not supported (repair loop covers it) |
| Calls out | `content[].type=="tool_use"` → `input` | `choices[0].message.tool_calls[].function.arguments` (JSON **string**) | `candidates[0].content.parts[].functionCall.args` | `message.tool_calls[].function.arguments` (object) |
| JSON mode | prompt-only | prompt-only | prompt-only | native `format: <schema>` |
| List models | `GET /v1/models` | `GET /models` | `GET /models` (filter `generateContent`) | `GET /api/tags` |

Notes:
- **OpenAI uses Chat Completions, not the Responses API.** Chat Completions is the de facto "OpenAI-compatible" surface (vLLM, LM Studio, OpenRouter, Groq, and both Gemini's and Ollama's compatibility layers), so a single adapter serves every compatible endpoint. Responses can be added later as a second adapter if OpenAI-only features are needed. The adapter sends no `max_tokens`/`max_completion_tokens`, because compatible servers disagree on the name and a forced tool call is short.
- **Gemini `parametersJsonSchema`** accepts full JSON Schema. The older `parameters` field takes an OpenAPI subset that rejects our free-form `conditions` object. *Verify at implementation time* against the current API reference, and re-record the contract fixture (plan Task 17). If the field isn't available, the fallback is a `_gemini_schema()` sanitiser that maps `conditions` to `{"type":"object","properties":{}}` plus a description.
- **Ollama tool support is detected at use, not up front.** A model without tools answers HTTP 400 "… does not support tools". `_http` maps that to `ToolsUnsupported`, and `structured.py` retries the *same model* in JSON mode with `format: <schema>`. This is a mode switch, not a provider fallback. The mode used is recorded in the selection's `parsed_by.mode`.

## Structured output: forced tool, JSON mode, repair loop

`gmnspy.llm.structured.request_tool_call(provider, *, model, tool, user, system, validate, json_mode=False, max_repairs=1)`:

1. **Tools mode:** send `tools=(tool,)` and `force_tool=tool.name`. On `ToolsUnsupported`, switch to JSON mode.
2. **JSON mode:** append "Reply with ONLY one JSON object … schema: …" to the system prompt. Set `json_schema` so that Ollama constrains decoding natively.
3. **Extract:** take the matching tool call, or else the first `{…}` object in the text. This tolerates local models that answer in text even when tools are offered.
4. **Validate:** check the JSON schema (`jsonschema`, already in `[nl]`), then the caller's `validate` (`intent_from_payload`, which raises `IntentError` for "no primary selector", a bad direction, an empty anchor, and so on).
5. **Repair:** on a validation failure, append the previous reply as an assistant turn plus "Your previous reply was not usable: {error}. Try again: …". Allow at most `max_repairs` extra calls (default 1, so two calls in total).
6. **Give up:** raise `StructuredOutputError`. `LLMParser` turns it into `IntentError`, so the Workbench shows a normal `not_found` selection with the diagnostic "could not parse: …", exactly as for a stub parse failure today.

Transport, auth, rate-limit and timeout errors (`LLMError`) are **never** retried here and never trigger another provider.

## Model catalog (`gmnspy/llm/models.toml`)

Maintained data, one table per provider:

```toml
[anthropic]
label = "Anthropic"
kind = "remote"                      # remote = needs a key; local = no key
base_url = "https://api.anthropic.com"
key_env = ["GMNSPY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"]
default_model = "claude-sonnet-5"

[[anthropic.models]]
id = "claude-haiku-4-5-20251001"
label = "Haiku 4.5"
tier = "fast"                        # fast | balanced | best
tools = true
```

- **Anthropic:** Haiku 4.5 `claude-haiku-4-5-20251001` (fast), Sonnet 5 `claude-sonnet-5` (balanced, default), Opus 5.5 `claude-opus-5-5` (best).
- **OpenAI and Gemini:** starting entries are marked `# VERIFY`. They are editable and their ids are not guaranteed current. `gmnspy llm test <provider>` reports every catalog id the live endpoint does not serve (`catalog_missing`), so verification is one command at implementation time and again at each release.
- **Ollama:** the catalog lists only *suggestions* (Qwen tags marked `# VERIFY`), used for labels and for the "run `ollama pull …`" hint. The picker lists whatever `GET /api/tags` returns.
- **User overlay:** `<user config dir>/llm_models.toml`, the same directory as `config.toml`, can add or relabel models and change `label`/`default_model`. It **cannot** change `base_url`, `key_env` or `kind`. Those decide where keys are sent, so they stay in packaged data (see the threat model).
- `select.model` is a free string. The catalog drives the picker and is never a whitelist. A model id the catalog doesn't know still works and is shown as-is.

## Secrets

### Storage and resolution

`SecretStore.lookup(slot)` checks, in order (the same "explicit beats ambient" shape as datagrove's `resolve_credentials`):

1. **env**, for the official endpoint only: `GMNSPY_<PROVIDER>_API_KEY`, then the provider-standard name (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`). The names come from `key_env` in the catalog.
2. **OS keyring:** `keyring.get_password("gmnspy-llm", slot.name)`. This uses Keychain on macOS, Credential Manager on Windows, and Secret Service on Linux.
3. **file:** `<user config dir>/secrets.toml`, used **only** if no keyring backend is usable.
   - The file is written with mode 0600 through `os.open(..., 0o600)` plus an atomic replace.
   - It is *refused* on read if group or world bits are set, with the message "chmod 600 …".
   - It always lives in the user config dir, never the project dir, so it can't be committed with a project.
   - It is created only when the user ticks "Store in plain-text file" in the UI (or passes `gmnspy llm set-key --file`), and it is labelled as plain text everywhere it appears.

Datagrove gains one public helper, `system_keyring()`. It returns the `keyring` module when a real backend is active, or `None` when the package is missing or the fail/null backend is active (headless CI, containers, WSL). Both packages use it, so "is there a keyring?" has one answer. Datagrove's own `resolve_credentials` cascade for data hosts is unchanged. LLM keys use a separate keyring service (`gmnspy-llm`), so they never leak into fsspec `storage_options`.

**Env keys can't be removed from the UI.** The UI shows "key set · env" with no Remove button, because the user unsets the variable in their shell.

### Key slots are bound to an origin

`KeySlot(provider, origin)`:
- When `llm.<provider>.base_url` is unset, or equals the catalog's official URL, the slot is the plain provider name (`"openai"`), and env vars apply.
- Any other origin gets its own slot (`"openai@https://llm.example.org"`), with no env fallback.

So **pointing a provider at a new URL never sends an existing key there**. The new endpoint needs a key entered for it. This closes the "redirect the key" attack (T4 below) without having to decide which settings layers are trusted.

### Write-only flow: set → test → use

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant R as /api/llm routes
    participant S as SecretStore
    participant K as OS keyring
    participant P as Provider API
    participant D as Session.dispatch
    U->>R: PUT /api/llm/keys/openai {key, backend:"keyring"} + X-GMNSpy-Secrets: 1
    Note over R: loopback bind? header? Host/Origin guard (middleware)
    R->>S: set(KeySlot("openai"), key)
    S->>K: set_password("gmnspy-llm", "openai", key)
    R-->>U: {providers:[{provider:"openai", configured:true, source:"keyring"}...]}  (no key)
    R-->>U: SSE event "llm" (status only); log "llm key set for openai (keyring)"
    Note over U: input cleared immediately; key never enters store.js/DOM/storage
    U->>R: POST /api/llm/test {provider:"openai"}
    R->>S: get(slot) → key
    R->>P: GET /models (Authorization: Bearer …)
    R-->>U: {ok:true, latency_ms, models_served, catalog_missing:[…]}
    U->>D: POST /api/actions set_setting select.provider=openai, select.model=… (recorded, no secret)
    U->>D: POST /api/actions select {utterance}
    D->>S: get(slot) (via ProviderRegistry.provider)
    D->>P: POST /chat/completions (forced tool)
    D-->>U: selection {status, link_ids, parsed_by:{provider:"openai", model, mode:"tools"}}
```

Setting a key is **not an Action**. It can't be one without recording the key, and replaying it makes no sense. The only traces are:
- a status-only SSE `llm` event;
- one log line, `llm key set for openai (keyring)`.

`SetSetting` gains a guard: a value that *looks like* an API key (`sk-ant-…`, `sk-…`, `AIza…`, 20+ characters) is rejected at validation. That happens **before** the action is recorded, with "set keys in Settings → Language models". The `/api/actions` 422 body also stops echoing input values (`errors(include_input=False)`), so a pasted key isn't sent back over the wire.

## Settings changes (`gmnspy/config.py`)

```python
class SelectSettings(_Section):
    provider: Literal["stub", "anthropic", "openai", "gemini", "ollama"] = "stub"   # "claude" accepted, stored as "anthropic"
    model: str | None = None            # None → the provider's catalog default_model

class LLMEndpointSettings(_Section):
    base_url: str | None = None         # None → official endpoint; http(s) only
    timeout_s: float = 60.0             # 0 < t ≤ 600

class OllamaSettings(LLMEndpointSettings):
    base_url: str | None = "http://localhost:11434"
    timeout_s: float = 120.0            # local models can be slow to load

class LLMSettings(_Section):            # endpoints only — never keys
    anthropic, openai, gemini: LLMEndpointSettings
    ollama: OllamaSettings

class Settings: ... llm: LLMSettings
```

- **Back-compat:** `provider = "claude"`, whether from a file, `GMNSPY_SELECT__PROVIDER` or `--provider claude`, validates as `"anthropic"`.
- `select.model`'s default moves from `"claude-sonnet-5"` to `None` (meaning catalog default), which resolves to the same model for Anthropic.
- Changing any `llm.*` or `select.*` key resets the session's cached parser and provider registry.
- These are ordinary settings. The P1b Settings form, which is generated from the JSON schema, will show them with no special casing. The `credentials.keyring_hosts` section is left as is; it is about data hosts.

## API routes (`gmnspy/workbench/routes/llm.py`)

| Route | Recorded? | Guard | Returns |
|---|---|---|---|
| `GET /api/llm/providers` | no | Host guard | `{providers:[{provider,label,kind,base_url,local,configured,source,usable,error,models,default_model}], keyring, secrets_file, selected:{provider,model}, key_writes}` |
| `GET /api/llm/models?provider=` | no | Host guard | `{provider, models:[{id,label,tier,tools,installed?}]}` (catalog; Ollama is live) |
| `PUT /api/llm/keys/{provider}` body `{key, backend}` | **no** (log line + SSE status) | Host + Origin + loopback bind + `X-GMNSpy-Secrets: 1` | the providers snapshot |
| `DELETE /api/llm/keys/{provider}` | **no** | same | the providers snapshot |
| `POST /api/llm/test` body `{provider, model?}` | no | same | `{ok, latency_ms, models_served, catalog_missing, message}` or `{ok:false, error_type, message}` |

- `source` is `"env"`, `"keyring"`, `"file"` or `null`. No route takes or returns a key except the body of the `PUT`, and the `PUT` body is validated inside the handler so that a 422 can never echo it.
- Choosing a provider or model is **not** a route. It is `POST /api/actions {"type":"set_setting","key":"select.provider",…}`: recorded, replayable, and secret-free.

## UX

**Header picker** (next to the utterance box now; the P3 assistant drawer reuses the same component):

```
[ I-40 EB between …                 ] ● [Anthropic ▾] [Sonnet 5 · balanced ▾] [Models…] [Select]
```

- **Providers:** "Offline (pattern)" (the stub, always there), plus every provider with `usable: true`. A remote provider is usable when a key is configured. Ollama is usable when it is reachable and has at least one model.
  - If the current setting names a provider that isn't usable, it shows as a disabled "(not set up)" entry. It doesn't silently switch.
- **Status dot:** green = remote and usable; teal = local (Ollama, or any loopback `base_url`); amber = set up but not working (the last **Test** failed, or Ollama is running with no models); grey = not set up.
- **Models:** the catalog for remote providers ("Haiku 4.5 · fast", "Sonnet 5 · balanced", "Opus 5.5 · best"); the installed models for Ollama. Hidden for the stub.
- **Remembering the choice:** a change dispatches `set_setting` with `scope:"user"`, so it is remembered across launches.
  - If `/api/settings` sources show the key is pinned by the `project`, `env` or `session` layer, it uses `scope:"session"`, because a user-file write would be masked.
  - A provider change also sets `select.model` to that provider's `default_model`, so history is explicit and replayable.
- The picker's tooltip is the privacy note.

**"Language models" panel**, opened from **Models…**. Until P1b ships the Settings workspace, it is a floating panel. `llm.js` builds it into a container element, so P1b can mount the same code as a Settings section.

- **Privacy note:**
  > Remote providers (Anthropic, OpenAI, Gemini) receive your utterance and the selection tool's schema (GMNS field names such as `lanes`), never your network tables or files. Ollama runs on this machine, so nothing leaves it unless its URL points elsewhere. Keys stay in your OS keychain and are only sent to the provider they were entered for.
- **Storage line:** "Keys are stored in your OS keychain", or the plain-text-file warning with its path, or "key changes are disabled because the Workbench is exposed to the network; use `gmnspy llm set-key`".
- **One row per provider:** a dot, the label, a `local` tag, and a status ("key set · keyring", "no key", "running · 3 models", or the error text).
  - **Set key / Replace** opens an inline `type=password` field (`autocomplete=off`, `spellcheck=false`), with a "Store in plain-text file" checkbox only when there is no keyring.
  - **Remove** asks for confirmation first.
  - **Test** shows its result inline.
- **Ollama URL** field. Saving dispatches `set_setting llm.ollama.base_url` (user scope). Saving an empty value resets it to the default.
- **Model catalog** view: provider select → id, label, tier, tools. A hint names the overlay file to edit.

**Key hygiene in the browser.** The key exists only in the password input until the `PUT`. The input is cleared in the same tick, the form is removed from the DOM, and nothing is written to `store.js`, `localStorage` or `sessionStorage`. A static test asserts that `llm.js` never touches storage APIs or the store.

**CLI** (for headless use and for exposed binds, where the routes refuse key writes):
- `gmnspy llm status [--json]`
- `gmnspy llm set-key PROVIDER [--file] [--stdin]`: a hidden prompt, never an argv value, so keys stay out of shell history and `ps`
- `gmnspy llm remove-key PROVIDER`
- `gmnspy llm test PROVIDER [--model M]`
- `gmnspy llm models PROVIDER`

`gmnspy select` and `gmnspy app` accept `--provider {stub,anthropic,openai,gemini,ollama,claude}`, and `gmnspy select` adds `--model`.

## Error handling

| Condition | Raised | User sees (toast + failed history entry) |
|---|---|---|
| No key | `MissingKey` (from `SecretStore.get`) | "OpenAI: no API key is configured. Add one in Settings → Language models, or set GMNSPY_OPENAI_API_KEY / OPENAI_API_KEY." |
| 401/403 | `InvalidKey` | "OpenAI rejected the API key (HTTP 401). Replace it in Settings → Language models." (no provider detail, because some echo key fragments) |
| 429 | `RateLimited(retry_after_s)` | "Gemini rate limit or quota reached (HTTP 429); retry in 20 s." |
| Timeout / 408 | `ProviderTimeout` | "Ollama did not answer within 120 s; try again, or raise the timeout in Settings → Language models." |
| Connect error / 5xx / 529 | `ProviderUnavailable` | "could not reach Ollama at http://localhost:11434 (ConnectError)." / "Anthropic is unavailable (HTTP 529): Overloaded" |
| 404 | `ModelNotFound` | "Ollama: model or endpoint not found (HTTP 404): model "qwen3:8b" not found, try pulling it first" |
| Other 4xx | `BadRequest` | provider detail, scrubbed and truncated to 300 characters |
| Unexpected JSON shape, blocked prompt | `BadResponse` | "Gemini blocked the request (SAFETY)." |
| Model output invalid after repairs | `StructuredOutputError` → `IntentError` | a `not_found` selection, with the diagnostic "could not parse: …" (not an error) |
| `[nl]` extra missing | `ProviderUnavailable` | "…need the [nl] extra: pip install 'gmnspy[nl]'" |

How the session handles these:
- `Session._do_select` catches `LLMError` and re-raises `ActionError(str(exc))`. So the action is recorded as failed (`ok: false`), returns HTTP 400, and the UI toasts it.
- Any other parse failure keeps today's behaviour: a "could not parse" `not_found` selection.
- Nothing ever falls back to another provider. JSON mode on the same model is the only automatic change of strategy, and it is visible in `parsed_by.mode`.

Every message is built by our code from status codes plus provider `error.message`, which is passed through `redact()`. That replaces the exact key and anything key-shaped. The original `httpx` exceptions are raised `from None`, so request objects (which carry headers) aren't chained into tracebacks.

## Security review

### Assets

- **A-key:** provider API keys. They have monetary value and are tied to the account.
- **A-data:** utterances and network data. They are mostly public road data, but some projects are confidential, for example unreleased plans.
- **A-cfg:** settings integrity, meaning where requests go.

### Adversaries

- **ADV-web:** a malicious web page open in the user's browser, which can make cross-origin requests and do DNS rebinding.
- **ADV-repo:** a malicious `gmnspy.toml` in a cloned project, or a hostile env var.
- **ADV-local:** another OS user or process on the same machine that can reach `127.0.0.1:8850`.
- **ADV-lan:** a LAN host, when the user binds `--host 0.0.0.0`.
- **ADV-llm:** a provider's or model's output, including prompt injection carried in by the utterance.
- **ACC:** accidents. Logs, screenshots, history, "copy as Python", crash reports, shell history, and committing files.

### Threat model

| # | Threat | Adversary | Mitigation | Residual |
|---|---|---|---|---|
| T1 | Read a key through the API | web, local, lan | No route, response, SSE event, history entry or `to_python` snippet carries a key. The status shape is fixed. The canary test (plan Task 14) greps every route, SSE event and log record. | None via the API |
| T2 | Set, replace or delete a key cross-origin (CSRF) | web | The existing Host allowlist plus the Origin/`Sec-Fetch-Site` guard on non-GET requests. Key routes also need the `X-GMNSpy-Secrets: 1` header, which forces a CORS preflight that we never approve (there is no CORS middleware). | None known |
| T3 | DNS rebinding to read status or trigger tests | web | Host allowlist (P0) | Status reveals which providers are configured. Low impact |
| T4 | **Redirect a key to an attacker host** by changing `llm.<p>.base_url` (from a project file, an env var, CSRF'd `SetSetting`, or the future P3 assistant) | repo, web, llm | **Key slots are bound to the origin.** A non-official origin uses its own slot, with no env fallback. The catalog overlay can't change `base_url`/`key_env`. The P3 rule is that the assistant's tool vocabulary excludes `llm.*` keys. | The user must deliberately type a key for the new origin |
| T5 | Leak through history, `to_python` or SSE (pasting a key into a setting) | acc | `SetSetting` rejects key-shaped values *before* recording. The 422 response omits input values. Keys are never Action fields. | A non-key-shaped token pasted into an unrelated setting is recorded. The schema-generated UI offers no such field |
| T6 | Leak through logs | acc | The key value is never logged. httpx logs URLs only, and Gemini uses a header, not `?key=`. Adapters override `__repr__`. `SecretStr` is used in request models. Provider error text is scrubbed. Exceptions are raised `from None`. | A same-user debugger can see memory. Out of scope |
| T7 | Leak through error messages to the browser | acc, llm | Messages are composed by us. Detail is scrubbed, truncated, and omitted entirely for 401/403. | None known |
| T8 | Plain-text file disclosure | acc, local | It is a last resort only (no keyring), opted into explicitly, and labelled. Mode 0600 is set at creation, and loose permissions are refused on read. It lives in the user config dir, never the project dir. | Windows ignores POSIX modes (it is under `%APPDATA%`, which is per-user). Backups may copy it, and this is documented |
| T9 | Overwrite or delete a key from another local OS user or process | local | Writes don't disclose the key. The loopback bind limits exposure. | ADV-local can swap in their own key or delete yours (an integrity/DoS problem, not confidentiality). See open question Q4 (per-launch token) |
| T10 | Exposed bind (`0.0.0.0`) | lan | The key routes refuse writes (403, pointing to `gmnspy llm set-key`). Status-only reads stay available. P0 already warns loudly at startup. | Status disclosure to the LAN. Selections the LAN triggers spend the user's quota (same as P0's unauthenticated actions) |
| T11 | Prompt injection through the utterance or model output | llm | Model output is only ever a schema- and `SelectionIntent`-validated selection. It has no side effects and no code or SQL. Nothing mutating is reachable from NL in this phase. | P3 must keep draft-before-apply for mutating Actions and keep the `llm.*` exclusion |
| T12 | Same-user malware reads the keychain | — | Out of scope. It can already read the keyring through Python. Documented. | Accepted |
| T13 | Key in shell history or `ps` | acc | The CLI uses a hidden prompt or `--stdin`. Never argv. | None |
| T14 | Supply chain (vendor SDKs) | — | No vendor SDKs; one well-known HTTP client (`httpx`). | `httpx`, `keyring` |
| T15 | Utterance sent to an unexpected remote | repo | The UI labels each provider local or remote using its *effective* `base_url`. Ollama with a non-loopback URL is labelled remote. The privacy note is next to the picker. | The user must read the label |

### Does this need a per-launch token now?

**No**, with a narrow rationale:
- Confidentiality of keys doesn't depend on route auth, because no route returns a key.
- Cross-origin and rebinding attacks are already covered (T2, T3).
- The remaining gap is ADV-local integrity (T9), and an attacker who can do that can also dispatch any P0 Action.

The fix for both is the per-launch token that P4 introduces for `--console`. When that lands, it should gate `/api/actions` and `/api/llm/*` writes together. This is recorded as Q4.

## Dependency choice: hand-rolled `httpx` adapters (recommended) vs vendor SDK extras

**Recommendation: hand-roll the four adapters over `httpx`, move `httpx` and `keyring` into `[nl]`, and drop `anthropic`.**

| | Hand-rolled over httpx | Per-provider SDK extras (`anthropic`, `openai`, `google-genai`, `ollama`) |
|---|---|---|
| Surface we use | 1 completion + 1 list-models endpoint per provider, about 60–90 lines each | the same two calls, behind 4 large SDKs |
| Install weight | `httpx` (already in `[server]`; the Workbench needs it anyway) | 4 SDKs, each pinning `httpx`/`pydantic` ranges, plus `google-genai`'s auth stack. Conflicts are possible with our pydantic/fastapi pins |
| Secret hygiene | We own the headers, logging, error text and `repr`. Gemini key goes in a header | Each SDK has its own logging, retry and exception formats. Some put the key in the URL or repr. Four places to audit |
| Errors | One `_http` status map → typed `LLMError`, uniform messages | 4 exception hierarchies to translate |
| Testing | `httpx.MockTransport` for all four. Recorded JSON fixtures are plain dicts | 4 different mocking styles |
| OpenAI-compatible endpoints | Free (a `base_url` on the Chat Completions adapter) | Free with the `openai` SDK only |
| Cost | We own API drift: version headers, field renames | SDKs absorb drift, at the price of churn in their own APIs |
| Hidden behaviour | None. No silent retries, so explicit errors are guaranteed | SDKs retry 429/5xx by default, which hides the "no silent fallback" behaviour unless configured |

This matches the project's stated preference: thin wrappers over heavy dependencies, with changeable mappings in data files. The drift risk is bounded:
- recorded contract fixtures, re-recorded by script;
- the opt-in live smoke marker;
- pinned version headers;
- a data-driven catalog.

## Testing

- **Unit, per adapter:** `httpx.MockTransport` via a `fake_api` fixture. The tests check:
  - the request URL, headers (including that the key is in the right header and *not* in the URL) and body shape;
  - response parsing;
  - status mapping to the error type for 400 (tools unsupported), 401, 404, 429 (with Retry-After), 500 and timeout;
  - that the key is scrubbed from error text.
- **No real network:** a `no_network` fixture patches `httpx.HTTPTransport.handle_request` to fail loudly. Every LLM test module applies it. An autouse fixture makes `system_keyring()` return `None` in tests, so the developer's real keychain is never touched. Tests that need a keyring inject `FakeKeyring`.
- **Structured:** forced-tool success; repair after a schema error; repair after an `IntentError`; giving up after the budget; `ToolsUnsupported` → JSON mode; text-only replies parsed; `LLMError` not retried.
- **Secrets:**
  - the env/keyring/file order;
  - origin-bound slots ignore env;
  - the file is created 0600 and refused when loose;
  - file writes are refused when a keyring exists;
  - `remove` covers both stores;
  - `redact`;
  - `looks_like_secret`.
- **Routes:** status shape; PUT/DELETE require the header and a loopback bind; 422 doesn't echo; a cross-origin PUT is rejected by the middleware; `test` reports `catalog_missing`; and the **canary test**, which sets a key, exercises every route, SSE event and log, and asserts the canary string never appears.
- **Contract (recorded fixtures):** `tests/fixtures/llm/<provider>_select.json` holds `{endpoint, model, utterance, request_keys, response, expected}`. They start hand-authored from the API references and are re-recorded with `scripts/record_llm_fixtures.py`, which strips headers. The test replays each response through the real adapter plus `LLMParser`, and asserts both the request keys and the parsed intent.
- **Live smoke (opt-in):** `@pytest.mark.live_llm`, skipped unless `GMNSPY_LIVE_LLM=anthropic,openai,gemini,ollama`, which can be any subset. It uses real keys from env or keyring and runs one real selection per provider. CI never sets it.
- **Front end:** the existing static tests (module graph, ids used by JS exist, `node --check`), plus "`llm.js` never uses `localStorage`/`sessionStorage`/`store`". Then an end-to-end browser pass with Ollama (if installed) and a real key.

## Phasing and merge plan

One PR off the P0 branch, sequenced so that each task is green on its own (see the plan):
1. Core layer: `gmnspy.llm` types, errors, catalog, secrets (+ `datagrove.system_keyring`), `_http`, four adapters, `structured`, `registry`. No behaviour change yet.
2. Settings widened, plus the `SetSetting` secret guard and the 422 hardening.
3. `LLMParser`/`ClaudeParser`/`make_parser`; CLI `select --model`; `[nl]` extra swap.
4. Session wiring and `parsed_by`.
5. `/api/llm` routes and the canary test.
6. `gmnspy llm` CLI.
7. Front end: picker and panel.
8. Contract fixtures, live smoke, docs, end-to-end.

### Overlap and conflicts with parallel work

| File | P1a (Open/Import wizard) | This work | Resolution |
|---|---|---|---|
| `gmnspy/config.py` | adds `AppSettings.approve_above_s` (and probably `io.allowed_roots` default/enforcement) | changes `SelectSettings`, adds `LLMEndpointSettings`/`OllamaSettings`/`LLMSettings` classes and a `Settings.llm` field | Different classes, so the conflict is textual only. Both append a line to `class Settings`: keep both |
| `workbench/static/index.html` (header) | replaces `#open-src`/`#open-go` with **Open / Import…** + **Recent**, adds a jobs indicator | inserts `#nl-picker` between `#utterance` and `#go`, and adds `#llm-panel` after `#hist-panel` | Disjoint ranges in the header. Merge by hand if the header is reflowed. The header may get crowded, so P1a/P1b may want to move the utterance box and picker into a second row |
| `workbench/session.py` | adds a jobs runner, routes `OpenNetwork` through jobs, enforces `allowed_roots` | new `__init__` kwargs (`llm_transport`, `keyring`), `self.llm`, `reset_llm()`, `parser()`, `_do_select` error branch, `_do_set_setting` reset line | Disjoint methods. `__init__` is the one shared hunk: both add attributes, so keep both |
| `workbench/server.py` | includes new routers (browse, jobs) | includes `llm_router` | One line each |
| `workbench/static/js/main.js` | wires the wizard and jobs SSE | wires `llm.js` + the `llm` SSE event | Both extend `subscribe({...})` and `boot()`. Keep both |
| `app.css` | wizard styles | picker and panel styles | Append-only |

**Overlap with P1b (Settings workspace).** P1b builds the general schema-driven Settings form. This work builds only:
- the "Language models" panel, as a reusable `mountLLMPanel(container)`;
- the header picker.

When P1b lands, the Settings workspace mounts the same panel as its "Language models" section, and the floating panel is removed. The `llm.*` settings will also show up in P1b's generic form. That is harmless, but P1b should hide the `llm` section there, because the panel is the better editor for it.

**Overlap with P3 (assistant).** P3 consumes `ProviderRegistry.provider()`, `request_tool_call` (or a multi-tool sibling) and the picker. P3 must:
- exclude `llm.*` and `select.*` from the assistant's `SetSetting` vocabulary (T4, T11);
- add facility/anchor grounding behind its own privacy note update.

## Open questions (for the user)

1. **Keyring on your platforms.** On macOS (yours), `keyring` resolves to Keychain. Do collaborators run headless Linux or WSL without a Secret Service? If so, is the labelled 0600 file acceptable there, or should those users be limited to env vars?
2. **Default models.** The proposal: the Anthropic default is Sonnet 5 (`claude-sonnet-5`), with Haiku 4.5 listed as "fast". Should the default be Haiku for selection, which is cheap and probably sufficient for this one-tool task? For Ollama, which Qwen tag do you actually run (for example `qwen3:8b` vs `qwen2.5:7b`)? It becomes the suggestion and `default_model`.
3. **Picker persistence scope.** The proposal is user scope, remembered across launches, with session scope when a project or env layer pins the key. Would you rather the picker be session-only and the Settings panel set the persistent default?
4. **Per-launch token.** Gate `/api/llm/*` writes (and `/api/actions`) with a token now, or wait for P4's console token as proposed?
5. **OpenAI-compatible endpoints.** Is a `base_url` override on the `openai` provider enough (one custom endpoint at a time), or do you want named, multiple compatible endpoints (for example `openai_compatible.<name>`)? The origin-bound key slots already support multiple origins. Only the settings shape would change.
6. **Grounding.** Should selection send a capped list of facility names to improve anchor and facility matching? It isn't in this phase (better parses, at the cost of sending network vocabulary off-machine for remote providers), and it would come with a toggle.
7. **Catalog verification cadence.** Should `gmnspy llm test` with `catalog_missing` be a release-checklist item, or a scheduled CI job that has secrets?
