# Review report — Lens A: Architecture & API design

**Reviewer:** Lens A
**Range:** `8ee65c8..165cd21`
**Files in scope:** 29 files, 3826 lines added, 10 lines removed (CLI + server + MCP + tests for both packages)

## Strengths

- **Composition boundary holds in production code.** `grep` confirms zero `import gmnspy` / `from gmnspy` statements in any of `datagrove/cli/`, `datagrove/api/`, `datagrove/mcp/` (only doctest `Examples:` blocks reference `gmnspy.fixtures` — see Cross-lens flag). Datagrove never hard-codes GMNS table names like `link` or `node` either. The hard rule is honored.
- **`build_app()` factory pattern is consistent across all three generic surfaces.** `datagrove.cli.app.build_app() -> Typer`, `datagrove.api.app.build_app(settings, *, extra_router_factory=...) -> FastAPI`, `datagrove.mcp.server.build_server(name=...) -> FastMCP`. All three return fresh instances (verified by `test_build_app_returns_fresh_app_each_call`), all three are exported via `__init__.__all__`, and all three are mounted on a module-level singleton for the entry-point script. That's the right shape for the "GTFSpy or another consumer" reuse story.
- **Extension hooks are declarative, not mutation-based.** `gmnspy.server.app:39-56` composes via `datagrove.api.build_app(settings, extra_router_factory=_build_network_router)` rather than constructing a base app and then `.include_router()`-ing into it externally. `gmnspy.mcp.server:59` reuses `datagrove.mcp.build_server(name=name)` then registers extra tools on the returned `FastMCP`. Both compose-then-extend; neither monkey-patches.
- **`--json` contract is uniform** across CLI, HTTP, and MCP surfaces — `_report_to_json` / `_report_to_dict` in each surface produce the same `{issues: [...], spec_version}` shape (`datagrove/api/app.py:176-193`, `datagrove/mcp/server.py:101-117`, `gmnspy/server/app.py:119-141`, `gmnspy/mcp/server.py:127-148`). That's a deliberate, well-honoured contract that pays off for the agent audience (architecture §6.9).
- **Bearer-token + warn-on-unsafe-bind defaults are defensible** (`datagrove/api/config.py:88-108`). Localhost bind + bearer-by-default + `compare_digest` for token check + fail-fast on `bearer` mode without a token (`auth.py:58-61`, exercised by `test_bearer_without_token_in_settings_fails_fast`). The `is_public_bind()` / `warn_on_unsafe_combinations()` separation is clean.
- **Stateless MCP design is deliberately scoped, not accidentally limited.** Module docstring at `datagrove/mcp/server.py:8-13` and `gmnspy/mcp/server.py:16-18` both call out the deferral of stateful tools (`edit_session` with rollback) with reasoning. See I-3 for the architecture concern this leaves on the table.
- **CLI ↔ server ↔ MCP read the same `ServerSettings`.** `gmnspy server run` (`gmnspy/cli/app.py:253`) routes through `api_module.load_settings(config)` — operators have one config schema to learn.

## Findings

### Important

#### I-1 — gmnspy.server imports two private symbols from datagrove.api.app
- **File:** `packages/gmnspy/gmnspy/server/app.py:21,83`
- **Lens:** A
- **Category:** composition-boundary / extension-point
- **What's wrong:** `gmnspy.server.app` does `from datagrove.api.app import _safe_get` (a private helper, leading underscore) and reaches into `registry._refs[net_id].source` (a private dict attribute of `PackageRegistry`). Both bypass the public API. The first is the only existing "convert KeyError → 404" helper; the second is the only way to get the original source string after the registry has materialised the package.
- **Why it matters:** The composition story for "GTFSpy or another consumer will reuse datagrove" only works if domain extensions can build on the *public* surface. Today every domain consumer would have to reach into `_safe_get` and `_refs` the same way — meaning either every consumer breaks together when those names change, or they get re-declared as public after the fact. The `extra_router_factory` contract is otherwise excellent; this is the gap.
- **Suggestion:** Promote two pieces to public surface and re-export from `datagrove.api`:
  - Rename `_safe_get(registry, pkg_id)` to a public `get_or_404(registry, pkg_id)` (or make it a `PackageRegistry.get_or_404` method). It is exactly the kind of helper a downstream needs.
  - Add a `PackageRegistry.source_for(pkg_id) -> str` method (or include `source` in the `describe()` payload only and treat that as authoritative). Today `registry._refs[net_id].source` is the only path; that should be a method.
  - Bonus: consider passing `PackageRef` to `extra_router_factory` alongside `registry` and `auth_dep`, so the factory can introspect the original sources without going through the registry's internals.

