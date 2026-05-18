---
name: gmnspy-review
description: Use when reviewing GMNSpy + datagrove code changes — defines the three project-specific review lenses (architecture, code-quality + audience, legibility), severity levels, structured finding format, and triage convention. Invoke before dispatching review agents OR when synthesizing review reports.
---

# GMNSpy + datagrove code review

Project-specific extension of `superpowers:requesting-code-review`. Defines the lenses, audience, severity model, and finding format used across all code reviews in this monorepo.

## When to invoke

- **Orchestrator** — before dispatching `superpowers:code-reviewer` agents on a batch. Use this skill to pick lenses + craft per-lens prompts.
- **Synthesizing** — when consolidating multiple reviewers' reports into a single triage digest for the human reviewer.
- **Fix dispatch** — when briefing a coding agent on accepted findings (pair with `superpowers:receiving-code-review`).

## The three lenses

Each batch gets exactly **one agent per lens** dispatched in parallel. Each agent gets the same git diff + same architecture doc — but a different brief that focuses them on one dimension.

### Lens A — Architecture & API design

**Question:** Will this code still hold up six months from now when GTFSpy or another consumer wants to reuse datagrove?

Focus areas:
- **Composition boundary** — does datagrove ever import (or quietly assume) GMNS-specific names like `link`, `node`, `from_node_id`? Hard fail.
- **Protocol surface** — are `Engine`, `FormatAdapter`, `Schema` etc. signed for both Python power users AND AI agents (MCP tools, `--json` outputs)?
- **Extension points** — clear plugin hooks (entry points, registries) where a future consumer would add behavior?
- **Stability** — would changing the public signature break downstream tasks in our own plan?
- **Pattern consistency** — same composition pattern across `editing/clean`, `api/server`, `mcp/mcp`, `cli/cli`, `quality/quality`, `notebook/notebook`?
- **Sync, scope, FK, cost** — does the design honor the architecture doc's defaults? (Lazy by default, eager-index opt-in, OutOfSyncWarning on stale FK, etc.)

Does **NOT** focus on: code style, line-by-line clarity, test specifics.

### Lens B — Code quality + audience appropriateness

**Question:** Is this code production-grade for the people who will actually run it?

Focus areas:
- **Audiences:** (a) transportation modelers at MPOs / DOTs with intermediate Python; (b) GTFS-interop researchers; (c) AI agents calling via MCP / `--json`. The API surface should serve all three.
- **Idiomatic Python** — Pythonic, not Java-in-Python. Uses `dataclass` / `Pydantic` / `Protocol` appropriately.
- **Type hints** — present and accurate on every public symbol.
- **Errors** — specific exception subclasses (not bare `ValueError`); messages name the input that broke (path, field, value); include a remediation hint when feasible.
- **Docstrings** — Google style; every public function has `Examples:` (these run as doctests).
- **Legacy bug-class avoidance** — no Series-vs-bool truthiness errors (the v0.3 `_unique_constraint` bug), no copy-paste warning-list bugs (the v0.3 `apply_schema_to_df` bug), no silent exception-swallowing.
- **Performance smells** — `.iterrows()`, repeated dict-rebuilds in tight loops, missing `__slots__` on hot dataclasses (only when actually hot — not premature).
- **Test relevance** — tests assert behavior the user/agent cares about, not mock plumbing.

### Lens C — Legibility & approachability  ★ project priority

**Question:** Could an intermediate Python coder, opening this file cold, understand what's happening without clicking through four layers of abstraction?

This is a deliberate **project priority**: we will sacrifice some abstraction and some efficiency for readability. The audience includes transportation engineers who code part-time and contributors who want to extend the core without intimidation.

Focus areas:
- **Click-through depth** — to understand "what does X do," how many files does a reader open? Three is concerning; four is too many. Prefer inline + commented over decomposed-but-indirected.
- **Premature factoring** — a helper used in exactly one place is usually noise. Inline it unless naming it clarifies intent (the bar is "the name reads better than the body").
- **Length over indirection** — a 60-line function that reads top-to-bottom is preferable to six 10-line functions scattered across three files when neither is a public API.
- **Class-vs-function balance** — when no state and no polymorphism is involved, prefer module-level functions. Classes for protocols, stateful objects, and grouping; not for namespacing.
- **Naming for the reader** — `apply_field_constraints(df, schema)` not `_apply(df, s)`. Long-and-clear beats short-and-cryptic for non-hot-path code.
- **Comments that say WHY, not WHAT** — `# pad with None so polars round-trips ints with missing values cleanly` is gold; `# loop through rows` is noise.
- **Inline literals** — small enums / type maps inlined at point of use are often more readable than imported constants from a `defaults.py`.
- **No clever Python** — avoid metaclass tricks, `__init_subclass__`, descriptors, decorator-stacking, or `getattr`-based dispatch unless the problem genuinely demands them. If you use one, leave a comment explaining why.
- **No "abstract base classes for the sake of it"** — `Protocol` over `ABC` when a protocol suffices; no inheritance hierarchy when a function suffices.

