---
title: AI surface
audience: both
kind: concept
summary: Everything in this repo that an AI agent (Claude Code Skills, MCP clients, llms.txt consumers) can consume — and how the surfaces stay in sync with the human docs.
---

# AI surface

GMNSpy + datagrove are designed to be driven by AI agents as a first-class usage mode. Four distinct surfaces, all generated from the same source of truth as the human docs so they can't drift:

## 1. `llms.txt` + `llms-full.txt` (this site)

Two files at the site root, regenerated on every `mkdocs build`:

| Artifact | Purpose | Built from |
|---|---|---|
| [`llms.txt`](../llms.txt) | Site map for LLMs. Page titles + summaries + absolute URLs. The minimum context to pick the right page for a question. | The mkdocs `nav` + each page's `summary` frontmatter. |
| [`llms-full.txt`](../llms-full.txt) | The entire site flattened into one document. Drop into a context window when you want the model to have everything. | Same nav + full page bodies, excluding pages marked `ai_index: false`. |

Both follow the [llms.txt convention](https://llmstxt.org/).

### Use it from Claude / ChatGPT / your MCP host

The fastest way to bootstrap a model with this project's docs is to paste the `llms.txt` URL into a chat. The model fetches it, indexes the pages, then decides which ones to pull for follow-up questions:

```text
Read https://e-lo.github.io/GMNSpy/llms.txt to learn the structure
of the gmnspy + datagrove docs, then walk me through validating a
GMNS network at <path>.
```

The result is a model that knows what pages exist and what each one is for — without you having to remember the URL of every concept doc. Replace `<path>` with a real local path or the bundled fixture (`packages/gmnspy/gmnspy/fixtures/leavenworth/csv`) to anchor the conversation in something concrete.

### When to use which

The two variants serve different agent loops:

| Artifact | Best for | Trade-off |
|---|---|---|
| `llms.txt` | An agent picking the right page for a question. Minimum context. | The agent has to make a second fetch to actually read a page. |
| `llms-full.txt` | An agent that needs everything in one shot — large context windows, offline use, or one-pass synthesis. | Heavy. Don't drop into a 4k-token context. |

### Concrete use cases

* Drop into a fresh chat to bootstrap context before asking gmnspy-specific questions.
* Pin in an MCP client's system prompt so every conversation starts with the doc map loaded.
* Feed `llms-full.txt` to a model with a large context window for one-pass synthesis (migration planning, cross-page audits).
* CI: have an agent verify cookbook recipes still match the `api-index.json` shape after a refactor.

## 2. `ai/api-index.json` — public-API surface

[`ai/api-index.json`](api-index.json) is a structured snapshot of every public symbol in `datagrove` + `datagrove.reports` (and, in v1.1, `gmnspy`). Schema:

```json
{
  "schema_version": "1",
  "packages": [
    {
      "name": "datagrove",
      "version": "0.1.0",
      "symbols": [
        {
          "kind": "function | class | method",
          "qualname": "datagrove.dataset.Package.from_source",
          "signature": "(source, *, engine=None, spec=None, tables=None)",
          "stability": "stable | beta | experimental",
          "summary": "first line of docstring",
          "anchor": "https://e-lo.github.io/GMNSpy/reference/api/#datagrove.dataset.Package.from_source"
        }
      ]
    }
  ]
}
```

Built by `datagrove.docgen.llms.generate_api_index_json`. Refreshes each build.

### Use it from an agent

The index is small and structured — an agent can fetch the whole thing, then answer "which symbol should I use for X?" without round-tripping through the full API reference:

```text
Fetch https://e-lo.github.io/GMNSpy/ai/api-index.json. Find every
symbol with stability=stable in the gmnspy.scope module and tell me
which one I should use to get the connected component a node
belongs to.
```

That sort of question used to need either a search over the full reference page or a brittle grep over the codebase. With the index, the agent has the same answer in one fetch.

### Concrete use cases

* Bootstrap context for an MCP client without loading the full API docs into the context window.
* CI gate: an agent verifies cookbook code samples still reference symbols that exist (and at the expected stability level).
* Tool dispatch: an agent picks the right function from a user's question by grepping the index for matching names + summaries.
* Migration assistance: diff two versions' indexes to spot removed / renamed / newly-experimental symbols.
* Build a typed wrapper or client SDK directly from the JSON shape — every symbol has a signature and an anchor back to the docs.

### jq cheatsheet

The JSON shape is shallow enough that `jq` covers most ad-hoc questions. Fetch the file once and explore locally:

```bash
# List all public functions in gmnspy.scope
jq '.packages.gmnspy.symbols[]
    | select(.module | startswith("gmnspy.scope"))
    | select(.kind == "function")
    | .name' api-index.json

# Find every experimental symbol across all packages
jq '.packages | to_entries[] | .value.symbols[]
    | select(.stability == "experimental")' api-index.json

# Count stable vs beta vs experimental per package
jq '.packages | to_entries[] | {
      pkg: .key,
      counts: (.value.symbols | group_by(.stability) | map({(.[0].stability): length}) | add)
    }' api-index.json
```

These compose well inside CI scripts and one-liner agent prompts (`subprocess.run(["jq", "...", "api-index.json"])`).

## 3. Claude Code Skills (`skills/` in the repo)

Five skills shipped in-repo, installed via git URL:

```shell-session
$ claude code skill add https://github.com/e-lo/GMNSpy#path=skills/gmns-validate
```

| Skill | When it triggers |
|---|---|
| [`datagrove-validate`](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/skills/datagrove-validate/SKILL.md) | User has a Frictionless data package and wants to validate it. |
| [`gmns-author`](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/skills/gmns-author/SKILL.md) | User wants to construct a GMNS network from scratch. |
| [`gmns-validate`](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/skills/gmns-validate/SKILL.md) | User wants to understand a GMNS validation / quality report. |
| [`gmns-convert`](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/skills/gmns-convert/SKILL.md) | User wants to convert GMNS data between formats. |
| [`gmns-clean`](https://github.com/e-lo/GMNSpy/blob/refactor/v1.0/skills/gmns-clean/SKILL.md) | User wants to edit / clean a network with rollback. |

Each skill links back to the matching cookbook recipe + concept page on this site so an agent that loads the skill also has the long-form context.

## 4. MCP server (`gmnspy mcp serve`)

Stateless tools over stdio for Claude Desktop, Claude Code, or any MCP-compatible host:

```json
{
  "mcpServers": {
    "gmnspy": {"command": "gmnspy", "args": ["mcp", "serve"]}
  }
}
```

Tools shipped (full reference: [MCP tools](https://e-lo.github.io/GMNSpy/gmnspy/ai/mcp-tools/)):

* **Generic (inherited from `datagrove.mcp`)** — `describe_package`, `validate_package`, `list_tables`.
* **GMNS-aware** — `describe_network`, `quality_check`, `connected_components`, `scope_from_nodes`.

Stateful tools (`edit_session` with rollback, `convert`) deferred to a follow-up; see [the deferred-tools issue](https://github.com/e-lo/GMNSpy/issues/164) for the open design questions.

## The `--json` CLI contract

Every `datagrove` / `gmnspy` CLI command supports `--json`:

* **Single document** on stdout (no log noise, no progress bars).
* **Rich + prompts on stderr** — `--json` on stdout stays parseable even when an approval prompt fires.
* **Stable schemas** — same shape across versions inside a major. `ValidationReport`, `EditResult`, and the per-command summary dicts are documented in the [API reference](https://e-lo.github.io/GMNSpy/gmnspy/reference/api/).

That's the lowest-friction way to drive the CLI from a tool-call loop without spinning up MCP.

## How the surfaces stay in sync

Single source of truth: docstrings + the mkdocs nav. `llms.txt`, `llms-full.txt`, `api-index.json`, and the per-page `summary` frontmatter all flow from there. CI fails if a generated artifact can't parse a page or if a public symbol is missing a docstring summary.

When you change a public docstring or rename a page, those artifacts regenerate next build — no separate AI-surface step.

## See also

* [Page Style Guide](../_page-style-guide.md) — what every page on this site follows so the AI artifacts have something parseable to consume.
* [Architecture §6.9](../architecture.md#69-ai-accessibility) — design rationale for the four surfaces.
* [Migration guide](https://e-lo.github.io/GMNSpy/gmnspy/migration/v0.3-to-v1.0/#whats-new) — what's new vs v0.3 from an AI consumer's standpoint.
