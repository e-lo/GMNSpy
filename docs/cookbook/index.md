---
title: Cookbook
audience: users
kind: concept
summary: Task-oriented recipes for the common workflows — read from S3, validate after editing, convert formats, run a small server, hook up an AI agent.
---

# Cookbook

Each recipe is one task, one runnable example, one paragraph of why-it-works. Recipes are intentionally short — for the *design* behind a workflow, follow the "See also" link to the relevant concept page.

## I/O + format conversions

* [Read from S3 with credentials](read-from-s3.md) — credential cascade, partial loads, predicate pushdown.
* [Convert CSV ↔ Parquet ↔ DuckDB](convert-formats.md) — when to pick which format; roundtrip examples.

## Validation + data quality

* [Run validation and read the report](validate-network.md) — interpret severity / category / code.
* [Customise the data-quality rule pack](customise-quality.md) — threshold overrides, disable rules, plug in your own.

## Scope + geographic subsetting

* [Build a scope from seed nodes](scope-from-nodes.md) — BFS shortest-path, network buffers, FK pushdown.
* [Bounding-box and polygon scope](scope-bbox.md) — generic spatial; works on any geometry-bearing package.

## Editing with rollback

* [Edit a network with atomic rollback](edit-with-rollback.md) — `Session` lifecycle, dry-run preview, persisted history.

## Surfaces

* [Self-host the HTTP server](serve-http.md) — config file, bearer auth, deploying behind a proxy.
* [Wire the MCP server to Claude Code / Claude Desktop](serve-mcp.md) — stdio transport, tool list, agent prompts.
* [Run the bundled benchmarks](run-bench.md) — `gmnspy bench`, what to expect on Leavenworth vs regional networks.

## For AI agents specifically

* [Use the `--json` CLI contract from a tool-call loop](ai-json-cli.md) — every `gmnspy` subcommand emits a parseable document.
* [Read the api-index.json + llms.txt artifacts](../ai/index.md) — what's machine-readable on the site.

## Contributing a new recipe

A recipe is `kind: howto` per the [Page Style Guide](../_page-style-guide.md):

* `When to use this` — 1-2 sentences, the trigger.
* `Quick example` — ≤20 lines, copy-pasteable against the Leavenworth fixture.
* `Step-by-step` — numbered, one short paragraph each.
* Optional `Common variations` table + `Pitfalls`.
* `See also` — one link per related concept, no diffuse paths.

Open a PR with the new recipe + a link from this index. CI's doctest pass runs any python code blocks tagged `>>> `.
