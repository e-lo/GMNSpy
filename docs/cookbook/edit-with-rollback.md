---
title: Edit a network with atomic rollback
audience: users
kind: howto
summary: Mutate a network inside a datagrove.editing.Session — every op produces an EditResult with a diff and rollback hook; the session commits on clean exit and rolls back on exception.
---

# Edit a network with atomic rollback

## When to use this

You're applying a destructive operation to a network — simplify geometry, merge close nodes, remove orphan links, recompute lengths — and you want a safety net. The `Session` context manager records every change so you can undo all of them in LIFO order, either by raising inside the `with` block, by calling `session.rollback()` explicitly, or by replaying a persisted log later.

## Quick example

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.clean import simplify_geometry
from datagrove.editing import Session

net = Network.from_source(leavenworth.csv_dir())
with Session(net) as s:
    result = simplify_geometry(net, s, mode="redundant_only")
    print(f"removed {result.diff.removed_rows} redundant shape points")

# Clean exit committed. Persist:
net.write("./leavenworth-simplified.parquet")
```

If the `with` block raises, the session rolls back all ops and `net` is byte-identical to the pre-edit state.

## Step-by-step

### 1. Install

```text
$ pip install 'gmnspy[clean]'
```

The `[clean]` extra brings in `shapely` and `igraph`, which most of the editing ops depend on for geometry / connectivity work.

### 2. Open a Session

```python
from datagrove.editing import Session

with Session(net) as s:
    ...
```

A `Session` wraps the network in an editable view. Inside the `with` block you pass *both* `net` and `s` into each editing op — the op uses `net` to read state and `s` to record the change so the session can undo it later.

### 3. Apply one or more ops

```python
from gmnspy.clean import simplify_geometry, merge_close_nodes, remove_orphans

with Session(net) as s:
    r1 = simplify_geometry(net, s, mode="redundant_only", tolerance="0.5m")
    r2 = merge_close_nodes(net, s, threshold="2m")
    r3 = remove_orphans(net, s)
```

Each call returns an `EditResult`:

| Field | Type | Description |
|---|---|---|
| `.diff` | `Diff` | Per-table row counts: `added`, `removed`, `changed`. Cheap to print / log. |
| `.edit` | `Edit` | The high-level op description (op name, parameters). |
| `.rollback_data` | `RollbackData` | The state captured before the op ran — opaque, but stable across versions and what `Session.rollback()` replays. |

### 4. Commit or rollback

Clean exit from the `with` block commits all ops. Anything else rolls back in LIFO order:

```python
# Commit:
with Session(net) as s:
    simplify_geometry(net, s, mode="redundant_only")
# committed at __exit__

# Rollback by raising:
try:
    with Session(net) as s:
        merge_close_nodes(net, s, threshold="2m")
        raise RuntimeError("changed my mind")
except RuntimeError:
    pass  # net is back to pre-merge state

# Rollback explicitly while staying in the block:
with Session(net) as s:
    result = remove_orphans(net, s)
    if result.diff.removed_rows > 100:
        s.rollback()  # too aggressive — undo
```

### 5. Persist the edit log (optional)

```python
with Session(net, log_path="history.parquet") as s:
    simplify_geometry(net, s, mode="redundant_only")
    merge_close_nodes(net, s, threshold="2m")
```

The session writes a chronological record of each op (name, params, diff, rollback blob) to `history.parquet`. Later, in a fresh process:

```python
from datagrove.editing import rollback

net = Network.from_source("./edited.parquet")
rollback(net, log_path="history.parquet")  # replay in LIFO
```

This is the same mechanism the CLI's `--dry-run` uses, and the only way to undo edits across process boundaries.

### 6. Write the result

```python
net.write("./leavenworth-edited.parquet")
```

If you see an `OutOfSyncWarning` here when running outside the CLI, that's [#164](https://github.com/e-lo/GMNSpy/issues/164) — an FK index didn't refresh after the edit. Workaround until the fix lands:

```python
net.recompute_fks()
net.write("./leavenworth-edited.parquet")
```

## Common variations

| You want... | Do this |
|---|---|
| Preview without committing | `gmnspy clean simplify-geometry <src> --dry-run` — runs the op, prints the diff, never writes. |
| Chain ops in one transactional block | Put multiple ops in the same `with Session(net) as s:` block. Rollback undoes all of them. |
| Run one op via the CLI | `gmnspy clean simplify-geometry <src> --mode redundant_only --out ./out.parquet`. |
| Capture diffs for a PR description | `result.diff` has a `_repr_html_` — display in a notebook or `print(result.diff)` for plain text. |
| Replay only the last N ops | Trim `history.parquet` before calling `rollback`, or pass `n=N` if your version supports it (see [API reference](../reference/api.md)). |

## Pitfalls

* **Bulk `replace_table` edits aren't atomic per-row today** (tracked in [#163](https://github.com/e-lo/GMNSpy/issues/163)). A `replace_table` records one rollback blob for the whole replacement, so partial mid-op failures cleanly rollback the whole replacement — not a subset.
* **Ibis engine + null-typed columns.** If an edit produces a column that's 100% null, writing through the ibis/duckdb engine may fail. Same workaround as elsewhere ([#163](https://github.com/e-lo/GMNSpy/issues/163)): switch the engine for the write step.
* **The session captures snapshots, not journals.** Memory cost scales with the size of the tables an op touches. For a `simplify_geometry` over a 5M-row link table, expect a few hundred MB of resident rollback state. Long sessions over huge networks should commit periodically.
* **Don't mutate tables outside the session.** Direct `net.links.expr.execute().assign(...)` writes bypass the session entirely and aren't rollback-able.
* **`OutOfSyncWarning` after an edit means FKs haven't been re-resolved.** Call `net.recompute_fks()` before writing. CLI does this for you; programmatic use must do it explicitly until [#164](https://github.com/e-lo/GMNSpy/issues/164) lands.

## See also

* [Architecture](../architecture.md) — Session / EditResult / Diff design.
* [Validate a network](validate-network.md) — `sync.fk_stale` is the validator's way of telling you to call `recompute_fks`.
* [API reference](../reference/api.md) — `Session`, `EditResult`, `Diff`, `rollback`.