#### I-2 — Registry conflates `Package` and `Network`; gmnspy router re-loads to recover GMNS metadata
- **File:** `packages/gmnspy/gmnspy/server/app.py:70-86`, `packages/datagrove/datagrove/api/app.py:45-78`
- **Lens:** A
- **Category:** extension-point / protocol-surface
- **What's wrong:** `PackageRegistry.get(pkg_id)` always calls `Package.from_source(...)` — there is no extension hook for the domain package to say "load these sources via `Network.from_source`". The result is that `gmnspy.server.app:80-85` falls back to re-resolving the source as a `Network` solely to read `spec_version`, costing a second load and obscuring the design intent ("if the source was loaded via Network.from_source upstream of the registry it'd be a Network" — comment at `server/app.py:74-76` openly flags this).
- **Why it matters:** GTFSpy will hit the same wall on day one: its `Network` (or `Feed`) class has analogous metadata that the generic `Package` doesn't surface. The pattern as-shipped forces every domain to double-load, and the fallback is a `try/except Exception` swallow (`server/app.py:85-86`) — which silently degrades to `spec_version=None` instead of failing cleanly. This locks in a per-request perf cost across every domain extension.
- **Suggestion:** Make the loader an injection point. Options:
  - `PackageRegistry(settings, *, loader: Callable[[str], Package] = Package.from_source)` — gmnspy passes `Network.from_source`.
  - Or accept a loader on `build_app`: `build_app(settings, *, package_loader=Package.from_source, extra_router_factory=...)` and thread it through.
  - Either way, the cache then holds `Network` instances for domain servers, and the `get_network` endpoint can use `pkg.spec_version` directly. The fallback re-load + bare `except Exception` go away.

#### I-3 — Stateless MCP design forecloses on architecture-promised `edit_session` tool
- **File:** `packages/datagrove/datagrove/mcp/server.py:8-13`, `packages/gmnspy/gmnspy/mcp/server.py:16-18`
- **Lens:** A
- **Category:** protocol-surface / sync, scope, FK, cost
- **What's wrong:** Architecture §6.9 explicitly enumerates `edit_session` (with rollback) as part of the MCP tool surface. The current `build_server` shape — module-scope `Package.from_source(source)` inside each tool — has no place to hang per-session state. The module docstrings note this as deferred ("Stateful surfaces ... deliberately deferred to follow-up issues"). That's fine *if* the current factory shape can absorb a session-aware tool later without breaking back-compat; today, adding session state would require either a parallel `build_session_server()` or surgery on the generic factory.
- **Why it matters:** The two-package architecture stakes its identity on `EditResult` / `Session` / `Rollback` as first-class primitives (§6.4). If the MCP layer can't expose them, a major slice of the user story (agent-driven edits with audit) is locked behind a future refactor of the MCP server contract. Flagging now is cheaper than reshaping the factory after gmnspy MCP consumers depend on the current signature.
- **Suggestion:** Even without implementing `edit_session` in this batch, lock in a session-friendly seam:
  - Pass `state: dict | None = None` (or a typed `MCPServerState` dataclass) through `build_server` so the factory has a place to stash session registries when they land.
  - Or document explicitly in the docstring that the contract may grow a state arg, and that `gmnspy.mcp.build_server` should accept-and-forward kwargs.
  - Either way: write a single-line test that asserts `build_server` accepts unknown kwargs gracefully (or rejects them deliberately) so we know which way it goes before clients depend on the signature.

#### I-4 — `importlib.import_module` for optional extras is repeated five times with three different error shapes
- **File:** `packages/gmnspy/gmnspy/cli/app.py:241-251, 285-293, 761-771, 774-776, 779-781`
- **Lens:** A
- **Category:** pattern-consistency
- **What's wrong:** Five sites use `importlib.import_module("gmnspy.<extra>")` (server, mcp, clean, scope, indexes) but the error handling diverges:
  - `server` and `mcp` and `clean` catch `ImportError`, print a red message naming the extra (`[server]`, `[mcp]`, `[clean]`), and `raise typer.Exit(code=1)`.
  - `scope` and `indexes` (`_import_scope`, `_import_indexes`) **do not catch** the `ImportError` at all — they rely on the `_scope_errors()` context manager to convert it later. That context manager (line 862-867) catches `ImportError` and emits `"missing optional extra ... try \`pip install 'gmnspy[clean]'\`"` — always pointing at `[clean]`, even when the missing import was actually `gmnspy.scope` itself (which is core).
  - The architecture-blessed reason for `importlib` is the import-linter contract on static imports. That logic is identical in all five places; it has divergent ergonomics.
