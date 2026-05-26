---
title: Page Style Guide
audience: contributors
ai_index: false
summary: How every docs page in this site is structured so both humans and AI agents can find what they need fast.
---

# Page Style Guide

This is **not a public page** — it's the contract every other page in this site follows. Authors (humans + sub-agents writing markdown) read this first.

The site is built for two audiences in parallel:

* **Humans** scanning a page for the answer in 30 seconds.
* **AI agents** (LLM-based assistants, MCP clients, Claude Code Skills) parsing the page to extract context for a downstream task.

Optimising for one without the other produces docs that are either pretty-but-opaque (humans win, agents miss it) or comprehensive-but-tedious (agents win, humans bounce). The rules below thread the needle.

## Frontmatter — required on every page

Every `.md` page starts with YAML frontmatter. Three required keys, two optional:

```yaml
---
title: Quickstart                      # required — H1-equivalent
audience: users | contributors | both  # required
summary: One sentence (≤120 chars). What this page is for. Read by both LLMs and human skimmers.
ai_index: true                         # optional, default true. Set false to omit from llms.txt nav.
stability: stable | beta | experimental  # optional — public API pages only
---
```

The `summary` is consumed by the `llms.txt` generator (see `docs/llms.txt` at site root) and by humans as the page subtitle. Make it answer "should I be on this page?" — not a teaser.

## Section headers — predictable shape per page kind

We have **four page kinds**. Each has a fixed section order so an agent that learned the template once knows where to look on every page.

### `kind: concept` — "what is X"

```
## What it is
## Why we have it
## Mental model              ← diagrams / analogies / 3-bullet summary
## How it relates to ...     ← cross-link section (single canonical link per target)
## See also
```

### `kind: howto` — "how do I X"

```
## When to use this           ← 1-2 sentences. Triggering conditions.
## Quick example              ← runnable copy-paste code; ≤20 lines
## Step-by-step               ← numbered list with one short paragraph each
## Common variations          ← optional — table of "if X then Y"
## Pitfalls                   ← optional — explicit gotchas
## See also
```

### `kind: reference` — "exact details on X"

```
## Summary                    ← 2-3 sentences. What this reference covers.
## API / fields / flags       ← the actual reference content (auto-gen welcome)
## Examples                   ← 1-2 runnable snippets per public symbol
## See also
```

### `kind: tutorial` — "walk through Y end-to-end"

```
## What you'll build
## Prerequisites              ← env + extras required (e.g. `gmnspy[clean]`)
## Steps                      ← numbered, each ends with what the user should see
## Next steps                 ← link out to relevant concept + howto pages
```

## Runnable code — every block is real

Every Python block in `cookbook/`, `howto/`, `tutorial/`, and `reference/` examples must run as-is against the bundled Leavenworth fixture or a clearly-marked synthetic. A doctest pass over the docs catches drift.

For shell blocks, prefix with `$ ` so the prompt is visible but agents can `sed 's/^\$ //'` to copy:

```text
$ gmnspy validate --json packages/gmnspy/gmnspy/fixtures/leavenworth/csv
```

## Stable anchors

Anchors are the deep-link surface for `ai/api-index.json`, `llms-full.txt`, and external citations.

* Auto-generated heading slugs are fine **as long as you don't rename the heading**.
* For API reference pages: anchors must match the dotted symbol code (e.g. `#gmnspy.scope.from_nodes`). Use an explicit attr-list anchor (the `{#name}` syntax markdown-attr-list supports) if mkdocs's default slug doesn't match — wrap in a raw-Jinja block if you write that literal in a markdown page so the macros plugin doesn't try to parse it.

When you rename a heading, search the repo for the old anchor and update every link in one pass. No silent drift.

## Cross-links — one canonical target per concept

Every concept has **exactly one home page**. Other pages link to it; they don't re-explain it.

* Wrong: three pages all describe "what `Network.scope` is" in their own words.
* Right: one concept page (`concepts/scope.md`) defines it; the three other pages link to it (`See [Scope](../concepts/scope.md).`).

This is the most important rule for agent-efficient docs — an agent following links to gather context shouldn't see the same idea three different ways with three different example shapes.

## Voice

* Active, present tense: "The validator emits an Issue", not "An Issue will be emitted".
* Direct: "Pass `engine='polars'` to switch backends", not "It is possible to switch backends".
* No "we" / "you" tug-of-war: pick one per page kind. `concept` + `reference` → impersonal. `howto` + `tutorial` → "you".

## Length

* `concept` pages: 200–500 lines.
* `howto` pages: 80–250 lines.
* `reference` pages: as long as the surface; aim for one symbol per ~30 lines.
* `tutorial` pages: 300–800 lines.

If a page is over 800 lines, split it. If under 50, it probably belongs as a section on a larger page.

## AI artifacts that depend on this guide

Three machine-readable artifacts at `docs/` root are built at `mkdocs build` time and depend on the conventions above:

| Artifact | Built by | Depends on |
|---|---|---|
| `llms.txt` | `datagrove.docgen.llms.generate_llms_txt` | nav + page `summary` |
| `llms-full.txt` | `datagrove.docgen.llms.generate_llms_full_txt` | full page bodies (excluding `ai_index: false`) |
| `ai/api-index.json` | `datagrove.docgen.llms.generate_api_index_json` | public-API docstrings + reference page anchors |

When you change a page header or rename a section, those artifacts regenerate next build. CI fails if the generated artifacts can't parse a page.

## See also

* `docs/architecture.md` — the single source of truth for the v1.0 design. Pages reference it; they don't duplicate it.
* `skills/README.md` — Claude Code Skills installed via git URL. Each skill links back into this docs site for its long-form reference.
