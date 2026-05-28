---
title: gmnspy cookbook
audience: users
kind: concept
summary: Task-oriented recipes for the common GMNS workflows — validate, scope, edit, run the bench, self-host, drive from an AI agent.
---

# gmnspy cookbook

Each recipe is one task, one runnable example, one paragraph of why-it-works. Recipes are intentionally short — for the *design* behind a workflow, follow the "See also" link to the relevant concept page.

For generic Frictionless data-package recipes (S3 reads, format conversion, generic spatial scope), see the [datagrove cookbook](https://e-lo.github.io/GMNSpy/datagrove/cookbook/).

## Validation + data quality

* [Run validation and read the report](validate-network.md) — interpret severity / category / code.
* [Customise the data-quality rule pack](customise-quality.md) — threshold overrides, disable rules, plug in your own.

## Scope + geographic subsetting

* [Build a scope from seed nodes](scope-from-nodes.md) — BFS shortest-path, network buffers, FK pushdown.

For bbox / polygon (non-GMNS-specific) spatial scope, see [datagrove cookbook: spatial scope](https://e-lo.github.io/GMNSpy/datagrove/cookbook/scope-bbox/).

## Querying + editing linked tables

* [Query and update linked tables](query-and-update.md) — join across foreign keys, inspect lazily (no pandas), edit rows Network-Wrangler-style with rollback.
* [Edit a network with atomic rollback](edit-with-rollback.md) — `Session` lifecycle, dry-run preview, persisted history.

## Surfaces

* [Self-host the HTTP server](serve-http.md) — config file, bearer auth, deploying behind a proxy.
* [Wire the MCP server to Claude Code / Claude Desktop](serve-mcp.md) — stdio transport, tool list, agent prompts.
* [Run the bundled benchmarks](run-bench.md) — `gmnspy bench`, what to expect on Leavenworth vs regional networks.

## For AI agents specifically

* [Drive both packages from a tool-call loop](https://e-lo.github.io/GMNSpy/datagrove/ai/json-cli/) — every CLI command emits a parseable document with `--json`.
* [AI surface overview](https://e-lo.github.io/GMNSpy/datagrove/ai/) — llms.txt + api-index.json + Skills + MCP.

## Contributing a new recipe

A recipe is `kind: howto` per the [Page Style Guide](../_page-style-guide.md):

* `When to use this` — 1-2 sentences, the trigger.
* `Quick example` — ≤20 lines, copy-pasteable against the Leavenworth fixture, with **prose before the code**.
* `Step-by-step` — numbered, one short paragraph each.
* `Common variations` — collapsible accordions (`???`), one per variation.
* `Pitfalls` — explicit gotchas.
* `See also` — one link per related concept, no diffuse paths.

Open a PR with the new recipe + a link from this index. CI's doctest pass runs any python code blocks tagged `>>> `.