- **Why it matters:** Five repeats of the same pattern with three different error shapes makes the contract unstable: a user installing `gmnspy[clean]` to fix a `scope` error gets a misleading hint, and a future maintainer adding a sixth optional extra has three templates to choose from. The right time to consolidate is *before* the sixth extra lands.
- **Suggestion:** Introduce a small helper, e.g. `gmnspy.cli._extras.require_extra(module_name: str, extra_name: str) -> ModuleType` that:
  - calls `importlib.import_module(module_name)`,
  - on `ImportError` prints the consistent `pip install 'gmnspy[<extra>]'` message,
  - raises `typer.Exit(code=1)`.
  - Then `_import_clean`, `_import_scope`, `_import_indexes`, the `server run` and `mcp serve` blocks all become one-liners. The `_ScopeErrors` context manager can stop second-guessing what extra was missing (it currently has an ImportError branch that's wrong for non-`clean` extras).
  - The helper also gives us one place to add caching, dev-time warnings, etc.

### Suggestion

#### S-1 — `_report_to_json` / `_report_to_dict` is duplicated 4 times across surfaces
- **File:** `packages/datagrove/datagrove/api/app.py:176-193`, `packages/datagrove/datagrove/mcp/server.py:101-117`, `packages/gmnspy/gmnspy/server/app.py:119-141`, `packages/gmnspy/gmnspy/mcp/server.py:127-148`
- **Lens:** A
- **Category:** protocol-surface
- **What's wrong:** The "flatten a `ValidationReport` to JSON-safe dict" helper is repeated nearly verbatim four times. Two of the copies (in `gmnspy.server.app` and `gmnspy.mcp.server`) have explicit comments justifying the duplication ("Duplicates the helper in `datagrove.api.app` because importing a private from datagrove.api would couple too tightly"). The other two pairs differ in one field (`extra` is present in api/`gmnspy.server` copies but not in mcp copies). That divergence is exactly the kind of drift duplication invites.
- **Why it matters:** This *is* the `--json` contract. Today the api and mcp shapes already disagree in one field. A consumer that learned the shape from one surface and tried to read the other gets a `KeyError`. The "duplicate is fine because the helper is 10 lines" rationale only holds if the helper genuinely doesn't drift; the evidence in-tree says it does.
- **Suggestion:** Promote `_report_to_json` to a public `datagrove.reports.to_json_payload(report) -> dict` (or `ValidationReport.to_json_payload()`). All four surfaces import it. Single source of truth; one place to add a field; no `getattr(getattr(...))` chains. (The Lens C pass may have something to say about the readability of those nested `getattr`s too.)

#### S-2 — `extra_router_factory` type signature uses `Callable` instead of a `Protocol`
- **File:** `packages/datagrove/datagrove/api/app.py:81-84`
- **Lens:** A
- **Category:** protocol-surface
- **What's wrong:** `extra_router_factory: Callable[[PackageRegistry, Callable], APIRouter] | None`. The inner `Callable` (the auth dependency) is unparametrised, and the outer signature doesn't say what `Callable` shape the auth dep is — pyright/IDE users get no help, and a domain extension can pass a callable of the wrong arity.
- **Why it matters:** This is the *only* extension hook for domain HTTP routers; getting it right pays dividends across every consumer.
- **Suggestion:** Define a `Protocol` (or `TypeAlias`) for the factory:
  ```python
  AuthDep = Callable[[str | None], None]
  class ExtraRouterFactory(Protocol):
      def __call__(self, registry: "PackageRegistry", auth_dep: AuthDep) -> APIRouter: ...
  ```
  Same idea for the `package_loader` suggested in I-2. Costs ~5 LOC; meaningfully improves IDE / pyright surface for downstream consumers.

#### S-3 — `_resolve_engine` is duplicated between `datagrove.cli.app` and `gmnspy.cli.app`
- **File:** `packages/datagrove/datagrove/cli/app.py:160-189`, `packages/gmnspy/gmnspy/cli/app.py:567-590`
- **Lens:** A
- **Category:** pattern-consistency
- **What's wrong:** Both helpers do the same `name → Engine` resolution (`ibis` / `pandas` / `polars`). The gmnspy copy has a comment ("kept local so this module doesn't depend on the 4.2 helper landing first") — a forward-reference rationale that no longer applies once 4.2 has merged.
- **Why it matters:** A new engine (`duckdb-native`, `daft`, …) means editing two files in lockstep, and they'll drift on the next subtle change (error message, casing rules).
- **Suggestion:** Move to `datagrove.cli.engines.resolve_engine(name)` (or `datagrove.engines.resolve_engine`) and import from both CLIs. `BadParameter` raising is a tiny CLI-flavour concern that can be a thin wrapper in the CLI module, or you can accept that `datagrove.engines.resolve_engine` raises a generic `ValueError` and let the CLI convert.

### Nit

#### N-1 — `_infer_format_for_summary` re-implements `_infer_write_format` with a comment saying it intentionally re-implements
- **File:** `packages/datagrove/datagrove/cli/app.py:192-215`
- **Lens:** A
- **Category:** pattern-consistency
- **What's wrong:** The function exists solely to mirror a private dataset helper "to keep the CLI → dataset edge clean," and the docstring acknowledges this. The mirror is fine but invites the same drift problem as S-1 / S-3.
- **Suggestion:** Either promote `datagrove.dataset.package._infer_write_format` to public `infer_write_format` (and have the CLI import it), or extract a `datagrove.dataset.formats.detect_from_path(path) -> str | None` utility both call. Low priority — the rules are short and stable today.

## Cross-lens flags

- **Lens B/C:** `gmnspy.cli.app:846-875` — the `_ScopeErrors` context manager catches by exception **name** (`exc_type.__name__ in {"ScopeError", "CleanError", "NetworkError", "ValueError"}`). The comment justifies it as "avoid importing the optional modules just to register the class hierarchy here," but string-matching exception types is fragile (typo, refactor-rename), is invisible to pyright, and conflates a domain `ValueError` with a builtin one. Worth a Lens B look at the right factoring.
- **Lens B:** `gmnspy/server/app.py:85` and `gmnspy/mcp/server.py:123` use bare `except Exception` to swallow per-table count failures. The `# pragma: no cover - resilient` comment is honest; whether that's the right resilience model for the agent audience is a Lens B call. (See SKILL.md: "no silent exception-swallowing".)
- **Lens C:** `gmnspy.cli.app` is now ~940 LOC in a single module — twelve subcommand factories under one `_build_gmnspy_app` function plus a tail of helpers. Whether this hits the "click-through depth" sweet spot or starts to feel monolithic is a Lens C judgement.
- **Lens B:** `gmnspy.cli.app:194-204` (`bench`) uses `except ImportError` to skip the `is_connected` phase, with `_time("is_connected", ...)` followed by an unconditional `timings.append(...)` with `seconds=None`. That pattern (record-then-replace) reads awkwardly; Lens C may want to look at it.
- **Out of scope (per orchestrator brief):** `_FK_PUSHDOWN` in `gmnspy/scope/scope.py` is a static dict (3 references in `scope.py`). Flagged here without inspection — defer to the appropriate batch.
- **Doctest cross-package dependency (informational):** datagrove production code never imports gmnspy, but ~20 doctest `Examples:` blocks under `datagrove/dataset/` and `datagrove/io/` use `from gmnspy.fixtures import leavenworth` for runnable examples. That couples datagrove's doctest pass to gmnspy being installed. It's defensible (the fixture is the convenient real-world data on hand), and the production rule still holds, but the test-time coupling is worth being deliberate about — could move the fixture to `datagrove.fixtures` for a fully self-contained doctest run.

## Assessment

**Verdict (this lens only):** yellow

**Reasoning:** The composition boundary is honored, the factory pattern is consistent across all three surfaces, and the security defaults are sound. The four Important findings are all about extension-point hygiene — private-surface leakage into gmnspy.server (I-1), the `Package`/`Network` registry conflation forcing double-loads (I-2), the not-yet-grown MCP session seam that the architecture promises (I-3), and the divergent `importlib` patterns waiting for a sixth optional extra to multiply the inconsistency (I-4). None of these break correctness today; all four will cost real refactoring effort once a second domain package (GTFSpy) tries to compose on the same primitives. Fix before merging to develop.