When a tradeoff exists between A/B and C, flag it. The human reviewer decides.

## Severity model

| Severity | Definition | Action |
|---|---|---|
| **Critical** | Bug, security issue, data-loss risk, broken contract, hard rule violation (e.g. datagrove imports gmnspy, raw SQL outside ibis_engine), API design that locks out future work | Must fix before next batch dispatch |
| **Important** | Architecture problem, missing functionality vs spec, test gap on a real risk, audience-blocking poor UX, legibility issue that will compound | Fix before merging this branch to develop |
| **Suggestion** | Code-quality improvement, alternative approach worth considering, doc gap | Triage — accept now or file issue for later |
| **Nit** | Style preference, micro-optimization, naming polish | Default reject unless trivial |

Reviewers must categorize honestly — not everything is Critical, and not everything is a Nit.

## Output format (mandatory for review agents)

Each review agent returns a single markdown report following this template exactly. The orchestrator parses these into a triage digest.

```markdown
# Review report — Lens {A|B|C}: {lens name}

**Reviewer:** Lens {letter}
**Range:** {BASE_SHA}..{HEAD_SHA}
**Files in scope:** {N files, {M} lines added, {K} lines removed}

## Strengths

- {strength 1 — be specific, include file:line}
- {strength 2}

## Findings

### Critical

<!-- omit this section if none -->

#### C-1 — {short title}
- **File:** `path/to/file.py:LINE`
- **Lens:** A
- **Category:** {composition-boundary | protocol-surface | bug | …}
- **What's wrong:** {1-3 sentences}
- **Why it matters:** {1-2 sentences}
- **Suggestion:** {what to do — code snippet OK}

### Important

#### I-1 — {short title}
{same shape}

### Suggestion

#### S-1 — {short title}
{same shape}

### Nit

#### N-1 — {short title}
{same shape — keep brief}

## Cross-lens flags

<!-- Things you noticed that belong to another lens. The orchestrator will dedupe. -->

- Lens {B|C}: {brief note + file:line}

## Assessment

**Verdict (this lens only):** {green | yellow | red}

- **green** — no Critical or Important findings; safe to proceed.
- **yellow** — Important findings; should fix before this batch is considered done.
- **red** — Critical findings; do not proceed until addressed.

**Reasoning:** {1-2 sentences}
```

Reviewers must **NOT** suggest fixes for things outside their lens (note in "Cross-lens flags"). Reviewers must **NOT** modify code — review report only.

## Orchestrator workflow (when invoking this skill)

1. **Determine review range.** `BASE_SHA = last reviewed commit` (or commit just before the batch), `HEAD_SHA = current branch head`.
2. **Identify what landed.** `git log --oneline BASE_SHA..HEAD_SHA` and `git diff --stat BASE_SHA..HEAD_SHA`.
3. **Dispatch 3 review agents in parallel** via `superpowers:code-reviewer` agent type. Each gets the SAME diff + SAME architecture doc + their lens-specific brief from this skill. Use isolation: `worktree` only if the reviewer needs to run code; otherwise no isolation needed (reviewers only read).
4. **Wait for all three.** Don't proceed until all report back.
5. **Consolidate.** Merge into a single triage digest:
   - Dedupe findings raised by multiple lenses (cross-lens flags help)
   - Renumber under unified IDs (`A1`, `A2`, `B1`, …)
   - Group by severity
   - Surface verdict per lens + overall verdict
6. **Present to human** with per-finding triage chips: Accept / Defer (file issue) / Reject / Discuss.
7. **On triage results, dispatch fix agents.** Each fix agent gets the accepted findings for one file or one concern + `superpowers:receiving-code-review` skill reference + `superpowers:verification-before-completion` skill reference.

## Cadence

- **Per batch in Phase 1–3** (foundation): always review before merging the batch.
- **Per phase boundary** (Phase 1 → 2, etc.): always review before declaring the phase done.
- **Pre-beta**: final full-codebase review pass with all three lenses.
- **Hotfixes / single-line changes**: skip; just self-verify.

## Anti-patterns

- ❌ Dispatching a reviewer with all three lens briefs at once — they'll surface only the loudest issues per file, not the full set.
- ❌ Suggesting fixes inline in this skill instead of in the review report — separation of concerns.
- ❌ Skipping the consolidation step and forwarding raw reports to the human — wastes their attention.
- ❌ Acting on findings before human triage — the human review of reviewer suggestions is the whole point.

## Reference

This skill builds on:
- `superpowers:requesting-code-review` — the general request flow.
- `superpowers:dispatching-parallel-agents` — when 3 lenses run concurrently.
- `superpowers:receiving-code-review` — for fix agents.
- `superpowers:verification-before-completion` — for fix agents pre-claim-done.

Architecture context for reviewers:
- [docs/architecture.md](../../../docs/architecture.md) — single source of truth.
- [GitHub Epic #115](https://github.com/e-lo/GMNSpy/issues/115) — issue tree.
