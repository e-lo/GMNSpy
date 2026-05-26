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

## 3. Claude Code Skills (`skills/` in the repo)

Five skills shipped in-repo, installed via git URL:

```text
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

Tools shipped (full reference: [MCP tools](mcp-tools.md)):

* **Generic (inherited from `datagrove.mcp`)** — `describe_package`, `validate_package`, `list_tables`.
* **GMNS-aware** — `describe_network`, `quality_check`, `connected_components`, `scope_from_nodes`.

Stateful tools (`edit_session` with rollback, `convert`) deferred to a follow-up; see [the deferred-tools issue](https://github.com/e-lo/GMNSpy/issues/164) for the open design questions.

## The `--json` CLI contract

Every `datagrove` / `gmnspy` CLI command supports `--json`:

* **Single document** on stdout (no log noise, no progress bars).
* **Rich + prompts on stderr** — `--json` on stdout stays parseable even when an approval prompt fires.
* **Stable schemas** — same shape across versions inside a major. `ValidationReport`, `EditResult`, and the per-command summary dicts are documented in the [API reference](../reference/api.md).

That's the lowest-friction way to drive the CLI from a tool-call loop without spinning up MCP.

## How the surfaces stay in sync

Single source of truth: docstrings + the mkdocs nav. `llms.txt`, `llms-full.txt`, `api-index.json`, and the per-page `summary` frontmatter all flow from there. CI fails if a generated artifact can't parse a page or if a public symbol is missing a docstring summary.

When you change a public docstring or rename a page, those artifacts regenerate next build — no separate AI-surface step.

## See also

* [Page Style Guide](../_page-style-guide.md) — what every page on this site follows so the AI artifacts have something parseable to consume.
* [Architecture §6.9](../architecture.md#69-ai-accessibility) — design rationale for the four surfaces.
* [Migration guide](../migration/v0.3-to-v1.0.md#whats-new) — what's new vs v0.3 from an AI consumer's standpoint.
