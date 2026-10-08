# Workbench P2 (Validate + Edit) Implementation Plan

Status: **proposed** (branch `feat/workbench-p2`) · Date: 2026-10-07 · Owner: Elizabeth Sall

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Re-scoped 2026-10-07.** The first draft of this plan (commit `eeaa01b` on this branch, "Validate + Fix +
> Change log") put ProjectCards in core: a `netstead.changes` package (`NetworkChange`, `DraftCard`,
> `ChangeLog`), a vendored projectcard schema, a `[projectcard]` extra and a Changes tab. The accepted
> [plugins design](2026-10-05-workbench-plugins-design.md) moves all of that to an external **cards** plugin. This
> revision is **core only**: validate the network, edit its tables directly, see live warnings, and save a copy.
> The ProjectCard research is kept in [the cards plugin scope](2026-10-07-cards-plugin-scope.md); see
> [Moved to the cards plugin](#moved-to-the-cards-plugin).

## Depends on plugin Part 1 (read this first)

**Plugin Part 1 comes first, then P2** (decided 2026-10-08). P2 builds **on**
[plugins Part 1](2026-10-05-workbench-plugins-p1-plan.md), which is not implemented yet. Start P2 only after Part 1
has merged to `main`. P2's Actions register on Part 1's Action registry, and its edits go through `Session.mutate`
(what `Host.mutate` calls); plugins preview through `Host.derive`. P2 uses these Part 1 pieces as written there:

| Part 1 piece (task) | What P2 does with it |
|---|---|
| `BaseAction`, `CORE_ACTIONS`, per-session `ActionRegistry` (Task 1) | P2's six Actions subclass `BaseAction` and are **appended to `CORE_ACTIONS`**. Nothing is added to the closed `Action` union. |
| Handler table `Session._handlers`, built from `_do_<type>` for core (Task 2) | P2's handlers are `_do_<type>` / `_job_<type>` methods, so the table picks them up with no registration code. |
| `HistoryEntry.imports` and `history.js` building imports from entries (Tasks 2–3) | "Copy session as Python" covers the new Actions with no front-end change. |
| `Session.mutate(net_id, edits, *, note)` (Task 8) | Every P2 edit goes through it. P2 extends it with a `source` and a pending-edits ledger (Task 5). |
| `Session.derive` / `derived_copy` (Tasks 7–8) | Not used by P2 core edits (see Decision 3). |
| `Host` (Task 9): `selection`, `mutate`, `derive`, `writable` | P2 adds the facility form to `host.selection` (Task 2), passes `source` through `host.mutate`, and adds `undo`, `edit_warnings` and `plan_*` (Task 5, `HOST_API` 1.0 → 1.1). |

There is no "P2 first" path in this plan. (Landing P2 first would mean adding its Actions to the closed union,
copying Part 1's `Session.mutate` into P2, and moving the Host additions into Part 1; that was considered and
rejected on 2026-10-08.)

---

## Decisions from the user

Every question this plan raised is decided. None is open.

**Decided 2026-10-07 (with the re-scope):**
- **Edits are allowed, with non-blocking schema warnings** (the user's answer 3). Table values are edited in the
  Workbench: cell edits in the table, and the fix editor launched from an issue or from Details. An edit that the
  spec disagrees with (a foreign key not in the referenced table, a required field left empty, a wrong type or a
  value outside the enum, a duplicate primary key) is **applied** and shown as an edit warning on the cell, the row
  and the Issues tab, so the user can go and fix it. Only what the storage cannot hold is refused (Decision 1).
- **Save writes a new copy.** Edits live on the open handle, in memory; the source (a local folder or `s3://…`) is
  never written. `SaveNetwork` writes a **new** copy inside `io.allowed_roots`, never overwrites, and reports
  corral's `OutOfSyncWarning` as text. Before saving, the outstanding warnings are shown; while any remain, saving
  needs an explicit confirmation (`accept_warnings=True`).
- **ProjectCards are not core.** Everything card-shaped moves to the cards plugin (see
  [Moved to the cards plugin](#moved-to-the-cards-plugin)).

**(a) Undo. Decided 2026-10-08:** the last edit only, one at a time, no redo. Undo is itself a recorded Action.
- `UndoEdit` reverses the network's **last** pending edit (LIFO, one per click). It is recorded in history like any
  Action, so a replayed session reproduces the same network.
- Core undoes only core edits. When the last change came from a plugin (`host.mutate`), core's Undo is refused with
  the plugin's name ("undo it in cards"); the plugin undoes its own through `host.undo` (Task 5). This keeps a
  plugin's state (a draft card) in step with the network.
- No redo: re-applying is re-dispatching the `EditCells` shown in the history strip.

**(b) Add and delete. Decided 2026-10-08:** delete a link in the UI; add rows from Python and the API only.
- **Delete** is in Details and the fix editor. Deleting a link cascades to the rows that depend on it through the
  spec's foreign keys (`lane`, `link_tod`, then their own dependents), as one undoable edit. Before anything is
  removed, a confirmation shows what will go (`POST …/table/{name}/delete-plan`: rows per table). Deleting a node
  that a link still references is refused, naming the links.
- **Add** is `AddRows`, from Python and the API, for any table with a primary key. There is no draw tool. Added links
  without geometry draw as straight lines between their nodes (`viz/buffers` already falls back to node
  coordinates).

**(c) Re-validation. Decided 2026-10-08:** live per-edit checks, plus a stale full validation with a manual Re-run.
- **Live, per edit:** after every mutation the session checks the rows edits have touched (by key) against the
  spec: foreign key, required, type and enum, duplicate primary key (Task 4). These edit warnings are always current.
- **The full validation and quality run** (`RunValidation`) is marked **stale** when the network version moves past
  the one it ran on. The Issues tab says so and offers a manual **Re-run** button. Export report is refused until
  it is re-run. There is no automatic re-run.

**(d) Sequencing. Decided 2026-10-08:** plugin Part 1 first, then P2 (see
[Depends on plugin Part 1](#depends-on-plugin-part-1-read-this-first)).

---

**Goal:** Validate a network in the Workbench and fix what it finds by editing its tables directly.
- **Validate.** "Run validation" runs `Network.validate` plus the quality rules as a background job, with the rule
  config from Settings → `validation.rules`. An **Issues** drawer tab links issue ↔ map marker ↔ table row. It
  filters by severity, table and code, and lists unlocated issues separately. An edit marks the result stale;
  one click re-runs it. **Export report** downloads the existing `render_validation_html` page.
- **Edit.** Cell edits in the data table (double-click a cell), and the offline report's "Fix locally" editor,
  ported to an ES module and launched from an issue or from Details. Each edit is a recorded Action (`EditCells`,
  `DeleteRows`, `AddRows`) applied through `Session.mutate` as corral `Edit`s (`update_rows`, `delete_rows`,
  `add_rows`): recorded in history, with a network version bump and a lineage entry.
- **Live warnings.** After each edit, the touched rows are checked against the spec. Warnings show on the cell, the
  row and the Issues tab, and never block.
- **Pending edits.** An **Edits** drawer tab lists the pending edits (with their source: the Workbench or a
  plugin), **Undo last**, the open warnings, and **Save a copy**. A dirty badge marks unsaved edits on the tab and in
  the network switcher (plugins design, UX principle 7).

**Architecture:**
- **Edit planning is pure.** `workbench/editing.py` turns a request into an `EditPlan` (corral `Edit`s, a summary,
  rows per table) and refuses only what the storage cannot hold. `workbench/editcheck.py` checks rows against the
  spec. Neither mutates.
- **One mutation path.** Every edit, core or plugin, goes through `Session.mutate`. P2 extends it: each mutation
  becomes a `PendingEdit` in the network's `EditLedger` (with its `source`, note, corral results and touched keys),
  and the live checks re-run over every key the ledger has touched, so a later edit that fixes a foreign key clears
  the earlier warning. `Session.undo_last` reverses the last entry (corral `reverse_edit`, LIFO).
- **Validation is a job**, like Open and Build. `Session._commit` is generalised: a job returns an *outcome* with a
  `commit(session)` method (`_Loaded`, `_Validated`, `_Saved`), still committed and recorded in one critical
  section.
- **Issues are tied to records at validation time.** A rule reports a row *position*, which is only meaningful in
  the table order it read, at that version. `locate_issues` turns positions into primary keys and an `anchor`
  (`{"link": id}`, `{"node": id}` or `{"lonlat": [x, y]}`). The browser places anchors from the network buffer it
  has already decoded.
- **Host API 1.1** (additive): `host.selection` carries the ProjectCard facility form; `host.mutate` records its
  plugin as the source; `host.undo`, `host.edit_warnings` and `host.plan_update/plan_delete/plan_add` let the cards
  plugin lower card changes onto core edits with core's refusal rules.
- New read-only routes, none recorded: `GET …/issues`, `…/issues/markers`, `…/report.html`, `…/edits`, and
  `POST …/table/{name}/delete-plan`.
- Front end:
  - the right drawer gains tabs: **Details | Issues | Edits**;
  - an edit (same network id, new version) keeps the focus, highlights, table, page and scope, instead of resetting
    them the way a network switch does;
  - pure rules live in import-free `issuelist.js` and `editmodel.js`, unit-tested under node;
  - DOM wiring lives in `issues.js`, `fixeditor.js`, `edits.js` and `table.js` (cell editing).

**Tech Stack:**
- Python 3.11, pydantic v2, FastAPI.
- ibis 12 on DuckDB through corral. No raw SQL: `lint_no_sql.py` must stay clean.
- **No new dependencies.** (The first draft's `[projectcard]` extra is gone with the cards.)
- MapLibre GL 4.7.1 and deck.gl 9.0.38 (already loaded). Native ES modules, no build step. Node only in tests.

**Spec:**
- [2026-10-02-netstead-workbench-design.md](2026-10-02-netstead-workbench-design.md): §b "Inspect & Validate
  workspace" (Validation and Fixing) and the phasing row P2. Its "Two audit logs" and `NetworkChange` parts are
  superseded by the plugins design.
- [2026-10-05-workbench-plugins-design.md](2026-10-05-workbench-plugins-design.md): UX principles 1 (core owns the
  network nouns), 3 (nothing mutates silently), 4 (everything is an Action) and 7 (dirty state is visible); `Host`.

**Branch:** `feat/workbench-p2`, cut from `main` after plugins Part 1 has merged.

**Conventions:**
- Run commands from the repo root.
- **Tiered tests:**
  - while iterating, the task's own paths: `uv run --all-extras pytest <paths> -q`;
  - before every commit: `uv run --all-extras pytest packages -n auto -q` (the fast default tier);
  - before merge, once, in Task 16: `uv run --all-extras pytest packages -n auto -q -m ""` (everything, including
    `slow` and `perf`).
- Lint: `uv run ruff check packages && uv run ruff format --check packages`. Task 16 also runs `uv run lint-imports`
  and `uv run python scripts/lint_no_sql.py`.
- Ruff enforces Google-style docstrings (`D`) outside `tests/`, line length 120. `--doctest-modules` is on, so every
  `>>>` example below is a test.
- Not every snippet below is pre-wrapped to 120 columns. After pasting, run `uv run ruff format <files>`, then the
  check pair.
- `filterwarnings = error`: a stray warning fails a test. Writing an edited network raises corral's
  `OutOfSyncWarning`, which Task 9 handles deliberately.
- Never write under `netstead/fixtures` (the conftest guard fails the session). Mutating tests load their own
  network per test and write to `tmp_path`.
- Fixtures: **Leavenworth** (`leavenworth.parquet_dir()`: 339 links, 121 nodes, 429 lanes, 1 `link_tod` row, plus
  `geometry`) for anything edit- or validation-shaped; its CSV copy (`leavenworth.csv_dir()`) where a null matters;
  **RDU** (link + node only) where the existing session tests use it. Session tests use the `isolated_env` fixture
  (its allowed roots are `tmp_path` plus the fixture trees).
- Pure front-end logic goes in import-free modules, tested with the `node_module` fixture (`conftest.py`). DOM
  wiring is covered by the static tests (`test_relative_imports_resolve_to_real_exports`,
  `test_every_element_id_used_by_js_exists_in_index`, `test_js_syntax`) and by the browser walk-through in Task 16.
- **corral `Table.filter` takes an expression transform, not a predicate.** `table.filter(lambda e:
  e.filter(e.link_id.isin(ids)))` is right; `table.filter(lambda t: t.link_id.isin(ids))` returns a one-column
  table of booleans (probed; the first draft had this bug in its `_rows` helper). A corral `Edit` predicate is the
  other kind: `lambda t: t.link_id.isin(ids)`. `editing.py` has one helper for each (`_where`, `_in`).
- **Honesty note.** Probed on `main` (`aedc407`) while writing this revision (scripts in the scratchpad, not
  committed):
  - **corral `apply_edit` on a lazy table** (Leavenworth parquet and CSV): it reads the whole target table to Arrow,
    applies the op in an ibis memtable, and swaps `table.expr` for `engine.from_arrow(new)`, an in-memory DuckDB
    table. Untouched tables stay lazy. A one-row `update_rows` on `link` took 0.02 s warm; `reverse_edit` 0.04 s.
  - **The undo bug is still on `main`:** `_reverse_update_rows` and `_reverse_add_rows` anti-join with `=`, and
    `NULL = NULL` is never true. Undoing an edit to CSV link 27 (`name` is null) leaves **two** copies of link 27
    (339 → 340 rows). An ibis `identical_to` anti-join fixes it. Task 1.
  - **What corral accepts silently** (so the planner must refuse it first): `update_rows` with `lanes = 1.5` widens
    the `int64` column to `float64`; `add_rows` with an unknown key adds a new column (`colour`); `add_rows` with an
    existing `link_id` gives two rows with that key. A text value in a float column raises `IbisTypeError`
    ("Cannot compute precedence"). Setting `None` clears a cell and keeps the dtype.
  - **Tasks 3 and 4 were run.** Their modules and tests, as written below, passed against `main` in a scratch copy
    (Task 3: 35 tests and doctests; Task 4: 21), with Task 1's `affected_rows` and Task 3's `self_refs` shimmed in.
  - **Live checks:** every Leavenworth `link`, `node`, `lane` and `link_tod` row is clean (0 warnings), so a test
    edit's warnings are its own. Checking all 339 links took 0.8 s cold. `ctrl_type = "bogus"` on node 1 gives `edit.enum`; `from_node_id = 424242` gives `edit.fk_missing`;
    `directed = None` gives `edit.required_empty`; adding a second link 1 gives `edit.duplicate_key`.
  - **Deletion:** `plan_delete(link 1)` deletes 1 `lane` row and the link; reversing both restores 429 lanes and 339
    links. Deleting node 1 is refused: links 1–4 use it.
  - Undo moves the restored row to the end of the table (order is not preserved); dtypes are preserved.
  - Writing an edited network warns `OutOfSyncWarning` ("Package source '…' has 1 stale table(s): …").
  - `Network.validate()` gives 17 issues on Leavenworth (16 `structural.missing_optional_resource` info, 1
    `fk.unverifiable` warning), and `run_quality` gives 271 `quality.high_speed_residential` warnings: 288 in all.
    All quality issues carry `table="link"`, `column="free_speed"` and a row position. Link 1 (`free_speed` 40,
    residential) is one of them.
  - Row order: `table.select(pk).to_pandas()` matches `table.to_pandas()` order for link, node and lane in parquet,
    CSV and zip. Those tables are stored sorted by key, so this check is weak; Task 7 pins it with a test.
  - Part 1 is **not** on `main`, so the snippets that touch `BaseAction`, `CORE_ACTIONS`, `Session.mutate` and
    `Host` (Tasks 5–10) are written against the Part 1 plan's code, not run. Task 0 and Task 5's first step check
    that those names exist as written. The front-end rules in `editmodel.js` were run under node.
  - The plan as a whole has **not** been executed. Expected results say "pass" plus the new test names, not counts.
    Where a step fails, fix the plan's code; don't weaken the test.

## Decisions (technical, made here)

1. **Refuse what storage cannot hold; warn about what the spec says.** The planner (Task 3) coerces each value to
   its column's storage type and refuses one that does not fit (`"fast"` in a float column, `1.5` in an integer
   column), an unknown column, a key column, a column type P2 cannot edit (geometry, binary, dates, times), a
   missing row, and deleting a node a link still uses. Everything else (required, enum, spec type, foreign keys,
   duplicate keys) is an edit warning (Task 4).
   - Coercion: integers take integral numbers or integral text; floats take numbers or numeric text; text takes any
     scalar; booleans take `true/false/1/0/yes/no`; empty text in a non-text column, and `None`, clear the cell.
2. **Key columns are not edited in a cell.** Changing a primary key would orphan every row that points at it. A new
   key enters through `AddRows`, where a clash is an `edit.duplicate_key` warning.
3. **No derived networks for core edits.** A cell edit is immediate and undoable, and a deletion's preview is the
   `delete-plan` dry run (rows per table), so a copy-on-write preview network adds a step without adding
   information. `derive` stays the plugins' tool for previews and scenarios (the cards plugin previews a card on a
   derived network).
4. **Every mutation is a pending edit, whatever made it.** The ledger records core edits (`source="workbench"`) and
   plugin mutations (`source=<plugin id>`). Undo is LIFO per network and source-checked (decision a).
5. **Live checks cover whole touched rows**, not just the edited cells (a row is what the spec constrains), and are
   bounded: at most `MAX_CHECKED_KEYS = 10_000` keys per table; beyond that the Edits tab says the live check was
   cut short and suggests Run validation.
6. **Deletion cascades through the spec's foreign keys**, recursively (link → lane → `lane_tod`), never into `link`
   or `node` (a node a link uses is refused). Self-references (`link.parent_link_id`) are not followed; rows that
   pointed at a deleted row are re-checked, so they surface as `edit.fk_missing`. Orphaned `geometry` rows stay, as
   Wrangler's `clean_shapes: false` does.
7. **The selection payload carries its ProjectCard facility form.** `selection_payload` adds
   `projectcard: {picked, resolved, query}` (both `to_projectcard` forms) for a resolved selection, so
   `host.selection` exposes it with no new Host method (the plugins design: core owns the facility form).
8. **Job outcomes commit themselves:** `_Loaded` / `_Validated` / `_Saved` each have `commit(session) -> dict`, run
   inside `Session._commit`'s one critical section.
9. **Issue numbers** are positions in the stored report (`i`). Markers and pages refer to them. A new run replaces
   the set.
10. **Bounds:**
    - `/issues` pages hold at most 500;
    - `/issues/markers` returns at most `MAX_MARKERS = 50_000` located markers (`truncated` beyond that), plus a
      per-record index of issue numbers for row marks and the "This record" filter;
    - `EditCells` / `DeleteRows` take at most `MAX_EDIT_IDS = 10_000` ids, `AddRows` at most 10 000 rows.
11. **Export report refuses a stale set** (409, "re-run validation, then export"). Positions in the report are only
    valid at the version it ran on.
12. **Rule config keys are rule codes** (`validation.rules["quality.high_speed_residential"]`).
    - `RuleSettings.severity_override` becomes `Literal["error", "warning", "info"] | None`, so a typo fails at
      settings load, not mid-run.
    - Codes not registered are reported as `unknown_rules` in the run result.
13. **An edit keeps the view:** `linking.netChange(prev, next)` → `same | edited | switched`. Only `switched` resets
    focus, highlights and the table. `edited` refreshes rail counts, rows, related records, details, issues and
    edits in place.
14. **Issue markers are a store-only layer toggle** ("Issues" in Layers), not a `Style` field. It is per tab and not
    recorded, like the focus.
15. **After a deletion, a selection that includes a deleted link is cleared.** It would otherwise point at missing
    links.
16. **Saving with open warnings needs `accept_warnings=True`.** The flag is recorded, so a replayed save makes the
    same choice. A save that started at version *v* marks the ledger saved only if the network is still at *v* when
    the copy lands.

## Scope notes

- **In P2:**
  - the corral undo fix;
  - `to_projectcard` `ignore_missing`, and the facility form on the selection payload;
  - edit planning, live checks, the pending-edits ledger, undo, Host 1.1;
  - `RunValidation`, `EditCells`, `DeleteRows`, `AddRows`, `UndoEdit`, `SaveNetwork`;
  - issues, markers, report, edits and delete-plan routes;
  - drawer tabs; the Issues tab and markers; cell editing; the fix editor; the Edits tab with the dirty badge;
  - docs.
- **Deferred:**
  - redo;
  - a link-drawing UI for additions;
  - editing key columns, geometry, dates and times;
  - transit edits (P6: the Actions take `component` and answer "not yet supported" for `transit`);
  - auto re-validation;
  - a corral `update_rows` that runs as an ibis `mutate` against DuckDB without the Arrow round trip (follow-up;
    see Risks).
- **Unchanged:**
  - the P1a wizard and jobs (apart from the `_commit` refactor);
  - the P1b linking routes;
  - `map/edits` (the offline report's edit log and `apply_edits`). The Workbench does not import it in P2.

## Moved to the cards plugin

Everything ProjectCard-shaped from the first draft now belongs to the external cards plugin. Its scope, the
decisions the user has made for it, the schema facts and the mapping file are in
[**2026-10-07-cards-plugin-scope.md**](2026-10-07-cards-plugin-scope.md):

| First-draft item | Now |
|---|---|
| `netstead.changes`: `NetworkChange`, `PropertyChange`, `Selection`, `apply_change` / `reverse_change` | cards plugin; lowered onto core edits through `host.plan_*` + `host.mutate` |
| `DraftCard`, `ChangeLog` (commit, describe), `.yml` export and import, `read_card` | cards plugin (plugin state, `cards.*` Actions) |
| Vendored projectcard schema, `[projectcard]` extra, `card_errors` / `validate_card` | cards plugin, with `projectcard` as a **required** dependency and its own validator |
| `changes/mappings/gmns_to_wrangler.yaml` and `FieldMap` | cards plugin (content preserved in the scope) |
| The Changes drawer tab (card view, commit, export, validate, import) | cards plugin's Edit workspace and dock panel |
| Importing a `map/edits` edit-log YAML | cards plugin (pending decision) |
| `ApplyChange`, `CommitCard`, `ImportCard` Actions | `cards.*` Actions |

What stays in core because the plugin needs it: `to_projectcard` always writing `ignore_missing` and the facility
form on `host.selection` (Task 2), `host.mutate` with a recorded source, `host.undo`, `host.edit_warnings` and
`host.plan_*` (Task 5), and `SaveNetwork` (Task 9).

## File structure

| Path | Responsibility |
|---|---|
| `packages/corral/corral/editing/apply.py` (modify), `editing/__init__.py` (modify) | Null-safe `_reverse_add_rows` / `_reverse_update_rows`; `affected_rows` |
| `packages/netstead/netstead/select/emit.py` (modify) | `to_projectcard` always writes `ignore_missing` |
| `packages/netstead/netstead/workbench/selection.py` (modify) | `projectcard` facility forms on the selection payload |
| `packages/netstead/netstead/workbench/related.py` (modify) | `foreign_keys(..., self_refs=True)` |
| `packages/netstead/netstead/workbench/editing.py` (new) | `EditPlan`, `EditRefused`, `coerce_value`, `editable`, `table_keys`, `plan_update` / `plan_delete` / `plan_add` |
| `packages/netstead/netstead/workbench/editcheck.py` (new) | `EditWarning`, `CheckResult`, `check_rows`, `touched_keys` |
| `packages/netstead/netstead/workbench/ledger.py` (new) | `PendingEdit`, `EditLedger` |
| `packages/netstead/netstead/workbench/issues.py` (new) | `IssueSet`, `rule_configs`, `run_validation`, `locate_issues` |
| `packages/netstead/netstead/config.py` (modify) | `RuleSettings.severity_override` literal |
| `packages/netstead/netstead/workbench/actions.py` (modify) | `RunValidation`, `EditCells`, `DeleteRows`, `AddRows`, `UndoEdit`, `SaveNetwork`; appended to `CORE_ACTIONS` |
| `packages/netstead/netstead/workbench/session.py` (modify) | Ledger in `mutate`, `undo_last`, outcomes, issues/edits state, the new handlers |
| `packages/netstead/netstead/workbench/plugins/host.py`, `plugins/spec.py` (modify) | `HOST_API = "1.1"`; `undo`, `edit_warnings`, `plan_*`; `mutate` passes its source |
| `packages/netstead/netstead/workbench/build.py` (modify) | `output_path` shared by Build and Save |
| `packages/netstead/netstead/workbench/routes/common.py` (new) | `network_handle` (shared 404/501 logic) |
| `packages/netstead/netstead/workbench/routes/edit.py` (new) | `/issues`, `/issues/markers`, `/report.html`, `/edits`, `/table/{name}/delete-plan` |
| `packages/netstead/netstead/workbench/routes/network.py`, `server.py`, `__init__.py` (modify) | Use `network_handle`; mount `edit_router`; export actions |
| `packages/netstead/netstead/workbench/static/js/issuelist.js`, `editmodel.js` (new) | Pure rules (node-tested) |
| `packages/netstead/netstead/workbench/static/js/issues.js`, `fixeditor.js`, `edits.js` (new) | DOM: Issues tab, fix editor, Edits tab |
| `packages/netstead/netstead/workbench/static/js/{linking,store,main,side,map,table,header}.js`, `index.html`, `app.css` (modify) | Tabs, edit-aware refresh, markers, row and cell marks, cell editing, dirty badge |
| Tests (new): `test_workbench_editing.py`, `test_workbench_editcheck.py`, `test_workbench_edits.py`, `test_workbench_issues.py`, `test_workbench_edit_routes.py` | |
| Tests (modify): `corral/tests/editing/test_editing.py`, `test_select_emit.py`, `test_workbench_related.py`, `test_workbench_session.py`, `test_workbench_plugins.py`, `test_workbench_js.py` | |
| `packages/netstead/docs/cookbook/workbench.md`, `packages/netstead/docs/cookbook/workbench-plugins.md`, `docs/design/2026-10-02-netstead-workbench-design.md`, `docs/design/README.md` (modify) | Docs |

---

### Task 0: Branch and baseline

**Files:** none.

- [ ] **Step 1: Check that plugins Part 1 has merged**

```bash
git fetch origin
git log origin/main --oneline | grep -i "ActionRegistry\|Session.mutate\|plugin" | head
grep -n "CORE_ACTIONS\|class BaseAction" packages/netstead/netstead/workbench/actions.py
grep -n "def mutate\|def derive" packages/netstead/netstead/workbench/session.py
grep -n "HOST_API = " packages/netstead/netstead/workbench/plugins/spec.py
```

Expected: `CORE_ACTIONS`, `BaseAction`, `Session.mutate`, `Session.derive` and `HOST_API = "1.0"` all exist. If they
don't, stop and wait for Part 1 (decision d: Part 1 first).

- [ ] **Step 2: Cut the branch**

```bash
git checkout -b feat/workbench-p2-impl origin/main
uv sync --all-packages --all-extras
```

(`feat/workbench-p2` holds this plan; the implementation gets its own branch.)

- [ ] **Step 3: Record the baseline**

Run: `uv run --all-extras pytest packages -n auto -q`
Expected: all pass. Record the count in the PR description. Every later task only adds tests, except that Task 7
edits one expectation in `test_workbench_session.py`.

No commit.

---

### Task 1: corral: undo restores rows that contain nulls; `affected_rows`

`_reverse_add_rows` and `_reverse_update_rows` find "the rows this edit touched" with an anti-join on every shared
or untouched column, using `=`. `NULL = NULL` is unknown, so a row with any null never matches. Undoing an edit to
such a row then leaves both the edited copy *and* the restored one (probed on `main`: CSV link 27, 339 → 340 rows).

The live checks (Task 4) also need to know which rows an applied edit touched. That lives in the edit's rollback
blob, whose shape is corral's business, so corral gets a small public reader for it: `affected_rows`.

**Files:**
- Modify: `packages/corral/corral/editing/apply.py`, `packages/corral/corral/editing/__init__.py`
- Test: `packages/corral/tests/editing/test_editing.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/corral/tests/editing/test_editing.py`. Change the `from corral.editing.apply import apply_edit`
line to `from corral.editing.apply import affected_rows, apply_edit, reverse_edit`.

```python
def _with_nulls() -> Package:
    e = IbisEngine()
    rows = [{"id": 1, "name": "a", "v": 1.0}, {"id": 2, "name": None, "v": 2.0}, {"id": 3, "name": "c", "v": 3.0}]
    return Package.from_tables({"x": Table(name="x", expr=e.from_records(rows), engine=e)})


def _rows(pkg: Package) -> list[dict]:
    return sorted(pkg.tables["x"].expr.to_pyarrow().to_pylist(), key=lambda r: r["id"])


def test_reverse_update_restores_a_row_whose_other_columns_hold_null() -> None:
    pkg = _with_nulls()
    before = _rows(pkg)
    r = apply_edit(pkg, Edit(op="update_rows", table="x", payload={"predicate": lambda t: t.id == 2, "set": {"v": 9.0}}))
    reverse_edit(pkg, r)
    assert _rows(pkg) == before  # not two copies of id 2


def test_reverse_add_removes_an_added_row_that_holds_null() -> None:
    pkg = _with_nulls()
    before = _rows(pkg)
    r = apply_edit(pkg, Edit(op="add_rows", table="x", payload={"rows": [{"id": 4, "name": None, "v": 4.0}]}))
    reverse_edit(pkg, r)
    assert _rows(pkg) == before


def test_affected_rows_reads_each_op() -> None:
    pkg = _with_nulls()
    added = apply_edit(pkg, Edit(op="add_rows", table="x", payload={"rows": [{"id": 4, "name": "d", "v": 4.0}]}))
    changed = apply_edit(pkg, Edit(op="update_rows", table="x", payload={"predicate": lambda t: t.id == 1, "set": {"v": 5.0}}))
    removed = apply_edit(pkg, Edit(op="delete_rows", table="x", payload={"predicate": lambda t: t.id == 3}))
    assert [r["id"] for r in affected_rows(added)] == [4]
    assert affected_rows(changed) == [{"id": 1, "name": "a", "v": 1.0}]  # the values before the edit
    assert [r["id"] for r in affected_rows(removed)] == [3]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/corral/tests/editing/test_editing.py -q -k "null or affected"`
Expected: FAIL at import (`affected_rows`). With the import removed, the two null tests FAIL: the update test finds
id 2 twice, and the add test still finds id 4.

- [ ] **Step 3: Implement**

In `packages/corral/corral/editing/apply.py`, add after `_concat_arrow`:

```python
def _null_safe(left: ibis.Table, right: ibis.Table, columns: list[str]) -> list[Any]:
    """Join predicates that also match NULL to NULL (``=`` never does, so a row holding a null would never match).

    ``right`` is cast to ``left``'s types: a column that is all null in the recorded rows arrives typed ``null``.
    """
    return [left[c].identical_to(right[c].cast(left[c].type())) for c in columns]
```

In `_reverse_add_rows`, replace

```python
    return ibis.memtable(current).anti_join(ibis.memtable(added_arrow), predicates=join_cols).to_pyarrow()
```

with

```python
    left, right = ibis.memtable(current), ibis.memtable(added_arrow)
    return left.anti_join(right, predicates=_null_safe(left, right, join_cols)).to_pyarrow()
```

In `_reverse_update_rows`, replace

```python
    kept = ibis.memtable(current).anti_join(ibis.memtable(original_arrow), predicates=identity_cols).to_pyarrow()
```

with

```python
    left, right = ibis.memtable(current), ibis.memtable(original_arrow)
    kept = left.anti_join(right, predicates=_null_safe(left, right, identity_cols)).to_pyarrow()
```

Add one sentence to both docstrings: `Columns are compared null-safely (NULL matches NULL).`

Then add, after `reverse_edit`:

```python
def affected_rows(result: EditResult) -> list[dict]:
    """The rows an applied edit added, changed (as they were *before* the edit) or removed.

    Read from the edit's rollback data, so callers never interpret that blob themselves. Empty for
    ``replace_table`` (every row) and for an edit that matched nothing.

    Examples:
        >>> from corral.dataset import Package, Table
        >>> from corral.editing import Edit
        >>> from corral.engines.ibis_engine import IbisEngine
        >>> e = IbisEngine()
        >>> pkg = Package.from_tables({"x": Table(name="x", expr=e.from_records([{"a": 1}]), engine=e)})
        >>> affected_rows(apply_edit(pkg, Edit(op="add_rows", table="x", payload={"rows": [{"a": 2}]})))
        [{'a': 2}]
    """
    data = result.rollback_data or {}
    for key in ("added_rows", "original_rows", "deleted_rows"):
        if key in data:
            return list(data[key] or [])
    return []
```

In `packages/corral/corral/editing/__init__.py`, add `from .apply import affected_rows`, add `"affected_rows"` to
`__all__` (sorted), and add one bullet to the module docstring's public surface:
`* :func:`affected_rows` — the rows an applied edit touched.`

- [ ] **Step 4: Run the editing tests**

Run: `uv run --all-extras pytest packages/corral/tests/editing -q`
Expected: all pass, including the three new tests and the existing `test_leavenworth_round_trip`.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair.
Expected: all pass. The `affected_rows` doctest runs here.

- [ ] **Step 6: Commit**

```bash
git add packages/corral/corral/editing/apply.py packages/corral/corral/editing/__init__.py packages/corral/tests/editing/test_editing.py
git commit -m "fix(corral): undo restores rows that hold nulls (null-safe reverse joins); affected_rows"
```

---

### Task 2: The selection's ProjectCard facility form (`ignore_missing`, `host.selection`)

The plugins design gives the facility form to core: `host.selection` exposes the selection as a ProjectCard
facility, built by `select/emit.to_projectcard`. Two gaps today:
- ProjectCard's `select_links` marks `ignore_missing` as **required**, and `_query_links` writes it only when it is
  false, so every card built from a default selection fails the schema. The resolved form never writes it.
- The selection payload (what `host.selection` copies, Part 1 Task 9) carries only the GMNS fragment.

Which `ignore_missing` value a *card* should carry for a click-pick is the cards plugin's decision (pending, see
[the scope](2026-10-07-cards-plugin-scope.md)). Core writes the intent's value (default `true`, Wrangler's default)
and says whether the selection was picked by id, so the plugin can apply its own rule.

**Files:**
- Modify: `packages/netstead/netstead/select/emit.py`, `packages/netstead/netstead/workbench/selection.py`
- Test: `packages/netstead/tests/test_select_emit.py`, `packages/netstead/tests/test_workbench_session.py`,
  `packages/netstead/tests/test_workbench_plugins.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_select_emit.py`:

```python
def test_projectcard_links_always_carry_ignore_missing():
    # The ProjectCard schema requires it on every links selector (select_links.json "required").
    assert to_projectcard(_resolved())["links"]["ignore_missing"] is True
    page = SelectionIntent(facility=Facility(name=["Page Road"]))
    assert to_projectcard(_resolved_result(page), form="query")["links"]["ignore_missing"] is True
    strict = SelectionIntent(facility=Facility(name=["Page Road"]), ignore_missing=False)
    assert to_projectcard(_resolved_result(strict), form="query")["links"]["ignore_missing"] is False
    assert to_projectcard(_resolved_result(strict))["links"]["ignore_missing"] is False
```

Append to `packages/netstead/tests/test_workbench_session.py`:

```python
def test_a_selection_carries_its_projectcard_facility(opened):
    first = int(opened.registry.get("rdu-i40").links_df()["link_id"].iloc[0])
    sel = opened.dispatch(Select(link_ids=[first]))
    assert sel["projectcard"]["picked"] is True
    assert sel["projectcard"]["resolved"] == {"links": {"model_link_id": [first], "ignore_missing": True}}
    assert sel["projectcard"]["query"]["links"]["model_link_id"] == [first]
    json.dumps(sel)  # plain JSON: no numpy scalars


def test_an_unparsed_selection_has_no_facility(opened):
    sel = opened.dispatch(Select(utterance="zzzz not a road"))
    assert sel["status"] != "resolved" and sel["projectcard"] is None
```

(`json` and `Select` are already imported there; add them if not.) The `StubParser` gives a `not_found` or
unparsed result for that utterance; either way the facility is `None`.

Append to `packages/netstead/tests/test_workbench_plugins.py` (it already defines `make_session` and `make_hello`):

```python
def test_host_selection_exposes_the_facility_form(make_session, rdu_source):
    from netstead.workbench.actions import OpenNetwork, Select

    session = make_session(make_hello())
    session.dispatch(OpenNetwork(source=rdu_source))
    first = int(session.registry.get("rdu-i40").links_df()["link_id"].iloc[0])
    session.dispatch(Select(link_ids=[first]))
    facility = session._hosts["hello"].selection["projectcard"]
    assert facility["picked"] is True and facility["resolved"]["links"]["model_link_id"] == [first]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_select_emit.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_plugins.py -q -k "ignore_missing or facility"`
Expected: FAIL: `KeyError: 'ignore_missing'` and `KeyError: 'projectcard'`.

- [ ] **Step 3: Implement**

In `to_projectcard` (`select/emit.py`), add this after the `if form == "query": … else: …` block and before the
`from_match` lines:

```python
    # ProjectCard's select_links requires the flag even at its default (the GMNS fragment omits a default true).
    pc["links"]["ignore_missing"] = result.intent.ignore_missing
```

Add to its docstring: `` ``links.ignore_missing`` is always written: the ProjectCard schema requires it.``

In `workbench/selection.py`:
- add `import json` and `from netstead.select.emit import to_fragment, to_projectcard` (extend the existing import);
- add this helper before `selection_payload`:

```python
def facility_forms(result: Any) -> dict[str, Any]:
    """A resolved selection as ProjectCard facility objects, for plugins (``host.selection["projectcard"]``).

    ``resolved`` lists the link ids (``model_link_id``); ``query`` is the re-resolvable selector (name, ref, ...);
    ``picked`` says the selection was made by id (a click or "Set as selection"), not by a query.
    """
    forms = {
        "picked": bool(result.intent.link_ids),
        "resolved": to_projectcard(result),
        "query": to_projectcard(result, form="query"),
    }
    return json.loads(json.dumps(forms, default=json_scalar))  # numpy ids -> plain JSON
```

- in `selection_payload`'s returned dict, after `"fragment"`, add
  `"projectcard": facility_forms(result) if result.status == "resolved" else None,`;
- in `unparsed_payload`'s returned dict, after `"fragment"`, add `"projectcard": None,`;
- add `"facility_forms"` to `__all__`, and to `selection_payload`'s docstring: "``projectcard`` is the
  :func:`facility_forms` of a resolved selection (``None`` otherwise)."

- [ ] **Step 4: Run the selection and session tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_select_emit.py packages/netstead/tests/test_select_cli.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_plugins.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/select/emit.py packages/netstead/netstead/workbench/selection.py packages/netstead/tests/test_select_emit.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_plugins.py
git commit -m "feat(select): ProjectCard selectors always carry ignore_missing; host.selection carries the facility form"
```

---

### Task 3: Edit planning: requests become corral edits (`workbench/editing.py`)

Pure functions: read the network, return an `EditPlan`, never mutate. `Session.mutate` (Task 5) applies the plan.
The planner refuses only what the storage cannot hold (Decision 1); spec problems are Task 4's warnings.

**Files:**
- Create: `packages/netstead/netstead/workbench/editing.py`
- Modify: `packages/netstead/netstead/workbench/related.py` (`foreign_keys(..., self_refs=...)`)
- Test: `packages/netstead/tests/test_workbench_editing.py`, `packages/netstead/tests/test_workbench_related.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_editing.py`:

```python
"""Edit planning: requests become corral edits; only what the storage cannot hold is refused."""

import ibis.expr.datatypes as dt
import pandas as pd
import pytest
from corral.editing.apply import apply_edit, reverse_edit
from netstead import Network
from netstead.fixtures import leavenworth
from netstead.workbench.editing import EditRefused, coerce_value, editable, plan_add, plan_delete, plan_update

PK = {"link": "link_id", "node": "node_id", "lane": "lane_id"}


@pytest.fixture
def net():
    return Network.from_source(leavenworth.parquet_dir())  # per test: plans get applied


def apply(net, plan):
    return [apply_edit(net, e) for e in plan.edits]


def cell(net, table, key, column):
    df = net.tables[table].to_pandas()
    (value,) = df.loc[df[PK[table]] == key, column].tolist()
    return None if pd.isna(value) else value


def counts(net):
    return {name: t.count() for name, t in net.tables.items()}


@pytest.mark.parametrize(
    ("value", "dtype", "want"),
    [("45", dt.float64, 45.0), (2.0, dt.int64, 2), ("2", dt.int64, 2), (None, dt.int64, None), ("", dt.float64, None),
     ("yes", dt.boolean, True), ("0", dt.boolean, False), (7, dt.string, "7")],
)
def test_coerce_value_fits_the_storage_type(value, dtype, want):
    assert coerce_value(value, dtype, "c") == want


@pytest.mark.parametrize(
    ("value", "dtype"), [("fast", dt.float64), (1.5, dt.int64), ("maybe", dt.boolean), (float("nan"), dt.float64)]
)
def test_coerce_value_refuses_what_the_column_cannot_hold(value, dtype):
    with pytest.raises(EditRefused, match="does not fit"):
        coerce_value(value, dtype, "c")


def test_editable_storage_types():
    assert all(editable(t) for t in (dt.float64, dt.int64, dt.string, dt.boolean))
    assert not any(editable(t) for t in (dt.binary, dt.date, dt.time, dt.timestamp))


def test_an_update_is_one_edit_and_reverses(net):
    plan = plan_update(net, "link", [1], {"free_speed": "30"})
    assert plan.summary == "link 1: free_speed = 30.0" and plan.rows == {"link": 1} and len(plan.edits) == 1
    (result,) = apply(net, plan)
    assert cell(net, "link", 1, "free_speed") == 30.0
    reverse_edit(net, result)
    assert cell(net, "link", 1, "free_speed") == 40.0


def test_none_clears_a_cell(net):
    apply(net, plan_update(net, "link", [1], {"name": None}))
    assert cell(net, "link", 1, "name") is None


def test_ids_arrive_as_text_or_numbers(net):
    assert plan_update(net, "link", ["2", 2], {"lanes": 2.0}).rows == {"link": 1}


@pytest.mark.parametrize(
    ("table", "ids", "values", "message"),
    [
        ("link", [1], {"free_speed": "fast"}, "does not fit"),
        ("link", [1], {"lanes": 1.5}, "does not fit"),  # corral would widen the column to float
        ("link", [999999], {"lanes": 2}, "not found"),
        ("link", [1], {"link_id": 2}, "key"),
        ("link", [1], {"colour": "red"}, "no column"),  # corral would add the column
        ("nope", [1], {"x": 1}, "no nope table"),
        ("link", [], {"lanes": 2}, "at least one row"),
        ("link", [1], {}, "at least one column"),
    ],
)
def test_bad_updates_are_refused(net, table, ids, values, message):
    with pytest.raises(EditRefused, match=message):
        plan_update(net, table, ids, values)


def test_a_spec_problem_is_planned_not_refused(net):
    plan_update(net, "node", [1], {"ctrl_type": "bogus"})  # outside the enum: a live warning (Task 4)
    plan_update(net, "link", [1], {"from_node_id": 424242})  # not a node: a live warning too


def test_deleting_a_link_takes_its_lanes_and_reverses(net):
    before = counts(net)
    plan = plan_delete(net, "link", [1])
    assert plan.rows == {"lane": 1, "link": 1} and [e.table for e in plan.edits] == ["lane", "link"]
    assert plan.summary == "delete link 1 (and 1 lane rows that depend on it)"
    results = apply(net, plan)
    after = counts(net)
    assert (after["link"], after["lane"]) == (before["link"] - 1, before["lane"] - 1)
    for result in reversed(results):
        reverse_edit(net, result)
    assert counts(net) == before


def test_a_node_a_link_uses_is_not_deleted(net):
    with pytest.raises(EditRefused, match="still used by link"):
        plan_delete(net, "node", [1])


def test_missing_rows_are_not_deleted(net):
    with pytest.raises(EditRefused, match="not found"):
        plan_delete(net, "link", [999999])


def test_adding_rows(net):
    plan = plan_add(net, "node", [{"node_id": 9001, "x_coord": -120.66, "y_coord": 47.6}])
    assert plan.rows == {"node": 1} and plan.summary == "add node 9001"
    apply(net, plan)
    assert cell(net, "node", 9001, "x_coord") == -120.66 and cell(net, "node", 9001, "name") is None


@pytest.mark.parametrize(
    ("rows", "message"),
    [([], "at least one row"), ([{"link_id": 9001, "colour": "red"}], "no column"), ([{"name": "x"}], "needs its key")],
)
def test_bad_additions_are_refused(net, rows, message):
    with pytest.raises(EditRefused, match=message):
        plan_add(net, "link", rows)


def test_a_duplicate_key_is_added_not_refused(net):
    apply(net, plan_add(net, "link", [{"link_id": 1, "from_node_id": 1, "to_node_id": 2, "directed": False}]))
    assert net.tables["link"].count() == 340  # the live check reports edit.duplicate_key (Task 4)
```

Append to `packages/netstead/tests/test_workbench_related.py`:

```python
def test_foreign_keys_can_keep_self_references():
    from corral.spec.model import DataPackage, Field, ForeignKeyReference, Resource, Schema
    from corral.spec.model import ForeignKey as SpecFK
    from netstead.workbench.related import foreign_keys

    schema = Schema(
        fields=[Field(name="link_id"), Field(name="parent_link_id")],
        primary_key="link_id",
        foreign_keys=[SpecFK(fields="parent_link_id", reference=ForeignKeyReference(resource="", fields="link_id"))],
    )
    spec = DataPackage(name="x", resources=[Resource(name="link", path="link.csv", schema=schema)])
    columns = {"link": ["link_id", "parent_link_id"]}
    assert foreign_keys(spec, columns) == []
    assert [fk.label for fk in foreign_keys(spec, columns, self_refs=True)] == ["link.parent_link_id → link"]
```

If `DataPackage` needs more required fields than `name` and `resources`, pass what its model asks for; the
assertion is about the self-reference.

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_editing.py packages/netstead/tests/test_workbench_related.py -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'netstead.workbench.editing'`, and
`TypeError: foreign_keys() got an unexpected keyword argument 'self_refs'`.

- [ ] **Step 3: `foreign_keys(..., self_refs=...)`**

In `workbench/related.py`, change `foreign_keys`:

```python
def foreign_keys(spec: Any, columns: Mapping[str, Sequence[str]], *, self_refs: bool = False) -> list[ForeignKey]:
    """Single-column FKs between tables in ``columns``, both columns present.

    Same-table keys (``link.parent_link_id``) are skipped unless ``self_refs``: the related-records view
    never follows them; edit planning and the live checks do.
    """
    out: list[ForeignKey] = []
    for name, schema in _schemas(spec).items():
        if name not in columns:
            continue
        for fk in schema.foreign_keys:
            ref_table = fk.reference.resource or name
            column, ref_column = _single(fk.fields), _single(fk.reference.fields)
            if ref_table == name and not self_refs:
                continue
            if ref_table not in columns or column is None or ref_column is None:
                continue
            if column in columns[name] and ref_column in columns[ref_table]:
                out.append(ForeignKey(name, column, ref_table, ref_column))
    return out
```

- [ ] **Step 4: Create `workbench/editing.py`**

```python
"""Core table editing: turn a request (set cells, delete rows, add rows) into corral edits, checked first.

Nothing here mutates. Each ``plan_*`` reads the network and returns an :class:`EditPlan` whose ``edits``
:meth:`~netstead.workbench.session.Session.mutate` applies all-or-nothing. A plan refuses (raises
:class:`EditRefused`) only what the network cannot hold:

* a value its column's storage type cannot hold: ``"fast"`` in a float column, or ``1.5`` in an integer
  column, which corral would otherwise silently widen to float;
* a column the table does not have (corral would add it), a key column, or a column whose type P2 cannot
  edit (geometry, binary, dates, times);
* a missing row, and deleting a node that a link still starts or ends at.

What the *spec* says about a value (required, enum, type, foreign keys, duplicate keys) is a warning, never
a refusal: see :mod:`netstead.workbench.editcheck`. Two kinds of callable appear below: a corral ``Edit``
predicate maps a table to a boolean column (:func:`_in`); a corral ``Table.filter`` argument maps a table
expression to a filtered one (:func:`_where`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from corral.editing import Edit

from netstead.viz.styling import json_scalar

from .related import ForeignKey, foreign_keys, primary_keys

__all__ = [
    "EditPlan",
    "EditRefused",
    "coerce_value",
    "editable",
    "plan_add",
    "plan_delete",
    "plan_update",
    "table_keys",
]

#: A deletion never cascades into these: a link that still uses a deleted node is refused instead.
_NETWORK_TABLES = ("link", "node")


class EditRefused(ValueError):
    """The edit cannot be applied as asked; the message says why (nothing was changed)."""


@dataclass
class EditPlan:
    """The corral edits for one request, rows per table it adds, changes or removes, its keys, and a summary.

    ``recheck`` lists keys the live checks should look at besides the rows the edits touch: the rows whose
    self-reference pointed at a deleted row.
    """

    edits: list[Edit]
    summary: str
    rows: dict[str, int] = field(default_factory=dict)
    keys: list[Any] = field(default_factory=list)  # the target table's keys, coerced to the key's type
    recheck: dict[str, list[Any]] = field(default_factory=dict)


def table_keys(net: Any) -> dict[str, str | None]:
    """Each table's single-column primary key, from the spec (``None`` when it has none)."""
    return primary_keys(net.spec, _columns(net))


def editable(dtype: Any) -> bool:
    """Whether P2 can edit a column of this ibis storage type (numbers, text, booleans).

    >>> import ibis.expr.datatypes as dt
    >>> editable(dt.float64), editable(dt.binary)
    (True, False)
    """
    return bool(
        dtype.is_boolean() or dtype.is_integer() or dtype.is_floating() or dtype.is_decimal() or dtype.is_string()
    )


def coerce_value(value: Any, dtype: Any, column: str) -> Any:
    """``value`` as ``column``'s ibis storage ``dtype``, or :class:`EditRefused`.

    ``None``, and empty text in a non-text column, clear the cell. Integers take integral numbers or text;
    floats take numbers or numeric text; text takes any scalar; booleans take ``true/false/1/0/yes/no``.

    >>> import ibis.expr.datatypes as dt
    >>> coerce_value("45", dt.float64, "free_speed"), coerce_value(2.0, dt.int64, "lanes")
    (45.0, 2)
    >>> coerce_value("", dt.int64, "lanes") is None
    True
    """
    if value is None or (isinstance(value, str) and not value.strip() and not dtype.is_string()):
        return None
    if not editable(dtype):
        raise EditRefused(f"{column} ({dtype}) cannot be edited yet")
    try:
        if dtype.is_boolean():
            text = str(value).strip().lower()
            if text in ("true", "1", "yes"):
                return True
            if text in ("false", "0", "no"):
                return False
            raise ValueError(value)
        if dtype.is_integer():
            if isinstance(value, int):
                return int(value)
            number = float(value)
            if not number.is_integer():
                raise ValueError(value)
            return int(number)
        if dtype.is_floating() or dtype.is_decimal():
            number = float(value)
            if math.isnan(number):
                raise ValueError(value)
            return number
        return str(value)
    except (TypeError, ValueError):
        raise EditRefused(f"{column} holds {dtype}; {value!r} does not fit it") from None


def plan_update(net: Any, table: str, ids: Sequence[Any], values: Mapping[str, Any]) -> EditPlan:
    """Set ``values`` (``{column: value}``; ``None`` clears) on the rows of ``table`` whose key is in ``ids``."""
    src, pk = _table(net, table)
    if not ids:
        raise EditRefused("give at least one row to edit")
    if not values:
        raise EditRefused("give at least one column to set")
    schema = src.expr.schema()
    sets: dict[str, Any] = {}
    for column, value in values.items():
        if column == pk:
            raise EditRefused(f"{column} is the {table} key; keys cannot be edited here (add a row with the new key)")
        if column not in schema:
            raise EditRefused(f"{table} has no column {column!r}")
        sets[column] = coerce_value(value, schema[column], column)
    keys = _keys(src, pk, ids)
    _require_present(src, pk, keys, table)
    edit = Edit(op="update_rows", table=table, payload={"predicate": _in(pk, keys), "set": sets})
    what = ", ".join(f"{c} = {_show(v)}" for c, v in sets.items())
    return EditPlan([edit], f"{table} {_few(keys)}: {what}", {table: len(keys)}, keys)


def plan_delete(net: Any, table: str, ids: Sequence[Any]) -> EditPlan:
    """Delete rows of ``table`` and, first, every row that depends on them through the spec's foreign keys.

    Dependents are found recursively (a link's lanes, then each lane's ``lane_tod`` rows), deepest first. A
    link or a node is never deleted as a dependent: deleting a node a link still uses is refused, naming the
    links. Self-references are not followed; the rows that pointed at a deleted row go in ``recheck``.
    """
    src, pk = _table(net, table)
    if not ids:
        raise EditRefused("give at least one row to delete")
    keys = _keys(src, pk, ids)
    _require_present(src, pk, keys, table)
    plan = EditPlan([], "", keys=keys)
    fks = foreign_keys(net.spec, _columns(net), self_refs=True)
    _cascade(net, fks, table_keys(net), table, pk, keys, plan, seen=frozenset({table}))
    plan.edits.append(Edit(op="delete_rows", table=table, payload={"predicate": _in(pk, keys)}))
    plan.rows[table] = len(keys)
    deps = ", ".join(f"{n} {t}" for t, n in plan.rows.items() if t != table)
    plan.summary = f"delete {table} {_few(keys)}" + (f" (and {deps} rows that depend on it)" if deps else "")
    return plan


def plan_add(net: Any, table: str, rows: Sequence[Mapping[str, Any]]) -> EditPlan:
    """Append ``rows`` to ``table``: every row needs its key; columns left out are empty (null).

    A key that is already taken is added anyway; the live checks report it as ``edit.duplicate_key``.
    """
    src, pk = _table(net, table)
    if not rows:
        raise EditRefused("give at least one row to add")
    schema = src.expr.schema()
    out = []
    for i, row in enumerate(rows, start=1):
        unknown = sorted(set(row) - set(schema))
        if unknown:
            raise EditRefused(f"row {i}: {table} has no column(s) {', '.join(unknown)}")
        if row.get(pk) is None:
            raise EditRefused(f"row {i}: every added {table} row needs its key, {pk}")
        out.append({c: coerce_value(v, schema[c], c) for c, v in row.items()})
    keys = [r[pk] for r in out]
    edit = Edit(op="add_rows", table=table, payload={"rows": out})
    return EditPlan([edit], f"add {table} {_few(keys)}", {table: len(out)}, keys)


# ---------------------------------------------------------------- helpers


def _columns(net: Any) -> dict[str, list[str]]:
    return {name: t.columns() for name, t in net.tables.items()}


def _few(ids: Sequence[Any], n: int = 5) -> str:
    items = list(ids)
    shown = ", ".join(str(i) for i in items[:n])
    return shown + (f" (+{len(items) - n} more)" if len(items) > n else "")


def _show(value: Any) -> str:
    return "empty" if value is None else repr(value)


def _in(column: str, values: Sequence[Any]) -> Callable[[Any], Any]:
    """A corral ``Edit`` predicate: the rows whose ``column`` is in ``values``."""
    frozen = list(values)
    return lambda t: t[column].isin(frozen)


def _where(column: str, values: Sequence[Any]) -> Callable[[Any], Any]:
    """A corral ``Table.filter`` transform: the same rows, as a filtered expression."""
    frozen = list(values)
    return lambda expr: expr.filter(expr[column].isin(frozen))


def _table(net: Any, name: str) -> tuple[Any, str]:
    src = net.tables.get(name)
    if src is None:
        raise EditRefused(f"the network has no {name} table")
    pk = table_keys(net).get(name)
    if pk is None:
        raise EditRefused(f"{name} has no single-column primary key, so its rows cannot be edited here")
    return src, pk


def _keys(src: Any, pk: str, ids: Sequence[Any]) -> list[Any]:
    dtype = src.expr.schema()[pk]
    return list(dict.fromkeys(coerce_value(i, dtype, pk) for i in ids))


def _values(src: Any, column: str, values: Sequence[Any], out: str) -> list[Any]:
    """``out`` of every row of ``src`` whose ``column`` is in ``values`` (one bounded DuckDB read)."""
    frame = src.filter(_where(column, values)).select(out).to_pandas()
    return [json_scalar(v) for v in frame[out]]


def _require_present(src: Any, pk: str, keys: list[Any], name: str) -> None:
    found = set(_values(src, pk, keys, pk))
    missing = [k for k in keys if k not in found]
    if missing:
        raise EditRefused(f"{name} {_few(missing)} not found")


def _cascade(
    net: Any,
    fks: list[ForeignKey],
    pks: Mapping[str, str | None],
    table: str,
    column: str,
    values: list[Any],
    plan: EditPlan,
    seen: frozenset[str],
) -> None:
    """Queue deletes (deepest first) for rows of other tables whose key points at ``table.column`` in ``values``."""
    for fk in fks:
        if fk.ref_table != table or fk.ref_column != column:
            continue
        own_pk = pks.get(fk.table)
        hits = _values(net.tables[fk.table], fk.column, values, own_pk or fk.column)
        if not hits:
            continue
        if fk.table == table:  # a self-reference: not followed; the rows that pointed here are re-checked
            gone = set(values)
            plan.recheck.setdefault(table, []).extend(h for h in hits if h not in gone)
            continue
        if fk.table in _NETWORK_TABLES:
            raise EditRefused(
                f"{table} {_few(values)} is still used by {fk.table}.{fk.column} ({fk.table} {_few(hits)}); "
                f"delete those {fk.table}s first"
            )
        if fk.table in seen:  # a cycle through the spec's keys: stop
            continue
        if own_pk:
            _cascade(net, fks, pks, fk.table, own_pk, hits, plan, seen | {fk.table})
        plan.edits.append(Edit(op="delete_rows", table=fk.table, payload={"predicate": _in(fk.column, values)}))
        plan.rows[fk.table] = plan.rows.get(fk.table, 0) + len(hits)
```

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_editing.py packages/netstead/tests/test_workbench_related.py packages/netstead/tests/test_workbench_related_routes.py -q`
Expected: all pass. (The Task 3 code ran as a prototype against Leavenworth on `main`; see the honesty note.)

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass; the two doctests run.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/workbench/editing.py packages/netstead/netstead/workbench/related.py packages/netstead/tests/test_workbench_editing.py packages/netstead/tests/test_workbench_related.py
git commit -m "feat(workbench): edit planning (cells, cascading deletes, additions) refuses only what storage cannot hold"
```

---

### Task 4: Live edit checks (`workbench/editcheck.py`)

**Files:**
- Create: `packages/netstead/netstead/workbench/editcheck.py`
- Test: `packages/netstead/tests/test_workbench_editcheck.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_editcheck.py`:

```python
"""Live checks: what the spec says about rows an edit touched (warnings, never refusals)."""

import pytest
from corral.editing import Edit
from corral.editing.apply import apply_edit
from netstead import Network
from netstead.fixtures import leavenworth
from netstead.workbench import editcheck
from netstead.workbench.editcheck import check_rows, fits_type, touched_keys
from netstead.workbench.editing import plan_add, plan_delete, plan_update, table_keys


@pytest.fixture
def net():
    return Network.from_source(leavenworth.parquet_dir())


def apply(net, plan):
    return [apply_edit(net, e) for e in plan.edits]


def codes(net, touched):
    return sorted((w.code, w.table, w.key, w.column) for w in check_rows(net, touched).warnings)


def test_leavenworth_rows_start_clean(net):
    keys = net.tables["link"].select("link_id").to_pandas()["link_id"].tolist()
    assert check_rows(net, {"link": keys}).warnings == ()


def test_a_clean_edit_has_no_warnings(net):
    apply(net, plan_update(net, "link", [1], {"free_speed": 30}))
    assert codes(net, {"link": [1]}) == []


def test_a_value_outside_the_enum(net):
    apply(net, plan_update(net, "node", [1], {"ctrl_type": "bogus"}))
    (w,) = check_rows(net, {"node": [1]}).warnings
    assert (w.code, w.column, w.value) == ("edit.enum", "ctrl_type", "bogus") and "not one of" in w.message


def test_a_missing_foreign_key_and_an_empty_required_field(net):
    apply(net, plan_update(net, "link", [1], {"from_node_id": 424242, "directed": None}))
    assert codes(net, {"link": [1]}) == [
        ("edit.fk_missing", "link", 1, "from_node_id"),
        ("edit.required_empty", "link", 1, "directed"),
    ]


def test_fixing_the_foreign_key_clears_its_warning(net):
    apply(net, plan_update(net, "link", [1], {"from_node_id": 424242}))
    apply(net, plan_add(net, "node", [{"node_id": 424242, "x_coord": -120.66, "y_coord": 47.6}]))
    assert codes(net, {"link": [1], "node": [424242]}) == []


def test_a_duplicate_key(net):
    apply(net, plan_add(net, "link", [{"link_id": 1, "from_node_id": 1, "to_node_id": 2, "directed": False}]))
    assert ("edit.duplicate_key", "link", 1, "link_id") in codes(net, {"link": [1]})


def test_a_value_the_spec_type_cannot_hold(net):
    # A plugin's raw corral edit can widen an integer column to float (the planner would refuse 2.5).
    apply_edit(net, Edit(op="update_rows", table="link", payload={"predicate": lambda t: t.link_id == 1, "set": {"lanes": 2.5}}))
    assert ("edit.type", "link", 1, "lanes") in codes(net, {"link": [1]})


@pytest.mark.parametrize(
    ("value", "spec_type", "fits"),
    [(2, "integer", True), (2.0, "integer", True), (2.5, "integer", False), ("2", "number", False),
     (True, "number", False), (1, "boolean", True), ("x", "string", True), (3, "string", False), ("x", "any", True)],
)
def test_fits_type(value, spec_type, fits):
    assert fits_type(value, spec_type) is fits


def test_rows_that_no_longer_exist_are_skipped(net):
    apply(net, plan_delete(net, "link", [1]))
    assert codes(net, {"link": [1]}) == []


def test_touched_keys_reads_updates_and_additions_not_deletions(net):
    results = apply(net, plan_update(net, "link", [1, 2], {"lanes": 2}))
    results += apply(net, plan_add(net, "node", [{"node_id": 9001, "x_coord": 0.0, "y_coord": 0.0}]))
    results += apply(net, plan_delete(net, "link", [3]))
    assert touched_keys(results, table_keys(net)) == {"link": {1, 2}, "node": {9001}}


def test_the_check_is_bounded(net, monkeypatch):
    monkeypatch.setattr(editcheck, "MAX_CHECKED_KEYS", 1)
    result = check_rows(net, {"link": [1, 2]})
    assert result.truncated is True and result.warnings == ()


def test_warnings_for_some_rows(net):
    apply(net, plan_update(net, "node", [1, 2], {"ctrl_type": "bogus"}))
    result = check_rows(net, {"node": [1, 2]})
    assert [w.key for w in result.for_rows({"node": {2}})] == [2]
    assert result.to_dict()["warnings"][0]["code"] == "edit.enum"
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_editcheck.py -q`
Expected: FAIL with `ImportError: cannot import name 'editcheck'`.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/workbench/editcheck.py`:

```python
"""Live checks for edited rows: what the spec says about the values an edit left behind (warn, never block).

After every mutation the session re-checks the rows its pending edits have touched, by primary key:

* ``edit.required_empty``: a required field is empty;
* ``edit.type``: a value the column stores but the spec's type cannot hold (``2.5`` for an ``integer``
  field whose column was widened to float; text in a ``number`` field stored as text);
* ``edit.enum``: a value outside the field's ``enum``;
* ``edit.fk_missing``: a foreign-key value the referenced table does not have (self-references included);
* ``edit.duplicate_key``: another row has the same primary key.

Each check reads only the touched rows (an ibis ``IN`` filter) and the referenced keys it needs, so it is
bounded by the edit, not by the network; at most :data:`MAX_CHECKED_KEYS` keys per table are checked. A
whole row is checked, not just the edited cells: a row is what the spec constrains.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd
from corral.editing import EditResult, affected_rows

from netstead.viz.styling import json_scalar

from .editing import table_keys
from .related import _schemas, foreign_keys

__all__ = ["MAX_CHECKED_KEYS", "CheckResult", "EditWarning", "check_rows", "fits_type", "touched_keys"]

#: Keys checked per table after one mutation; beyond this the result says ``truncated``.
MAX_CHECKED_KEYS = 10_000


@dataclass(frozen=True)
class EditWarning:
    """One thing the spec says is wrong with an edited row (shown on its cell, its row and the Issues tab)."""

    code: str
    table: str
    key: Any
    column: str | None
    value: Any
    message: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return asdict(self)


@dataclass(frozen=True)
class CheckResult:
    """The warnings for a set of touched rows, and whether :data:`MAX_CHECKED_KEYS` cut the check short."""

    warnings: tuple[EditWarning, ...] = ()
    truncated: bool = False

    def for_rows(self, touched: Mapping[str, Iterable[Any]]) -> list[EditWarning]:
        """The warnings on the rows in ``touched`` (``{table: keys}``)."""
        wanted = {(t, k) for t, keys in touched.items() for k in keys}
        return [w for w in self.warnings if (w.table, w.key) in wanted]

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return {"warnings": [w.to_dict() for w in self.warnings], "truncated": self.truncated}


def fits_type(value: Any, spec_type: str | None) -> bool:
    """Whether a non-null ``value`` is what the spec's Frictionless ``type`` says (``any`` and others: yes).

    >>> fits_type(2.0, "integer"), fits_type(2.5, "integer"), fits_type(True, "number")
    (True, False, False)
    """
    if spec_type == "integer":
        integral = isinstance(value, float) and value.is_integer()
        return (isinstance(value, int) and not isinstance(value, bool)) or integral
    if spec_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if spec_type == "boolean":
        return isinstance(value, bool) or value in (0, 1)
    if spec_type == "string":
        return isinstance(value, str)
    return True


def touched_keys(results: Sequence[EditResult], pks: Mapping[str, str | None]) -> dict[str, set[Any]]:
    """``{table: keys}`` of the rows ``results`` changed or added. Deleted rows are gone, so they are not listed."""
    out: dict[str, set[Any]] = {}
    for result in results:
        pk = pks.get(result.edit.table)
        if pk is None or result.edit.op == "delete_rows":
            continue
        for row in affected_rows(result):
            if row.get(pk) is not None:
                out.setdefault(result.edit.table, set()).add(json_scalar(row[pk]))
    return out


def check_rows(net: Any, touched: Mapping[str, Iterable[Any]]) -> CheckResult:
    """Check the rows in ``touched`` (``{table: keys}``) that still exist; tables without a key are skipped."""
    pks = table_keys(net)
    schemas = _schemas(net.spec)
    fks = foreign_keys(net.spec, {n: t.columns() for n, t in net.tables.items()}, self_refs=True)
    found: list[EditWarning] = []
    truncated = False
    for table, wanted in touched.items():
        src, pk = net.tables.get(table), pks.get(table)
        keys = sorted(set(wanted), key=str)
        if src is None or pk is None or not keys:
            continue
        if len(keys) > MAX_CHECKED_KEYS:  # check the first ones; Run validation covers the rest
            keys, truncated = keys[:MAX_CHECKED_KEYS], True
        frame = src.filter(_where(pk, keys)).to_pandas()
        if frame.empty:
            continue
        rows = [{c: _plain(v) for c, v in r.items()} for r in frame.to_dict("records")]
        fields = {f.name: f for f in schemas[table].fields} if table in schemas else {}
        found += _field_checks(table, pk, rows, fields)
        found += _duplicate_keys(table, pk, src, keys)
        found += _fk_checks(net, table, pk, rows, [fk for fk in fks if fk.table == table])
    return CheckResult(tuple(found), truncated)


# ---------------------------------------------------------------- helpers


def _where(column: str, values: Sequence[Any]) -> Any:
    frozen = list(values)
    return lambda expr: expr.filter(expr[column].isin(frozen))


def _plain(value: Any) -> Any:
    """A pandas cell as a plain Python value (NA -> None)."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):  # a list or array cell: not a scalar NA
        pass
    return json_scalar(value)


def _few(values: Sequence[Any], n: int = 5) -> str:
    shown = ", ".join(str(v) for v in values[:n])
    return shown + (f" (+{len(values) - n} more)" if len(values) > n else "")


def _field_checks(table: str, pk: str, rows: list[dict[str, Any]], fields: Mapping[str, Any]) -> list[EditWarning]:
    out = []
    for row in rows:
        key = row[pk]
        for name, spec_field in fields.items():
            if name not in row:
                continue
            value, c = row[name], spec_field.constraints
            if value is None:
                if c is not None and c.required:
                    msg = f"{table} {key}: {name} is required but empty"
                    out.append(EditWarning("edit.required_empty", table, key, name, None, msg))
                continue
            if not fits_type(value, spec_field.type):
                msg = f"{table} {key}: {name} is {spec_field.type} in the spec; {value!r} is not"
                out.append(EditWarning("edit.type", table, key, name, value, msg))
            elif c is not None and c.enum and value not in c.enum:
                msg = f"{table} {key}: {name} {value!r} is not one of {_few(c.enum)}"
                out.append(EditWarning("edit.enum", table, key, name, value, msg))
    return out


def _duplicate_keys(table: str, pk: str, src: Any, keys: list[Any]) -> list[EditWarning]:
    counts = src.filter(_where(pk, keys)).select(pk).to_pandas()[pk].map(json_scalar).value_counts()
    return [
        EditWarning("edit.duplicate_key", table, k, pk, k, f"{table} {k}: {n} rows have this {pk}")
        for k, n in counts.items()
        if n > 1
    ]


def _fk_checks(net: Any, table: str, pk: str, rows: list[dict[str, Any]], fks: list[Any]) -> list[EditWarning]:
    out = []
    for fk in fks:
        values = sorted({r[fk.column] for r in rows if r.get(fk.column) is not None}, key=str)
        if not values:
            continue
        ref = net.tables[fk.ref_table].filter(_where(fk.ref_column, values)).select(fk.ref_column).to_pandas()
        present = {json_scalar(v) for v in ref[fk.ref_column]}
        for r in rows:
            value = r.get(fk.column)
            if value is not None and value not in present:
                msg = f"{table} {r[pk]}: {fk.column} {value!r} is not a {fk.ref_table}.{fk.ref_column}"
                out.append(EditWarning("edit.fk_missing", table, r[pk], fk.column, value, msg))
    return out
```

`_schemas` is `related.py`'s private reader of the spec's table schemas; importing it keeps one reading of the spec.
If ruff flags the private import, make it public there as `table_schemas` (keeping `_schemas` as an alias).

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_editcheck.py packages/netstead/tests/test_workbench_editing.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench/editcheck.py packages/netstead/tests/test_workbench_editcheck.py
git commit -m "feat(workbench): live edit checks (required, type, enum, foreign key, duplicate key) on touched rows"
```

---

### Task 5: Pending edits, live re-checks and undo in `Session.mutate`; Host API 1.1

Part 1's `Session.mutate` applies corral edits all-or-nothing, bumps the version, appends to the lineage and
publishes `state`. This task makes every mutation visible and reversible: it becomes a `PendingEdit` in the
network's `EditLedger`, the live checks re-run over every key the ledger has touched, and `Session.undo_last`
reverses the newest entry. `Host` passes its plugin id as the source and gains `undo`, `edit_warnings` and
`plan_*` (`HOST_API` 1.0 → 1.1, additive).

**Files:**
- Create: `packages/netstead/netstead/workbench/ledger.py`
- Modify: `packages/netstead/netstead/workbench/session.py`
- Modify: `packages/netstead/netstead/workbench/plugins/host.py`, `plugins/spec.py`, `plugins/__init__.py`
- Modify: `packages/netstead/docs/cookbook/workbench-plugins.md` (Part 1's authoring guide)
- Test: `packages/netstead/tests/test_workbench_edits.py` (new), `packages/netstead/tests/test_workbench_plugins.py`

- [ ] **Step 1: Check Part 1's names**

Run: `grep -n "def mutate\|def derive\|class Host\|def writable\|HOST_API" packages/netstead/netstead/workbench/session.py packages/netstead/netstead/workbench/plugins/*.py`
Expected: `Session.mutate(self, net_id, edits, *, note)`, `Session.derive`, `Host.mutate`, `Host.writable` and
`HOST_API = "1.0"`, as in Part 1 Tasks 8–9. If a signature differs, adapt the snippets below to it, not the other way
round.

- [ ] **Step 2: Write the failing tests**

Create `packages/netstead/tests/test_workbench_edits.py`:

```python
"""Pending edits: every mutation is recorded, re-checked live, undone last-first, and shown as dirty state."""

import pytest
from corral.editing import Edit, UnsupportedEditOp
from netstead.fixtures import leavenworth
from netstead.select.parse import StubParser
from netstead.workbench import Session
from netstead.workbench.actions import CloseNetwork, OpenNetwork
from netstead.workbench.editing import plan_add, plan_update
from netstead.workbench.errors import ActionError

SRC = str(leavenworth.parquet_dir())


@pytest.fixture
def session(tmp_path, isolated_env):
    s = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), plugins=[])
    s.dispatch(OpenNetwork(source=SRC))
    return s


def handle(s):
    return s.registry.get("leavenworth")


def cell(s, link_id, column="free_speed"):
    df = handle(s).links_df()
    return df.loc[df.link_id == link_id, column].tolist()


def mutate(s, plan, **kwargs):
    return s.mutate("leavenworth", plan.edits, note=plan.summary, **kwargs)


def test_a_mutation_is_a_pending_edit(session):
    mutate(session, plan_update(handle(session).roadway, "link", [1], {"free_speed": 30}))
    (entry,) = session.edits["leavenworth"].entries
    assert (entry.seq, entry.source, entry.version, entry.touched) == (1, "workbench", 1, {"link": {1}})
    assert entry.view()["rows"] == {"link": 1}
    assert session.state()["edits"]["leavenworth"] == {
        "pending": 1, "unsaved": 1, "dirty": True, "warnings": 0, "truncated": False, "last_source": "workbench",
    }


def test_live_warnings_follow_later_edits(session):
    net = handle(session).roadway
    mutate(session, plan_update(net, "link", [1], {"from_node_id": 424242}))
    assert [w.code for w in session.edit_check("leavenworth").warnings] == ["edit.fk_missing"]
    mutate(session, plan_add(net, "node", [{"node_id": 424242, "x_coord": -120.66, "y_coord": 47.6}]))
    assert session.edit_check("leavenworth").warnings == ()  # the second edit fixed the first one's key


def test_undo_reverses_the_last_edit_only(session):
    h = handle(session)
    mutate(session, plan_update(h.roadway, "link", [1], {"free_speed": 30}))
    mutate(session, plan_update(h.roadway, "link", [1], {"free_speed": 25}))
    undone = session.undo_last("leavenworth")
    assert undone.seq == 2 and cell(session, 1) == [30.0] and h.version == 3
    assert h.lineage[-1] == "undo: link 1: free_speed = 25.0"
    session.undo_last("leavenworth")
    assert cell(session, 1) == [40.0] and session.edits["leavenworth"].entries == []
    with pytest.raises(ActionError, match="nothing to undo"):
        session.undo_last("leavenworth")


def test_undo_restores_a_row_that_holds_nulls(tmp_path, isolated_env):
    s = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), plugins=[])
    s.dispatch(OpenNetwork(source=str(leavenworth.csv_dir())))
    h = s.registry.get(s.active)
    s.mutate(h.id, plan_update(h.roadway, "link", [27], {"lanes": 3}).edits, note="lanes")  # link 27's name is null
    s.undo_last(h.id)
    assert int((h.links_df().link_id == 27).sum()) == 1  # Task 1: not two copies


def test_core_does_not_undo_a_plugins_change(session):
    mutate(session, plan_update(handle(session).roadway, "link", [1], {"lanes": 2}), source="cards")
    with pytest.raises(ActionError, match="made by cards"):
        session.undo_last("leavenworth")
    assert session.undo_last("leavenworth", source="cards").source == "cards"


def test_a_failed_mutation_records_nothing(session):
    h = handle(session)
    good = plan_update(h.roadway, "link", [1], {"lanes": 2}).edits
    with pytest.raises(UnsupportedEditOp):
        session.mutate("leavenworth", [*good, Edit(op="explode", table="link")], note="bad")
    assert "leavenworth" not in session.edits and h.version == 0 and cell(session, 1, "lanes") == [1]


def test_saving_and_undoing_a_saved_edit(session):
    mutate(session, plan_update(handle(session).roadway, "link", [1], {"lanes": 2}))
    ledger = session.edits["leavenworth"]
    ledger.mark_saved()
    assert ledger.summary()["dirty"] is False and ledger.summary()["unsaved"] == 0
    session.undo_last("leavenworth")
    assert ledger.summary()["dirty"] is True  # the open network no longer matches the saved copy


def test_closing_the_network_drops_its_edits(session):
    mutate(session, plan_update(handle(session).roadway, "link", [1], {"lanes": 2}))
    session.dispatch(CloseNetwork(net_id="leavenworth"))
    assert session.edits == {} and "leavenworth" not in session.state()["edits"]
```

Append to `packages/netstead/tests/test_workbench_plugins.py` (it already imports `ClassVar`, `Literal`,
`BaseAction`, `ActionSpec`, `WorkbenchPlugin` and defines `make_session`):

```python
class Retag(BaseAction):
    type: Literal["tagger.retag"] = "tagger.retag"
    mutates: ClassVar[bool] = True
    link_id: int


def test_host_1_1_plans_mutates_reports_and_undoes(make_session):
    from netstead.fixtures import leavenworth
    from netstead.workbench.actions import OpenNetwork
    from netstead.workbench.plugins import EditRefused

    def retag(host, action: Retag) -> list[str]:
        plan = host.plan_update(None, "link", [action.link_id], {"from_node_id": 424242})
        host.mutate(None, plan.edits, note=plan.summary)
        return [w["code"] for w in host.edit_warnings()]

    tagger = WorkbenchPlugin(
        id="tagger", name="Tagger", version="0.1", requires_api="1.1", actions=(ActionSpec(Retag, retag),)
    )
    session = make_session(tagger)
    session.dispatch(OpenNetwork(source=str(leavenworth.parquet_dir())))
    assert session.dispatch(Retag(link_id=1)) == ["edit.fk_missing"]
    assert session.edits["leavenworth"].entries[-1].source == "tagger"
    host = session._hosts["tagger"]
    assert host.undo()["source"] == "tagger" and host.edit_warnings() == []
    with pytest.raises(EditRefused, match="does not fit"):
        host.plan_update(None, "link", [1], {"lanes": 1.5})


def test_host_api_is_1_1():
    assert HOST_API == "1.1"
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py packages/netstead/tests/test_workbench_plugins.py -q -k "edit or host_1_1 or host_api or mutation or undo or saving or closing"`
Expected: FAIL: `AttributeError: 'Session' object has no attribute 'edits'`, then `ImportError: EditRefused`.

- [ ] **Step 4: `workbench/ledger.py`**

```python
"""Pending edits: every mutation of an open network, kept until it is closed.

The Edits tab lists them, :meth:`~netstead.workbench.session.Session.undo_last` reverses the newest, and the
dirty badge counts the ones no saved copy holds yet. Each entry records who made it (``source``: the
Workbench, or a plugin's id) so an undo never reverses someone else's change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from corral.editing import EditResult

from .editcheck import CheckResult

__all__ = ["CORE_SOURCE", "EditLedger", "PendingEdit"]

#: The source of edits made by the Workbench itself (plugins use their id).
CORE_SOURCE = "workbench"


@dataclass
class PendingEdit:
    """One applied mutation: who made it, why, the version it produced, and the corral results that undo it."""

    seq: int
    source: str
    note: str
    version: int
    results: list[EditResult] = field(repr=False)
    touched: dict[str, set[Any]] = field(default_factory=dict)
    saved: bool = False

    def view(self) -> dict[str, Any]:
        """JSON-safe: what the Edits tab shows (rows per table counts added, removed and changed rows)."""
        rows: dict[str, int] = {}
        for r in self.results:
            n = r.diff.rows_added + r.diff.rows_removed + r.diff.rows_changed
            rows[r.edit.table] = rows.get(r.edit.table, 0) + n
        return {
            "seq": self.seq,
            "source": self.source,
            "note": self.note,
            "version": self.version,
            "rows": rows,
            "saved": self.saved,
        }


class EditLedger:
    """One network's pending edits (newest last) and the live check over every key they touched."""

    def __init__(self) -> None:
        """Start empty."""
        self.entries: list[PendingEdit] = []
        self.check = CheckResult()
        self.diverged = False  # an undo reversed a saved edit: the open network differs from the saved copy
        self._seq = 0

    def add(
        self, source: str, note: str, version: int, results: list[EditResult], touched: dict[str, set[Any]]
    ) -> PendingEdit:
        """Record one applied mutation and return it."""
        self._seq += 1
        entry = PendingEdit(self._seq, source, note, version, list(results), touched)
        self.entries.append(entry)
        return entry

    def last(self) -> PendingEdit | None:
        """The newest entry (``None`` when there is none)."""
        return self.entries[-1] if self.entries else None

    def pop(self) -> PendingEdit:
        """Drop the newest entry (after its edits were reversed) and return it."""
        entry = self.entries.pop()
        if entry.saved:
            self.diverged = True
        return entry

    def touched(self) -> dict[str, set[Any]]:
        """Every key any pending entry touched: what the live check covers."""
        out: dict[str, set[Any]] = {}
        for entry in self.entries:
            for table, keys in entry.touched.items():
                out.setdefault(table, set()).update(keys)
        return out

    def mark_saved(self) -> None:
        """A copy holding every pending edit was written."""
        for entry in self.entries:
            entry.saved = True
        self.diverged = False

    def summary(self) -> dict[str, Any]:
        """JSON-safe counts for the session state (the dirty badge reads ``dirty`` and ``unsaved``)."""
        unsaved = sum(not e.saved for e in self.entries)
        last = self.last()
        return {
            "pending": len(self.entries),
            "unsaved": unsaved,
            "dirty": bool(unsaved or self.diverged),
            "warnings": len(self.check.warnings),
            "truncated": self.check.truncated,
            "last_source": last.source if last else None,
        }
```

- [ ] **Step 5: The session**

In `packages/netstead/netstead/workbench/session.py`:

1. Imports: `from .editcheck import CheckResult, check_rows, touched_keys`, `from .editing import table_keys`,
   `from .ledger import CORE_SOURCE, EditLedger, PendingEdit`.
2. In `__init__`, after `self.history`: `self.edits: dict[str, EditLedger] = {}  # net_id -> its pending edits`.
3. Replace Part 1's `mutate` with:

```python
    def mutate(
        self,
        net_id: str | None,
        edits: Sequence[Edit],
        *,
        note: str,
        source: str = CORE_SOURCE,
        recheck: Mapping[str, Sequence[Any]] | None = None,
    ) -> list[EditResult]:
        """Apply corral ``edits`` to a network's roadway, in order and all-or-nothing; return their results.

        A failing edit reverses the ones already applied and re-raises; nothing is recorded. On success the
        network's ``version`` is bumped (dropping its caches), ``note`` is appended to its lineage, the
        mutation becomes a :class:`~netstead.workbench.ledger.PendingEdit` from ``source`` (the Workbench, or
        a plugin's id), the live checks re-run (``recheck`` adds keys beyond the touched rows), and ``state``
        is published. Not an Action itself: the Action that calls it is what history records.
        """
        with self._lock:
            handle = self._handle(net_id)
            applied: list[EditResult] = []
            try:
                for edit in edits:
                    applied.append(apply_edit(handle.roadway, edit))
            except Exception:
                for result in reversed(applied):
                    reverse_edit(handle.roadway, result)
                raise
            handle.bump()
            handle.lineage.append(note)
            touched = touched_keys(applied, table_keys(handle.roadway))
            for table, keys in (recheck or {}).items():
                touched.setdefault(table, set()).update(keys)
            ledger = self.edits.setdefault(handle.id, EditLedger())
            ledger.add(source, note, handle.version, applied, touched)
            self._recheck(handle, ledger)
            self.events.publish({"type": "state", "state": self.state()})
        return applied

    def undo_last(self, net_id: str | None, *, source: str = CORE_SOURCE) -> PendingEdit:
        """Reverse the network's newest pending edit, if ``source`` made it; return the entry undone.

        Raises :class:`ActionError` when there is nothing to undo, or when the newest change came from
        another source (core never undoes a plugin's change, nor a plugin core's).
        """
        with self._lock:
            handle = self._handle(net_id)
            ledger = self.edits.get(handle.id)
            last = ledger.last() if ledger else None
            if ledger is None or last is None:
                raise ActionError(f"nothing to undo on {handle.id}")
            if last.source != source:
                who = "the Workbench" if last.source == CORE_SOURCE else last.source
                raise ActionError(f"the last change to {handle.id} was made by {who} ({last.note}); undo it there")
            for result in reversed(last.results):
                reverse_edit(handle.roadway, result)
            ledger.pop()
            handle.bump()
            handle.lineage.append(f"undo: {last.note}")
            self._recheck(handle, ledger)
            self.events.publish({"type": "state", "state": self.state()})
        return last

    def edit_check(self, net_id: str | None) -> CheckResult:
        """The live edit warnings on a network now (empty before any edit)."""
        with self._lock:
            ledger = self.edits.get(self._handle(net_id).id)
            return ledger.check if ledger else CheckResult()

    def _recheck(self, handle: NetworkHandle, ledger: EditLedger) -> None:
        """Re-run the live checks over every key the ledger touched (call with the lock held)."""
        try:
            ledger.check = check_rows(handle.roadway, ledger.touched())
        except Exception:  # boundary: a failing check must not undo a good edit; Run validation still works
            logger.exception("live edit check on %s failed", handle.id)
            ledger.check = CheckResult(truncated=True)
```

   Add `Any` to the typing import and `Mapping` to `collections.abc` if Part 1 did not. Place `undo_last` and
   `edit_check` with the public API methods (after `derive`), and `_recheck` with the private helpers.
4. In `state()`, add `"edits": {nid: ledger.summary() for nid, ledger in self.edits.items()},`.
5. In `_do_close_network`, after the examples line: `self.edits.pop(action.net_id, None)`.

- [ ] **Step 6: Host 1.1**

In `plugins/spec.py`, set `HOST_API = "1.1"` and extend its comment: `1.1 adds Host.undo, Host.edit_warnings and
Host.plan_update/plan_delete/plan_add, and records the plugin as the source of its mutations.`

In `plugins/host.py`:
- import `from ..editing import EditPlan, plan_add, plan_delete, plan_update` (outside `TYPE_CHECKING`);
- change `mutate` to pass the source:

```python
    def mutate(self, net_id: str | None, edits: Sequence[Edit], *, note: str) -> list[EditResult]:
        """Apply corral edits all-or-nothing; lineage gets ``"<plugin id>: <note>"``; the pending edit is ours."""
        return self._session.mutate(net_id, edits, note=f"{self.plugin_id}: {note}", source=self.plugin_id)
```

- add after `derive`:

```python
    def undo(self, net_id: str | None = None) -> dict[str, Any]:
        """Reverse this plugin's newest mutation of a network, if it is the network's newest change.

        Raises ``ActionError`` when the newest change came from core or another plugin. Returns the undone
        entry's view (``seq``, ``source``, ``note``, ``version``, ``rows``).
        """
        return self._session.undo_last(net_id, source=self.plugin_id).view()

    def edit_warnings(self, net_id: str | None = None) -> list[dict[str, Any]]:
        """The live edit warnings on a network now, from every source: show them before committing anything."""
        return [w.to_dict() for w in self._session.edit_check(net_id).warnings]

    def plan_update(self, net_id: str | None, table: str, ids: Sequence[Any], values: dict[str, Any]) -> EditPlan:
        """Core's plan for setting cells (raises ``EditRefused`` for what storage cannot hold). Apply it with ``mutate``."""
        return plan_update(self.network(net_id).roadway, table, ids, values)

    def plan_delete(self, net_id: str | None, table: str, ids: Sequence[Any]) -> EditPlan:
        """Core's plan for deleting rows and their dependents (``plan.rows`` says what goes)."""
        return plan_delete(self.network(net_id).roadway, table, ids)

    def plan_add(self, net_id: str | None, table: str, rows: Sequence[dict[str, Any]]) -> EditPlan:
        """Core's plan for adding rows."""
        return plan_add(self.network(net_id).roadway, table, rows)
```

A plan reads the network, so call `mutate` with it before anything else changes the network (a handler runs under
the session lock, so inside one handler that holds).

In `plugins/__init__.py`, add `from ..editing import EditPlan, EditRefused` and put both names in `__all__`.

In `packages/netstead/docs/cookbook/workbench-plugins.md`, add a short section "Editing networks (API 1.1)": plan
with `host.plan_*`, apply with `host.mutate(net_id, plan.edits, note=plan.summary)`, read `host.edit_warnings()`
before committing anything to disk, and undo your own newest change with `host.undo()`. Say that core shows every
plugin mutation in its Edits tab with the plugin's id, and never undoes it.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py packages/netstead/tests/test_workbench_plugins.py packages/netstead/tests/test_workbench_session.py -q`
Expected: all pass. Part 1's `test_mutate_*` tests still pass: `source` and `recheck` default.

- [ ] **Step 8: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add packages/netstead/netstead/workbench/ledger.py packages/netstead/netstead/workbench/session.py packages/netstead/netstead/workbench/plugins packages/netstead/docs/cookbook/workbench-plugins.md packages/netstead/tests/test_workbench_edits.py packages/netstead/tests/test_workbench_plugins.py
git commit -m "feat(workbench): pending edits with live re-checks and source-checked undo; Host API 1.1"
```

---

### Task 6: Edit Actions: `EditCells`, `DeleteRows`, `AddRows`, `UndoEdit`

Each is a core Action on Part 1's registry (appended to `CORE_ACTIONS`; the closed `Action` union is not touched).
Its handler plans with Task 3, applies through `Session.mutate` (Task 5), and returns the plan's summary, the rows
it touched, and the live warnings on those rows.

**Files:**
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py`
- Test: `packages/netstead/tests/test_workbench_edits.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_edits.py`, and extend its actions import to
`from netstead.workbench.actions import AddRows, CloseNetwork, DeleteRows, EditCells, OpenNetwork, Select, UndoEdit`
plus `from netstead.workbench.errors import ActionError, NotSupportedYet`:

```python
def test_a_cell_edit_is_one_recorded_action(session):
    result = session.dispatch(EditCells(ids=[1], values={"free_speed": 30}, note="signed 30 mph"))
    assert cell(session, 1) == [30.0] and result["version"] == 1 and result["warnings"] == []
    assert result["summary"] == "link 1: free_speed = 30.0" and result["rows"] == {"link": 1} and result["keys"] == [1]
    entry = session.history[-1]
    assert entry.python == "app.do(EditCells(ids=[1], values={'free_speed': 30}, note='signed 30 mph'))"
    assert entry.imports == "from netstead.workbench import EditCells"
    assert handle(session).lineage == ["link 1: free_speed = 30.0 (signed 30 mph)"]


def test_an_edit_the_spec_disagrees_with_is_applied_and_warned(session):
    result = session.dispatch(EditCells(table="node", ids=[1], values={"ctrl_type": "bogus"}))
    assert [w["code"] for w in result["warnings"]] == ["edit.enum"] and result["open_warnings"] == 1
    assert session.state()["edits"]["leavenworth"]["warnings"] == 1


def test_what_storage_cannot_hold_is_refused_and_recorded(session):
    with pytest.raises(ActionError, match="does not fit"):
        session.dispatch(EditCells(ids=[1], values={"lanes": 1.5}))
    assert not session.history[-1].ok and handle(session).version == 0 and "leavenworth" not in session.edits


def test_delete_a_link_then_undo(session):
    lanes = handle(session).roadway.tables["lane"].count()
    result = session.dispatch(DeleteRows(ids=[1]))
    assert result["rows"] == {"lane": 1, "link": 1} and 1 not in set(handle(session).links_df().link_id)
    session.dispatch(UndoEdit())
    assert 1 in set(handle(session).links_df().link_id) and handle(session).roadway.tables["lane"].count() == lanes
    assert [e.action["type"] for e in session.history[-2:]] == ["delete_rows", "undo_edit"]


def test_deleting_a_node_a_link_uses_is_refused(session):
    with pytest.raises(ActionError, match="still used by link"):
        session.dispatch(DeleteRows(table="node", ids=[1]))


def test_deleting_a_selected_link_clears_the_selection(session):
    session.dispatch(Select(link_ids=[1, 2]))
    session.dispatch(DeleteRows(ids=[1]))
    assert session.selection is None


def test_add_rows_from_python(session):
    node = {"node_id": 9001, "x_coord": -120.66, "y_coord": 47.6}
    link = {"link_id": 9001, "from_node_id": 1, "to_node_id": 9001, "directed": False, "name": "New Street"}
    session.dispatch(AddRows(table="node", rows=[node]))
    result = session.dispatch(AddRows(table="link", rows=[link]))
    assert result["warnings"] == [] and cell(session, 9001, "name") == ["New Street"]


def test_undo_with_nothing_is_a_recorded_failure(session):
    with pytest.raises(ActionError, match="nothing to undo"):
        session.dispatch(UndoEdit())
    assert not session.history[-1].ok


def test_transit_edits_are_not_supported_yet(session):
    with pytest.raises(NotSupportedYet):
        session.dispatch(EditCells(component="transit", ids=[1], values={"lanes": 2}))


@pytest.mark.parametrize(
    "bad",
    [{"type": "edit_cells", "ids": [], "values": {"lanes": 2}}, {"type": "edit_cells", "ids": [1], "values": {}},
     {"type": "add_rows", "table": "link", "rows": []}],
)
def test_empty_requests_fail_validation(session, bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        session.actions.parse(bad)


def test_a_replayed_history_reproduces_the_edits(session, tmp_path):
    session.dispatch(EditCells(ids=[1], values={"free_speed": 30}))
    session.dispatch(EditCells(ids=[2], values={"lanes": 2}))
    session.dispatch(UndoEdit())
    other = Session(project_dir=tmp_path, environ=session._environ, parser=StubParser(), plugins=[])
    namespace = {"app": other}
    for entry in session.history:
        exec(entry.imports, namespace)  # noqa: S102  (replaying our own recorded snippets)
        exec(entry.python, namespace)  # noqa: S102
    df = other.registry.get("leavenworth").links_df()
    assert df.loc[df.link_id == 1, "free_speed"].tolist() == [30.0]
    assert df.loc[df.link_id == 2, "lanes"].tolist() == [1]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py -q`
Expected: FAIL with `ImportError: cannot import name 'AddRows'`.

- [ ] **Step 3: The Actions**

In `packages/netstead/netstead/workbench/actions.py`, add after `SetSetting`:

```python
#: Ids one ``EditCells`` / ``DeleteRows`` takes, and rows one ``AddRows`` takes.
MAX_EDIT_IDS = 10_000
#: A cell value: ``None`` clears the cell. The session coerces it to the column's storage type.
CellValue = bool | int | float | str | None


class EditCells(BaseAction):
    """Set cells on rows of one table, picked by primary key (``None`` clears a cell).

    Each value is coerced to its column's storage type; one that does not fit is refused, as are key columns
    and unknown columns. What the spec says about the new values (required, type, enum, foreign keys,
    duplicate keys) comes back as ``warnings``: they warn, they never block.
    """

    type: Literal["edit_cells"] = "edit_cells"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    component: Component = "roadway"
    table: str = "link"
    ids: list[int | str] = Field(min_length=1, max_length=MAX_EDIT_IDS)
    values: dict[str, CellValue] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=500)


class DeleteRows(BaseAction):
    """Delete rows of one table by key, with every row that depends on them through the spec's foreign keys.

    A link takes its lanes and time-of-day rows with it. A node that a link still uses is refused.
    ``POST …/table/<table>/delete-plan`` shows what would go, without deleting anything.
    """

    type: Literal["delete_rows"] = "delete_rows"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    component: Component = "roadway"
    table: str = "link"
    ids: list[int | str] = Field(min_length=1, max_length=MAX_EDIT_IDS)
    note: str | None = Field(default=None, max_length=500)


class AddRows(BaseAction):
    """Append rows to one table (Python and the API; the app has no drawing tool). Each row needs its key."""

    type: Literal["add_rows"] = "add_rows"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    component: Component = "roadway"
    table: str
    rows: list[dict[str, CellValue]] = Field(min_length=1, max_length=MAX_EDIT_IDS)
    note: str | None = Field(default=None, max_length=500)


class UndoEdit(BaseAction):
    """Reverse the network's last edit, when the Workbench made it (a plugin undoes its own changes)."""

    type: Literal["undo_edit"] = "undo_edit"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
```

`CellValue` lists `bool` first so pydantic's smart union keeps `True` a boolean (it would anyway; the order documents
it). Append the four classes to `CORE_ACTIONS`, add them and `MAX_EDIT_IDS` to `__all__`, and export the four
classes from `workbench/__init__.py` (import and `__all__`): `import_line` writes
`from netstead.workbench import EditCells` for a core Action.

- [ ] **Step 4: The handlers**

In `packages/netstead/netstead/workbench/session.py`:
- imports: add `EditCells, DeleteRows, AddRows, UndoEdit` to the `.actions` import;
  `from corral.editing import EditingError`; `from .editing import EditPlan, EditRefused, plan_add, plan_delete,
  plan_update` (extend Task 5's `table_keys` import); `from collections.abc import Callable` if Part 1 did not add it;
- add after `_do_set_setting`:

```python
    def _edit_target(self, action: EditCells | DeleteRows | AddRows) -> NetworkHandle:
        if action.component != "roadway":
            raise NotSupportedYet("transit edits arrive with the transit component (phase P6)")
        return self._handle(action.net_id)

    def _apply_plan(self, handle: NetworkHandle, plan: EditPlan, note: str | None) -> dict[str, Any]:
        """Apply ``plan`` as one pending edit and describe it, with the live warnings on the rows it touched."""
        try:
            self.mutate(handle.id, plan.edits, note=f"{plan.summary} ({note})" if note else plan.summary, recheck=plan.recheck)
        except EditingError as exc:  # corral refused the payload; mutate already reversed what it applied
            raise ActionError(f"the edit failed: {exc}") from exc
        ledger = self.edits[handle.id]
        entry = ledger.last()
        return {
            "net_id": handle.id,
            "version": handle.version,
            "summary": plan.summary,
            "rows": dict(plan.rows),
            "keys": list(plan.keys),
            "warnings": [w.to_dict() for w in ledger.check.for_rows(entry.touched)],
            "open_warnings": len(ledger.check.warnings),
        }

    def _do_edit_cells(self, action: EditCells) -> dict[str, Any]:
        handle = self._edit_target(action)
        plan = _planned(lambda: plan_update(handle.roadway, action.table, action.ids, action.values))
        return self._apply_plan(handle, plan, action.note)

    def _do_delete_rows(self, action: DeleteRows) -> dict[str, Any]:
        handle = self._edit_target(action)
        plan = _planned(lambda: plan_delete(handle.roadway, action.table, action.ids))
        result = self._apply_plan(handle, plan, action.note)
        sel = self.selection
        if action.table == "link" and sel and sel["net_id"] == handle.id and set(sel["link_ids"]) & set(plan.keys):
            self.selection = None  # it would point at deleted links
        return result

    def _do_add_rows(self, action: AddRows) -> dict[str, Any]:
        handle = self._edit_target(action)
        plan = _planned(lambda: plan_add(handle.roadway, action.table, action.rows))
        return self._apply_plan(handle, plan, action.note)

    def _do_undo_edit(self, action: UndoEdit) -> dict[str, Any]:
        entry = self.undo_last(action.net_id)
        handle = self._handle(action.net_id)
        return {
            "net_id": handle.id,
            "version": handle.version,
            "undone": entry.view(),
            "open_warnings": len(self.edit_check(handle.id).warnings),
        }
```

- add a module-level helper next to `_follows_endpoint`:

```python
def _planned(build: Callable[[], EditPlan]) -> EditPlan:
    """Run an edit planner; its refusal becomes a recorded :class:`ActionError` (nothing changed)."""
    try:
        return build()
    except EditRefused as exc:
        raise ActionError(str(exc)) from exc
```

`_do_*` handlers run under the session lock (`dispatch_recorded`), and `mutate` re-enters it (an `RLock`), so a plan,
its application and the version bump are one step for every reader that takes the lock.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_actions.py packages/netstead/tests/test_workbench_action_registry.py -q`
Expected: all pass. `test_default_registry_holds_exactly_the_core_actions` reads `CORE_ACTIONS`, so it grows with it.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_edits.py
git commit -m "feat(workbench): EditCells, DeleteRows (FK cascade), AddRows and UndoEdit actions"
```

---

### Task 7: `RunValidation`: a background job, with issues located by key and anchor

**Files:**
- Create: `packages/netstead/netstead/workbench/issues.py`
- Modify: `packages/netstead/netstead/config.py` (`RuleSettings.severity_override`)
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py` (the session's job outcomes)
- Test: `packages/netstead/tests/test_workbench_issues.py`; modify `packages/netstead/tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_issues.py`:

```python
"""Validation in the workbench: RunValidation as a recorded job; issues tied to record keys and map anchors."""

import pytest
from corral.reports import Category, Issue, Severity, ValidationReport
from netstead import Network
from netstead.config import ValidationSettings
from netstead.fixtures import leavenworth
from netstead.select.parse import StubParser
from netstead.workbench import Session
from netstead.workbench.actions import EditCells, RunValidation, SetSetting
from netstead.workbench.issues import locate_issues, rule_configs
from pydantic import ValidationError

SRC = str(leavenworth.parquet_dir())


@pytest.fixture
def session(tmp_path, isolated_env):
    s = Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), plugins=[])
    s.dispatch({"type": "open_network", "source": SRC})
    return s


def test_run_validation_is_a_recorded_job_with_counts(session):
    result = session.dispatch(RunValidation())
    # Leavenworth: 16 structural infos + 1 fk.unverifiable warning, and 271 high_speed_residential warnings.
    assert result["counts"] == {"error": 0, "warning": 272, "info": 16}
    assert result["version"] == 0 and result["stale"] is False and result["unknown_rules"] == []
    entry = session.history[-1]
    assert entry.ok and entry.python == "app.do(RunValidation())"
    assert session.state()["issues"]["leavenworth"] == {"version": 0, "stale": False, "counts": result["counts"]}


def test_quality_issues_carry_their_link_key_and_anchor(session):
    session.dispatch(RunValidation())
    issues = session.issues["leavenworth"].issues
    links = session.registry.get("leavenworth").links_df()
    speed = [i for i in issues if i["code"] == "quality.high_speed_residential"]
    first = speed[0]
    assert first["key"] == int(links.link_id.iloc[first["row"]])
    assert first["anchor"] == {"link": first["key"]} and first["fixable"] is True
    structural = [i for i in issues if i["code"].startswith("structural.")]
    assert structural and all(i["anchor"] is None and i["key"] is None for i in structural)


def test_rule_settings_reach_the_rules(session):
    session.dispatch(SetSetting(key="validation.rules", value={"quality.high_speed_residential": {"enabled": False}}))
    assert session.dispatch(RunValidation())["counts"]["warning"] == 1


def test_unknown_rule_codes_are_reported(session):
    session.dispatch(SetSetting(key="validation.rules", value={"quality.no_such_rule": {"enabled": False}}))
    assert session.dispatch(RunValidation())["unknown_rules"] == ["quality.no_such_rule"]


def test_severity_overrides_are_checked_when_settings_load():
    cfg = rule_configs(ValidationSettings(rules={"quality.high_speed_residential": {"severity_override": "info"}}))
    assert cfg["quality.high_speed_residential"].severity_override == Severity.INFO
    with pytest.raises(ValidationError):
        ValidationSettings(rules={"x": {"severity_override": "fatal"}})


def test_a_column_read_alone_keeps_the_order_rules_read():
    # locate_issues rests on this: rule row positions come from Table.to_pandas(); keys from select(pk).
    net = Network.from_source(leavenworth.parquet_dir())
    for name, pk in (("link", "link_id"), ("node", "node_id"), ("lane", "lane_id")):
        table = net.tables[name]
        assert table.select(pk).to_pandas()[pk].tolist() == table.to_pandas()[pk].tolist()


def test_a_lane_issue_anchors_on_its_link_and_coordinates_anchor_themselves():
    net = Network.from_source(leavenworth.parquet_dir())
    lanes = net.tables["lane"].to_pandas()
    report = ValidationReport(
        issues=[
            Issue(Severity.WARNING, Category.DATA_QUALITY, "t.lane", "m", table="lane", column="width", row=0),
            Issue(Severity.INFO, Category.DATA_QUALITY, "t.xy", "m", extra={"lon": -120.6, "lat": 47.6}),
        ]
    )
    lane, xy = locate_issues(report, net)
    assert lane["key"] == int(lanes.lane_id.iloc[0]) and lane["anchor"] == {"link": int(lanes.link_id.iloc[0])}
    assert lane["fixable"] is True  # lane has a key, and width is a number the editor can set
    assert xy["anchor"] == {"lonlat": [-120.6, 47.6]} and xy["key"] is None


def test_an_edit_makes_the_issue_set_stale_and_a_rerun_sees_it(session):
    session.dispatch(RunValidation())
    session.dispatch(EditCells(ids=[1], values={"free_speed": 30}))
    assert session.state()["issues"]["leavenworth"]["stale"] is True
    assert session.dispatch(RunValidation())["counts"]["warning"] == 271  # link 1 is no longer flagged


def test_closing_the_network_drops_its_issues(session):
    session.dispatch(RunValidation())
    session.dispatch({"type": "close_network", "net_id": "leavenworth"})
    assert session.issues == {} and "leavenworth" not in session.state()["issues"]
```

In `packages/netstead/tests/test_workbench_session.py`, the settings-payload test asserts
`set(p["notes"]) == {"engine", "validation", "credentials"}`. Change it to `{"engine", "credentials"}`: validation
is now used.

If `Issue(...)` takes keyword-only fields, pass `severity=`, `category=`, `code=`, `message=` by name. Its
dataclass order is severity, category, code, message, table, column, row, fix_hint, extra.

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_issues.py -q`
Expected: FAIL with `ImportError: cannot import name 'RunValidation'`.

- [ ] **Step 3: Settings**

In `packages/netstead/netstead/config.py`, change `RuleSettings.severity_override` to:

```python
    severity_override: Literal["error", "warning", "info"] | None = None
```

Change the `ValidationSettings` docstring to
`"""Per-rule quality configuration, keyed by rule code (e.g. ``quality.high_speed_residential``)."""`.

- [ ] **Step 4: Create `workbench/issues.py`**

```python
"""Validation in the workbench: run the checks, then tie each issue to a record and to a map anchor.

A rule reports a row *position* (``Issue.row``) in the order it read the table (``Table.to_pandas()``), at the
version it ran on. Positions are turned into primary keys here, once, from that same order, so the UI can link
an issue to its row by key and to the map by ``anchor``:

* ``{"link": id}`` / ``{"node": id}``: the record itself, or the link/node a row points at (a lane's ``link_id``);
* ``{"lonlat": [x, y]}``: a rule that reported coordinates (``Issue.extra`` ``lon``/``lat`` or ``x``/``y``);
* ``None``: unlocated (a missing table, a whole-table finding).

The browser places anchors from the network buffer it has already decoded, so no geometry is sent twice.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from corral.quality import RuleConfig, run_quality
from corral.quality.registry import list_rules
from corral.reports import Severity, ValidationReport

from netstead.config import ValidationSettings
from netstead.quality import register_all
from netstead.viz.styling import json_scalar

from .editing import editable
from .related import primary_keys

__all__ = ["MAX_MARKERS", "SEVERITIES", "IssueSet", "locate_issues", "rule_configs", "run_validation"]

SEVERITIES = ("error", "warning", "info")
#: Located issues sent to the map; beyond this the markers answer says ``truncated``.
MAX_MARKERS = 50_000
#: Tables the map draws: an issue on one of their records anchors on the record itself.
_MAP_TABLES = ("link", "node")
#: Columns that place a row of another table on the map, via the record they point at.
_POINTS_AT = (("link_id", "link"), ("node_id", "node"))


@dataclass(frozen=True)
class IssueSet:
    """One validation run of one network version: the located issues, plus the report for the HTML export."""

    net_id: str
    version: int
    issues: tuple[dict[str, Any], ...]
    report: ValidationReport
    unknown_rules: tuple[str, ...] = ()
    ran_at: float = field(default_factory=time.time)

    def counts(self) -> dict[str, int]:
        """Issues per severity (every severity present, zeros included)."""
        found = Counter(i["severity"] for i in self.issues)
        return {s: found.get(s, 0) for s in SEVERITIES}

    def facets(self) -> dict[str, dict[str, int]]:
        """Issue counts per severity, table (``(none)`` for none) and code, over the whole set."""
        return {
            "severity": self.counts(),
            "table": dict(Counter(i["table"] or "(none)" for i in self.issues).most_common()),
            "code": dict(Counter(i["code"] for i in self.issues).most_common()),
        }

    def query(
        self,
        *,
        severity: Sequence[str] = (),
        table: str | None = None,
        code: str | None = None,
        located: bool | None = None,
        record: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """The issues matching every given filter, in report order. ``record`` is ``(table, str(key))``."""

        def keep(i: dict[str, Any]) -> bool:
            return (
                (not severity or i["severity"] in severity)
                and (table is None or (i["table"] or "(none)") == table)
                and (code is None or i["code"] == code)
                and (located is None or (i["anchor"] is not None) == located)
                and (record is None or (i["table"] == record[0] and str(i["key"]) == record[1]))
            )

        return [i for i in self.issues if keep(i)]

    def by_record(self) -> dict[str, dict[str, list[int]]]:
        """``{table: {str(key): [issue numbers]}}``, for issues tied to a record (row marks, "This record")."""
        out: dict[str, dict[str, list[int]]] = {}
        for i in self.issues:
            if i["table"] and i["key"] is not None:
                out.setdefault(i["table"], {}).setdefault(str(i["key"]), []).append(i["i"])
        return out


def rule_configs(settings: ValidationSettings) -> dict[str, RuleConfig]:
    """``validation.rules`` as corral ``RuleConfig`` objects, keyed by rule code."""
    return {
        code: RuleConfig(
            enabled=rule.enabled,
            severity_override=Severity(rule.severity_override) if rule.severity_override else None,
            thresholds=dict(rule.thresholds),
        )
        for code, rule in settings.rules.items()
    }


def run_validation(
    net: Any, settings: ValidationSettings, *, quality: bool = True
) -> tuple[ValidationReport, tuple[str, ...]]:
    """Spec, key and structure checks (``Network.validate``), then the quality rules: ``(report, unknown rule codes)``."""
    report = net.validate()
    if not quality:
        return report, ()
    register_all()  # the entry point can be missing in an editable install (the quality CLI does the same)
    unknown = tuple(sorted(set(settings.rules) - set(list_rules())))
    run_quality(net, config=rule_configs(settings), report=report)
    return report, unknown


def locate_issues(report: ValidationReport, net: Any) -> tuple[dict[str, Any], ...]:
    """Every issue as a JSON-safe dict, with its record ``key``, its map ``anchor``, and whether it is ``fixable``."""
    tables = net.tables
    pks = primary_keys(net.spec, {name: t.columns() for name, t in tables.items()})
    columns: dict[tuple[str, str], list[Any]] = {}

    def at(table: str, column: str, row: int) -> Any:
        if (table, column) not in columns:
            src = tables[table]
            columns[(table, column)] = src.select(column).to_pandas()[column].tolist() if column in src.columns() else []
        values = columns[(table, column)]
        return json_scalar(values[row]) if 0 <= row < len(values) else None

    out = []
    for n, issue in enumerate(report.issues):
        table = issue.table if issue.table in tables else None
        pk = pks.get(table) if table else None
        key = at(table, pk, issue.row) if table and pk and issue.row is not None else None
        schema = tables[table].expr.schema() if table else {}
        fixable = key is not None and issue.column not in (None, pk) and issue.column in schema
        fixable = fixable and editable(schema[issue.column])
        out.append(
            {
                "i": n,
                "severity": issue.severity.value,
                "category": issue.category.value,
                "code": issue.code,
                "message": issue.message,
                "fix_hint": issue.fix_hint,
                "table": issue.table,
                "column": issue.column,
                "row": issue.row,
                "key": key,
                "anchor": _anchor(issue, table, key, at),
                "fixable": bool(fixable),
            }
        )
    return tuple(out)


def _anchor(issue: Any, table: str | None, key: Any, at: Callable[[str, str, int], Any]) -> dict[str, Any] | None:
    x = issue.extra.get("lon", issue.extra.get("x"))
    y = issue.extra.get("lat", issue.extra.get("y"))
    if isinstance(x, int | float) and isinstance(y, int | float):
        return {"lonlat": [float(x), float(y)]}
    if table is None or key is None:
        return None
    if table in _MAP_TABLES:
        return {table: key}
    for column, target in _POINTS_AT:
        value = at(table, column, issue.row)
        if value is not None:
            return {target: value}
    return None
```

- [ ] **Step 5: The action**

In `packages/netstead/netstead/workbench/actions.py`, add after `Navigate`:

```python
class RunValidation(BaseAction):
    """Validate a network (spec, keys, structure, and the quality rules in Settings → validation) as a background job."""

    type: Literal["run_validation"] = "run_validation"
    runs_as_job: ClassVar[bool] = True
    net_id: str | None = None
    quality: bool = True

    def job_label(self) -> str:
        """``validate <network>``."""
        return f"validate {self.net_id or 'network'}"
```

Append it to `CORE_ACTIONS`, and add it to `__all__` and `workbench/__init__.py` (import and `__all__`). Do not add
it to the closed `Action` union: Part 1's registry is the one list.

- [ ] **Step 6: The session: job outcomes commit themselves**

In `packages/netstead/netstead/workbench/session.py`:

1. Imports: add `RunValidation` to the `.actions` import, and
   `from .issues import IssueSet, locate_issues, run_validation`.
2. Give `_Loaded` a `commit` method, and add `_Validated` after it:

```python
    def commit(self, session: Session) -> dict[str, Any]:
        """Register the network and make it active (called under the session lock)."""
        handle = session.registry.add(self.net, source=self.source, label=self.label, net_id=self.net_id)
        handle.prime(**self.frames)
        session.active = handle.id
        return {"net_id": handle.id, **self.extra}


@dataclass
class _Validated:
    """A validation job's issues, waiting to be stored for the network version they describe."""

    handle: NetworkHandle
    issues: IssueSet

    def commit(self, session: Session) -> dict[str, Any]:
        """Store the issue set (called under the session lock); the network may have been edited meanwhile."""
        h = self.handle
        if h.id not in session.registry.ids() or session.registry.get(h.id) is not h:
            raise ActionError(f"network {h.id!r} was closed while it was being validated")
        session.issues[h.id] = self.issues
        return {
            "net_id": h.id,
            "version": self.issues.version,
            "stale": h.version != self.issues.version,
            "counts": self.issues.counts(),
            "unknown_rules": list(self.issues.unknown_rules),
        }
```

3. Replace the body of `Session._commit`: it now commits any outcome. Keep the docstring, and add "The outcome's
   `commit` registers a network, stores issues, …":

```python
        with self._lock:
            result = outcome.commit(self)
            entry = self._record(action, ok=True, result=result, error=None, error_type=None)
            self._committed[ctx.job_id] = entry.seq
        return result
```

   Rename its parameter from `loaded: _Loaded` to `outcome: _Outcome` (Part 1 already typed `action` as
   `BaseAction`). Define, after the outcome classes, `_Outcome = _Loaded | _Validated` (Task 9 adds `_Saved`).
4. In `__init__`, after `self.history`: `self.issues: dict[str, IssueSet] = {}  # net_id -> last validation`.
5. Add the job after `_job_build_network`:

```python
    def _job_run_validation(self, action: RunValidation, ctx: JobContext) -> _Validated:
        with self._lock:
            handle = self._handle(action.net_id)
            version, rules = handle.version, self.settings.validation
        ctx.stage("validate", progress=0.05)
        try:
            report, unknown = run_validation(handle.roadway, rules, quality=action.quality)
            ctx.stage("locate", progress=0.85)
            issues = locate_issues(report, handle.roadway)
        except ActionError:
            raise
        except Exception as exc:  # boundary: a crashing check is a reported failure, with its reason
            logger.exception("workbench validation of %s failed", handle.id)
            raise ActionError(f"validation failed: {type(exc).__name__}: {exc}") from exc
        ctx.stage("store", progress=0.95)  # last cancellation checkpoint
        return _Validated(handle, IssueSet(handle.id, version, issues, report, unknown))

    def issue_set(self, net_id: str) -> IssueSet | None:
        """The last validation of ``net_id`` (``None`` before any)."""
        with self._lock:
            return self.issues.get(net_id)
```

   (`issue_set` is a public method: place it with the other public API methods, after `state`.)
6. In `state()`, add:

```python
                "issues": {
                    nid: {"version": s.version, "stale": s.version != self.registry.get(nid).version, "counts": s.counts()}
                    for nid, s in self.issues.items()
                },
```

7. In `_do_close_network`, after Task 5's `self.edits.pop(...)` line: `self.issues.pop(action.net_id, None)`.
8. In `_SECTION_NOTES`, delete the `"validation"` entry.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_issues.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_session_jobs.py packages/netstead/tests/test_workbench_jobs.py packages/netstead/tests/test_workbench_actions.py -q`
Expected: all pass. The `_commit` refactor is covered by the existing open/build job tests.

- [ ] **Step 8: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add packages/netstead/netstead/config.py packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_issues.py packages/netstead/tests/test_workbench_session.py
git commit -m "feat(workbench): RunValidation job; issues located by record key and map anchor"
```

---

### Task 8: Issues, markers and report routes

**Files:**
- Create: `packages/netstead/netstead/workbench/routes/common.py`
- Create: `packages/netstead/netstead/workbench/routes/edit.py`
- Modify: `packages/netstead/netstead/workbench/routes/network.py`, `server.py`
- Test: `packages/netstead/tests/test_workbench_edit_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_edit_routes.py`:

```python
"""Validation and edit routes: read-only views of what actions produced (never recorded)."""

import json

import pytest
from fastapi.testclient import TestClient
from netstead.fixtures import leavenworth
from netstead.select.parse import StubParser
from netstead.workbench import Session, build_app

BASE = "/api/n/leavenworth/roadway"
SRC = str(leavenworth.parquet_dir())


def _session(tmp):
    env = {"NETSTEAD_CONFIG_DIR": str(tmp / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([SRC, str(tmp)])}
    s = Session(project_dir=tmp, environ=env, parser=StubParser(), plugins=[])
    s.dispatch({"type": "open_network", "source": SRC})
    return s


@pytest.fixture(scope="module")
def validated(tmp_path_factory):
    s = _session(tmp_path_factory.mktemp("wb"))
    s.dispatch({"type": "run_validation"})
    return s


@pytest.fixture(scope="module")
def client(validated):
    return TestClient(build_app(validated))


@pytest.fixture
def fresh(tmp_path):
    return TestClient(build_app(_session(tmp_path)))


def test_issues_before_any_validation(fresh):
    j = fresh.get(f"{BASE}/issues").json()
    assert j["version"] is None and j["issues"] == [] and j["total"] == 0
    assert fresh.get(f"{BASE}/issues/markers").json()["markers"] == []


def test_a_page_with_facets(client):
    j = client.get(f"{BASE}/issues?limit=10").json()
    assert (j["total"], len(j["issues"]), j["unlocated"], j["stale"]) == (288, 10, 17, False)
    assert j["facets"]["code"]["quality.high_speed_residential"] == 271
    assert j["facets"]["severity"] == {"error": 0, "warning": 272, "info": 16}


def test_filters(client):
    assert client.get(f"{BASE}/issues?severity=info").json()["total"] == 16
    assert client.get(f"{BASE}/issues?severity=error,info").json()["total"] == 16
    assert client.get(f"{BASE}/issues?code=fk.unverifiable").json()["total"] == 1
    assert client.get(f"{BASE}/issues?located=no").json()["total"] == 17
    first = client.get(f"{BASE}/issues?located=yes&limit=1").json()["issues"][0]
    rec = client.get(f"{BASE}/issues?record=link:{first['key']}").json()
    assert rec["total"] >= 1 and all(i["key"] == first["key"] for i in rec["issues"])


def test_markers_and_the_record_index(client):
    j = client.get(f"{BASE}/issues/markers").json()
    assert len(j["markers"]) == 271 and j["truncated"] is False
    assert set(j["markers"][0]) == {"i", "severity", "anchor", "table", "key"}
    assert sum(len(v) for v in j["records"]["link"].values()) == 271


def test_bad_queries(client):
    assert client.get(f"{BASE}/issues?limit=501").status_code == 422
    assert client.get(f"{BASE}/issues?record=link").status_code == 422
    assert client.get("/api/n/leavenworth/transit/issues").status_code == 501
    assert client.get("/api/n/nope/roadway/issues").status_code == 404


def test_the_report_downloads(client):
    r = client.get(f"{BASE}/report.html")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "<html" in r.text.lower() and "high_speed_residential" in r.text


def test_the_report_needs_a_current_validation(fresh, tmp_path):
    assert fresh.get(f"{BASE}/report.html").status_code == 409


def test_reads_are_not_recorded(validated, client):
    before = len(validated.history)
    client.get(f"{BASE}/issues")
    client.get(f"{BASE}/issues/markers")
    assert len(validated.history) == before
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py -q`
Expected: FAIL. The routes 404.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/workbench/routes/common.py`:

```python
"""Helpers shared by the per-network routers (``/api/n/{net_id}/{component}/...``)."""

from __future__ import annotations

from fastapi import HTTPException

from ..registry import NetworkHandle
from ..session import Session

__all__ = ["network_handle"]


def network_handle(session: Session, net_id: str, component: str) -> NetworkHandle:
    """The open handle for ``net_id`` (404 when unknown); ``transit`` answers 501 until phase P6."""
    if component == "transit":
        raise HTTPException(501, "the transit component is not supported yet (phase P6)")
    if component != "roadway":
        raise HTTPException(404, f"unknown component {component!r}")
    try:
        return session.registry.get(net_id)
    except KeyError as exc:
        raise HTTPException(404, exc.args[0]) from exc
```

In `routes/network.py`, replace the inner `def handle(...)` body with
`return network_handle(session, net_id, component)`, and import it from `.common`.

Create `packages/netstead/netstead/workbench/routes/edit.py`. Task 10 adds the edit routes to it.

```python
"""Validation and edit views of one network: ``/api/n/{net_id}/{component}/issues``, ``/report.html``, ``/edits``.

Read-only: they show what actions produced (``RunValidation``, ``EditCells``, ``DeleteRows``, ...), and the
delete plan is a dry run. Nothing here is recorded in the session history.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from ..issues import MAX_MARKERS
from ..session import Session
from .common import network_handle

__all__ = ["MAX_ISSUE_PAGE", "edit_router"]

#: Issues returned in one page.
MAX_ISSUE_PAGE = 500


def _record(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    table, sep, key = text.partition(":")
    if not (sep and table and key):
        raise HTTPException(422, "record is <table>:<key>")
    return table, key


def edit_router(session: Session) -> APIRouter:
    """Build the validation and edit routes bound to ``session``."""
    router = APIRouter(prefix="/api/n/{net_id}/{component}")

    @router.get("/issues")
    def issues(
        net_id: str,
        component: str,
        severity: str | None = None,
        table: str | None = None,
        code: str | None = None,
        located: Literal["yes", "no"] | None = None,
        record: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=MAX_ISSUE_PAGE),
    ) -> dict[str, Any]:
        """One page of the issues that match every filter, with the set's version, staleness and facets."""
        h = network_handle(session, net_id, component)
        found = _record(record)
        s = session.issue_set(h.id)
        if s is None:
            return {"net_id": h.id, "version": None, "current_version": h.version, "stale": False, "total": 0,
                    "unlocated": 0, "facets": {}, "offset": 0, "issues": []}
        rows = s.query(
            severity=[v for v in (severity or "").split(",") if v],
            table=table,
            code=code,
            located=None if located is None else located == "yes",
            record=found,
        )
        return {
            "net_id": h.id,
            "version": s.version,
            "current_version": h.version,
            "stale": s.version != h.version,
            "total": len(rows),
            "unlocated": sum(1 for i in s.issues if i["anchor"] is None),
            "facets": s.facets(),
            "offset": offset,
            "issues": rows[offset : offset + limit],
        }

    @router.get("/issues/markers")
    def markers(net_id: str, component: str) -> dict[str, Any]:
        """Located issues for the map (number, severity, anchor, record), plus issue numbers per record."""
        h = network_handle(session, net_id, component)
        s = session.issue_set(h.id)
        if s is None:
            return {"version": None, "stale": False, "truncated": False, "markers": [], "records": {}}
        located = [i for i in s.issues if i["anchor"] is not None]
        fields = ("i", "severity", "anchor", "table", "key")
        return {
            "version": s.version,
            "stale": s.version != h.version,
            "truncated": len(located) > MAX_MARKERS,
            "markers": [{k: i[k] for k in fields} for i in located[:MAX_MARKERS]],
            "records": s.by_record(),
        }

    @router.get("/report.html")
    def report(net_id: str, component: str) -> HTMLResponse:
        """The offline validation report (the ``render_validation_html`` page) for the last, still-current run."""
        h = network_handle(session, net_id, component)
        s = session.issue_set(h.id)
        if s is None:
            raise HTTPException(409, "run validation first")
        if s.version != h.version:
            raise HTTPException(409, "the network changed since validation; re-run it, then export the report")
        from netstead.map import render_validation_html  # jinja2 is a corral dependency: always present

        html = render_validation_html(h.roadway, s.report, title=f"validation: {h.label}")
        disposition = f'attachment; filename="{h.id}-validation.html"'
        return HTMLResponse(html, headers={"Content-Disposition": disposition})

    return router
```

In `server.py`, import `edit_router` and add `app.include_router(edit_router(session))` after the network router.

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py packages/netstead/tests/test_workbench_network_routes.py packages/netstead/tests/test_workbench_related_routes.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench/routes packages/netstead/netstead/workbench/server.py packages/netstead/tests/test_workbench_edit_routes.py
git commit -m "feat(workbench): issues, markers and report routes"
```


---

### Task 9: `SaveNetwork`: write the edited network as a new copy (warnings need confirming)

**Files:**
- Modify: `packages/netstead/netstead/workbench/build.py` (`output_path`)
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py`
- Test: `packages/netstead/tests/test_workbench_edits.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_edits.py`. Add `SaveNetwork` to the actions import, and
`from pathlib import Path` and `from netstead import Network` at the top:

```python
def outdir(tmp_path):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return str(out)


def test_save_writes_a_new_copy_and_never_the_source(session, tmp_path):
    session.dispatch(EditCells(ids=[1], values={"free_speed": 30}))
    result = session.dispatch(SaveNetwork(output_dir=outdir(tmp_path), name="edited", output_format="parquet"))
    assert Path(result["output"]).parent == Path(outdir(tmp_path)) and result["edits_saved"] == 1
    assert result["edited_while_saving"] is False and result["accepted_warnings"] == 0
    assert any("stale" in n for n in result["notes"])  # corral's OutOfSyncWarning: kept as text, not raised
    assert session.state()["edits"]["leavenworth"]["dirty"] is False
    back = Network.from_source(result["output"]).tables["link"].to_pandas()
    assert back.loc[back.link_id == 1, "free_speed"].tolist() == [30.0]
    source = Network.from_source(SRC).tables["link"].to_pandas()
    assert source.loc[source.link_id == 1, "free_speed"].tolist() == [40.0]
    with pytest.raises(ActionError, match="already exists"):
        session.dispatch(SaveNetwork(output_dir=outdir(tmp_path), name="edited", output_format="parquet"))


def test_saving_with_open_warnings_needs_confirmation(session, tmp_path):
    session.dispatch(EditCells(table="node", ids=[1], values={"ctrl_type": "bogus"}))
    with pytest.raises(ActionError, match="1 open edit warning"):
        session.dispatch(SaveNetwork(output_dir=outdir(tmp_path), name="edited", output_format="parquet"))
    assert session.history[-1].result["warnings"][0]["code"] == "edit.enum"
    result = session.dispatch(
        SaveNetwork(output_dir=outdir(tmp_path), name="edited", output_format="parquet", accept_warnings=True)
    )
    assert result["accepted_warnings"] == 1
    assert "accept_warnings=True" in session.history[-1].python  # a replay makes the same choice


def test_save_stays_inside_the_allowed_roots(session):
    with pytest.raises(PathNotAllowed):
        session.dispatch(SaveNetwork(output_dir="/etc", name="x", output_format="parquet"))
```

Add `PathNotAllowed` to the `netstead.workbench.errors` import.

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py -q -k save`
Expected: FAIL with `ImportError: cannot import name 'SaveNetwork'`.

- [ ] **Step 3: A shared destination check**

In `packages/netstead/netstead/workbench/build.py`, extract the destination check out of `plan_build`:

```python
def output_path(output_dir: str, name: str, output_format: str, settings: Settings, *, what: str = "builds") -> Path:
    """Where ``name`` lands in ``output_dir`` (inside ``io.allowed_roots``); never an existing path.

    Raises:
        PathNotAllowed: ``output_dir`` is outside ``io.allowed_roots``.
        ActionError: the folder does not exist, or the destination already does.
    """
    out_dir = _local(output_dir, "output_dir", settings)
    if not out_dir.is_dir():
        raise ActionError(f"output folder does not exist: {output_dir}")
    suffix = _SUFFIX[output_format]
    dest = out_dir / (name if name.lower().endswith(suffix) else f"{name}{suffix}")
    if dest.exists():
        raise ActionError(f"{dest} already exists; choose another name ({what} never overwrite)")
    return dest
```

Then replace the matching lines in `plan_build` (from `out_dir = _local(...)` through the `dest.exists()` check) with
`dest = output_path(action.output_dir, action.name, action.output_format, settings)`, and add `output_path` to
`build.__all__`.

- [ ] **Step 4: The Action**

In `actions.py`, hoist the build-name pattern next to `_OUTPUT_SUFFIXES`, and factor `BuildNetwork`'s suffix check
into a function both Actions call:

```python
#: A file or folder name: letters, digits, ``_ . -``; no path separator, no leading dot.
_NAME_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?$"


def _check_name(name: str, output_format: str) -> None:
    suffix = PurePath(name).suffix.lower()
    if suffix in _OUTPUT_SUFFIXES and suffix != f".{output_format}":
        raise ValueError(f"name {name!r} ends in {suffix} but output_format is {output_format!r}")
```

Make `BuildNetwork.name` use `Field(pattern=_NAME_PATTERN, max_length=100)`, and call `_check_name(self.name,
self.output_format)` in its validator in place of the inline check. Then add:

```python
class SaveNetwork(BaseAction):
    """Write the open network, with its edits, as a new copy in ``output_dir``. The source is never written to.

    While the network has open edit warnings the save is refused, listing them, unless ``accept_warnings``.
    """

    type: Literal["save_network"] = "save_network"
    mutates: ClassVar[bool] = True
    runs_as_job: ClassVar[bool] = True
    net_id: str | None = None
    output_dir: str
    output_format: Literal["parquet", "csv", "duckdb", "zip"]
    name: str = Field(pattern=_NAME_PATTERN, max_length=100)
    accept_warnings: bool = False

    @model_validator(mode="after")
    def _name_matches_format(self) -> SaveNetwork:
        _check_name(self.name, self.output_format)
        return self

    def job_label(self) -> str:
        """``save <name>``."""
        return f"save {self.name}"
```

Append it to `CORE_ACTIONS`, and add it to `__all__` and `workbench/__init__.py`.

- [ ] **Step 5: The job**

In `session.py`:
- add `import warnings` and `from corral.dataset.package import OutOfSyncWarning`;
- add `SaveNetwork` to the actions import;
- add the outcome after `_Validated`, and extend the alias to `_Outcome = _Loaded | _Validated | _Saved`:

```python
@dataclass
class _Saved:
    """A save job's output, reported once the copy is in place."""

    handle: NetworkHandle
    version: int
    output: str
    notes: list[str]
    edits: int
    accepted: int

    def commit(self, session: Session) -> dict[str, Any]:
        """Mark the pending edits saved, if the network did not change while saving (called under the lock)."""
        edited = self.handle.version != self.version
        ledger = session.edits.get(self.handle.id)
        if ledger is not None and not edited:
            ledger.mark_saved()
        return {
            "net_id": self.handle.id,
            "output": self.output,
            "version": self.version,
            "edited_while_saving": edited,
            "edits_saved": self.edits,
            "accepted_warnings": self.accepted,
            "notes": self.notes,
        }
```

Then the job, after `_job_run_validation`:

```python
    def _job_save_network(self, action: SaveNetwork, ctx: JobContext) -> _Saved:
        with self._lock:
            handle = self._handle(action.net_id)
            version, settings = handle.version, self.settings
            ledger = self.edits.get(handle.id)
            pending = len(ledger.entries) if ledger else 0
            open_warnings = ledger.check.warnings if ledger else ()
        if open_warnings and not action.accept_warnings:
            n = len(open_warnings)
            refused = ActionError(
                f"the network has {n} open edit warning{'s' if n != 1 else ''}; review them in the Issues tab, "
                "then save with accept_warnings=True"
            )
            refused.payload = {"count": n, "warnings": [w.to_dict() for w in open_warnings[:50]]}
            raise refused
        dest = build.output_path(action.output_dir, action.name, action.output_format, settings, what="saves")
        build.remove_stale_partials(dest.parent)
        # Writing an edited network warns OutOfSyncWarning ("... stale table(s) ..."): keep the text for the
        # result instead of letting the warning escape. (catch_warnings is process-global; jobs are few and
        # short, and other warnings keep their configured behaviour.)
        with build.staging(dest) as tmp, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", OutOfSyncWarning)
            build.write_output(handle.roadway, tmp, action.output_format, ctx)
            ctx.stage("save", progress=0.95)  # last cancellation checkpoint
            build.promote(tmp, dest)
        notes = [scrub(str(w.message), limit=None) for w in caught if issubclass(w.category, OutOfSyncWarning)]
        return _Saved(handle, version, str(dest), notes, pending, len(open_warnings))
```

The source in the warning may be a presigned URL, so `scrub` it. The refusal's `payload` reaches the history entry
the way `BuildNetwork`'s estimate does, so the browser can list the warnings it was refused for.

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edits.py packages/netstead/tests/test_workbench_session.py -q`
Then the build job tests: `uv run --all-extras pytest packages/netstead/tests -q -k "build or wizard or estimate"`.
Expected: all pass. The `plan_build` refactor keeps its messages, because `what` defaults to "builds".

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_edits.py
git commit -m "feat(workbench): SaveNetwork writes a new copy; open edit warnings need accept_warnings"
```

---

### Task 10: Edit routes: `/edits` and the delete plan

**Files:**
- Modify: `packages/netstead/netstead/workbench/routes/edit.py`, `session.py`
- Test: `packages/netstead/tests/test_workbench_edit_routes.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_edit_routes.py`:

```python
@pytest.fixture
def edited(tmp_path):
    s = _session(tmp_path)
    s.dispatch({"type": "edit_cells", "table": "node", "ids": [1], "values": {"ctrl_type": "bogus"}, "note": "test"})
    return s, TestClient(build_app(s))


def test_the_edits_view(edited):
    _, c = edited
    j = c.get(f"{BASE}/edits").json()
    (entry,) = j["entries"]
    assert entry["source"] == "workbench" and entry["rows"] == {"node": 1} and entry["note"].endswith("(test)")
    assert (j["version"], j["pending"], j["unsaved"], j["dirty"], j["can_undo"]) == (1, 1, 1, True, True)
    assert [(w["code"], w["table"], w["key"], w["column"]) for w in j["warnings"]] == [("edit.enum", "node", 1, "ctrl_type")]


def test_the_edits_view_before_any_edit(fresh):
    j = fresh.get(f"{BASE}/edits").json()
    assert j["entries"] == [] and j["warnings"] == [] and j["dirty"] is False and j["can_undo"] is False


def test_the_delete_plan_is_a_dry_run(edited):
    s, c = edited
    before = len(s.history)
    j = c.post(f"{BASE}/table/link/delete-plan", json={"ids": [1]}).json()
    assert j == {
        "table": "link", "refused": None, "rows": {"lane": 1, "link": 1},
        "summary": "delete link 1 (and 1 lane rows that depend on it)",
    }
    assert c.post(f"{BASE}/table/node/delete-plan", json={"ids": [1]}).json()["refused"].startswith("node 1 is still used")
    assert len(s.history) == before and len(s.registry.get("leavenworth").links_df()) == 339


def test_bad_delete_plans(edited):
    _, c = edited
    assert c.post(f"{BASE}/table/link/delete-plan", json={"ids": []}).status_code == 422
    assert c.post("/api/n/nope/roadway/table/link/delete-plan", json={"ids": [1]}).status_code == 404


def test_edit_reads_are_not_recorded(edited):
    s, c = edited
    before = len(s.history)
    c.get(f"{BASE}/edits")
    assert len(s.history) == before
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py -q -k "edits or delete_plan"`
Expected: FAIL. The routes 404.

- [ ] **Step 3: Session views**

In `session.py`, add with the public API methods (after `edit_check`):

```python
    def edits_payload(self, handle: NetworkHandle) -> dict[str, Any]:
        """The Edits tab's data: pending edits (newest first), undo state, dirty state and the live warnings."""
        with self._lock:
            ledger = self.edits.get(handle.id) or EditLedger()
            last = ledger.last()
            return {
                "net_id": handle.id,
                "version": handle.version,
                "entries": [e.view() for e in reversed(ledger.entries)],
                **ledger.summary(),
                "can_undo": bool(last and last.source == CORE_SOURCE),
                "warnings": [w.to_dict() for w in ledger.check.warnings],
            }

    def delete_preview(self, handle: NetworkHandle, table: str, ids: Sequence[Any]) -> dict[str, Any]:
        """What deleting ``ids`` from ``table`` would remove (rows per table), or why it is refused. Changes nothing."""
        with self._lock:
            try:
                plan = plan_delete(handle.roadway, table, ids)
            except EditRefused as exc:
                return {"table": table, "refused": str(exc), "rows": {}, "summary": None}
            return {"table": table, "refused": None, "rows": dict(plan.rows), "summary": plan.summary}
```

`**ledger.summary()` puts `warnings` (a count) in the dict first; the explicit `"warnings"` list after it wins. The
count is still there as `len(warnings)`.

- [ ] **Step 4: Routes**

In `routes/edit.py`:
- add `from pydantic import BaseModel, ConfigDict, Field` and `from ..actions import MAX_EDIT_IDS`;
- add, before `edit_router`:

```python
class DeletePlanQuery(BaseModel):
    """The keys a deletion would start from."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    ids: list[int | str] = Field(min_length=1, max_length=MAX_EDIT_IDS)
```

- add before `return router`:

```python
    @router.get("/edits")
    def edits(net_id: str, component: str) -> dict[str, Any]:
        """Pending edits, undo and dirty state, and the live edit warnings (always current, never stale)."""
        return session.edits_payload(network_handle(session, net_id, component))

    @router.post("/table/{table_name}/delete-plan")
    def delete_plan(net_id: str, component: str, table_name: str, q: DeletePlanQuery) -> dict[str, Any]:
        """A dry run of ``DeleteRows``: rows per table that would go, or why the deletion is refused."""
        return session.delete_preview(network_handle(session, net_id, component), table_name, q.ids)
```

Add `"DeletePlanQuery"` to the module's `__all__`.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py packages/netstead/tests/test_workbench_network_routes.py -q`
Expected: all pass.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_edit_routes.py
git commit -m "feat(workbench): edits view and delete-plan dry run routes"
```

---

### Task 11: Pure front-end rules: `issuelist.js`, `editmodel.js`, and `linking.js` additions

**Files:**
- Create: `packages/netstead/netstead/workbench/static/js/issuelist.js`
- Create: `packages/netstead/netstead/workbench/static/js/editmodel.js`
- Modify: `packages/netstead/netstead/workbench/static/js/linking.js`
- Test: `packages/netstead/tests/test_workbench_js.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_js.py`:

```python
NET = (
    "const net = {id2idx: new Map([[7, 0]]), nodeId2idx: new Map([[3, 1]]), linkStart: [0, 3],"
    " linkPositions: [0, 0, 1, 1, 2, 2], nodePositions: [9, 9, 5, 6]};"
)


def test_issues_query_string(node_module):
    got = node_module(
        "issuelist.js",
        ["issuesQuery"],
        'issuesQuery({severity: ["error", "warning"], table: "link", code: "", located: "yes", '
        'record: {table: "link", id: 7}}, 100, 50)',
    )
    assert got == "offset=100&limit=50&severity=error%2Cwarning&table=link&located=yes&record=link%3A7"


def test_anchor_positions(node_module):
    expr = (
        f"(() => {{ {NET} return [anchorPosition({{link: 7}}, net), anchorPosition({{node: 3}}, net), "
        "anchorPosition({lonlat: [1, 2]}, net), anchorPosition({link: 99}, net), anchorPosition(null, net)]; })()"
    )
    assert node_module("issuelist.js", ["anchorPosition"], expr) == [[1, 1], [5, 6], [1, 2], None, None]


def test_marker_points_keep_what_the_map_can_place(node_module):
    expr = (
        f"(() => {{ {NET} return markerPoints([{{i: 0, severity: 'warning', table: 'link', key: 7, anchor: {{link: 7}}}},"
        " {i: 1, severity: 'info', table: 'link', key: 99, anchor: {link: 99}}], net); })()"
    )
    assert node_module("issuelist.js", ["markerPoints"], expr) == [
        {"i": 0, "severity": "warning", "table": "link", "key": 7, "position": [1, 1]}
    ]


def test_record_issues_and_the_status_line(node_module):
    assert node_module("issuelist.js", ["recordIssues"], 'recordIssues({link: {"7": [0, 4]}}, "link", 7)') == [0, 4]
    assert node_module("issuelist.js", ["recordIssues"], 'recordIssues(null, "link", 7)') == []
    line = node_module(
        "issuelist.js", ["statusLine"], "statusLine({version: 2, stale: true, counts: {error: 0, warning: 272, info: 16}})"
    )
    assert line == "Validated v2: 272 warnings, 16 info · the network changed since: re-run"
    assert node_module("issuelist.js", ["statusLine"], "statusLine(null)") == "Not validated yet."
    assert node_module("issuelist.js", ["rangeLabel"], "rangeLabel(100, 50, 288)") == "101–150 of 288"


@pytest.mark.parametrize(
    ("raw", "sample", "want"),
    [("45", 40, 45), ("abc", 40, "abc"), ("true", True, True), ("0", False, False), (" x ", "y", "x"),
     ("", 40, None), ("  ", "y", None), ("007", "1", "007")],
)
def test_parse_cell(node_module, raw, sample, want):
    got = node_module("editmodel.js", ["parseCell"], f"parseCell({json.dumps(raw)}, {json.dumps(sample)})")
    assert got == want


def test_a_bad_boolean_is_refused(node_module):
    expr = '(() => { try { parseCell("maybe", true); return "accepted"; } catch (e) { return e.message; } })()'
    assert "Enter true or false" in node_module("editmodel.js", ["parseCell"], expr)


def test_cell_and_delete_actions(node_module):
    fix = node_module(
        "editmodel.js",
        ["cellAction"],
        'cellAction({table: "link", ids: [1], column: "free_speed", raw: "30", current: 40, note: "why"})',
    )
    assert fix == {"type": "edit_cells", "table": "link", "ids": [1], "values": {"free_speed": 30}, "note": "why"}
    clear = node_module(
        "editmodel.js", ["cellAction"], 'cellAction({table: "link", ids: [1, 2], column: "name", raw: "", current: "Main"})'
    )
    assert clear == {"type": "edit_cells", "table": "link", "ids": [1, 2], "values": {"name": None}}
    gone = node_module("editmodel.js", ["deleteAction"], 'deleteAction("link", [1])')
    assert gone == {"type": "delete_rows", "table": "link", "ids": [1]}


def test_cell_warnings_index_one_table(node_module):
    expr = (
        'cellWarnings([{table: "link", key: 1, column: "from_node_id", message: "m1"},'
        ' {table: "node", key: 1, column: "ctrl_type", message: "m2"},'
        ' {table: "link", key: 1, column: "directed", message: "m3"}], "link")'
    )
    assert node_module("editmodel.js", ["cellWarnings"], expr) == {"1": {"from_node_id": ["m1"], "directed": ["m3"]}}


def test_delete_plan_text(node_module):
    text = node_module("editmodel.js", ["deletePlanText"], 'deletePlanText({table: "link", rows: {lane: 2, link: 1}, refused: null})')
    assert text == "Delete 1 link row? This also deletes 2 lane rows. Undo is in the Edits tab."
    refused = node_module("editmodel.js", ["deletePlanText"], 'deletePlanText({table: "node", rows: {}, refused: "node 1 is still used"})')
    assert refused == "node 1 is still used"


def test_pending_lines_and_badges(node_module):
    lines = node_module(
        "editmodel.js",
        ["pendingLine"],
        '[pendingLine({seq: 2, note: "link 1: lanes = 2", source: "workbench"}), pendingLine({seq: 3, note: "cards: x", source: "cards"})]',
    )
    assert lines == ["#2 link 1: lanes = 2", "#3 cards: x [cards]"]
    badges = node_module(
        "editmodel.js",
        ["dirtyBadge"],
        "[dirtyBadge({dirty: true, unsaved: 2}), dirtyBadge({dirty: true, unsaved: 0}), dirtyBadge({dirty: false}), dirtyBadge(null)]",
    )
    assert badges == ["2 unsaved", "changed since saved", "", ""]
    blocked = node_module(
        "editmodel.js",
        ["undoBlocked"],
        '[undoBlocked({pending: 1, last_source: "workbench"}), undoBlocked({pending: 1, last_source: "cards"}), undoBlocked({pending: 0})]',
    )
    assert blocked == ["", "The last change was made by cards; undo it there.", "Nothing to undo."]
    cols = node_module("editmodel.js", ["editableColumns"], 'editableColumns({link_id: 1, name: "a", geometry: "x", lanes: 2}, "link_id")')
    assert cols == ["name", "lanes"]


@pytest.mark.parametrize(
    ("prev", "nxt", "want"),
    [("a@1", "a@2", "edited"), ("a@1", "b@1", "switched"), (None, "a@0", "switched"), ("a@1", None, "switched"),
     ("a@1", "a@1", "same"), ("a-2@1", "a@2", "switched")],
)
def test_net_change(node_module, prev, nxt, want):
    assert node_module("linking.js", ["netChange"], f"netChange({json.dumps(prev)}, {json.dumps(nxt)})") == want


def test_row_marks_flag_issues_and_edit_warnings(node_module):
    expr = 'rowMarks({table: "link", id: 1, selection: null, highlights: new Set(), focus: null, via: null, issues: 2, warned: true})'
    assert node_module("linking.js", ["rowMarks"], expr) == ["iss", "warn"]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_js.py -q`
Expected: the new tests FAIL. The modules don't exist yet; `netChange` is not exported; `rowMarks` ignores
`issues` and `warned`.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/workbench/static/js/issuelist.js`:

```js
// Issues-tab rules. Import-free and DOM-free: unit-tested under node (tests/test_workbench_js.py).
//
// An issue's `anchor` places it on the map: {link: id} (its middle vertex), {node: id}, or {lonlat: [x, y]}.
// The server sends anchors, not coordinates; positions come from the network buffer the browser already has.

export const SEVERITIES = ["error", "warning", "info"];
export const SEVERITY_RGB = { error: [224, 82, 77], warning: [240, 170, 60], info: [90, 150, 220] };

// The /issues query string for a filter ({severity: [...], table, code, located, record: {table, id}}) and a page.
export function issuesQuery({ severity = [], table = "", code = "", located = "", record = null }, offset = 0, limit = 100) {
  const q = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (severity.length) q.set("severity", severity.join(","));
  if (table) q.set("table", table);
  if (code) q.set("code", code);
  if (located) q.set("located", located);
  if (record) q.set("record", `${record.table}:${record.id}`);
  return q.toString();
}

// [lon, lat] for an anchor, or null when this network buffer cannot place it.
export function anchorPosition(anchor, net) {
  if (!anchor || !net) return null;
  if (anchor.lonlat) return anchor.lonlat;
  if (anchor.node != null) {
    const i = net.nodeId2idx.get(anchor.node);
    return i == null ? null : [net.nodePositions[2 * i], net.nodePositions[2 * i + 1]];
  }
  if (anchor.link != null) {
    const i = net.id2idx.get(anchor.link);
    if (i == null) return null;
    const a = net.linkStart[i], b = net.linkStart[i + 1], k = a + Math.floor((b - a - 1) / 2);
    return [net.linkPositions[2 * k], net.linkPositions[2 * k + 1]];
  }
  return null;
}

// Map markers: [{i, severity, table, key, position}] for the issues this network can place.
export function markerPoints(markers, net) {
  const out = [];
  for (const m of markers || []) {
    const position = anchorPosition(m.anchor, net);
    if (position) out.push({ i: m.i, severity: m.severity, table: m.table, key: m.key, position });
  }
  return out;
}

// The issue numbers recorded against one record ({table: {"<key>": [i, ...]}} from /issues/markers).
export const recordIssues = (records, table, id) => (records && records[table] && records[table][String(id)]) || [];

export const rangeLabel = (offset, shown, total) => (total ? `${offset + 1}–${offset + shown} of ${total}` : "No issues");

// One line on the state of the last validation.
export function statusLine(meta) {
  if (!meta) return "Not validated yet.";
  const c = meta.counts || {};
  const parts = SEVERITIES.filter(s => c[s]).map(s => `${c[s].toLocaleString("en-US")} ${s}${c[s] === 1 || s === "info" ? "" : "s"}`);
  return `Validated v${meta.version}: ${parts.join(", ") || "no issues"}` + (meta.stale ? " · the network changed since: re-run" : "");
}
```

Create `packages/netstead/netstead/workbench/static/js/editmodel.js`:

```js
// Edit rules: cell values, edit actions, and how pending edits and warnings read. Ported in part from the
// offline report's "Fix locally" editor (map/templates/map_component.js: coerceLikely). Import-free and
// DOM-free: unit-tested under node (tests/test_workbench_js.py).

// The typed text as the value to send. Empty clears the cell (null). A number when the current value is a
// number; true/false for a yes/no value; otherwise the text as typed (a text column keeps "007"). The server
// coerces to the column's real type and refuses a value that does not fit.
export function parseCell(input, sample) {
  const text = input == null ? "" : String(input).trim();
  if (text === "") return null;
  if (typeof sample === "boolean") {
    if (/^(true|1|yes)$/i.test(text)) return true;
    if (/^(false|0|no)$/i.test(text)) return false;
    throw new Error(`Enter true or false (got "${text}").`);
  }
  if (typeof sample === "number") {
    const n = Number(text);
    if (Number.isFinite(n)) return n;
  }
  return text;
}

// The EditCells action: one column of one or more rows of one table.
export function cellAction({ table, ids, column, raw, current, note = null }) {
  const action = { type: "edit_cells", table, ids: [...ids], values: { [column]: parseCell(raw, current) } };
  if (note) action.note = note;
  return action;
}

export function deleteAction(table, ids, note = null) {
  const action = { type: "delete_rows", table, ids: [...ids] };
  if (note) action.note = note;
  return action;
}

// The columns the editor offers for a record: everything but its key and its geometry.
export const editableColumns = (attributes, pk) => Object.keys(attributes).filter(k => k !== pk && k !== "geometry");

// One table's edit warnings, indexed for the grid: {"<key>": {"<column>": ["message", ...]}}.
export function cellWarnings(warnings, table) {
  const out = {};
  for (const w of warnings || []) {
    if (w.table !== table) continue;
    const row = (out[String(w.key)] ||= {});
    (row[w.column || ""] ||= []).push(w.message);
  }
  return out;
}

const rowCount = (n, table) => `${n} ${table} row${n === 1 ? "" : "s"}`;

// The confirmation for a deletion (from POST …/delete-plan), or the reason it is refused.
export function deletePlanText(plan) {
  if (plan.refused) return plan.refused;
  const also = Object.entries(plan.rows).filter(([t]) => t !== plan.table).map(([t, n]) => rowCount(n, t));
  return `Delete ${rowCount(plan.rows[plan.table] || 0, plan.table)}?` +
    (also.length ? ` This also deletes ${also.join(", ")}.` : "") + " Undo is in the Edits tab.";
}

// One pending edit in the Edits tab; a plugin's carries its id.
export const pendingLine = e => `#${e.seq} ${e.note}${e.source === "workbench" ? "" : ` [${e.source}]`}`;

// The dirty badge for a network's edit summary (session state `edits[net_id]`): "" when clean.
export function dirtyBadge(summary) {
  if (!summary || !summary.dirty) return "";
  return summary.unsaved ? `${summary.unsaved} unsaved` : "changed since saved";
}

// Why core's Undo is unavailable, or "" when it can undo.
export function undoBlocked(summary) {
  if (!summary || !summary.pending) return "Nothing to undo.";
  if (summary.last_source !== "workbench") return `The last change was made by ${summary.last_source}; undo it there.`;
  return "";
}
```

In `linking.js`:
- add after `pageOffset`:

```js
// What a new decoded-network key ("<id>@<version>") means for the view: "switched" (another network, or none),
// "edited" (the same network at a new version: an edit or an undo), or "same".
export function netChange(prevKey, nextKey) {
  if (prevKey === nextKey) return "same";
  const id = k => (k ? k.slice(0, k.lastIndexOf("@")) : null);
  return prevKey && nextKey && id(prevKey) === id(nextKey) ? "edited" : "switched";
}
```

- change `rowMarks` to accept `issues = 0, warned = false`, and add before its `return`:
  `if (issues) marks.push("iss");` and `if (warned) marks.push("warn");`
- extend its comment: `` `issues`: how many issues the last validation recorded against this record; `warned`: it
  has live edit warnings.``

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_js.py packages/netstead/tests/test_workbench_static.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench/static/js packages/netstead/tests/test_workbench_js.py
git commit -m "feat(workbench): issue-list and edit rules as unit-tested modules"
```

---

### Task 12: Drawer tabs, the edits feed, and an edit keeps the view

**Files:**
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`
- Create: `packages/netstead/netstead/workbench/static/js/edits.js` (Task 15 adds the Edits tab to it)
- Modify: `packages/netstead/netstead/workbench/static/js/store.js`, `side.js`, `main.js`, `table.js`

- [ ] **Step 1: The drawer**

In `index.html`, replace the opening `<aside id="side">` line with the lines below, and put a `</section>`
immediately before the existing `</aside>`. The Issues and Edits panes are filled by Tasks 13 and 15. They are
added now so the tab bar is complete.

```html
  <aside id="side">
    <nav id="side-tabs" role="tablist" aria-label="Drawer">
      <button role="tab" data-tab="details" class="on" aria-selected="true">Details</button>
      <button role="tab" data-tab="issues" aria-selected="false">Issues <span id="issues-count" class="pcount">0</span></button>
      <button role="tab" data-tab="edits" aria-selected="false">Edits <span id="edits-count" class="pcount">0</span></button>
    </nav>
    <section class="side-pane" data-pane="details" role="tabpanel">
```

Then, between that `</section>` and `</aside>`, add two empty panes:

```html
    <section class="side-pane" data-pane="issues" role="tabpanel" hidden></section>
    <section class="side-pane" data-pane="edits" role="tabpanel" hidden></section>
```

Append to `app.css`:

```css
  #side-tabs { display:flex; gap:4px; margin:-4px 0 12px; border-bottom:1px solid var(--edge); }
  #side-tabs button { background:none; color:var(--muted); border-radius:6px 6px 0 0; padding:6px 10px; font-size:12.5px; }
  #side-tabs button.on { color:var(--ink); box-shadow:inset 0 -2px 0 var(--accent); }
  a.btn { display:inline-block; text-decoration:none; padding:5px 10px; border-radius:8px; font-size:12px;
          border:1px solid var(--edge); color:var(--ink); }
  a.btn.off { opacity:.45; pointer-events:none; }
```

- [ ] **Step 2: Store keys**

In `store.js`, add to the initial state:

```js
  drawerTab: "details",       // details | issues | edits (per tab, never recorded)
  issues: null,               // /issues/markers for the active network: {net_id, version, markers, records}
  issueFilter: { severity: [], table: "", code: "", located: "", thisRecord: false },
  issueFocus: null,           // the issue number last picked in the list or on the map
  showIssues: true,           // the map's issue-marker layer (Layers panel; view state only)
  edits: null,                // GET /edits for the active network: pending edits and live edit warnings
```

- [ ] **Step 3: Tabs**

In `side.js`, add:

```js
// The drawer's tabs (Details | Issues | Edits): which pane shows is per-tab view state.
export function showTab(name) { store.set({ drawerTab: name }); }

function renderTab(name) {
  for (const b of document.querySelectorAll("#side-tabs button")) {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
  }
  for (const pane of document.querySelectorAll(".side-pane")) pane.hidden = pane.dataset.pane !== name;
}
```

At the end of `wireSide()`, add:

```js
  for (const b of document.querySelectorAll("#side-tabs button")) b.onclick = () => showTab(b.dataset.tab);
  store.subscribe(["drawerTab"], s => renderTab(s.drawerTab));
  renderTab(store.get().drawerTab);
```

- [ ] **Step 4: An edit keeps the view**

In `table.js`, add after `onNetworkChanged`:

```js
// The same network at a new version (an edit or an undo): refresh the rail's row counts and the rows in place,
// keeping the table, page, sort, filters and scope.
export function onNetworkEdited() {
  if (!TBL.loaded) return;
  refreshRail().catch(fail);
  refreshRows();
}

async function refreshRail() {
  const id = activeId();
  if (!id) return;
  const j = await getJSON(netPath(id, "tables"));
  const counts = new Map(j.tables.map(t => [t.name, t.rows]));
  for (const el of document.querySelectorAll(".tbl-item")) {
    const n = counts.get(el.dataset.name), rc = el.querySelector(".rc");
    if (rc && n != null) rc.textContent = n.toLocaleString();
  }
}
```

In `main.js`:
- import `netChange` from `./linking.js` and `onNetworkEdited` from `./table.js`;
- replace

```js
  store.subscribe(["netKey"], () => { cancelRelated(); onNetworkChanged(); store.set({ highlights: new Set(), focus: null, related: null }); clearDetails(); });
```

  with `store.subscribe(["netKey"], s => onNetKey(s.netKey));`;
- add near `onFocus`:

```js
// A newly decoded network. Another network resets the view. The same network at a new version (an edit, an undo)
// keeps focus, highlights, the table and its scope, and refreshes what depends on the data.
let shownKey = null;
function onNetKey(key) {
  const kind = netChange(shownKey, key);
  shownKey = key;
  if (kind === "same") return;
  if (kind === "edited") {
    onNetworkEdited();
    scheduleRelated();
    const f = store.get().focus;
    if (f) showDetails(f.table, f.id);
    return;
  }
  cancelRelated(); onNetworkChanged(); store.set({ highlights: new Set(), focus: null, related: null }); clearDetails();
}
```

- [ ] **Step 5: The edits feed**

Create `packages/netstead/netstead/workbench/static/js/edits.js`. The Issues tab (warnings), the grid (cell marks) and
the Edits tab all read `store.edits`; this keeps it current.

```js
// The active network's pending edits and live edit warnings (GET /edits), kept in `store.edits`.
// Task 15 adds the Edits tab's rendering and buttons to this module.
import { getJSON, netPath } from "./api.js";
import { toast } from "./dom.js";
import { store } from "./store.js";

let seq = 0, feedKey = null;
const activeId = () => { const s = store.get().server; return s && s.active; };

export async function loadEdits() {
  const id = activeId(), mine = ++seq;
  if (!id) { store.set({ edits: null }); return; }
  const j = await getJSON(netPath(id, "edits"));
  if (mine === seq && activeId() === id) store.set({ edits: j });
}

// Server state arrived: reload when the active network, its version, or its edit summary moved.
export function onEditsState(server) {
  const id = server.active, h = server.networks.find(n => n.id === id);
  const key = JSON.stringify([id, h && h.version, server.edits && server.edits[id]]);
  if (key === feedKey) return;
  feedKey = key;
  loadEdits().catch(e => toast(e.message));
}
```

In `main.js`, import `{ onEditsState }` from `./edits.js` and add to `wireStore()`:
`store.subscribe(["server"], s => onEditsState(s.server));`

- [ ] **Step 6: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass. Every new id is in `index.html`, and every import resolves.

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): drawer tabs, the edits feed; an edit keeps focus, highlights and the table"
```

---

### Task 13: The Issues tab (validation and edit warnings), map markers and row marks

**Files:**
- Create: `packages/netstead/netstead/workbench/static/js/issues.js`
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`
- Modify: `packages/netstead/netstead/workbench/static/js/map.js`, `table.js`, `main.js`

`issues.js` imports `openFixEditor` from `fixeditor.js` (Task 15). To keep this task's module graph complete, this
task creates `fixeditor.js` with only that export as a stub, and Task 15 fills it in:

```js
// The fix editor (Task 15).
export async function openFixEditor() {}
```

- [ ] **Step 1: The pane**

In `index.html`, fill `<section class="side-pane" data-pane="issues" …>`. Edit warnings come first: they are
always current, while a validation run can be stale.

```html
      <div class="label">Edit warnings <span id="iss-edit-count" class="pcount">0</span></div>
      <div id="iss-edit"><span class="empty">No edit warnings.</span></div>
      <div class="label">Validation</div>
      <div class="row wrap"><button class="mini" id="iss-run">Run validation</button>
        <a class="btn mini ghost off" id="iss-report" href="#" download>Export report</a></div>
      <div id="iss-status" class="diag">Not validated yet.</div>
      <div class="iss-filters">
        <select id="iss-sev" aria-label="Severity"></select>
        <select id="iss-table" aria-label="Table"></select>
        <select id="iss-code" aria-label="Issue code"></select>
        <label><input type="checkbox" id="iss-this"> This record</label>
      </div>
      <div id="iss-list"><span class="empty">Run validation to list issues.</span></div>
      <div class="iss-pager"><button class="mini ghost" id="iss-prev">&#8592;</button><span id="iss-range"></span>
        <button class="mini ghost" id="iss-next">&#8594;</button></div>
      <div class="label">Unlocated <span id="iss-unloc-count" class="pcount">0</span></div>
      <div id="iss-unlocated"></div>
```

In the Layers panel, after the Selection row, add:

```html
        <div class="row"><label class="sw"><input type="checkbox" id="tg-issues" checked><span></span></label>
          <span class="lbl">Issues</span></div>
```

Append to `app.css`:

```css
  .iss-filters { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; font-size:12px; }
  .iss-filters select { max-width:100%; }
  .iss { display:flex; gap:8px; align-items:flex-start; padding:7px 6px; border-bottom:1px solid var(--edge);
         cursor:pointer; font-size:12.5px; }
  .iss:hover, .iss.on { background:#20242e; }
  .iss .sev-dot { width:9px; height:9px; border-radius:50%; margin-top:4px; flex:none; }
  .sev-error .sev-dot { background:rgb(224,82,77); } .sev-warning .sev-dot { background:rgb(240,170,60); }
  .sev-info .sev-dot { background:rgb(90,150,220); }
  .iss-body { flex:1; min-width:0; } .iss-msg { color:var(--muted); overflow-wrap:anywhere; }
  .iss-pager { display:flex; align-items:center; gap:8px; margin:6px 0; font-size:12px; color:var(--muted); }
  #tbl-grid tr.iss td:first-child { box-shadow:inset 3px 0 0 rgb(240,170,60); }
```

- [ ] **Step 2: `issues.js`**

```js
// Issues tab: the live edit warnings, then validation: run it (a background job), list issues by filter, and link
// issue <-> map marker <-> row. The list, markers and report are read-only views of the last RunValidation and of
// GET /edits; nothing here is recorded.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { openFixEditor } from "./fixeditor.js";
import { SEVERITIES, issuesQuery, rangeLabel, statusLine } from "./issuelist.js";
import { flyTo } from "./map.js";
import { showTab } from "./side.js";
import { store } from "./store.js";

const PAGE = 100;
let offset = 0, seq = 0, metaKey = null;
const fail = e => toast(e.message);
const activeId = () => { const s = store.get().server; return s && s.active; };
export const issueMeta = s => (s.server && s.server.issues && s.server.issues[s.server.active]) || null;

// Server state arrived: reload markers and the list when the active network's issue set (or its staleness) moved.
export function onIssuesState(s) {
  const meta = issueMeta(s), key = JSON.stringify([s.server && s.server.active, meta]);
  renderStatus(meta);
  if (key === metaKey) return;
  metaKey = key;
  loadMarkers().catch(fail);
  reloadIssues({ restart: true });
}

export function reloadIssues({ restart = false } = {}) {
  if (restart) offset = 0;
  loadList().catch(fail);
}

function renderStatus(meta) {
  const id = activeId(), current = meta && !meta.stale;
  $("iss-status").textContent = statusLine(meta);
  renderCount();
  $("iss-run").textContent = meta && meta.stale ? "Re-run validation" : "Run validation";
  $("iss-report").classList.toggle("off", !current);
  $("iss-report").href = current && id ? netPath(id, "report.html") : "#";
}

// The tab's count: validation issues plus live edit warnings.
function renderCount() {
  const s = store.get(), meta = issueMeta(s);
  const warned = s.edits && s.edits.net_id === activeId() ? s.edits.warnings.length : 0;
  $("issues-count").textContent = (meta ? SEVERITIES.reduce((n, k) => n + (meta.counts[k] || 0), 0) : 0) + warned;
}

// The live edit warnings (GET /edits, via store.edits): click one to focus its record; Fix opens the editor on its
// column, so a missing foreign key or an empty required field can be put right where it was found.
export function renderEditWarnings(edits) {
  const list = edits && edits.net_id === activeId() ? edits.warnings : [];
  $("iss-edit-count").textContent = list.length;
  $("iss-edit").innerHTML = list.length ? list.map((w, k) =>
    `<div class="iss sev-warning" data-w="${k}" tabindex="0"><span class="sev-dot"></span><div class="iss-body">` +
    `<div><b>${esc(w.code)}</b> <span class="diag">${esc(w.table)} ${esc(w.key)}${w.column ? ` · ${esc(w.column)}` : ""}</span></div>` +
    `<div class="iss-msg">${esc(w.message)}</div></div><button class="mini ghost iss-fix">Fix</button></div>`).join("")
    : '<span class="empty">No edit warnings.</span>';
  for (const row of $("iss-edit").querySelectorAll(".iss")) {
    const w = list[Number(row.dataset.w)];
    row.onclick = e => { if (!e.target.closest(".iss-fix, .fix-editor")) store.set({ focus: { table: w.table, id: w.key, from: "table" } }); };
    row.querySelector(".iss-fix").onclick = () => openFixEditor(row, { table: w.table, id: w.key, column: w.column }).catch(fail);
  }
  renderCount();
}

async function loadMarkers() {
  const id = activeId();
  if (!id || !issueMeta(store.get())) { store.set({ issues: null }); return; }
  const j = await getJSON(netPath(id, "issues/markers"));
  if (activeId() === id) store.set({ issues: { ...j, net_id: id } });
}

async function loadList() {
  const id = activeId(), mine = ++seq, s = store.get();
  if (!id || !issueMeta(s)) {
    $("iss-list").innerHTML = '<span class="empty">Run validation to list issues.</span>';
    $("iss-unlocated").innerHTML = ""; $("iss-range").textContent = ""; $("iss-unloc-count").textContent = "0";
    return;
  }
  const f = s.issueFilter, record = f.thisRecord && s.focus ? s.focus : null;
  const [page, unlocated] = await Promise.all([
    getJSON(netPath(id, `issues?${issuesQuery({ ...f, record }, offset, PAGE)}`)),
    getJSON(netPath(id, `issues?${issuesQuery({ located: "no" }, 0, 50)}`)),
  ]);
  if (mine !== seq) return;
  renderFacets(page.facets, f);
  $("iss-list").innerHTML = page.issues.map(issueHTML).join("") || '<span class="empty">No issues match.</span>';
  $("iss-range").textContent = rangeLabel(offset, page.issues.length, page.total);
  $("iss-prev").disabled = offset <= 0;
  $("iss-next").disabled = offset + PAGE >= page.total;
  $("iss-unloc-count").textContent = unlocated.total;
  const more = unlocated.total - unlocated.issues.length;
  $("iss-unlocated").innerHTML = unlocated.issues.map(issueHTML).join("") + (more > 0 ? `<div class="empty">and ${more} more</div>` : "");
  wireRows($("iss-list"), page.issues);
  wireRows($("iss-unlocated"), unlocated.issues);
  markFocusedIssue();
}

function fill(select, options, value) {
  select.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  select.value = value;
}

function renderFacets(facets, f) {
  fill($("iss-sev"), [["", "All severities"], ...SEVERITIES.map(s => [s, `${s} (${(facets.severity || {})[s] || 0})`])], f.severity[0] || "");
  fill($("iss-table"), [["", "All tables"], ...Object.entries(facets.table || {}).map(([t, n]) => [t, `${t} (${n})`])], f.table);
  fill($("iss-code"), [["", "All codes"], ...Object.entries(facets.code || {}).map(([c, n]) => [c, `${c} (${n})`])], f.code);
}

function issueHTML(i) {
  const where = i.key != null ? `${i.table} ${i.key}` : i.table || "";
  const fix = i.fixable ? `<button class="mini ghost iss-fix">Fix</button>` : "";
  return `<div class="iss sev-${esc(i.severity)}" data-i="${i.i}" tabindex="0"><span class="sev-dot"></span>` +
    `<div class="iss-body"><div><b>${esc(i.code)}</b> <span class="diag">${esc(where)}${i.column ? ` · ${esc(i.column)}` : ""}</span></div>` +
    `<div class="iss-msg">${esc(i.message)}</div>${i.fix_hint ? `<div class="diag">${esc(i.fix_hint)}</div>` : ""}</div>${fix}</div>`;
}

function wireRows(el, issues) {
  const byI = new Map(issues.map(i => [String(i.i), i]));
  for (const row of el.querySelectorAll(".iss")) {
    const issue = byI.get(row.dataset.i);
    row.onclick = e => { if (!e.target.closest(".iss-fix, .fix-editor")) selectIssue(issue); };
    const fix = row.querySelector(".iss-fix");
    if (fix) fix.onclick = () => openFixEditor(row, {
      table: issue.table, id: issue.key, column: issue.column, note: `${issue.code}: ${issue.message}`,
    }).catch(fail);
  }
}

// An issue in the list: mark it and focus its record. The map flies there and the table scrolls to its row.
function selectIssue(issue) {
  const a = issue.anchor || {};
  const patch = { issueFocus: issue.i };
  if (issue.key != null) patch.focus = { table: issue.table, id: issue.key, from: "table" };
  else if (a.link != null || a.node != null) patch.focus = { table: a.link != null ? "link" : "node", id: a.link ?? a.node, from: "table" };
  store.set(patch);
  if (!patch.focus && a.lonlat) flyTo(a.lonlat[0], a.lonlat[1]);
}

// A marker clicked on the map: open the Issues tab filtered to that record, with the issue marked.
export function onIssueMarker(m) {
  showTab("issues");
  const patch = { issueFocus: m.i };
  if (m.key != null) {
    patch.focus = { table: m.table, id: m.key, from: "map" };
    patch.issueFilter = { ...store.get().issueFilter, thisRecord: true };
  }
  store.set(patch);
}

export function markFocusedIssue() {
  const i = store.get().issueFocus;
  for (const row of document.querySelectorAll("#side .iss")) {
    const on = row.dataset.i === String(i);
    row.classList.toggle("on", on);
    if (on) row.scrollIntoView({ block: "nearest" });
  }
}

function setFilter(patch) { store.set({ issueFilter: { ...store.get().issueFilter, ...patch } }); }

export function wireIssues() {
  $("iss-run").onclick = () => dispatch({ type: "run_validation" }).catch(fail);
  $("iss-sev").onchange = e => setFilter({ severity: e.target.value ? [e.target.value] : [] });
  $("iss-table").onchange = e => setFilter({ table: e.target.value });
  $("iss-code").onchange = e => setFilter({ code: e.target.value });
  $("iss-this").onchange = e => setFilter({ thisRecord: e.target.checked });
  $("iss-prev").onclick = () => { offset = Math.max(0, offset - PAGE); reloadIssues(); };
  $("iss-next").onclick = () => { offset += PAGE; reloadIssues(); };
  $("tg-issues").checked = store.get().showIssues;
  $("tg-issues").onchange = e => store.set({ showIssues: e.target.checked });
}
```

- [ ] **Step 3: Map markers**

In `map.js`:
- import `SEVERITY_RGB` and `markerPoints` from `./issuelist.js`;
- add `onIssueClick() {}` to the default `handlers`;
- add, before `render`:

```js
// Validation issues: a dot per located issue, coloured by severity; the picked issue is drawn larger.
let issueCache = { key: null, points: [] };
function issueLayer(s) {
  const key = `${s.netKey}|${s.issues.net_id}|${s.issues.version}`;
  if (issueCache.key !== key) issueCache = { key, points: markerPoints(s.issues.markers, s.net) };
  return new deck.ScatterplotLayer({ id: "issues", data: issueCache.points, getPosition: p => p.position,
    getRadius: p => (p.i === s.issueFocus ? 8 : 4.5), radiusUnits: "pixels", stroked: true, lineWidthMinPixels: 1,
    getFillColor: p => [...SEVERITY_RGB[p.severity], 230], getLineColor: [17, 21, 26],
    updateTriggers: { getRadius: s.issueFocus }, pickable: true, parameters: { depthTest: false },
    onClick: info => { if (info && info.object) handlers.onIssueClick(info.object); } });
}

export function flyTo(lon, lat) {
  if (!map) return;
  store.set({ marker: { lon, lat } });
  map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 15), duration: 500 });
}
```

- in `render()`, before the `if (s.marker)` line:
  `if (s.showIssues && s.issues && s.issues.net_id === s.server.active) layers.push(issueLayer(s));`

The marker cache is keyed on `netKey`, so an edit (a new version) re-places the markers. The issue set itself
stays the one validated, until it is re-run.

- [ ] **Step 4: Row marks**

In `table.js`:
- import `recordIssues` from `./issuelist.js`;
- in `renderRows`, before the `body.innerHTML = …` line, add
  `const records = s.issues && s.issues.net_id === activeId() ? s.issues.records : null;`;
- in the row map, compute `const nIss = recordIssues(records, TBL.name, pv).length;`;
- pass `issues: nIss` to `rowMarks`;
- replace the `title` line with:

```js
    const tip = [vias[i] ? `related via ${vias[i]}` : "", nIss ? `${nIss} issue${nIss === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ");
    const title = tip ? ` title="${esc(tip)}"` : "";
```

- [ ] **Step 5: Wire it in `main.js`**

- import `{ markFocusedIssue, onIssueMarker, onIssuesState, reloadIssues, renderEditWarnings, wireIssues }` from
  `./issues.js`;
- call `wireIssues()` in `boot()` with the other `wire*()` calls;
- pass `onIssueClick: onIssueMarker` to `initMap`;
- add to `wireStore()`:

```js
  store.subscribe(["server"], s => onIssuesState(s));
  store.subscribe(["issueFilter"], s => { $("iss-this").checked = s.issueFilter.thisRecord; reloadIssues({ restart: true }); });
  store.subscribe(["focus"], s => { if (s.issueFilter.thisRecord) reloadIssues({ restart: true }); });
  store.subscribe(["issueFocus"], () => markFocusedIssue());
  store.subscribe(["issues", "showIssues", "issueFocus"], () => render());
  store.subscribe(["issues"], () => refreshRows());
  store.subscribe(["edits"], s => renderEditWarnings(s.edits));
```

- [ ] **Step 6: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass.

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): Issues tab (edit warnings, validation) linked to map markers and rows; export report"
```

---

### Task 14: Cell editing in the data table, with warning marks

A row click focuses the record (P1b). A click on a cell of the **focused** row opens that cell for editing: Enter
applies an `EditCells` action, Escape or leaving cancels. Cells with live edit warnings are underlined, with the
messages as their tooltip, and their row is marked. In the focused row a foreign-key cell shows its value as text
plus a small ↗ link, so a click on the value edits it and the ↗ still jumps to the referenced row.

**Files:**
- Modify: `packages/netstead/netstead/workbench/static/js/table.js`, `main.js`
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`

- [ ] **Step 1: Imports and state**

In `table.js`:
- extend the api import to `import { dispatch, getJSON, netPath, postJSON } from "./api.js";`;
- add `import { cellAction, cellWarnings } from "./editmodel.js";`;
- after `let rowsTimer = …`, add:

```js
// The cell open for editing ({td, html}); rows do not reload under it, they catch up when it closes.
let editing = null;
```

- in `refreshRows`, change `if (!tableVisible()) { dirty = true; return; }` to
  `if (!tableVisible() || editing) { dirty = true; return; }`.

- [ ] **Step 2: Render marks and the focused row**

Replace `cellHTML` with:

```js
// A grid cell. A navigable foreign key is a link to its row; in the focused row the value is plain text (a click
// edits it) and a small ↗ does the jump.
function cellHTML(value, fk, focused = false) {
  if (value === null) return '<span class="empty">·</span>';
  if (fk && fk.navigable) {
    const link = `<a class="fk${focused ? " go" : ""}" href="#" data-ref="${esc(fk.ref_table)}" data-id="${esc(value)}" ` +
      `data-num="${typeof value === "number" ? 1 : ""}" title="Go to ${esc(fk.ref_table)} ${esc(value)}">${focused ? "↗" : esc(value)}</a>`;
    return focused ? `${esc(value)} ${link}` : link;
  }
  return esc(value);
}
```

In `renderRows`:
- keep the page for the cell editor: add `TBL.cols = cols; TBL.rows = rows;` at the top;
- before `body.innerHTML = …`, add
  `const warned = s.edits && s.edits.net_id === activeId() ? cellWarnings(s.edits.warnings, TBL.name) : {};`;
- in the row map, after `pv`, add `const rw = warned[String(pv)];` and
  `const focused = Boolean(s.focus && s.focus.table === TBL.name && s.focus.id === pv);`, pass `warned: Boolean(rw)`
  to `rowMarks` (next to Task 13's `issues: nIss`), and replace the `tds` line with:

```js
    const tds = r.map((v, c) => {
      const msgs = rw && rw[cols[c]];
      const mark = msgs ? ` class="cw" title="${esc(msgs.join("\n"))}"` : "";
      return `<td data-c="${c}"${mark}>${cellHTML(v, fks.get(cols[c]), focused)}</td>`;
    }).join("");
```

- replace the row click wiring with:

```js
  for (const tr of body.querySelectorAll("tr.data")) tr.onclick = e => {
    const td = e.target.closest("td[data-c]");
    if (tr.classList.contains("focus") && td && editableColumn(TBL.cols[Number(td.dataset.c)])) startCellEdit(tr, td);
    else rowClick(tr.dataset.pk);
  };
```

- [ ] **Step 3: The cell editor**

Add after `rowClick`:

```js
// The key is never edited in a cell (decision 2); everything else may be (the server refuses what it cannot hold).
const editableColumn = name => Boolean(name) && name !== TBL.schema.primary_key;

// Edit one cell of the focused row in place: Enter applies an EditCells action; Escape or leaving cancels.
function startCellEdit(tr, td) {
  if (editing) return;
  const c = Number(td.dataset.c), column = TBL.cols[c];
  const current = TBL.rows[[...tr.parentNode.children].indexOf(tr)][c];
  const id = coerceId(tr.dataset.pk, pkNumeric());
  editing = { td, html: td.innerHTML };
  td.innerHTML = `<input class="cell-in" aria-label="${esc(column)}">`;
  const input = td.querySelector("input");
  input.value = current == null ? "" : String(current);
  const close = () => {
    if (!editing || editing.td !== td) return;
    td.innerHTML = editing.html;
    editing = null;
    if (dirty) refreshRows();
  };
  input.onclick = e => e.stopPropagation();
  input.onblur = () => setTimeout(close, 150); // an Enter in flight wins
  input.onkeydown = async e => {
    if (e.key === "Escape") { close(); return; }
    if (e.key !== "Enter") return;
    try {
      await dispatch(cellAction({ table: TBL.name, ids: [id], column, raw: input.value, current }));
      editing = null; // the edit bumps the version: the rows reload with the new value and its warnings
      refreshRows();
    } catch (err) { toast(err.message); input.focus(); }
  };
  input.focus();
  input.select();
}
```

`cellAction` throws for a bad boolean before anything is sent; the server refuses a value its column cannot hold.
Either way the toast says why and the input stays open.

- [ ] **Step 4: Styles, the hint and the wiring**

Append to `app.css`:

```css
  #tbl-grid td.cw { box-shadow:inset 0 -2px 0 rgb(240,170,60); }
  #tbl-grid tr.warn td:first-child { box-shadow:inset 3px 0 0 rgb(224,120,60); }
  #tbl-grid tr.focus td { cursor:text; }
  #tbl-grid a.fk.go { text-decoration:none; opacity:.75; margin-left:2px; }
  .cell-in { width:100%; min-width:64px; font:inherit; padding:1px 4px; }
```

In `index.html`, in `#tbl-bar` after `<span id="tbl-hint" class="empty"></span>`, add
`<span class="diag">Click a row, then a cell of it, to edit.</span>`.

In `main.js`, add to `wireStore()`: `store.subscribe(["edits"], () => refreshRows());` (the warning marks follow the
live check).

- [ ] **Step 5: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass. The editing behaviour itself is checked in the Task 16 walk-through.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): edit cells in the data table; live warning marks on cells and rows"
```

---

### Task 15: The fix editor, Details edit and delete, the Edits tab, the dirty badge, and Save a copy

**Files:**
- Modify (fill the stub): `packages/netstead/netstead/workbench/static/js/fixeditor.js`
- Modify: `packages/netstead/netstead/workbench/static/js/edits.js`, `side.js`, `header.js`, `main.js`
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`

- [ ] **Step 1: `fixeditor.js`**

Replace the stub:

```js
// The fix editor, ported from the offline report's "Fix locally" mini-editor (map_component.js): one property of
// one record (or of every selected link), applied as an EditCells action. Delete asks the server what the cascade
// would remove (a dry run) and says so before anything is deleted.
import { dispatch, getJSON, netPath, postJSON } from "./api.js";
import { esc, toast } from "./dom.js";
import { cellAction, deleteAction, deletePlanText, editableColumns } from "./editmodel.js";
import { activeSelection, store } from "./store.js";

// Open the editor inside `host` for {table, id, column?, note?}; a second call on the same host closes it.
export async function openFixEditor(host, { table, id, column = null, note = "" }) {
  const open = host.querySelector(".fix-editor");
  if (open) { open.remove(); return; }
  const s = store.get();
  const rec = await getJSON(netPath(s.server.active, `feature/${encodeURIComponent(table)}/${encodeURIComponent(id)}`));
  const cols = editableColumns(rec.attributes, rec.pk);
  const sel = activeSelection(s);
  const many = table === "link" && sel && sel.status === "resolved" && sel.link_ids.includes(id) && sel.link_ids.length > 1;
  const el = document.createElement("div");
  el.className = "fix-editor";
  el.innerHTML =
    `<div class="row"><b>${esc(table)} ${esc(id)}</b></div>` +
    `<div class="row"><select class="fx-col" aria-label="Property">` +
    cols.map(c => `<option${c === column ? " selected" : ""}>${esc(c)}</option>`).join("") + "</select>" +
    `<input class="fx-val grow" aria-label="New value" placeholder="empty clears it"></div>` +
    `<div class="row"><input class="fx-note grow" aria-label="Note" placeholder="Why (kept with the edit)" value="${esc(note || "")}"></div>` +
    (many ? `<label class="row"><input type="checkbox" class="fx-sel"> all ${sel.link_ids.length} selected links</label>` : "") +
    `<div class="row"><button class="mini fx-apply">Apply</button><button class="mini ghost fx-cancel">Cancel</button>` +
    `<button class="mini ghost fx-delete">Delete…</button><span class="diag fx-now"></span></div>`;
  const current = () => rec.attributes[el.querySelector(".fx-col").value];
  const showCurrent = () => {
    const v = current();
    el.querySelector(".fx-now").textContent = `now: ${v == null || v === "" ? "empty" : v}`;
    el.querySelector(".fx-val").value = v == null ? "" : String(v);
  };
  el.querySelector(".fx-col").onchange = showCurrent;
  el.querySelector(".fx-cancel").onclick = () => el.remove();
  el.querySelector(".fx-delete").onclick = () => deleteRecord(table, id).then(done => { if (done) el.remove(); });
  el.querySelector(".fx-apply").onclick = async () => {
    try {
      const box = el.querySelector(".fx-sel");
      await dispatch(cellAction({ table, ids: box && box.checked ? sel.link_ids : [id], column: el.querySelector(".fx-col").value,
        raw: el.querySelector(".fx-val").value, current: current(), note: el.querySelector(".fx-note").value.trim() || null }));
      el.remove();
    } catch (e) { toast(e.message); }
  };
  host.appendChild(el);
  showCurrent();
  el.querySelector(".fx-val").focus();
}

// Delete one record after showing what goes with it; resolves to whether it was deleted.
export async function deleteRecord(table, id) {
  try {
    const plan = await postJSON(netPath(store.get().server.active, `table/${encodeURIComponent(table)}/delete-plan`), { ids: [id] });
    if (plan.refused) { toast(plan.refused); return false; }
    if (!window.confirm(deletePlanText(plan))) return false;
    await dispatch(deleteAction(table, [id]));
    return true;
  } catch (e) { toast(e.message); return false; }
}
```

- [ ] **Step 2: Edit and delete from Details**

In `side.js`:
- import `{ deleteRecord, openFixEditor }` from `./fixeditor.js`;
- in `showDetails`, replace `el.innerHTML = \`${head}<table>${rows}</table>\`;` with:

```js
    const actions = `<div class="row det-actions"><button class="mini ghost" data-act="edit">Edit…</button>` +
      `<button class="mini ghost" data-act="delete">Delete…</button></div>`;
    el.innerHTML = `${head}${actions}<table>${rows}</table>`;
    el.querySelector('[data-act="edit"]').onclick = () =>
      openFixEditor(el.querySelector(".det-actions"), { table, id }).catch(e => toast(e.message));
    el.querySelector('[data-act="delete"]').onclick = () => deleteRecord(table, id);
```

Any focused record can be edited (any table with a key); the delete plan says when a deletion is refused (a node a
link uses) before anything happens.

- [ ] **Step 3: The Edits pane**

In `index.html`, fill `<section class="side-pane" data-pane="edits" …>`:

```html
      <p class="diag">Every change to this network since it was opened, newest first: your edits and any plugin's.
        Undo reverses your newest edit. The strip at the bottom is the session history (every action).</p>
      <div class="row wrap"><button class="mini ghost" id="ed-undo" disabled>Undo last</button>
        <span class="diag" id="ed-undo-why"></span></div>
      <div id="ed-status" class="diag"></div>
      <div id="ed-list"><span class="empty">No edits yet.</span></div>
      <div class="label">Save a copy</div>
      <div class="row wrap"><input id="ed-save-name" placeholder="leavenworth-fixed" aria-label="Copy name">
        <select id="ed-save-format" aria-label="Format"><option value="parquet">Parquet folder</option>
          <option value="csv">CSV folder</option><option value="duckdb">DuckDB file</option><option value="zip">Zip</option></select>
        <button class="mini ghost" id="ed-save">Choose folder…</button></div>
      <div class="fb" id="ed-save-fb" hidden></div>
```

Append to `app.css`:

```css
  .chg { padding:7px 0; border-bottom:1px solid var(--edge); font-size:12.5px; }
  .chg.unsaved { box-shadow:inset 3px 0 0 var(--accent); padding-left:8px; }
  .pcount.dirty { background:var(--accent); }
  .fix-editor { margin:6px 0; padding:8px; border:1px solid var(--edge); border-radius:8px; background:#0c0e12; }
  .fix-editor .row { display:flex; gap:6px; align-items:center; margin:4px 0; }
  .row.wrap { flex-wrap:wrap; }
```

- [ ] **Step 4: The Edits tab in `edits.js`**

Extend Task 12's `edits.js`: change its imports to

```js
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { dirtyBadge, pendingLine, undoBlocked } from "./editmodel.js";
import { createFileBrowser } from "./filebrowser.js";
import { store } from "./store.js";
```

and add:

```js
let saver = null;
const fail = e => toast(e.message);

// The Edits tab: pending edits (newest first), why Undo is unavailable, dirty state and the save controls.
export function renderEdits(edits) {
  const e = edits && edits.net_id === activeId() ? edits : null;
  $("edits-count").textContent = e ? e.unsaved : 0;
  $("edits-count").classList.toggle("dirty", Boolean(e && e.dirty));
  const why = undoBlocked(e);
  $("ed-undo").disabled = Boolean(why);
  $("ed-undo-why").textContent = e && e.pending ? why : "";
  const parts = e ? [dirtyBadge(e) || (e.pending ? "Every edit is in a saved copy." : ""),
    e.warnings.length ? `${e.warnings.length} open warning(s): see Issues.` : "",
    e.truncated ? "The live check was cut short: run validation." : ""] : [];
  $("ed-status").textContent = parts.filter(Boolean).join(" · ");
  $("ed-list").innerHTML = e && e.entries.length ? e.entries.map(x =>
    `<div class="chg${x.saved ? "" : " unsaved"}">${esc(pendingLine(x))}<div class="diag">` +
    `${esc(Object.entries(x.rows).map(([t, n]) => `${n} ${t}`).join(", "))} · v${x.version}${x.saved ? " · saved" : ""}</div></div>`).join("")
    : '<span class="empty">No edits yet. Click a row, then a cell, to edit it; or fix an issue.</span>';
}

// Save a copy into `folder`. Open warnings are listed first, and saving anyway is an explicit choice.
function save(folder) {
  const e = store.get().edits, n = e ? e.warnings.length : 0;
  const action = { type: "save_network", output_dir: folder, name: $("ed-save-name").value.trim(),
    output_format: $("ed-save-format").value };
  if (n) {
    const shown = e.warnings.slice(0, 10).map(w => `• ${w.message}`).join("\n");
    const more = n > 10 ? `\n… and ${n - 10} more` : "";
    if (!window.confirm(`${n} edit warning${n === 1 ? " is" : "s are"} still open:\n${shown}${more}\n\nSave the copy anyway?`)) return;
    action.accept_warnings = true;
  }
  dispatch(action).then(() => toast("Saving a copy… (see Jobs)")).catch(fail);
}

export function wireEdits() {
  $("ed-undo").onclick = () => dispatch({ type: "undo_edit" }).catch(fail);
  $("ed-save").onclick = () => {
    if (!$("ed-save-name").value.trim()) { toast("Name the copy first."); $("ed-save-name").focus(); return; }
    const fb = $("ed-save-fb");
    fb.hidden = !fb.hidden;
    if (fb.hidden) return;
    saver ||= createFileBrowser(fb, { kinds: [], pickFolder: true, onPick: entry => { fb.hidden = true; save(entry.path); } });
    saver.show();
  };
}
```

`save_network` is a job: the request answers 202 at once, and the outcome arrives as a `job` event in the Jobs
panel (a refusal lists the warnings in its history entry).

- [ ] **Step 5: The dirty badge in the network switcher**

In `header.js`, import `{ dirtyBadge }` from `./editmodel.js`, and in `renderHeader` change the option text to show
the badge (plugins design, UX principle 7):

```js
  const badge = n => { const b = dirtyBadge((server.edits || {})[n.id]); return b ? ` • ${b}` : ""; };
  sel.innerHTML = server.networks.length
    ? server.networks.map(n => `<option value="${esc(n.id)}"${n.id === server.active ? " selected" : ""}>${esc(n.label)}${esc(badge(n))}</option>`).join("")
    : '<option value="">No network open</option>';
```

`editmodel.js` is import-free, so `header.js` importing it adds no cycle.

- [ ] **Step 6: Wire it**

In `main.js`:
- import `{ renderEdits, wireEdits }` from `./edits.js` (next to Task 12's `onEditsState`);
- call `wireEdits()` in `boot()` with the other `wire*()` calls;
- add to `wireStore()`: `store.subscribe(["edits"], s => renderEdits(s.edits));`

- [ ] **Step 7: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass. Every new id is in `index.html`, and every import resolves.

- [ ] **Step 8: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): fix editor, delete with a cascade preview, Edits tab with undo, dirty badge and save a copy"
```

---

### Task 16: Docs, the full suite, lint, and the browser walk-through

**Files:**
- Modify: `packages/netstead/docs/cookbook/workbench.md`
- Modify: `docs/design/2026-10-02-netstead-workbench-design.md`, `docs/design/README.md`

- [ ] **Step 1: The Workbench cookbook**

In `packages/netstead/docs/cookbook/workbench.md`, add before `## Language models …`:

```markdown
## Validate and fix

- **Issues → Run validation** checks the spec, the keys and the quality rules, as a background job. The
  rules use **Settings → Validation** (`validation.rules`, keyed by rule code, such as
  `quality.high_speed_residential`).
- Click an issue: its record is focused, the map flies to it and its row is marked. Click a dot on the map:
  the Issues tab opens on that record's issues. Rows with issues are marked in the table.
- Filter by severity, table and code. **This record** lists only the focused record's issues. Issues with
  no place on the map are listed under **Unlocated**.
- After an edit the validation says it is stale: **Re-run validation** checks again. **Export report**
  downloads the offline HTML report for a current validation.

## Edit tables

- **In the table:** click a row to focus it, then click one of its cells, type, and press Enter (Escape
  cancels; an empty value clears the cell). The key column is not edited in place.
- **From an issue or Details:** **Fix** (on an issue) and **Edit…** (in Details) open a small editor for any
  property of the record, or of every selected link at once.
- **Delete…** (Details or the editor) first says what goes with the record: a link takes its lanes and
  time-of-day rows. A node that a link still uses cannot be deleted.
- **Adding rows** is Python or the API only: `app.do(AddRows(table="node", rows=[{...}]))`.
- Each edit is one action in the session history (so "copy as Python" replays it), bumps the network's
  version, and is listed in the **Edits** tab. **Undo last** reverses your newest edit; changes a plugin made
  are undone in that plugin.

### Edit warnings

An edit the spec disagrees with is still applied, and warned about at once: a foreign key that is not in the
referenced table, a required field left empty, a value of the wrong type or outside the allowed list, or a
duplicate key. The cell is underlined (hover for why), the row is marked, and the warning is listed at the
top of the Issues tab with a **Fix** button. A later edit that puts it right clears the warning.

### Save a copy

**Edits → Save a copy** writes the edited network to a new folder or file inside your allowed folders; the
network you opened, local or remote, is never written to. If edit warnings are still open, they are listed and
you choose whether to save anyway (`SaveNetwork(..., accept_warnings=True)` in Python). The badge in the
network switcher and on the Edits tab counts edits no saved copy holds yet.
```

- [ ] **Step 2: The design records**

In `docs/design/2026-10-02-netstead-workbench-design.md`, below the P1b plan line under the phasing table, add:

```markdown
P2 plan: [2026-10-07-workbench-p2-plan.md](2026-10-07-workbench-p2-plan.md): validation and direct table edits in core
(live warnings, cascading deletes, undo, Save a copy), built on plugins Part 1. ProjectCard editing is the cards
plugin's ([scope](2026-10-07-cards-plugin-scope.md)).
```

In `docs/design/README.md`, set this plan's status to `implemented` with the PR number, move it from "In flight" to
the plans table, and update the Workbench design row's notes ("P2 implemented; next: …").

- [ ] **Step 3: The full tier, before merge**

Run: `uv run --all-extras pytest packages -n auto -q -m ""`
Expected: all pass, including `slow` (the doc contract test runs the cookbook pages) and `perf`.

Run: `uv run ruff check packages && uv run ruff format --check packages && uv run lint-imports && uv run python scripts/lint_no_sql.py`
Expected: clean. `lint-imports` keeps every contract: `netstead.workbench` imports no plugin package.

- [ ] **Step 4: Browser walk-through**

Start the app through `preview_start`, with a `.claude/launch.json` entry that runs
`uv run netstead app packages/netstead/netstead/fixtures/leavenworth/parquet --port 8852`. Then check each item:

1. **Validate.**
   - Issues → **Run validation**. The Jobs badge counts it, and the tab then reads
     `Validated v0: 272 warnings, 16 info`.
   - Orange dots appear on the map, and the Unlocated list has 17 entries.
2. **Issue ↔ map ↔ row.**
   - Split view, link table. Click a `quality.high_speed_residential` issue. The map flies to the link, its row
     is focused and scrolled into view, and the row carries the issue mark.
   - Click another dot on the map. The Issues tab opens on **This record**, with that issue marked.
3. **Fix from an issue.**
   - Click **Fix** on link 1's issue. The editor shows `free_speed`, now 40. Enter `30` and Apply.
   - The row shows 30, and the focus and table page are unchanged (no reset).
   - The Edits tab lists `#1 link 1: free_speed = 30.0 (…)`, the badge reads 1, the network switcher shows
     `• 1 unsaved`, and the bottom strip shows `app.do(EditCells(...))`.
   - The Issues tab says the validation is stale. **Re-run validation** gives 271 warnings, and **Export
     report** downloads `leavenworth-validation.html`.
4. **Cell edit with a warning.** Focus link 2's row, click its `from_node_id` value, type `424242`, Enter. The cell
   is underlined (hover: "is not a node.node_id"), the row is marked, and Issues → Edit warnings lists it. Click
   the cell again, type link 2's old value, Enter: the warning clears.
5. **Refusal.** Click link 1's `lanes` cell, type `1.5`, Enter. A toast says it does not fit; nothing changes
   and no edit is listed.
6. **Undo.** Edits → **Undo last**. The value is back, the entry is gone, and the history has `UndoEdit`.
7. **Delete.** Details for a link → **Delete…**. The confirmation names the lane rows that go with it. Confirm:
   the link disappears from the map, and the lane count in the rail drops. **Undo last** brings both back.
   Details for node 1 → **Delete…**: refused, naming the links that use it.
8. **Save with a warning.** Make an edit with a warning (step 4's first half), then **Save a copy**: the
   confirmation lists the warning. Cancel: nothing is written. Save again and accept: the job writes the copy,
   the badge clears, and the opened fixture is unchanged (re-open it to check).
9. **Network.** Nothing goes to a non-local host except the basemap tiles and the CDN.

Fix anything that fails before opening the PR. Reset the viewport afterwards (`preset: "desktop"`) if you changed
it.

- [ ] **Step 5: Commit**

```bash
git add packages/netstead/docs/cookbook/workbench.md docs/design/2026-10-02-netstead-workbench-design.md docs/design/README.md
git commit -m "docs(workbench): validate, edit tables, edit warnings and save a copy"
```

---

## Self-review (against the design)

**Spec coverage:**

| Requirement | Where |
|---|---|
| Validation + quality checks as a job, rule config from Settings | Task 7 (`RunValidation`, `run_validation`, `rule_configs`; `severity_override` checked at load) |
| Issues panel: issue ↔ map marker ↔ table row | Task 7 (keys and anchors), 8 (`/issues`, `/issues/markers`), 13 (list, markers, row marks, `onIssueMarker`) |
| Filter by severity, table, code; unlocated listed separately | Task 8 (`query`, facets, `located=no`), 13 (selects, "This record", Unlocated) |
| Export report via `render_validation_html` | Task 8 (`/report.html`, refused when stale), 13 (button) |
| Edits in the UX: cell edits; the ported "fix locally" editor from an issue | Task 14 (cells), 15 (`fixeditor.js`, Details), 11 (`parseCell`, ported from `coerceLikely`) |
| Edits apply through `Host.mutate`/`Session.mutate` as corral `update_rows`/`delete_rows`/`add_rows`, in history, version bump + lineage | Task 3 (plans), 5 (`mutate` + ledger), 6 (Actions on the registry) |
| Live, non-blocking warnings: FK missing, required empty, type/enum, duplicate key; on cell, row and Issues tab | Task 4 (`check_rows`), 5 (re-check after every mutation), 13 (Issues list), 14 (cell and row marks) |
| Warnings shown before saving; explicit confirmation while any remain | Task 9 (`accept_warnings`), 15 (confirmation listing them) |
| Pending-edits list with a dirty badge (UX principle 7) | Task 5 (`EditLedger.summary`), 10 (`/edits`), 15 (Edits tab, tab and switcher badges) |
| Undo of the last edit, one at a time, itself a recorded Action (decision a) | Task 5 (`undo_last`), 6 (`UndoEdit`), 15 (button) |
| Delete cascades through spec FKs and shows what goes; a referenced node is refused (decision b) | Task 3 (`plan_delete`), 10 (`delete-plan`), 15 (`deleteRecord`) |
| Adding rows from Python and the API (decision b) | Task 3 (`plan_add`), 6 (`AddRows`) |
| Live checks per edit; full validation stale with a manual Re-run (decision c) | Task 4–5 (live), 7 (`stale`), 13 ("Re-run validation") |
| Built on plugins Part 1; Actions on the registry, not the closed union (decision d) | Header; Tasks 6, 7, 9 (`CORE_ACTIONS`) |
| `to_projectcard` always writes `ignore_missing`; `host.selection` exposes the facility form | Task 2 |
| Save writes a new copy inside the allowed roots, never overwrites; `OutOfSyncWarning` handled | Task 9 |
| Nothing mutates silently (UX principle 3) | Task 5: every mutation, core or plugin, is a pending edit with its source |
| corral null-safe undo | Task 1 |
| An edit keeps the current view | Task 12 (`netChange`, `onNetworkEdited`) |

**Placeholder scan:**
- No "TBD" and no "similar to Task N".
- New files are given in full, except `fixeditor.js` (a one-line stub in Task 13, given in full in Task 15) and
  `edits.js` (the feed in Task 12, the tab added in Task 15).
- Conditional instructions remain only where the plan cannot know a fact. Each says what to check and what to do:
  - Part 1's exact names and signatures (Task 0 and Task 5, Step 1);
  - `DataPackage`'s required fields (Task 3);
  - `Issue` positional arguments (Task 7);
  - a private-import lint on `_schemas` (Task 4).

**Name consistency:**
- Python: `plan_update/plan_delete/plan_add`, `EditPlan(edits, summary, rows, keys, recheck)`, `EditRefused`,
  `check_rows`, `CheckResult.for_rows/to_dict`, `touched_keys`, `EditLedger.add/last/pop/touched/mark_saved/summary`,
  `PendingEdit.view`, `Session.mutate/undo_last/edit_check/edits_payload/delete_preview/issue_set` and
  `Host.undo/edit_warnings/plan_*` are used the same way in Tasks 3–15.
- Action `type`s: `run_validation`, `edit_cells`, `delete_rows`, `add_rows`, `undo_edit`, `save_network`. These are
  what the front end dispatches (`issues.js`, `table.js`, `fixeditor.js`/`editmodel.js`, `edits.js`).
- Store keys (`drawerTab`, `issues`, `issueFilter`, `issueFocus`, `showIssues`, `edits`) are the same across
  `store.js`, `main.js`, `issues.js`, `map.js`, `table.js` and `edits.js`.
- Ids added to `index.html`: `side-tabs`, `issues-count`, `edits-count`, `iss-*`, `tg-issues`, `ed-*`. None were
  removed. The static tests enforce both directions.

**Risks:**
- **Edits on large networks.** Each edit to a big table round-trips that table through Arrow, and every edit to
  `link` or `node` re-packs `network.bin`. Regional networks with 1M+ links will feel it; the follow-up is a
  DuckDB-native `update_rows`.
- **Live checks grow with the ledger.** They re-check every key any pending edit touched; `MAX_CHECKED_KEYS` bounds
  each table, and the Edits tab says when the check was cut short.
- **Issue positions.** They assume DuckDB returns a table in the same order to `to_pandas()` and to
  `select(pk).to_pandas()`. Task 7 pins this on Leavenworth, whose tables happen to be sorted by key. A multi-file
  parquet source could break it; the longer-term fix is for rules to report keys in `Issue.extra`.
- **`warnings.catch_warnings` in `SaveNetwork`** is process-global. A warning raised on another thread during a
  save could be swallowed into the save's notes. Jobs are few and short; noted in the code.
- **Concurrent validation and edits.** An edit while a validation job runs can give the job a mix of versions. The
  result is stored with the version it started on, so it shows as stale and the UI offers a re-run.
- **Undo after a plugin change.** Strict LIFO across sources means core's Undo is blocked until the plugin undoes
  its own change. That is deliberate (a plugin's draft state stays true), and the Edits tab says who to ask.
- **Part 1 drift.** Snippets that touch `BaseAction`, `CORE_ACTIONS`, `Session.mutate` and `Host` follow the Part 1
  plan, not merged code. Task 0 and Task 5 Step 1 check the names first.
