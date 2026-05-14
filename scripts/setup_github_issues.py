#!/usr/bin/env python3
"""Populate GitHub labels, milestones, and issue tree for the v1.0 refactor.

Idempotent — safe to re-run; existing labels/milestones/issues with matching
names are skipped (issues are deduplicated by exact title match).

Usage:
    uv run python scripts/setup_github_issues.py [--dry-run] [--repo OWNER/NAME]

Default repo: e-lo/GMNSpy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field

DEFAULT_REPO = "e-lo/GMNSpy"

# ---------------------------------------------------------------------------
# Labels — see PRD §"GitHub Governance / Labels"
# ---------------------------------------------------------------------------

LABELS: list[tuple[str, str, str]] = [
    # phase
    ("phase:0", "0e8a16", "Phase 0 — Repo prep"),
    ("phase:1", "1d76db", "Phase 1 — datagrove foundation"),
    ("phase:2", "5319e7", "Phase 2 — validation + dataset"),
    ("phase:3", "b60205", "Phase 3 — operations + GMNS bindings"),
    ("phase:4", "fbca04", "Phase 4 — surfaces (CLI/notebook/API/MCP/skills)"),
    ("phase:5", "d93f0b", "Phase 5 — hardening + beta + GA"),
    # package
    ("pkg:datagrove", "0366d6", "datagrove (generic engine)"),
    ("pkg:gmnspy", "0366d6", "gmnspy (GMNS-specific)"),
    ("pkg:skills", "0366d6", "Claude Code Skills"),
    ("pkg:repo", "0366d6", "monorepo / cross-cutting"),
    # area
    ("area:engine", "c2e0c6", "engine abstraction (ibis/polars/pandas)"),
    ("area:io", "c2e0c6", "format adapters / URL / credentials"),
    ("area:validation", "c2e0c6", "schema / FK / sync-state / data-quality"),
    ("area:quality", "c2e0c6", "data-quality rules"),
    ("area:clean", "c2e0c6", "network editing + rollback"),
    ("area:server", "c2e0c6", "self-hostable API server"),
    ("area:mcp", "c2e0c6", "MCP server"),
    ("area:cli", "c2e0c6", "CLI"),
    ("area:notebook", "c2e0c6", "notebook surface"),
    ("area:scope", "c2e0c6", "scoping (geographic + network-aware)"),
    ("area:docs", "c2e0c6", "documentation"),
    ("area:ci", "c2e0c6", "CI / CD"),
    ("area:spec", "c2e0c6", "GMNS spec / vendoring"),
    # type
    ("type:feature", "a2eeef", "new feature"),
    ("type:refactor", "a2eeef", "refactor"),
    ("type:bug", "d73a4a", "bug"),
    ("type:docs", "0075ca", "documentation"),
    ("type:test", "bfdadc", "tests"),
    ("type:chore", "ffffff", "chore / housekeeping"),
    # effort
    ("effort:S", "ededed", "≤1 day"),
    ("effort:M", "cccccc", "2-3 days"),
    ("effort:L", "9e9e9e", "4-7 days"),
    ("effort:XL", "616161", "8+ days"),
    # workflow
    ("subagent-friendly", "7057ff", "self-contained; suitable for sub-agent dispatch"),
    ("blocks-beta", "b60205", "blocks v1.0 beta release"),
    ("blocks-ga", "b60205", "blocks v1.0 GA release"),
    ("spec-sync", "fbca04", "auto-applied by spec-sync bot"),
    ("upstream-candidate", "0e8a16", "potential PR upstream to zephyr-data-specs/GMNS"),
    ("epic", "5319e7", "tracking epic"),
    ("phase", "5319e7", "phase issue (parent of tasks)"),
]

MILESTONES: list[tuple[str, str]] = [
    ("datagrove-v0.1.0-beta.1", "First public beta of the generic datagrove engine."),
    ("gmnspy-v1.0.0-beta.1", "First public beta of GMNSpy v1.0."),
    ("gmnspy-v1.0.0", "GMNSpy v1.0 GA. All 29 product-owner requirements verified."),
    ("v1.1", "Post-GA additive: more cleanup ops, more quality rules, polygon scope, CLI edit REPL."),
]

# ---------------------------------------------------------------------------
# Issue tree
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str  # e.g. "0.1", "1.12"
    title: str
    body: str
    labels: list[str]
    effort: str = "M"
    sa: bool = True
    milestone: str | None = None


@dataclass
class Phase:
    id: str  # "0".."5"
    title: str
    summary: str
    tasks: list[Task] = field(default_factory=list)


def _task_body(t: Task, phase: Phase) -> str:
    sa_line = "Yes — self-contained; suitable for sub-agent dispatch." if t.sa else "No."
    return f"""**Phase:** {phase.title}
