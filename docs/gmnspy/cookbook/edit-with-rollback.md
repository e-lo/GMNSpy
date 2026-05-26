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

Open a session, run a geometry simplification, and exit cleanly so the edit commits. Then write the result out:

```python
from gmnspy import Network
from gmnspy.fixtures import leavenworth
from gmnspy.clean import simplify_geometry
from datagrove.editing import Session

net = Network.from_source(leavenworth.csv_dir())
with Session(net) as s:
    result = simplify_geometry(net, s, mode="redundant_only")
    print(f"removed {result.diff.rows_changed} redundant shape points")

# Clean exit committed. Persist:
net.write("./leavenworth-simplified.parquet")
```

If the `with` block raises, the session rolls back all ops and `net` is byte-identical to the pre-edit state.

![Diff card showing the simplify_geometry result on Leavenworth](../../assets/screenshots/leavenworth-simplify-edit-result.png){ .screenshot }
*EditResult diff card: per-table row counts (added / removed / changed) plus a before/after geometry preview.*

## Step-by-step

### 1. Install

The `[clean]` extra brings in `shapely` and `igraph`, which most of the editing ops depend on for geometry / connectivity work:

```bash
pip install 'gmnspy[clean]'
```

### 2. Open a Session

A `Session` wraps the network in an editable view. Inside the `with` block you pass *both* `net` and `s` into each editing op — the op uses `net` to read state and `s` to record the change so the session can undo it later:

```python
from datagrove.editing import Session

with Session(net) as s:
    ...
```

### 3. Apply one or more ops

Multiple ops in the same `with` block share a single transactional boundary — rollback undoes all of them:

```python
from gmnspy.clean import simplify_geometry, merge_close_nodes, remove_orphans

with Session(net) as s:
    r1 = simplify_geometry(net, s, mode="redundant_only", tolerance="0.5m")
    r2 = merge_close_nodes(net, s, threshold="2m")
    r3 = remove_orphans(net, s)
```

Each call returns an `EditResult` with three fields:

| Field | Type | Description |
|---|---|---|
| `.diff` | `Diff` | Per-table row counts: `added`, `removed`, `changed`. Cheap to print / log. |
| `.edit` | `Edit` | The high-level op description (op name, parameters). |
| `.rollback_data` | `RollbackData` | The state captured before the op ran — opaque, but stable across versions and what `Session.rollback()` replays. |

### 4. Commit or rollback

Clean exit from the `with` block commits all ops. An exception or an explicit `s.rollback()` undoes them in LIFO order:

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
    if result.diff.rows_changed > 100:
        s.rollback()  # too aggressive — undo
```

### 5. Persist the edit log (optional)

Pass `log_path=` to write a chronological record of each op (name, params, diff, rollback blob) to a sidecar parquet. The log is the only way to undo edits across process boundaries:

```python
with Session(net, log_path="history.parquet") as s:
    simplify_geometry(net, s, mode="redundant_only")
    merge_close_nodes(net, s, threshold="2m")
```

Later, in a fresh process, replay the log in LIFO to undo:

```python
from datagrove.editing import rollback

net = Network.from_source("./edited.parquet")
rollback(net, log_path="history.parquet")  # replay in LIFO
```

This is the same mechanism the CLI's `--dry-run` uses.

### 6. Write the result

Persist the edited network. If you see an `OutOfSyncWarning` when running outside the CLI, that's [#164](https://github.com/e-lo/GMNSpy/issues/164) — an FK index didn't refresh after the edit:

```python
net.write("./leavenworth-edited.parquet")
```

Workaround until the fix lands — call `recompute_fks` explicitly before the write:

```python
net.recompute_fks()
net.write("./leavenworth-edited.parquet")
```

## Common variations

???+ note "Default — transactional block with a single op"
    Most common pattern: open session, run one op, exit cleanly to commit.

    ```python
    with Session(net) as s:
        simplify_geometry(net, s, mode="redundant_only")
    ```

??? note "Chain multiple ops in one atomic block"
    All-or-nothing: rollback undoes the whole batch.

    ```python
    with Session(net) as s:
        simplify_geometry(net, s, mode="redundant_only")
        merge_close_nodes(net, s, threshold="2m")
        remove_orphans(net, s)
    ```

??? note "Preview without committing"
    `--dry-run` on the CLI runs the op, prints the diff, and reverts before exit.

    ```bash
    gmnspy clean simplify-geometry <src> --dry-run
    ```

??? note "Run one op from the shell"
    Useful in pipelines; the CLI handles `recompute_fks` for you.

    ```bash
    gmnspy clean simplify-geometry <src> --mode redundant_only --out ./out.parquet
    ```

??? note "Capture the diff for a PR description"
    `Diff` ships a `_repr_html_` for notebooks and a clean `__str__` for plain text.

    ```python
    print(result.diff)
    ```

??? note "Replay an edit log to undo across processes"
    The log is a parquet sidecar; pass the path and `rollback` replays in LIFO.

    ```python
    from datagrove.editing import rollback
    rollback(net, log_path="history.parquet")
    ```

## Pitfalls

* **Bulk `replace_table` edits aren't atomic per-row today** (tracked in [#163](https://github.com/e-lo/GMNSpy/issues/163)). A `replace_table` records one rollback blob for the whole replacement, so partial mid-op failures cleanly rollback the whole replacement — not a subset.
* **Ibis engine + null-typed columns.** If an edit produces a column that's 100% null, writing through the ibis/duckdb engine may fail. Same workaround as elsewhere ([#163](https://github.com/e-lo/GMNSpy/issues/163)): switch the engine for the write step.
* **The session captures snapshots, not journals.** Memory cost scales with the size of the tables an op touches. For a `simplify_geometry` over a 5M-row link table, expect a few hundred MB of resident rollback state. Long sessions over huge networks should commit periodically.
* **Don't mutate tables outside the session.** Direct `net.links.expr.execute().assign(...)` writes bypass the session entirely and aren't rollback-able.
* **`OutOfSyncWarning` after an edit means FKs haven't been re-resolved.** Call `net.recompute_fks()` before writing. CLI does this for you; programmatic use must do it explicitly until [#164](https://github.com/e-lo/GMNSpy/issues/164) lands.

## See also

* [Architecture](../../shared/architecture.md) — Session / EditResult / Diff design.
* [Validate a network](validate-network.md) — `sync.fk_stale` is the validator's way of telling you to call `recompute_fks`.
* [API reference](../reference/api.md) — `Session`, `EditResult`, `Diff`, `rollback`.
