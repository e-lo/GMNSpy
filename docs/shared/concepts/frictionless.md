---
title: Frictionless data packages
audience: both
kind: concept
summary: What the Frictionless Data Package format is, how datagrove + gmnspy use it, what each Frictionless term maps to in this codebase, and how to handle data that isn't (yet) a Frictionless package.
---

# Frictionless data packages

!!! info "Stub — to be filled by docs Wave D-2 task #15"
    Full content lands in the next docs pass. This page is in nav so cross-links work today.

## What it is

(One paragraph: the [Frictionless Data Package](https://datapackage.org/) spec is a tiny, JSON-based way to describe a directory of tables, their schemas, and the foreign-key relationships between them.)

## The four moving parts

* **Data Package** — the directory + `datapackage.json` manifest. Maps to `datagrove.Package` / `gmnspy.Network`.
* **Resource** — one table. Maps to `pkg.tables[name]` / `net.tables[name]`.
* **Table Schema** — field definitions for one table. Maps to the per-table `<name>.schema.json`.
* **Foreign Keys** — declared in `datapackage.json`. Walked by `pkg.validate()`'s FK pass.

## GMNS-to-Frictionless mapping table

| GMNS concept | Frictionless concept | gmnspy / datagrove name |
|---|---|---|
| The whole network | Data Package | `gmnspy.Network` |
| `link` / `node` / etc. table | Resource | `net.tables["link"]` |
| `link.schema.json` | Table Schema | `net.tables["link"].schema` |
| `link.from_node_id → node.node_id` | Foreign Key | walked by `net.validate()` |

## What Frictionless gives you (and what it doesn't)

(Gets: cross-tool interop, machine-readable schemas, declarative FKs. Doesn't: semantics — Frictionless is structural only.)

## Handling non-Frictionless data

(Real GMNS-adjacent data isn't always Frictionless. CSV directories without `datapackage.json`, GTFS feeds, OGC GeoPackage. Today's escape valve: pass `spec=` explicitly. Tomorrow's: the `SchemaProbe` extension surface — see [v1.1 issue #TBD](#).)

## See also

* [Frictionless Data Package spec](https://datapackage.org/)
* [Architecture](../architecture.md) for the design decisions on top of Frictionless
* [gmnspy Schema reference](../../gmnspy/reference/spec.md)