**Task ID:** `{t.id}`
**Effort:** {t.effort}
**Sub-agent friendly:** {sa_line}

---

{t.body}

---

This issue is part of the v1.0 refactor tracked in the Epic. See the PRD ([docs/PRD.md](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/docs/PRD.md)) and the plan file in `.claude/plans/` for full context.
"""


# Phase definitions — mirrors docs/PRD.md and the approved plan.
# Each task body is concise; the rich plan lives in docs/PRD.md.

PHASES: list[Phase] = [
    Phase(
        id="0",
        title="Phase 0 — Repo prep",
        summary="Branch, workspace, vendored specs, dev tooling, CI scaffold, issue tree.",
        tasks=[
            Task(
                "0.1",
                "Cut refactor/v1.0 + clear legacy modules",
                "Cut `refactor/v1.0` from `develop` (or current main if develop is stale). Plan calls for a clean break — delete legacy `gmnspy/` Python modules at end of phase.",
                ["pkg:repo", "area:ci", "type:chore"],
                effort="S",
                sa=False,
            ),
            Task(
                "0.2",
                "Set up uv workspace at repo root",
                "Create `packages/datagrove/` and `packages/gmnspy/` with stub `pyproject.toml` files and a workspace-root `pyproject.toml` declaring `[tool.uv.workspace]`.",
                ["pkg:repo", "area:ci", "type:chore"],
                effort="S",
            ),
            Task(
                "0.3",
                "Vendor GMNS spec versions side-by-side",
                "Move existing spec into `packages/gmnspy/gmnspy/spec/0.97/`; vendor 0.95 + 0.96 from upstream tags. Add `VERSION` files. Multi-version support per req #29.",
                ["pkg:gmnspy", "area:spec", "type:chore"],
                effort="M",
            ),
            Task(
                "0.4",
                "Set up shared dev tooling (ruff, pyright, import-linter, coverage, pytest-benchmark, pre-commit)",
                "Configure shared dev tooling at workspace root. import-linter contracts: datagrove cannot import gmnspy; gmnspy core cannot require optional-extra submodules. ruff replaces black + flake8 + isort + pydocstyle.",
                ["pkg:repo", "area:ci", "type:chore"],
                effort="M",
            ),
            Task(
                "0.5",
                "Create empty module skeletons",
                "Create `__init__.py` per architecture map for both packages with one-line docstrings.",
                ["pkg:repo", "type:chore"],
                effort="S",
            ),
            Task(
                "0.6",
                "Split publish.yml into per-package workflows; update tests.yml",
                "`publish-datagrove.yml` (tag pattern `datagrove-v*`) + `publish-gmnspy.yml` (`gmnspy-v*`). `tests.yml` rewritten for monorepo (uv, ruff, importlinter, per-package pytest with doctest).",
                ["pkg:repo", "area:ci", "type:chore"],
                effort="M",
            ),
            Task(
                "0.7",
                "Create GitHub Epic + Phase + Task issues with labels/milestones",
                "This very issue tree, populated by `scripts/setup_github_issues.py`.",
                ["pkg:repo", "type:chore"],
                effort="M",
                sa=False,
            ),
        ],
    ),
    Phase(
        id="1",
        title="Phase 1 — datagrove foundation",
        summary="Spec model, engine abstraction, format adapters, Leavenworth fixture.",
        tasks=[
            Task(
                "1.1",
                "Pydantic spec model + Frictionless loader (multi-version)",
                "Pydantic v2 models for `DataPackage`, `Resource`, `Schema`, `Field`, `ForeignKey`, `MissingValues`, `SharedCategory`. Loader resolves `$ref` + `shared_categories.json`. Round-trip tests for each vendored schema.",
                ["pkg:datagrove", "area:spec", "type:feature"],
                effort="M",
            ),
            Task(
                "1.2",
                "Engine ABC + registry",
                "Engine protocol: `scan/materialize/to_pandas/to_polars/write`. Registry with `set_engine`/`get_engine`. Stub impls.",
                ["pkg:datagrove", "area:engine", "type:feature"],
                effort="S",
            ),
            Task(
                "1.3",
                "Ibis engine impl (duckdb backend)",
                "All internal queries via ibis expressions (no raw SQL — req #28). In-memory default; file-backed for `.duckdb` sources.",
                ["pkg:datagrove", "area:engine", "type:feature"],
                effort="M",
            ),
            Task(
                "1.4",
                "Polars engine impl (lazy frames)",
                "Polars LazyFrame backend for users who prefer polars.",
                ["pkg:datagrove", "area:engine", "type:feature"],
                effort="M",
            ),
            Task(
                "1.5",
                "Pandas engine impl (eager)",
                "Pandas backend for compatibility / familiarity.",
                ["pkg:datagrove", "area:engine", "type:feature"],
                effort="S",
            ),
            Task(
                "1.6",
                "FormatAdapter ABC + registry + dispatch",
                "Extension/scheme-based adapter dispatch. Pluggable.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="S",
            ),
            Task(
                "1.7",
                "CSV adapter",
                "Read/write CSV via the active engine.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="S",
            ),
            Task(
                "1.8",
                "Parquet adapter (single + partitioned)",
                "Partition pruning verified via duckdb `EXPLAIN` snapshot test. Default persistent format per req #8.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="M",
            ),
            Task(
                "1.9",
                "DuckDB adapter",
                "Read `.duckdb` file as a Package; write Package to `.duckdb`. Default API-download format per req #8.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="M",
            ),
            Task(
                "1.10",
                "Zip-CSVs adapter",
                "Read/write a zipped CSV bundle as a Package.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="S",
            ),
            Task(
                "1.11",
                "Remote (URL) layer + credentials cascade",
                "fsspec-backed remote IO. Credentials cascade: kwarg → `GMNSPY_CRED_<host>_TOKEN` env → `keyring` → `.netrc`. Per req #4.",
                ["pkg:datagrove", "area:io", "type:feature"],
                effort="M",
            ),
            Task(
                "1.12",
                "Leavenworth WA fixture network",
                "Sub-agent task: pull OSM + city open data and synthesize a tiny GMNS network covering ≥6 tables incl. one TOD + shared_categories. CSV + Parquet + DuckDB + zip variants. Provenance documented.",
                ["pkg:gmnspy", "area:spec", "type:test"],
                effort="L",
            ),
        ],
    ),
    Phase(
        id="2",
        title="Phase 2 — Validation + dataset surface",
        summary="ValidationReport, interactive HTML, schema/FK/structural/sync-state, lazy Package/Table/View, generic edit/rollback.",
        tasks=[
            Task(
                "2.1",
                "ValidationReport + Issue dataclasses; rich + JSON renderers",
                "Severity levels (Error/Warning/Info/DataQuality); `category` field. Rich console + JSON output.",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="S",
            ),
            Task(
                "2.2",
                "Interactive HTML report renderer",
                "Self-contained single-file HTML (Jinja2 + DataTables + Vega-Lite). Severity ranking, filter by table/severity/rule/category, click-to-expand row context, embedded map view. Per req #25.",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="L",
            ),
            Task(
                "2.3",
                "Schema check (required/types/enums/min/max/regex)",
                "Engine-agnostic via ibis expressions. Regression tests for the 4 latent bugs in legacy `constraint_checking.py`.",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="M",
            ),
            Task(
                "2.4",
                "Foreign-key validator (lazy / streaming-aware)",
                "Cross-table FK validation pushed to the engine where supported (duckdb does).",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="M",
            ),
            Task(
                "2.5",
                "Structural validator (required tables, file presence)",
                "Detect missing required tables and required files in a package directory.",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="S",
            ),
            Task(
                "2.6",
                "DirtyTracker + sync-state model",
                "Content hashes per table + FK-validation hash stamps. `OutOfSyncWarning` on stale FK at write. Per req #5.",
                ["pkg:datagrove", "area:validation", "type:feature"],
                effort="M",
            ),
            Task(
                "2.7",
                "Lazy Package + Table wrappers",
                "Lazy ibis-backed `Package`, `Table` with provenance, dirty flag, scope, mutation surface.",
                ["pkg:datagrove", "area:engine", "type:feature"],
                effort="L",
            ),
            Task(
                "2.8",
                "Generic spatial scoping in datagrove.dataset.view",
                "bbox, polygon, geometry-buffer; predicate pushdown verified via duckdb `EXPLAIN`. (Network-aware scope is gmnspy-side, Phase 3.)",
                ["pkg:datagrove", "area:scope", "type:feature"],
                effort="M",
            ),
            Task(
                "2.9",
                "Generic Edit/Diff/Session/Rollback framework",
                "`EditResult` carries diff + log entry; `Session` records ops + rollback records to sidecar parquet. No GMNS semantics here. Per req #27.",
                ["pkg:datagrove", "area:clean", "type:feature"],
                effort="L",
            ),
        ],
    ),
    Phase(
        id="3",
        title="Phase 3 — Operations + GMNS bindings + quality + clean + docs",
        summary="Cost model, GMNS Network + semantics, quality rules, clean ops with rollback, docgen.",
        tasks=[
            Task(
                "3.1",
                "Cost model + gating (>30s estimate, >3min approval)",
                "Calibrate on Leavenworth + synthetic regional fixture. Per req #12.",
                ["pkg:datagrove", "type:feature"],
                effort="M",
            ),
            Task(
                "3.2",
                "Pool / batch context manager (atomic on exception)",
                "`with net.batch():` defers + coalesces. Per req #6.",
                ["pkg:datagrove", "type:feature"],
                effort="M",
            ),
            Task(
                "3.3",
                "Progress wrapper (rich, notebook-aware)",
                "Rich progress with `force_terminal=False` for inline notebook rendering.",
                ["pkg:datagrove", "type:feature"],
                effort="S",
            ),
            Task(
                "3.4",
                "Markdown docgen (port from legacy)",
                "Port `document_schemas_to_md` / `document_spec_to_md` to new spec model. Snapshot test against current output. Update `main.py` mkdocs-macros.",
                ["pkg:datagrove", "area:docs", "type:refactor"],
                effort="M",
            ),
            Task(
                "3.5",
                "AI docgen (llms.txt, llms-full.txt, ai/api-index.json)",
                "mkdocs build hook generates AI-consumable artifacts. Per req #22.",
                ["pkg:datagrove", "area:docs", "type:feature"],
                effort="M",
            ),
            Task(
                "3.6",
                "GMNS spec loader (multi-version)",
                "`SUPPORTED_SPECS = ['0.95','0.96','0.97']`, `DEFAULT_SPEC = '0.97'`. Per req #29.",
                ["pkg:gmnspy", "area:spec", "type:feature"],
                effort="M",
            ),
            Task(
                "3.7",
                "GMNS Network class + accessors + dirty-tracked mutations",
                "`Network` = `Package` + `.links`/`.nodes`/... accessors + `add_*`/`update_*` routed through `DirtyTracker`.",
                ["pkg:gmnspy", "type:feature"],
                effort="L",
            ),
            Task(
                "3.8",
                "GMNS semantics (connectivity, geometry assembly, TOD resolution)",
                "Domain-specific operations; some can slip to v1.1 if Phase 3 runs hot.",
                ["pkg:gmnspy", "type:feature"],
                effort="L",
            ),
            Task(
                "3.9",
                "gmnspy.indexes — spatial (STRtree) + graph (igraph)",
                "Build/cache/load. Sidecar parquet keyed on content hash. Auto-build heuristic >50k nodes. Per req #29.",
                ["pkg:gmnspy", "area:scope", "type:feature"],
                effort="L",
            ),
            Task(
                "3.10",
                "gmnspy.scope — network-aware scope ops",
                "`from_nodes`, `from_node`, `from_link`, `from_point`, `connected_component`, `from_zone`. Chainable composition. Per req #29.",
                ["pkg:gmnspy", "area:scope", "type:feature"],
                effort="L",
            ),
            Task(
                "3.11",
                "gmnspy.quality — data-quality rules + plugin pattern",
                "Configurable thresholds; entry-point plugin pattern. Initial rules: high-speed-residential, disconnected components, lane-count mismatch, near-duplicate nodes, sharp-angle bends, implausible v/c, missing critical-but-optional fields. Per req #26.",
                ["pkg:gmnspy", "area:quality", "type:feature"],
                effort="L",
            ),
            Task(
                "3.12",
                "gmnspy.clean (optional extra) — editing ops with rollback",
                "`simplify_geometry`, `merge_close_nodes`, `remove_orphans`, `split_link_at_node`, `connect_disconnected_components`, `recompute_lengths`, `snap_to_reference`. Each returns `EditResult`. Per req #27.",
                ["pkg:gmnspy", "area:clean", "type:feature"],
                effort="L",
            ),
        ],
    ),
    Phase(
        id="4",
        title="Phase 4 — Surfaces (CLI / notebook / API / MCP / Skills) + docs polish",
        summary="User-facing surfaces and the awesome-docs work.",
        tasks=[
            Task(
                "4.1",
                "Typer CLI scaffold + read/info/validate (with --json on every command)",
                "Per req #13 + AI consumption (req #22).",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="M",
            ),
            Task(
                "4.2",
                "CLI convert (csv↔parquet↔duckdb↔zip)",
                "Format conversion with progress + cost gating.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="M",
            ),
            Task(
                "4.3",
                "CLI spec sync|list|diff",
                "Vendored spec management via CLI.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="S",
            ),
            Task(
                "4.4",
                "CLI bench",
                "Run engine benchmarks on Leavenworth + synthetic.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="S",
            ),
            Task(
                "4.5",
                "CLI doctor",
                "Env + spec version + sample-data smoke + credential resolution diagnostic.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="S",
            ),
            Task(
                "4.6",
                "CLI quality / clean / scope / index",
                "Wraps quality, clean, scope, indexes modules; rollback/save and index-cache semantics surfaced.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="M",
            ),
            Task(
                "4.7",
                "CLI prompts + approval gating (--yes / GMNSPY_AUTO_APPROVE)",
                "Claude Code-style short prompts; auto-approval flags. Per req #12.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="M",
            ),
            Task(
                "4.8",
                "CLI edit REPL (stretch — defer to v1.1 if hot)",
                "Implicit batch + `:save`/`:abort`.",
                ["pkg:gmnspy", "area:cli", "type:feature"],
                effort="L",
            ),
            Task(
                "4.9",
                "Notebook _repr_html_ for Network/Table/ValidationReport/EditResult",
                "Pretty inline rendering in JupyterLab.",
                ["pkg:gmnspy", "area:notebook", "type:feature"],
                effort="M",
            ),
            Task(
                "4.10",
                "gmnspy.server (optional extra) — FastAPI + auto-OpenAPI",
                "Endpoints per architecture spec. Pluggable auth. Config-file driven. Dockerfile + docker-compose example. Per req #23.",
                ["pkg:gmnspy", "area:server", "type:feature"],
                effort="L",
            ),
            Task(
                "4.11",
                "gmnspy.mcp (optional extra) — MCP server",
                "Tools: `read_network`, `describe_network`, `query_table`, `scope`, `validate`, `quality_check`, `convert`, `edit_session`. `gmnspy mcp serve` CLI entry. Also a `datagrove mcp serve` for the generic case. Per req #22.",
                ["pkg:gmnspy", "pkg:datagrove", "area:mcp", "type:feature"],
                effort="L",
            ),
            Task(
                "4.12",
                "Populate Skills in skills/",
                "Fill in SKILL.md bodies for `datagrove-validate`, `gmns-author`, `gmns-validate`, `gmns-convert`, `gmns-clean`. Per req #22.",
                ["pkg:skills", "area:docs", "type:docs"],
                effort="M",
            ),
            Task(
                "4.13",
                "Awesome human docs",
                "Intro pages (what-is-gmns, quickstart, visual-tour with Leavenworth map embed). Auto-generated table-of-tables + ER diagrams (mermaid). Cookbook. Glossary. Doctest in CI. Search via mkdocs-material. Per req #14, #24.",
                ["pkg:repo", "area:docs", "type:docs"],
                effort="XL",
            ),
            Task(
                "4.14",
                "Migration guide v0.3 → v1.0",
                "Side-by-side API table.",
                ["pkg:repo", "area:docs", "type:docs"],
                effort="M",
            ),
            Task(
                "4.15",
                "Write docs/PRD.md (full content) + thin docs/architecture.md pointer",
                "Replaces the empty `docs/architecture.md` stub; full PRD per outline in plan file.",
                ["pkg:repo", "area:docs", "type:docs"],
                effort="M",
            ),
        ],
    ),
    Phase(
        id="5",
        title="Phase 5 — Hardening + beta + GA",
        summary="Coverage, perf bench, spec-sync bot, release-drafter, beta cycle, GA.",
        tasks=[
            Task(
                "5.1",
                "Coverage gate (datagrove ≥85%, gmnspy ≥75%)",
                "Fail-on-drop in CI.",
                ["pkg:repo", "area:ci", "type:test"],
                effort="M",
                sa=False,
            ),
            Task(
                "5.2",
                "Performance regression bench (pytest-benchmark)",
                "Runs on PRs touching engine/IO/validation. Posts numbers as PR comment.",
                ["pkg:repo", "area:ci", "type:test"],
                effort="M",
            ),
            Task(
                "5.3",
                "Spec-sync bot workflow (daily PR on upstream release)",
                "Opens PR labeled `spec-sync` against `develop`.",
                ["pkg:repo", "area:ci", "area:spec", "type:feature"],
                effort="M",
            ),
            Task(
                "5.4",
                "release-drafter config",
                "Pre-fills release notes from PR labels.",
                ["pkg:repo", "area:ci", "type:chore"],
                effort="S",
            ),
            Task(
                "5.5",
                "Verify TestPyPI publish for both packages",
                "Smoke install of `datagrove`, `gmnspy`, `gmnspy[clean]`, `gmnspy[server]`, `gmnspy[mcp]`, `gmnspy[notebook]` from TestPyPI on a fresh venv.",
                ["pkg:repo", "area:ci", "type:test"],
                effort="M",
            ),
            Task(
                "5.6",
                "Docker image for gmnspy[server] → ghcr.io",
                "Built and pushed on `gmnspy-v*` tags.",
                ["pkg:gmnspy", "area:server", "area:ci", "type:feature"],
                effort="M",
            ),
            Task(
                "5.7",
                "Release datagrove-v0.1.0-beta.1 + gmnspy-v1.0.0-beta.1",
                "Via GitHub release UI. Trusted-publishing fires.",
                ["pkg:repo", "type:chore", "blocks-beta"],
                effort="S",
                sa=False,
            ),
            Task(
                "5.8",
                "BETA_FEEDBACK.md issue template + recruit ≥3 beta users",
                "Get real-world feedback before GA.",
                ["pkg:repo", "area:docs"],
                effort="S",
                sa=False,
            ),
            Task(
                "5.9",
                "Iterate beta.N every 2 weeks based on feedback",
                "Until all 29 reqs verified + beta users sign off.",
                ["pkg:repo", "blocks-ga"],
                effort="XL",
                sa=False,
            ),
            Task(
                "5.10",
                "Release datagrove-v0.1.0 + gmnspy-v1.0.0 (GA)",
                "README updates + announcement.",
                ["pkg:repo", "type:chore", "blocks-ga"],
                effort="S",
                sa=False,
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def gh(*args: str, dry: bool = False, capture: bool = True) -> str:
    cmd = ["gh", *args]
    if dry:
        print("[dry-run]", " ".join(cmd))
        return ""
    if capture:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: {' '.join(cmd)}\n  stderr: {result.stderr.strip()}", file=sys.stderr)
        return result.stdout.strip()
    else:
        subprocess.run(cmd, check=False)
        return ""


def label_exists(repo: str, name: str) -> bool:
    out = gh("label", "list", "-R", repo, "--json", "name", "--limit", "200")
    if not out:
        return False
    return name in {lbl["name"] for lbl in json.loads(out)}


def ensure_labels(repo: str, dry: bool):
    existing = set()
    out = gh("label", "list", "-R", repo, "--json", "name", "--limit", "200")
    if out:
        existing = {lbl["name"] for lbl in json.loads(out)}
    for name, color, desc in LABELS:
        if name in existing:
            continue
        gh("label", "create", name, "-R", repo, "--color", color, "--description", desc, dry=dry)
    print(f"  labels: {len(LABELS)} total, {len(LABELS) - len(set(n for n, _, _ in LABELS) & existing)} created")


def ensure_milestones(repo: str, dry: bool):
    out = gh("api", f"repos/{repo}/milestones", "--paginate")
    existing = {m["title"] for m in json.loads(out)} if out else set()
    for title, desc in MILESTONES:
        if title in existing:
            continue
        if dry:
            print(f"[dry-run] gh api repos/{repo}/milestones -f title={title!r} -f description={desc!r}")
            continue
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/milestones",
                "-f",
                f"title={title}",
                "-f",
                f"description={desc}",
                "-f",
                "state=open",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    print(f"  milestones: {len(MILESTONES)} total")


def get_existing_issue_titles(repo: str) -> set[str]:
    out = gh("issue", "list", "-R", repo, "--state", "all", "--limit", "500", "--json", "title")
    if not out:
        return set()
    return {i["title"] for i in json.loads(out)}


def create_issue(repo: str, title: str, body: str, labels: list[str], milestone: str | None, dry: bool) -> str | None:
    args = ["issue", "create", "-R", repo, "--title", title, "--body", body]
    for lbl in labels:
        args += ["--label", lbl]
    if milestone:
        args += ["--milestone", milestone]
    out = gh(*args, dry=dry)
    return out or None


def epic_body(phase_issue_urls: dict[str, str]) -> str:
    lines = [
        "**GMNSpy v1.0 + datagrove v0.1 refactor**",
        "",
        "Major restructure to a two-package monorepo (datagrove generic engine + gmnspy GMNS-specific).",
        "Full plan in [docs/PRD.md](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/docs/PRD.md) and the workspace plan file.",
        "",
        "## Phases",
        "",
    ]
    for phase in PHASES:
        url = phase_issue_urls.get(phase.id, "(not yet created)")
        lines.append(f"- [ ] {url} — {phase.title}: {phase.summary}")
    return "\n".join(lines)


def phase_body(phase: Phase, task_urls: dict[str, str], epic_url: str | None) -> str:
    lines = [
        f"**{phase.title}**",
        "",
        phase.summary,
        "",
    ]
    if epic_url:
        lines.append(f"Tracked by: {epic_url}")
        lines.append("")
    lines.append("## Tasks")
    lines.append("")
    for t in phase.tasks:
        url = task_urls.get(t.id, f"(task {t.id} pending)")
        lines.append(f"- [ ] {url} — {t.title}  `({t.effort})`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo
    dry = args.dry_run

    print(f"Setting up issue tree for {repo}...")
    print()

    print("[1/4] Labels")
    ensure_labels(repo, dry)

    print("[2/4] Milestones")
    ensure_milestones(repo, dry)

    print("[3/4] Issues")
    existing_titles = get_existing_issue_titles(repo) if not dry else set()

    epic_title = "Epic: GMNSpy v1.0 + datagrove v0.1 refactor"

    # Pass 1: create task issues, recording URLs
    task_urls: dict[str, str] = {}
    for phase in PHASES:
        for t in phase.tasks:
            full_title = f"[{t.id}] {t.title}"
            if full_title in existing_titles:
                # Find the existing URL
                out = gh(
                    "issue",
                    "list",
                    "-R",
                    repo,
                    "--state",
                    "all",
                    "--limit",
                    "500",
                    "--search",
                    f'"{full_title}" in:title',
                    "--json",
                    "url,title",
                )
                if out:
                    matches = [i for i in json.loads(out) if i["title"] == full_title]
                    if matches:
                        task_urls[t.id] = matches[0]["url"]
                continue
            labels = list(t.labels)
            if t.sa:
                labels.append("subagent-friendly")
            labels.append(f"phase:{phase.id}")
            labels.append(f"effort:{t.effort}")
            milestone = t.milestone
            if milestone is None:
                # Default milestone: beta milestone for tasks in phases 0-4; GA-blocking for phase 5
                if phase.id in ("0", "1", "2"):
                    milestone = "datagrove-v0.1.0-beta.1"
                elif phase.id in ("3", "4"):
                    milestone = "gmnspy-v1.0.0-beta.1"
                else:
                    milestone = "gmnspy-v1.0.0"
            url = create_issue(repo, full_title, _task_body(t, phase), labels, milestone, dry)
            if url:
                task_urls[t.id] = url
                print(f"    + {t.id} {url}")

    # Pass 2: create phase issues with checklists referencing task URLs
    phase_urls: dict[str, str] = {}
    for phase in PHASES:
        ptitle = f"[Phase {phase.id}] {phase.title}"
        if ptitle in existing_titles:
            out = gh(
                "issue",
                "list",
                "-R",
                repo,
                "--state",
                "all",
                "--limit",
                "500",
                "--search",
                f'"{ptitle}" in:title',
                "--json",
                "url,title",
            )
            if out:
                matches = [i for i in json.loads(out) if i["title"] == ptitle]
                if matches:
                    phase_urls[phase.id] = matches[0]["url"]
            continue
        labels = ["phase", f"phase:{phase.id}"]
        url = create_issue(repo, ptitle, phase_body(phase, task_urls, None), labels, None, dry)
        if url:
            phase_urls[phase.id] = url
            print(f"  + Phase {phase.id} {url}")

    # Pass 3: create epic with checklist of phase URLs
    if epic_title not in existing_titles:
        epic_url = create_issue(repo, epic_title, epic_body(phase_urls), ["epic"], "gmnspy-v1.0.0", dry)
        if epic_url:
            print(f"+ Epic {epic_url}")

    print()
    print("[4/4] Done.")


if __name__ == "__main__":
    main()
