# Design records — index

This folder is the one place for netstead / corral planning: decisions, product requirements,
feature designs, implementation plans and scoping studies. It is internal (excluded from the
published sites by `exclude_docs` in the root `mkdocs.yml`) but lives in git, so every record is
reviewed in a PR like code.

**What lives where**

| Question | Source of truth |
|---|---|
| How is the software built *today*? | [`packages/corral/docs/architecture.md`](../../packages/corral/docs/architecture.md) |
| Why did we choose X over Y? | an **ADR** here |
| What should a feature do, and for whom? | a **PRD** or **Design** here |
| How do we build it, step by step? | a **Plan** here |
| Is X worth doing, and how big is it? | a **Scope** here |
| What exactly is left to do? | GitHub issues, linked from the record |
| What shipped in a release? | `packages/*/CHANGELOG.md` |

On conflict: architecture.md > accepted ADRs > PRDs / designs > plans > issue bodies > code comments.
When a decision changes, write a new ADR (or amend the old one's status), then update
architecture.md and this index in the same PR.

## Conventions

- **File name:** `YYYY-MM-DD-<slug>-<kind>.md`, e.g. `2026-10-01-geometry-encoding-adr.md`.
  Kinds: `adr`, `prd`, `design`, `plan`, `scope`. A few older records predate this rule; they
  keep their names because other records link to them.
- **Status line** right under the title:
  `Status: **<status>** (<PRs>) · Date: … · Owner: …`. Statuses:
  - `proposed` — open for review
  - `accepted` — agreed, not yet built
  - `implemented` — merged; cite the PRs
  - `superseded` — replaced; link the replacement
  - `abandoned` — not pursued
- **Mark, don't delete.** When a record is done or overtaken, update its status and add a short
  note at the top saying what changed. The reasoning is the value; don't rewrite history in the body.
- **Plans** close out by setting `implemented` in the PR that finishes them.
- Update the table below in the same PR as any status change.

## Records on `main`

### Decisions (ADRs)

| Record | Date | Status | Implemented in | Open follow-ups |
|---|---|---|---|---|
| [Engine strategy: DuckDB-only, stay on ibis](2026-10-01-engine-strategy-reevaluation.md) | 10-01 | implemented | #195, #198 | — |
| [Geometry encoding: WKB in memory, WKT CSV, GeoParquet](2026-10-01-geometry-encoding-adr.md) | 10-01 | implemented | #201, #202 | regenerate committed fixtures with GeoParquet `geo` metadata |
| [Foreign keys: report, don't enforce](2026-10-01-fk-constraints-adr.md) | 10-01 | accepted | — (records current behavior) | opt-in "trusted store" export with native constraints: backlog, no issue |

### Product requirements and feature designs

| Record | Kind | Date | Status | Implemented in | Notes |
|---|---|---|---|---|---|
| [NL selection](2026-09-23-nl-selection-design.md) | design | 09-23 | implemented | #194 | multi-provider LLM parsing extends it (PR #211) |
| [Network viewer (`netstead.viz`)](2026-09-30-network-viewer-prd.md) | PRD | 09-30 | accepted; P1–P2 implemented | #194 | P3 (diff) and P4 (multimodal / GTFS) roll up under the Workbench design |

### Implementation plans

| Plan | Parent | Status | Implemented in |
|---|---|---|---|
| [Viewer P1: core render path](2026-09-30-viz-p1-plan.md) | viewer PRD | implemented | #194 |
| [Viewer P2: inspect & style](2026-09-30-viz-p2-plan.md) | viewer PRD | implemented | #194 |
| [DuckDB-only engine consolidation](2026-10-01-engine-consolidation-plan.md) | engine ADR | implemented | #195 |

### Scopes

| Scope | Date | Status | Implemented in | Open follow-ups |
|---|---|---|---|---|
| [Data-table exploration view](data-table-exploration-scope.md) | 09-30 | Phases 0–1 implemented | #194 | Phase 2+ (cross-linking, export) not scheduled |
| [Overture → GMNS pipeline](overture-to-gmns-pipeline-scope.md) | 09-30 | implemented | #196 | "Phase 2" attribute refinements listed in the scope |
| [Benchmarking suite](benchmarking-suite-scope.md) | 09-30 | implemented (DuckDB-only) | #197 | nightly perf regression job: [#100](https://github.com/e-lo/netstead/issues/100) |

## In flight (not on `main` yet)

These records exist on branches. Add them to the tables above when they merge.

| Record | Kind | Where | Status |
|---|---|---|---|
| `2026-10-02-netstead-workbench-design.md` — one front end (`netstead app`) for open / select / inspect / edit; umbrella for the viewer PRD's later phases | design | PR #211 (`feat/nl-providers`) | accepted; P0 + P1a built in the PR |
| `2026-10-02-workbench-p0-plan.md`, `2026-10-02-workbench-p1a-plan.md` | plans | PR #211 | implemented in the PR; mark `implemented` when it merges |
| `2026-10-02-nl-providers-design.md` + `-plan.md` — multi-provider (Anthropic / OpenAI / Gemini / Ollama) NL parsing | design + plan | PR #211 | accepted; implemented in the PR |
| `2026-10-05-workbench-p1b-plan.md` — Settings dialog, two-way map/table linking, FK related records | plan | PR #212 (`feat/workbench-p1b`, stacked on #211) | implemented in the PR |
| `2026-10-05-workbench-plugins-design.md` — entry-point plugin API (`netstead.workbench.plugins`), core owns network nouns, ProjectCard editing moves to an external plugin repo | design | `docs/workbench-plugins` PR | accepted. **Amends the Workbench design:** the in-core `changes/` package it planned is superseded; core stays card-agnostic |
| `2026-10-05-workbench-plugins-p1-plan.md` — Part 1, Python plugin core | plan | `docs/workbench-plugins` PR | not started; stacks on #211 + #212 |

## Gaps to close

- **No product-level PRD.** Issue [#98](https://github.com/e-lo/netstead/issues/98) planned one for the
  v1.0 rewrite; architecture.md §1 (mission) plus the feature designs above have covered the need so
  far. Either write `YYYY-MM-DD-netstead-prd.md` (personas, roadmap to GA and past it) or close #98.
- **Zip-CSV packages don't load on `main`:** `Network.from_source("x.csv.zip")` mis-dispatches each
  member to the CSV adapter, so `leavenworth.load("zip")` raises `NotImplementedError`. Fixed in
  PR #211 (`4b743fb`), which also removes the guard.
- **Pre-v1 issues** (#1–#8, #25–#29) predate the rewrite and need triage against v1. Open
  tracking issues #98, #103, #104, #106–#108, #113–#115 still use the old `gmnspy` / `datagrove` names.
