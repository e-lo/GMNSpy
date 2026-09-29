# Natural-language network *selection* → validated GMNS selection fragment (v1)

**Scope:** selection only (no edit, no map UI). Turn an utterance like
*"I-40 EB between Harrison Avenue and NC 54 exits"* into a validated, repeatable
set of GMNS `link_id`s emitted as a selection fragment.

## Decisions

- **Anchor resolution:** in-network topological traversal only (no geocoding,
  no new GMNS attributes). Interstates/routes matched on `ref` (carried via
  `extra_tags=["ref"]` at OSM build; a standard attribute, not a GMNS change).
- **Limited-access interchanges — gore/merge rule:** the upstream (`from`)
  anchor resolves to the off-ramp **diverge (gore)** node; the downstream (`to`)
  anchor to the on-ramp **merge** node, both on the requested-direction
  carriageway. (EB and WB are separate carriageways → disjoint link sets.)
- **Parser:** provider-agnostic seam. `ClaudeParser` (Anthropic tool-use,
  structured output) is the wired provider; `StubParser` is deterministic for
  tests/offline. The model emits a `SelectionIntent`, never ids.
- **Output:** a GMNS-native selection fragment (`links.link_id`, `from.node_id`,
  `to.node_id`, `notes`) validated against `select/schema/gmns_selection.schema.json`;
  `emit.to_projectcard()` adapts it to ProjectCard `model_link_id`/`model_node_id`.
- **Engines:** DuckDB/Parquet default, pandas a valid fallback. Facility/anchor
  narrowing is set-based; the tiny post-filter subnet uses a hand-rolled
  BFS/Dijkstra (no networkx/geopandas/osmnx).

## Pipeline (`gmnspy.select`)

`parse` (utterance→`SelectionIntent`) → `resolve` (intent+network→`SelectionResult`;
facility narrow → direction filter → gore/merge anchor resolution → shortest
path → validate) → `emit` (result→validated fragment). `SelectionResult.status`
∈ {resolved, ambiguous, not_found}; ambiguity is a first-class return with ranked
candidates (feeds the future map-confirm step).

## Validated (spike + tests, `tests/test_select_*.py`)

Real RTP I-40 fixture (`fixtures/rdu_i40`, built from OSM). Golden regression:
*"I-40 EB between South Miami Blvd and Airport Blvd"* → 14 mainline links,
gore node 170505098, merge node 195387716; WB reverse → 17 links (disjoint set).
Exact-ref matching rejects the `40`→`I 540`/`NC 540` substring collision.

## Deferred

Editing/mutation; map editor + interactive confirm; geocoding fallback; transit
selections; full-card assembly; multi-facility routes; sub-link/segment extents;
ramp-`destination` attribute path (data supports it later).

## Known env note

End-to-end via the real `Network.from_source` loader was not verified in the
build environment: `ibis 12 / duckdb 1.5.5` breaks datagrove's `create_table`,
and loading a hand-written `datapackage.json` needs gmnspy loader conventions
not fully replicated here. The resolver/emit are verified on the real fixture
frames and the CLI orchestration via an injected network. Verify the real
loader path (`gmnspy select … --engine pandas`) in a clean env.
