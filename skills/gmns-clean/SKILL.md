---
name: gmns-clean
description: Apply network-editing operations (simplify geometries, merge close nodes, drop orphans) to a GMNS network inside a transactional Session that supports commit or rollback. Use when the user wants to tidy a network without risking destructive changes.
---

# gmns-clean

Use this skill when a user wants to clean up a GMNS network — drop stranded
nodes, merge nodes that are within a few meters of each other, simplify
overdetailed link geometries, or remove duplicate links — and wants to
preview the result before committing. The `gmnspy.clean` operations all run
inside a `datagrove.editing.Session`, which records every mutation so you
can either `commit()` or `rollback()` at the end.

This skill requires the `[clean]` extra, which pulls in `shapely` (for
geometry ops) and `igraph` (for connectivity analysis):

```bash
pip install "gmnspy[clean]"
# or, in this repo:
uv sync --extra clean
```

For *finding* what needs cleaning, use `gmns-validate` first — the quality
warnings tell you which operations to run.

## Workflow

1. **Validate first** so you know what's actually wrong:
   ```bash
   gmnspy validate ./net --json | jq '.issues | group_by(.code)
       | map({code: .[0].code, count: length})'
   ```
2. **Open a `Session` around the network.** The `with` block is the
   transaction boundary; exiting without `commit()` rolls everything back.
3. **Run clean ops in this order** (matters — geometry before topology):
   1. `simplify_geometry` — drop redundant vertices on link geometries
   2. `merge_close_nodes` — collapse near-duplicate nodes (re-routes their
      links to the survivor)
   3. `drop_stranded_nodes` — remove nodes with no incident links
   4. `dedupe_links` — collapse parallel duplicates (with a strategy:
      `keep_first`, `keep_highest_capacity`, etc.)
4. **Inspect the diff** (`session.summary()`) before committing. The
   summary tells you how many rows were added / modified / removed per
   table.
5. **Commit or roll back:**
   - `session.commit()` writes the changes to the live `Network` object
   - exiting the `with` block *without* committing rolls them back
6. **Re-validate** after committing to confirm the issue counts dropped
   and no new errors appeared.

## Example

End-to-end clean of a network with stranded nodes and over-detailed
geometries:

```python
from gmnspy import Network
from gmnspy.clean import (
    simplify_geometry,
    merge_close_nodes,
    drop_stranded_nodes,
    dedupe_links,
)
from datagrove.editing import Session

net = Network.from_source("./network")

with Session(net) as s:
    simplify_geometry(net, s, tolerance_m=1.0)
    merge_close_nodes(net, s, threshold_m=5.0)
    drop_stranded_nodes(net, s)
    dedupe_links(net, s, strategy="keep_highest_capacity")

    print(s.summary())
    # {"node": {"removed": 12, "modified": 3},
    #  "link": {"removed": 4, "modified": 87}}

    # Preview only — if this looks wrong, just don't commit.
    s.commit()

# Persist to disk
net.write("./network_clean", format="csv")
```

Rollback example (no commit, no changes survive):

```python
with Session(net) as s:
    drop_stranded_nodes(net, s)
    if s.summary()["node"]["removed"] > 100:
        # Too aggressive — bail out
        raise RuntimeError("unexpected node count; aborting")
    s.commit()
```

If the `RuntimeError` fires, the `Session` exits without committing and
`net` is untouched.

## Per-op notes

- **`simplify_geometry(net, s, tolerance_m=1.0)`** — Douglas-Peucker on
  `link.geometry` (WKT LINESTRING). Tolerance is in meters; 1 m is safe for
  most road networks, 5 m for regional studies. Leaves endpoints untouched.
- **`merge_close_nodes(net, s, threshold_m=5.0)`** — finds node clusters
  within `threshold_m`, picks one survivor per cluster (lowest `node_id`),
  rewrites `from_node_id` / `to_node_id` on all affected links, then drops
  the merged nodes. Will not merge nodes connected by a link (those are
  legitimate short segments).
- **`drop_stranded_nodes(net, s)`** — removes nodes with no incident links.
  Always safe; reversible inside the session.
- **`dedupe_links(net, s, strategy=...)`** — collapses links sharing the
  same `(from_node_id, to_node_id)` pair. Strategies:
  - `"keep_first"` — keep lowest `link_id`
  - `"keep_highest_capacity"` — keep the link with the largest `capacity`
  - `"keep_widest"` — keep the link with the most `lanes`

## Pitfalls

- **`merge_close_nodes` is sensitive to threshold.** 5 m collapses true
  duplicates; 20 m starts eating real intersections. When in doubt, run on
  a copy first.
- **Order matters.** Don't `drop_stranded_nodes` *before* `merge_close_nodes`
  — the merge can produce strandeds the drop would have missed.
- **Geometry simplification preserves topology**, but if your geometries
  are wildly malformed (self-intersecting), `simplify_geometry` won't fix
  that. Repair geometries upstream first.
- **The Session holds the whole diff in memory.** For >5M-link networks,
  chunk the operations or skip the session and edit tables directly.

## See also

- `gmns-validate` — find what needs cleaning before you start
- `gmns-author` — manual edits as an alternative to ops
- `packages/gmnspy/tests/test_clean.py` — runnable examples for every op
- `packages/datagrove/datagrove/editing/session.py` — Session internals
