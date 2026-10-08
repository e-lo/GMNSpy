# Workbench P2 (Validate + Fix + Change log) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate a network in the Workbench, fix what it finds, and keep every fix as a ProjectCard change.
- **Validate.** "Run validation" runs `Network.validate` plus the quality rules as a background job, with the rule
  config from Settings → `validation.rules`. An **Issues** drawer tab links issue ↔ map marker ↔ table row. It
  filters by severity, table and code, and lists unlocated issues separately. An edit marks the result stale;
  one click re-runs it.
- **`netstead.changes`.** A new core package:
  - `NetworkChange`, a discriminated union mirroring the ProjectCard change types:
    `roadway_property_change`, `roadway_addition`, `roadway_deletion`, and the four transit types, which are
    declared now and answer "not yet supported";
  - `apply_change(net, change) -> ChangeResult`, lowered to corral `apply_edit`, atomic, and reversible with
    `reverse_change`;
  - `DraftCard` (project, tags, dependencies, `changes[]`) and `ChangeLog` (apply, undo, commit);
  - `.yml` export and import, and validation against the vendored projectcard JSON schema through an optional
    `[projectcard]` extra;
  - field names mapped through the maintained `changes/mappings/gmns_to_wrangler.yaml`.
- **Fix editor.** The offline report's "Fix locally" editor, ported to an ES module. Each fix dispatches an
  `ApplyEdit` action, which compiles to a `NetworkChange`. A **Changes** drawer tab shows the draft card (changes,
  existing → set, selection) with commit, undo, export `.yml`, validate and import (including a `map/edits` YAML).
- **Export report.** The app downloads the existing `render_validation_html` for the last validation.
- **Two logs.** The session history (Actions) and the change log (ProjectCards) stay separate, as the design says.

**Architecture:**
- `netstead.changes` depends only on corral and the core `netstead` package, never on the workbench. A notebook user
  gets `apply_change`, `ChangeLog` and cards without the app.
- One applier: `apply_change` opens a corral `editing.Session`, adds one or more `Edit`s (`update_rows`,
  `delete_rows`, `add_rows`), and so inherits corral's atomicity: if any edit fails, the ones before it are
  reversed. `ChangeResult.edits` keeps the `EditResult`s, so `reverse_change` reverses them in LIFO order.
- The workbench keeps one `ChangeLog` per open network (`Session.changes`). Every mutating action goes through
  `Session._apply_change`, which applies, appends to the draft, and bumps the handle's `version`. Caches are keyed
  by version, so the map buffer, tables and related records rebuild.
- Validation is a job, like Open and Build. `Session._commit` is generalised: a job returns an *outcome* with a
  `commit(session)` method (`_Loaded`, `_Validated`, `_Saved`), still committed and recorded in one critical
  section.
- Issues are tied to records **at validation time**. A rule reports a row *position*, which is only meaningful in
  the table order it read, at that version. `locate_issues` turns positions into primary keys and an `anchor`
  (`{"link": id}`, `{"node": id}`, or `{"lonlat": [x, y]}`). The browser places anchors from the network buffer it
  has already decoded, so no geometry is sent twice.
- New read-only routes, none recorded: `GET …/issues`, `…/issues/markers`, `…/report.html`, `…/changes`,
  `…/changes/card.yml`, `…/changes/validate`.
- Front end:
  - the right drawer gains tabs: **Details | Issues | Changes**;
  - an edit (same network id, new version) keeps the focus, highlights, table and scope, instead of resetting
    them the way a network switch does;
  - pure rules live in import-free `issuelist.js` and `editmodel.js`, unit-tested under node;
  - DOM wiring lives in `issues.js`, `fixeditor.js` and `changes.js`.

**Tech Stack:**
- Python 3.11, pydantic v2, FastAPI.
- ibis 12 on DuckDB through corral. No raw SQL: `lint_no_sql.py` must stay clean.
- `[projectcard]` extra = `pyyaml` + `jsonschema>=4.18` (for its `referencing` registry). Both are small and
  already in other extras. The `projectcard` package is a **dev-only** dependency, for the interop test: at
  runtime it pulls `ruff`, `toml`, `tabulate` and `jsonref`.
- MapLibre GL 4.7.1 and deck.gl 9.0.38 (already loaded). Native ES modules, no build step. Node only in tests.

**Spec:** [2026-10-02-netstead-workbench-design.md](2026-10-02-netstead-workbench-design.md):
- "Two audit logs: session Actions vs ProjectCard changes";
- §b "Inspect & Validate workspace": Validation and Fixing;
- "Transit (designed now, built in a later phase)": the `NetworkChange` transit variants;
- the phasing row P2.

**Branch:** `feat/workbench-p2`, cut from `origin/feat/workbench-p1b` (P0 + P1a + NL providers + P1b).

**Conventions:**
- Run commands from the repo root.
- **Tiered tests:**
  - while iterating, the task's own paths: `uv run --all-extras pytest <paths> -q`;
  - before every commit: `uv run --all-extras pytest packages -n auto -q` (the fast default tier);
  - before merge, once, in Task 18: `uv run --all-extras pytest packages -n auto -q -m ""` (everything, including
    `slow` and `perf`).
- Lint: `uv run ruff check packages && uv run ruff format --check packages`. Tasks 7 and 18 also run
  `uv run lint-imports`; Task 18 runs `uv run python scripts/lint_no_sql.py`.
- Ruff enforces Google-style docstrings (`D`) outside `tests/`, line length 120. `--doctest-modules` is on, so every
  `>>>` example below is a test.
- Not every snippet below is pre-wrapped to 120 columns. After pasting, run `uv run ruff format <files>`, then the
  check pair.
- `filterwarnings = error`: a stray warning fails a test. Writing an edited network raises corral's
  `OutOfSyncWarning`, which Task 12 handles deliberately.
- Never write under `netstead/fixtures` (the conftest guard fails the session). Mutating tests load their own
  `Network` per test and write to `tmp_path`.
- Fixtures: **Leavenworth** (`leavenworth.parquet_dir()`: 339 links, 121 nodes, 429 lanes, 1 `link_tod` row, plus
  `geometry`) for anything edit- or validation-shaped; **RDU** (link + node only) where the existing session tests
  use it.
- Pure front-end logic goes in import-free modules, tested with the `node_module` fixture (`conftest.py`). DOM
  wiring is covered by the static tests (`test_relative_imports_resolve_to_real_exports`,
  `test_every_element_id_used_by_js_exists_in_index`, `test_js_syntax`) and by the browser walk-through in Task 18.
- **Honesty note.** These were probed on `origin/feat/workbench-p1b` while writing this plan (scripts in the
  scratchpad, not committed):
  - **corral `apply_edit` on a lazy table** (Leavenworth parquet and CSV): it reads the whole target table to Arrow
    (`_arrow_of(table.expr)`), applies the op in an ibis memtable, and swaps `table.expr` for
    `engine.from_arrow(new)`, an in-memory DuckDB table. Untouched tables stay lazy. A one-row `update_rows` on
    `link` took 0.02 s warm; `reverse_edit` 0.04 s.
  - **A real undo bug:** `_reverse_update_rows` and `_reverse_add_rows` anti-join on every untouched column with
    `=`, and `NULL = NULL` is never true. Undoing an edit to a link whose `name` is null (CSV link 27) left **two**
    copies of link 27 (339 → 340 rows). An ibis `identical_to` anti-join fixes it (probed). Task 1.
  - Undo moves the restored row to the end of the table (order is not preserved); dtypes are preserved.
  - `delete_rows` + reverse restores the row count; an edited network writes to parquet and CSV and reads back
    with the edit, but `Network.write` warns `OutOfSyncWarning` naming the source path.
  - `Network.validate()` gives 17 issues on Leavenworth (16 `structural.missing_optional_resource` info, 1
    `fk.unverifiable` warning), and `run_quality` gives 271 `quality.high_speed_residential` warnings. All
    quality issues carry `table="link"`, `column="free_speed"` and a row position. Link 1 (`free_speed` 40,
    residential) is one of them. Validation after an edit raises no warning.
  - Row order: `table.select(pk).to_pandas()` matches `table.to_pandas()` order for link, node and lane in parquet,
    CSV and zip. Those tables are stored sorted by key, so this check is weak; Task 9 pins it with a test.
  - **ProjectCard schema** (network-wrangler/projectcard; latest release v0.3.3, 2024-10-16; Apache-2.0), read from
    `main`:
    - `select_links` and `select_nodes` **require `ignore_missing`**;
    - `roadway_property_change` has `additionalProperties: false`, so no per-change `notes`;
    - a property set allows only `existing`/`set`/`change` of type `number | string` (no null, no bool), plus
      `existing_value_conflict`;
    - `roadway_link` requires `A, B, name, model_link_id, roadway, lanes, walk_access, bike_access, drive_access`;
    - the transit addition type is named `transit_route_addition`.
    - Task 3 vendors the **v0.3.3 tag**; its test pins the change-type names, so a difference from `main` shows up
      there.
  - Consequences found while reading code: today's `to_projectcard` omits `ignore_missing` unless it is false, and
    `map/edits.dump_edit_log` writes `facility: {model_link_id: [...]}` (not under `links`) plus a per-change
    `notes`. Neither validates against the schema. Task 2 fixes the first; Task 8 reads the second tolerantly.
  - The plan as a whole has **not** been executed. Expected results say "pass" plus the new test names, not counts.
    Where a step fails, fix the plan's code; don't weaken the test.

---

## Open questions (recommendations; not yet decided)

1. **Which ProjectCard schema, and do we vendor it?**
   - **Recommended:** vendor the **projectcard v0.3.3** release's `projectcard/schema/` tree verbatim into
     `netstead/changes/schema/projectcard/`. Add a `VERSION` file (tag + commit) and the upstream `LICENSE`
     (Apache-2.0).
     - Validate offline with `jsonschema` + `referencing`, resolving the files' relative `$ref`s against a made-up
       base URI, so nothing is fetched.
     - Bump the schema by re-running the Task 3 copy step and re-running the tests.
   - Don't depend on the `projectcard` package at runtime: it pulls `ruff`, `toml`, `tabulate` and `jsonref`. It
     goes in the workspace `dev` group only, for the "a card we write loads in `projectcard.read_card`" interop test.
   - *Alternative:* `[projectcard] = ["projectcard>=0.3.3"]` and call its validator. That is less code, but a
     heavier extra, and the schema version moves when the user upgrades.
2. **Transit variant names.** The design lists `add_transit_routes`; the schema calls it `transit_route_addition`.
   - **Recommended:** mirror the schema (`transit_property_change`, `transit_routing_change`,
     `transit_route_addition`, `transit_service_deletion`).
   - Fix the design doc's name in Task 18.
3. **How far do `roadway_addition` and `roadway_deletion` go in P2?**
   - **Recommended:**
     - **Deletion is complete:**
       - the applier;
       - a "Delete link" button in Details;
       - card export and import.
       - Deleting a link also deletes the rows whose foreign key points at it: `lane`, `link_tod`, `segment`, … as
         read from the spec (one change, one undo).
       - Deleting a node that a remaining link still uses is refused.
       - `clean_nodes` removes end nodes that nothing uses any more.
       - Orphaned `geometry` rows are left, as Wrangler's `clean_shapes: false` does.
     - **Addition** works in the applier, through `ApplyChange` (Python and the assistant) and through card import
       and export. There is **no drawing UI** in P2.
       - Added links without geometry draw as straight lines between their nodes (`viz/buffers` already falls back
         to node coordinates).
       - On export, Wrangler-required link fields with no GMNS column (`walk_access`, …) are derived through the
         mapping file. Anything still missing shows up as a schema error, never as an invented default.
4. **How are edits to lazy (DuckDB) tables applied?**
   - Verified: corral reads the edited table to Arrow and replaces it with an in-memory DuckDB table on the same
     engine; other tables stay lazy. Each later edit to that table costs O(table) in Arrow (two copies at peak), and
     each edit re-packs `network.bin`.
   - **Recommended:** accept this for P2. It is exact and reversible, and interactive fixes are a few at a time.
     - Task 6 adds a `perf`-marked test: 200 000 links, one update plus its reverse, under 5 s.
     - Follow-up: a corral `update_rows` that runs as an ibis `mutate` against a DuckDB temp table, with no Arrow
       round trip.
5. **Is undo limited to the draft card?**
   - **Recommended:** yes.
     - `UndoChange` pops and reverses the **last** change of the active draft (LIFO, one per click).
     - Committed cards are frozen and stay in the handle's `lineage`.
     - Undo is itself a recorded Action, so a replayed session reproduces the same network.
     - No redo in P2: re-applying is re-dispatching the `ApplyEdit` shown in the history.
6. **Where is the edited copy saved, especially when the network came from a remote URL?**
   - **Recommended:** edits live on the open handle, in memory. The source is never written to, whether it is a
     local folder or `s3://…`.
     - A new `SaveNetwork(output_dir, name, output_format)` job writes a **new** copy inside `io.allowed_roots`. It
       never overwrites, and it reuses the build's staging, write and promote steps.
     - The handle keeps its `source` and `lineage`; the result reports the path and any `OutOfSyncWarning` text
       (scrubbed).
     - The `.yml` card is the portable record. Applying it to the base reproduces the copy, once `apply_card` lands.
7. **Values a ProjectCard cannot carry.** `set` must be a number or string.
   - **Recommended:** refuse an empty `set` and list-valued `set` with a clear message ("a ProjectCard cannot set a
     property to empty").
   - Booleans become `1`/`0`, which Wrangler's access flags use anyway.
   - Clearing a value stays a direct Python edit, outside the change log.
8. **Re-validation after edits.**
   - **Recommended:** an edit marks the issue set **stale** (its version ≠ the network's). The Issues tab says so and
     offers **Re-run**. Export report is refused until it is re-run.
     - Marking individual issues as "edited since" needs a per-change record of versions; that is a follow-up.
     - There is no automatic re-run: validation of a regional network takes minutes (the Leavenworth cold run was
       8 s).
     - *Alternative:* a `validation.rerun_after_edit` setting, default off.
9. **Provenance for query-form selections.**
   - A change cannot carry extra fields (`additionalProperties: false`).
   - **Recommended:** write provenance as card-level `notes` lines: `netstead.resolved[<i>]: model_link_id=[…]` and
     `netstead.note[<i>]: …`. This follows the `key: value` notes convention `map/edits` already uses.
     - Import reads them back, so our own query-form cards re-import onto the ids they resolved to.
     - Re-resolving a query on another network version is `apply_card` (later). P2 import refuses a query facility
       that has no provenance, and says so.
10. **The offline report's edit-log YAML.**
    - **Recommended:** import it tolerantly: `facility: {model_link_id: […]}` at the top level, per-change `notes`
      read into `note`.
    - Leave the offline writer as it is, and flag a follow-up to make it schema-valid. It is a separate surface,
      with its own tests.
11. **`ignore_missing` on our own selectors.**
    - **Recommended:**
      - click-picks and deletions write `ignore_missing: false`: a fix aimed at a missing link should fail loudly;
      - NL and query selections carry the intent's value (default `true`, Wrangler's default).

## Decisions (technical, made here)

1. **corral's reverse joins become null-safe** (Task 1): an `identical_to` anti-join for `add_rows` and
   `update_rows`. The fix is generic, and P2's undo depends on it.
2. **`apply_change` coerces values to the column's ibis dtype** before handing them to corral:
   - integer columns take integral numbers or numeric text;
   - float columns take numbers or numeric text;
   - text columns take anything scalar, as text;
   - boolean columns take `true/false/1/0`;
   - other types (geometry, dates) are refused in P2.
3. **`existing` follows Wrangler's `existing_value_conflict`:** `error` (our default), `warn`, `skip`.
   - The editor fills `existing` from the current value when all target rows share one value.
   - A delta (`change`) on records with different current values becomes one `update_rows` per distinct value.
4. **Selections are GMNS-native in the model, Wrangler-native only in the card:**
   - `Selection.ids` are `link_id`/`node_id`;
   - `Selection.query` is already card-form (`to_projectcard(..., form="query")`);
   - `Selection.resolved` is the provenance.
   - P2 applies a query selection to its `resolved` ids; re-resolving is `apply_card`.
5. **FK helpers move to core:** `ForeignKey` / `foreign_keys` / `primary_keys` go from `workbench/related.py` to
   `netstead/spec/keys.py`, so `netstead.changes` (deletion cascade) and the workbench share one reading of the
   spec. `related.py` re-exports them unchanged.
6. **Job outcomes commit themselves:** `_Loaded` / `_Validated` / `_Saved` each have `commit(session) -> dict`, run
   inside `Session._commit`'s one critical section.
7. **Issue numbers** are positions in the stored report (`i`). Markers and pages refer to them. A new run replaces
   the set.
8. **Bounds:**
   - `/issues` pages hold at most 500;
   - `/issues/markers` returns at most `MAX_MARKERS = 50_000` located markers (`truncated` beyond that), plus a
     per-record index of issue numbers for row marks and the "This record" filter.
9. **Export report refuses a stale set** (409, "re-run validation, then export"). Positions in the report are only
   valid at the version it ran on.
10. **Rule config keys are rule codes** (`validation.rules["quality.high_speed_residential"]`).
    - `RuleSettings.severity_override` becomes `Literal["error", "warning", "info"] | None`, so a typo fails at
      settings load, not mid-run.
    - Codes not registered are reported as `unknown_rules` in the run result.
11. **An edit keeps the view:** `linking.netChange(prev, next)` → `same | edited | switched`. Only `switched` resets
    focus, highlights and the table. `edited` refreshes rail counts, rows, related records, details, issues and
    changes in place.
12. **Issue markers are a store-only layer toggle** ("Issues" in Layers), not a `Style` field. It is per tab and not
    recorded, like the focus.
13. **After a deletion, a selection that includes a deleted link is cleared.** It would otherwise point at missing
    links.

## Scope notes

- **In P2:**
  - the corral undo fix;
  - `to_projectcard` `ignore_missing`;
  - the vendored schema and the `[projectcard]` extra;
  - `netstead.changes` (types, mapping, apply, cards, log);
  - `RunValidation`, `ApplyEdit`, `ApplyChange`, `UndoChange`, `CommitCard`, `ImportCard`, `SaveNetwork`;
  - issues, markers, report and changes routes;
  - drawer tabs;
  - the Issues panel and markers;
  - the fix editor;
  - the Changes tab;
  - docs.
- **Deferred:**
  - `apply_card` (re-resolving query selections; a card applied to another network version);
  - scenarios;
  - redo;
  - a link-drawing UI for additions;
  - transit changes (P6: the union is declared, and handlers answer "not yet supported");
  - `pycode` and `roadway_managed_lanes`;
  - auto re-validation;
  - making the offline report's YAML writer schema-valid (follow-up);
  - DuckDB-native `update_rows` (follow-up, Open question 4);
  - card conflict and dependency resolution.
- **Unchanged:**
  - the P1a wizard and jobs (apart from the `_commit` refactor);
  - the P1b linking routes;
  - `map/edits.apply_edits`. It stays the offline Python path; the Workbench imports through
    `netstead.changes.read_card` instead.

## File structure

| Path | Responsibility |
|---|---|
| `packages/corral/corral/editing/apply.py` (modify) | Null-safe `_reverse_add_rows` / `_reverse_update_rows` |
| `packages/netstead/netstead/select/emit.py` (modify) | `to_projectcard` always writes `ignore_missing` |
| `packages/netstead/netstead/changes/__init__.py` (new) | Public surface of `netstead.changes` |
| `packages/netstead/netstead/changes/schema/projectcard/**` (new, vendored) | projectcard v0.3.3 JSON schema + `VERSION` + `LICENSE` |
| `packages/netstead/netstead/changes/schema.py` (new) | `SCHEMA_DIR`, `SCHEMA_VERSION`, `card_errors`, `validate_card`, `CardInvalid` |
| `packages/netstead/netstead/changes/mappings/gmns_to_wrangler.yaml` (new) | Maintained GMNS ↔ Wrangler names, values, derived fields |
| `packages/netstead/netstead/changes/mapping.py` (new) | `FieldMap`, `load_mapping` |
| `packages/netstead/netstead/changes/types.py` (new) | `PropertyChange`, `Selection`, the `NetworkChange` union, `parse_change` |
| `packages/netstead/netstead/changes/apply.py` (new) | `apply_change`, `reverse_change`, `ChangeResult`, `ChangeError` family |
| `packages/netstead/netstead/changes/card.py` (new) | `DraftCard`, `Dependencies`, `to_card`/`from_card`, `to_yaml`/`read_card` |
| `packages/netstead/netstead/changes/log.py` (new) | `ChangeLog` (apply, apply_all, undo, commit) |
| `packages/netstead/netstead/spec/keys.py` (new) | `ForeignKey`, `foreign_keys`, `primary_keys` (moved from `workbench/related.py`) |
| `packages/netstead/netstead/workbench/related.py` (modify) | Re-export the moved helpers |
| `packages/netstead/netstead/config.py` (modify) | `RuleSettings.severity_override` literal |
| `packages/netstead/netstead/workbench/issues.py` (new) | `IssueSet`, `rule_configs`, `run_validation`, `locate_issues` |
| `packages/netstead/netstead/workbench/editing.py` (new) | `compile_edit`, `change_view` |
| `packages/netstead/netstead/workbench/actions.py` (modify) | `RunValidation`, `ApplyEdit`, `ApplyChange`, `UndoChange`, `CommitCard`, `ImportCard`, `SaveNetwork` |
| `packages/netstead/netstead/workbench/session.py` (modify) | Outcomes, issues/changes state, the new handlers |
| `packages/netstead/netstead/workbench/build.py` (modify) | `output_path` shared by Build and Save |
| `packages/netstead/netstead/workbench/files.py` (modify) | `.yml`/`.yaml` → kind `card` |
| `packages/netstead/netstead/workbench/routes/common.py` (new) | `network_handle` (shared 404/501 logic) |
| `packages/netstead/netstead/workbench/routes/edit.py` (new) | `/issues`, `/issues/markers`, `/report.html`, `/changes`, `/changes/card.yml`, `/changes/validate` |
| `packages/netstead/netstead/workbench/routes/network.py`, `server.py`, `__init__.py` (modify) | Use `network_handle`; mount `edit_router`; export actions |
| `packages/netstead/netstead/workbench/static/js/issuelist.js`, `editmodel.js` (new) | Pure rules (node-tested) |
| `packages/netstead/netstead/workbench/static/js/issues.js`, `fixeditor.js`, `changes.js` (new) | DOM: Issues tab, editor, Changes tab |
| `packages/netstead/netstead/workbench/static/js/{linking,store,main,side,map,table,history}.js`, `index.html`, `app.css` (modify) | Tabs, edit-aware refresh, markers, row marks |
| `packages/netstead/pyproject.toml`, `pyproject.toml` (modify) | `[projectcard]` extra, wheel includes, dev dep, import-linter source |
| Tests (new): `test_changes_schema.py`, `test_changes_mapping.py`, `test_changes_types.py`, `test_changes_apply.py`, `test_changes_card.py`, `test_workbench_issues.py`, `test_workbench_changes.py`, `test_workbench_edit_routes.py` | |
| Tests (modify): `corral/tests/editing/test_editing.py`, `test_select_emit.py`, `test_workbench_js.py`, `test_workbench_session.py`, `test_workbench_files.py` | |
| `packages/netstead/docs/cookbook/workbench.md`, `packages/netstead/docs/cookbook/project-cards.md` (new), `docs/design/2026-10-02-netstead-workbench-design.md` (modify) | Docs |

---
### Task 0: Branch and baseline

**Files:** none.

- [ ] **Step 1: Cut the branch**

```bash
git fetch origin && git checkout -b feat/workbench-p2 origin/feat/workbench-p1b
```

- [ ] **Step 2: Record the baseline**

Run: `uv run --all-extras pytest packages -n auto -q`
Expected: all pass. Record the count in the PR description. Every later task only adds tests, except that Task 9
edits one expectation in `test_workbench_session.py`.

No commit.

---

### Task 1: corral: undo restores rows that contain nulls

`_reverse_add_rows` and `_reverse_update_rows` find "the rows this edit touched" with an anti-join on every shared
or untouched column, using `=`. `NULL = NULL` is unknown, so a row with any null never matches. Undoing an edit to
such a row then leaves both the edited copy *and* the restored one (probed: CSV link 27, 339 → 340 rows).

**Files:**
- Modify: `packages/corral/corral/editing/apply.py`
- Test: `packages/corral/tests/editing/test_editing.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/corral/tests/editing/test_editing.py`, and add `reverse_edit` to the existing
`from corral.editing.apply import apply_edit` line:

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
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/corral/tests/editing/test_editing.py -q -k "null"`
Expected: both FAIL. The update test finds id 2 twice; the add test still finds id 4.

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

- [ ] **Step 4: Run the editing tests**

Run: `uv run --all-extras pytest packages/corral/tests/editing -q`
Expected: all pass, including the two new tests and the existing `test_leavenworth_round_trip`.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/corral/corral/editing/apply.py packages/corral/tests/editing/test_editing.py
git commit -m "fix(corral): undo restores rows that hold nulls (null-safe reverse joins)"
```

---

### Task 2: `to_projectcard` always writes `ignore_missing`

The ProjectCard `select_links` schema marks `ignore_missing` as **required**. `_query_links` writes it only when it
is false, so every card built from a default selection fails validation.

**Files:**
- Modify: `packages/netstead/netstead/select/emit.py`
- Test: `packages/netstead/tests/test_select_emit.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/netstead/tests/test_select_emit.py`:

```python
def test_projectcard_links_always_carry_ignore_missing():
    # The ProjectCard schema requires it on every links selector (select_links.json "required").
    assert to_projectcard(_resolved())["links"]["ignore_missing"] is True
    page = SelectionIntent(facility=Facility(name=["Page Road"]))
    assert to_projectcard(_resolved_result(page), form="query")["links"]["ignore_missing"] is True
    strict = SelectionIntent(facility=Facility(name=["Page Road"]), ignore_missing=False)
    assert to_projectcard(_resolved_result(strict), form="query")["links"]["ignore_missing"] is False
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run --all-extras pytest packages/netstead/tests/test_select_emit.py -q`
Expected: `test_projectcard_links_always_carry_ignore_missing` FAILS with `KeyError: 'ignore_missing'`.

- [ ] **Step 3: Implement**

In `to_projectcard`, add this after the `if form == "query": … else: …` block and before the `from_match` lines:

```python
    # ProjectCard's select_links requires the flag even at its default (the GMNS fragment omits a default true).
    pc["links"]["ignore_missing"] = result.intent.ignore_missing
```

Add to its docstring: `` ``links.ignore_missing`` is always written: the ProjectCard schema requires it.``

- [ ] **Step 4: Run the selection tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_select_emit.py packages/netstead/tests/test_select_cli.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/select/emit.py packages/netstead/tests/test_select_emit.py
git commit -m "fix(select): ProjectCard selectors always carry ignore_missing"
```

---

### Task 3: The vendored ProjectCard schema, the `[projectcard]` extra, and offline validation

**Files:**
- Create: `packages/netstead/netstead/changes/__init__.py`
- Create (vendored): `packages/netstead/netstead/changes/schema/projectcard/**`, plus `VERSION` and `LICENSE`
- Create: `packages/netstead/netstead/changes/schema.py`
- Modify: `packages/netstead/pyproject.toml`, `pyproject.toml`
- Test: `packages/netstead/tests/test_changes_schema.py`

- [ ] **Step 1: Vendor the schema (copy it; do not edit it)**

Clone the tag into a temporary folder outside the repo:

```bash
git clone --quiet --depth 1 --branch v0.3.3 https://github.com/network-wrangler/projectcard /tmp/projectcard-v0.3.3
```

Copy the schema tree and the licence:

```bash
mkdir -p packages/netstead/netstead/changes/schema/projectcard
cp -R /tmp/projectcard-v0.3.3/projectcard/schema/. packages/netstead/netstead/changes/schema/projectcard/
cp /tmp/projectcard-v0.3.3/LICENSE packages/netstead/netstead/changes/schema/projectcard/LICENSE
```

Write `packages/netstead/netstead/changes/schema/projectcard/VERSION`, with the commit from
`git -C /tmp/projectcard-v0.3.3 rev-parse HEAD`:

```text
v0.3.3 <commit sha>
Copied verbatim from network-wrangler/projectcard, projectcard/schema/ (Apache-2.0; see LICENSE).
```

Check the layout:

```bash
ls packages/netstead/netstead/changes/schema/projectcard
```

Expected: `LICENSE VERSION changes defs projectcard.json roadway transit`.

If the tag's tree differs from this, stop and update Task 5's union to match the tag. Task 5's first test names the
change types.

- [ ] **Step 2: Write the failing tests**

Create `packages/netstead/tests/test_changes_schema.py`:

```python
"""The vendored ProjectCard schema validates cards offline (the [projectcard] extra)."""

import copy

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("referencing")

from netstead.changes.schema import SCHEMA_VERSION, CardInvalid, card_errors, validate_card  # noqa: E402

GOOD = {
    "project": "fix speeds",
    "tags": ["fixes"],
    "changes": [
        {
            "roadway_property_change": {
                "facility": {"links": {"model_link_id": [1, 2], "ignore_missing": False}},
                "property_changes": {"free_speed": {"existing": 40, "set": 30}},
            }
        }
    ],
}


def _prop(card):
    return card["changes"][0]["roadway_property_change"]


def test_the_vendored_schema_is_pinned():
    assert SCHEMA_VERSION == "v0.3.3"


def test_a_valid_card_has_no_errors():
    assert card_errors(GOOD) == []
    validate_card(GOOD)  # does not raise


def test_a_links_selector_without_ignore_missing_is_invalid():
    bad = copy.deepcopy(GOOD)
    del _prop(bad)["facility"]["links"]["ignore_missing"]
    assert card_errors(bad)


@pytest.mark.parametrize("prop", [{"set": 1, "change": 1}, {"set": None}, {"existing": 1}])
def test_a_property_needs_exactly_one_scalar_set_or_change(prop):
    bad = copy.deepcopy(GOOD)
    _prop(bad)["property_changes"]["free_speed"] = prop
    assert card_errors(bad)


def test_a_change_takes_no_extra_fields():
    bad = copy.deepcopy(GOOD)
    _prop(bad)["notes"] = "per-change notes are not in the schema"
    assert card_errors(bad)


def test_validate_card_raises_with_every_error():
    with pytest.raises(CardInvalid) as info:
        validate_card({"tags": "not-a-list"})
    assert info.value.errors and str(info.value).startswith("not a valid ProjectCard")


def test_validation_never_touches_the_network(no_network):
    assert card_errors(GOOD) == []
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_schema.py -q`
Expected: FAIL at import, with `ModuleNotFoundError: No module named 'netstead.changes'`.

- [ ] **Step 4: Implement**

Create `packages/netstead/netstead/changes/__init__.py`. Tasks 4–8 extend it.

```python
"""ProjectCard-shaped network changes: apply, undo, group into cards, and read/write card files.

Every edit is a :data:`NetworkChange` that mirrors a ProjectCard change type. :func:`apply_change`
executes one against a :class:`~netstead.network.Network` (lowered to corral edits, atomic and
reversible); a :class:`ChangeLog` groups applied changes into a draft :class:`DraftCard` until it is
committed. Card files are YAML; validating them uses the vendored projectcard JSON schema. Both need
the ``[projectcard]`` extra (``pyyaml`` + ``jsonschema``); applying changes needs neither.
"""

from .schema import SCHEMA_VERSION, CardInvalid, card_errors, validate_card

__all__ = ["SCHEMA_VERSION", "CardInvalid", "card_errors", "validate_card"]
```

Create `packages/netstead/netstead/changes/schema.py`:

```python
"""Validate ProjectCards against the vendored projectcard JSON schema, offline.

The files under ``schema/projectcard/`` are copied verbatim from a pinned projectcard release (see its
``VERSION``). They reference each other with relative ``$ref``s, which resolve against a made-up base URI in a
:mod:`referencing` registry holding every vendored file, so validation never fetches anything.
Needs the ``[projectcard]`` extra (``jsonschema`` >= 4.18, which ships ``referencing``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_DIR", "SCHEMA_VERSION", "CardInvalid", "card_errors", "validate_card"]

#: The vendored projectcard schema tree.
SCHEMA_DIR = Path(str(resources.files(__package__).joinpath("schema/projectcard")))
#: The projectcard release the vendored schema comes from (the first word of ``VERSION``).
SCHEMA_VERSION = (SCHEMA_DIR / "VERSION").read_text(encoding="utf-8").split()[0]
#: Base URI the vendored files are registered under. ``.invalid`` can never resolve, so a missing file is an
#: error, never a download.
_BASE = "https://projectcard.netstead.invalid/schema/"
_HINT = "validating ProjectCards needs the [projectcard] extra: pip install 'netstead[projectcard]'"


class CardInvalid(ValueError):
    """A card does not match the ProjectCard schema; ``errors`` lists every problem."""

    def __init__(self, errors: list[str]) -> None:
        """Keep ``errors``, and summarise the first few in the message."""
        self.errors = errors
        shown = "; ".join(errors[:3]) + (f" (+{len(errors) - 3} more)" if len(errors) > 3 else "")
        super().__init__(f"not a valid ProjectCard: {shown}")


@lru_cache(maxsize=1)
def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry
        from referencing.jsonschema import DRAFT7
    except ImportError as exc:
        raise ImportError(_HINT) from exc
    pairs = [
        (_BASE + path.relative_to(SCHEMA_DIR).as_posix(), DRAFT7.create_resource(json.loads(path.read_text("utf-8"))))
        for path in sorted(SCHEMA_DIR.rglob("*.json"))
    ]
    registry = Registry().with_resources(pairs)
    return jsonschema.Draft7Validator({"$ref": _BASE + "projectcard.json"}, registry=registry)


def card_errors(card: Mapping[str, Any]) -> list[str]:
    """Every way ``card`` breaks the ProjectCard schema, as ``"<json path>: <message>"`` (empty when valid).

    Each error is narrowed with :func:`jsonschema.exceptions.best_match`. A failed ``oneOf`` over the change
    types therefore reports the branch that came closest, not "is not valid under any of the given schemas".
    """
    from jsonschema.exceptions import best_match

    out = set()
    for error in _validator().iter_errors(dict(card)):
        leaf = best_match([error]) or error
        where = "/".join(str(p) for p in leaf.absolute_path) or "(card)"
        out.add(f"{where}: {leaf.message}")
    return sorted(out)


def validate_card(card: Mapping[str, Any]) -> None:
    """Raise :class:`CardInvalid` (carrying every error) unless ``card`` matches the ProjectCard schema."""
    errors = card_errors(card)
    if errors:
        raise CardInvalid(errors)
```

In `packages/netstead/pyproject.toml`:
- add the extra after `reports`:

```toml
projectcard = [
    # ProjectCard files (netstead.changes). pyyaml reads and writes card YAML; jsonschema validates cards
    # against the vendored projectcard schema (>=4.18 for its `referencing` registry: offline $ref resolution).
    # Deliberately not the `projectcard` package itself: it pulls ruff, toml, tabulate and jsonref at runtime.
    "pyyaml>=6",
    "jsonschema>=4.18",
]
```

- add `projectcard` to `all`: `"netstead[clean,server,mcp,notebook,osm,overture,graph,reports,nl,bench,projectcard]"`;
- add to the wheel `include` list, after the selection-schema line:

```toml
    # Vendored projectcard JSON schema (netstead.changes; see its VERSION) and the
    # maintained GMNS <-> Wrangler field mapping.
    "netstead/changes/schema/**/*.json",
    "netstead/changes/schema/**/VERSION",
    "netstead/changes/schema/**/LICENSE",
    "netstead/changes/mappings/*.yaml",
```

In the root `pyproject.toml`:
- in `[dependency-groups] dev`, add
  `"projectcard>=0.3.3",  # interop test only (tests/test_changes_card.py)`;
- in the `[[tool.importlinter.contracts]]` named "netstead core must not require optional-extra submodules", add
  `"netstead.changes"` to `source_modules`.

Run: `uv sync --all-extras`. This updates the local `uv.lock`, which is not tracked.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_schema.py -q`
Expected: all pass.

If `test_a_links_selector_without_ignore_missing_is_invalid` finds no errors, the tag does not require the flag.
Record that under Open question 11, and keep Task 2 anyway: the flag is harmless and valid.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q`, the ruff pair and `uv run lint-imports`.
Expected: all pass; `lint-imports` keeps every contract.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/changes packages/netstead/pyproject.toml pyproject.toml packages/netstead/tests/test_changes_schema.py
git commit -m "feat(changes): vendored ProjectCard schema and offline card validation"
```

---

### Task 4: The maintained GMNS ↔ Wrangler field mapping

**Files:**
- Create: `packages/netstead/netstead/changes/mappings/gmns_to_wrangler.yaml`
- Create: `packages/netstead/netstead/changes/mapping.py`
- Test: `packages/netstead/tests/test_changes_mapping.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_changes_mapping.py`:

```python
"""The GMNS <-> Wrangler mapping is data (mappings/gmns_to_wrangler.yaml), read once."""

import pytest

pytest.importorskip("yaml")

from netstead.changes.mapping import load_mapping  # noqa: E402


@pytest.fixture(scope="module")
def m():
    return load_mapping()


def test_selectors(m):
    assert m.selector("link") == ("link_id", "model_link_id")
    assert m.selector("node") == ("node_id", "model_node_id")


def test_field_names_round_trip(m):
    assert m.to_card("link", "from_node_id") == "A"
    assert m.to_card("link", "facility_type") == "roadway"
    assert m.to_card("link", "free_speed") == "free_speed"  # unlisted: keeps its GMNS name
    assert m.from_card("link", "B") == "to_node_id"
    assert m.from_card("node", "X") == "x_coord"
    assert m.from_card("link", "free_speed") == "free_speed"


def test_derived_access_flags_come_from_allowed_uses(m):
    assert m.derive({"allowed_uses": "auto,truck,walk"}) == {"walk_access": 1, "bike_access": 0, "drive_access": 1}
    assert m.derive({}) == {}  # no source column: nothing invented (schema validation reports what is missing)


def test_a_custom_mapping_file_is_read(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("version: 1\nselectors: {link: {link_id: my_id}}\nfields: {}\nvalues: {}\nderived: {}\n")
    assert load_mapping(path).selector("link") == ("link_id", "my_id")
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_mapping.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'netstead.changes.mapping'`.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/changes/mappings/gmns_to_wrangler.yaml`:

```yaml
# GMNS (netstead) <-> network_wrangler / ProjectCard names. This is maintained data, not code: when Wrangler
# renames a field, change it here. A column not listed keeps its GMNS name in cards (ProjectCard allows
# any property name in property_changes).
version: 1
selectors:            # the key a card's facility uses to pick records by id
  link: {link_id: model_link_id}
  node: {node_id: model_node_id}
fields:               # property names (property changes) and record fields (roadway additions)
  link:
    link_id: model_link_id
    from_node_id: A
    to_node_id: B
    facility_type: roadway
  node:
    node_id: model_node_id
    x_coord: X
    y_coord: Y
values:               # per card field: GMNS value -> card value (an unlisted value passes through)
  roadway: {}
derived:              # link fields Wrangler requires that GMNS has no column for; written on additions only
  walk_access: {column: allowed_uses, any_of: [walk]}
  bike_access: {column: allowed_uses, any_of: [bike]}
  drive_access: {column: allowed_uses, any_of: [auto, drive, truck]}
```

Create `packages/netstead/netstead/changes/mapping.py`:

```python
"""GMNS <-> network_wrangler/ProjectCard field names, from the maintained ``mappings/gmns_to_wrangler.yaml``.

Only card I/O uses this: applying a change works in GMNS names throughout. It therefore needs ``pyyaml`` from the
``[projectcard]`` extra, imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = ["DEFAULT_MAPPING", "FieldMap", "load_mapping"]

#: The maintained mapping file shipped with netstead.
DEFAULT_MAPPING = Path(str(resources.files(__package__).joinpath("mappings/gmns_to_wrangler.yaml")))


@dataclass(frozen=True)
class FieldMap:
    """Name and value translations between GMNS tables and ProjectCard records."""

    selectors: dict[str, dict[str, str]]
    fields: dict[str, dict[str, str]]
    values: dict[str, dict[Any, Any]]
    derived: dict[str, dict[str, Any]]

    def selector(self, table: str) -> tuple[str, str]:
        """``(GMNS key column, card selector key)`` for ``table`` (``KeyError`` for an unmapped table)."""
        ((pk, key),) = self.selectors[table].items()
        return pk, key

    def to_card(self, table: str, column: str) -> str:
        """The card name for GMNS ``table.column`` (unchanged when not listed)."""
        return self.fields.get(table, {}).get(column, column)

    def from_card(self, table: str, name: str) -> str:
        """The GMNS column for card field ``name`` on ``table`` (unchanged when not listed)."""
        reverse = {v: k for k, v in self.fields.get(table, {}).items()}
        return reverse.get(name, name)

    def card_value(self, field: str, value: Any) -> Any:
        """``value`` as the card writes it for card ``field``."""
        return self.values.get(field, {}).get(value, value)

    def gmns_value(self, field: str, value: Any) -> Any:
        """A card ``value`` for ``field``, back as the GMNS value."""
        reverse = {v: k for k, v in self.values.get(field, {}).items()}
        return reverse.get(value, value)

    def derive(self, record: dict[str, Any]) -> dict[str, int]:
        """Derived card fields (``1``/``0``) for a GMNS link record; a rule whose column is absent yields nothing."""
        out: dict[str, int] = {}
        for name, rule in self.derived.items():
            raw = record.get(rule["column"])
            if raw is None:
                continue
            uses = {u.strip().lower() for u in str(raw).split(",")}
            out[name] = int(bool(uses & {str(v).lower() for v in rule["any_of"]}))
        return out


@lru_cache(maxsize=8)
def load_mapping(path: str | Path | None = None) -> FieldMap:
    """Read a mapping file (default: :data:`DEFAULT_MAPPING`); cached per path."""
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("ProjectCard files need the [projectcard] extra: pip install 'netstead[projectcard]'") from exc
    data = yaml.safe_load(Path(path or DEFAULT_MAPPING).read_text(encoding="utf-8")) or {}
    if data.get("version") != 1:
        raise ValueError(f"unsupported mapping version {data.get('version')!r} (expected 1)")
    return FieldMap(
        selectors=dict(data.get("selectors") or {}),
        fields=dict(data.get("fields") or {}),
        values={k: dict(v or {}) for k, v in (data.get("values") or {}).items()},
        derived=dict(data.get("derived") or {}),
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_mapping.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/changes/mapping.py packages/netstead/netstead/changes/mappings packages/netstead/tests/test_changes_mapping.py
git commit -m "feat(changes): maintained GMNS <-> Wrangler field mapping"
```

---

### Task 5: The `NetworkChange` union

**Files:**
- Create: `packages/netstead/netstead/changes/types.py`
- Modify: `packages/netstead/netstead/changes/__init__.py`
- Test: `packages/netstead/tests/test_changes_types.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_changes_types.py`:

```python
"""NetworkChange: the ProjectCard change types as a discriminated union (transit declared, not yet applied)."""

import json

import pytest
from netstead.changes.schema import SCHEMA_DIR
from netstead.changes.types import (
    CHANGE_TYPES,
    TRANSIT_TYPES,
    PropertyChange,
    RoadwayAddition,
    RoadwayDeletion,
    RoadwayPropertyChange,
    Selection,
    parse_change,
)
from pydantic import ValidationError


def test_union_mirrors_the_vendored_schema_change_types():
    top = json.loads((SCHEMA_DIR / "projectcard.json").read_text(encoding="utf-8"))
    in_schema = {k for k, v in top["properties"].items() if "changes/" in json.dumps(v)}
    # roadway_managed_lanes reuses roadway_property_change; managed lanes are out of scope (design).
    assert set(CHANGE_TYPES) == in_schema - {"roadway_managed_lanes"}
    assert TRANSIT_TYPES <= set(CHANGE_TYPES)


def test_parse_picks_the_type():
    c = parse_change(
        {"type": "roadway_property_change", "facility": {"ids": [1]}, "property_changes": {"lanes": {"set": 2}}}
    )
    assert isinstance(c, RoadwayPropertyChange) and c.facility.table == "link"
    assert isinstance(parse_change({"type": "roadway_deletion", "links": [1]}), RoadwayDeletion)
    assert parse_change({"type": "transit_property_change"}).type == "transit_property_change"


@pytest.mark.parametrize("bad", [{}, {"set": 1, "change": 1}, {"existing": 1}])
def test_a_property_change_is_set_or_change(bad):
    with pytest.raises(ValidationError):
        PropertyChange(**bad)


def test_booleans_become_integers():
    assert PropertyChange(set=True).set == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"ids": [1], "query": {"links": {"name": ["X"]}}, "resolved": [1]},
        {"ids": []},
        {"query": {"links": {"name": ["X"]}}},  # a query must record what it resolved to
        {"table": "node", "query": {"links": {"name": ["X"]}}, "resolved": [1]},
    ],
)
def test_a_selection_is_ids_or_a_resolved_query(kwargs):
    with pytest.raises(ValidationError):
        Selection(**kwargs)


def test_target_ids():
    assert Selection(ids=[3, 4]).target_ids() == [3, 4]
    assert Selection(query={"links": {"name": ["X"]}}, resolved=[7]).target_ids() == [7]


def test_deletion_and_addition_need_something():
    with pytest.raises(ValidationError):
        RoadwayDeletion()
    with pytest.raises(ValidationError):
        RoadwayAddition()
    with pytest.raises(ValidationError, match="link_id"):
        RoadwayAddition(links=[{"from_node_id": 1, "to_node_id": 2}])
```

`test_booleans_become_integers` relies on pydantic's smart-mode union. If pydantic keeps `True` as a `bool`, add a
`field_validator("existing", "set", mode="before")` that maps a `bool` to `int`. That makes the "no bool in a
card" rule explicit.

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_types.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'netstead.changes.types'`.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/changes/types.py`:

```python
"""NetworkChange: one record per ProjectCard change type, discriminated on ``type``.

The models hold GMNS-native names (``link_id``, ``from_node_id``); :mod:`netstead.changes.card` translates to
and from a card's Wrangler names. Transit types are declared now, so that the union, the action schema and the
LLM tool vocabulary are stable from P2. :func:`~netstead.changes.apply.apply_change` answers "not yet
supported" for them until the transit component lands (P6).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

__all__ = [
    "CHANGE_TYPES",
    "ROADWAY_TYPES",
    "TRANSIT_TYPES",
    "NetworkChange",
    "PropertyChange",
    "RoadwayAddition",
    "RoadwayDeletion",
    "RoadwayPropertyChange",
    "Scalar",
    "Selection",
    "TransitPropertyChange",
    "TransitRouteAddition",
    "TransitRoutingChange",
    "TransitServiceDeletion",
    "change_json_schema",
    "parse_change",
]

#: A value a ProjectCard property can hold (no null, no list). Booleans validate to 1/0.
Scalar = int | float | str
Id = int | str


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PropertyChange(_Model):
    """One property: ``set`` it, or ``change`` it by a numeric delta; ``existing`` is checked first when given."""

    existing: Scalar | None = None
    set: Scalar | None = None
    change: float | None = None
    existing_value_conflict: Literal["error", "warn", "skip"] = "error"

    @model_validator(mode="after")
    def _set_or_change(self) -> PropertyChange:
        if (self.set is None) == (self.change is None):
            raise ValueError("give exactly one of set or change (a ProjectCard cannot set a property to empty)")
        return self


class Selection(_Model):
    """Which records a property change applies to.

    ``ids`` picks records by GMNS key (``link_id`` / ``node_id``), as a click-pick does. ``query`` keeps a
    re-resolvable ProjectCard facility, already in card form (as :func:`netstead.select.emit.to_projectcard`
    emits it), and ``resolved`` records the link ids it resolved to when the change was made (provenance). P2
    applies a query to its ``resolved`` ids; re-resolving it on another network version is ``apply_card`` (later).
    """

    table: Literal["link", "node"] = "link"
    ids: list[Id] | None = None
    query: dict[str, Any] | None = None
    resolved: list[Id] | None = None

    @model_validator(mode="after")
    def _ids_or_query(self) -> Selection:
        if (self.ids is None) == (self.query is None):
            raise ValueError("give exactly one of ids or query")
        if self.ids is not None and not self.ids:
            raise ValueError("ids must not be empty")
        if self.query is not None and (self.resolved is None or self.table != "link"):
            raise ValueError("a query selects links and must record the link ids it resolved to (resolved=[...])")
        return self

    def target_ids(self) -> list[Id]:
        """The ids this selection applies to now."""
        return list(self.ids if self.ids is not None else self.resolved or [])


class RoadwayPropertyChange(_Model):
    """Change properties of selected links or nodes (ProjectCard ``roadway_property_change``)."""

    type: Literal["roadway_property_change"] = "roadway_property_change"
    facility: Selection
    property_changes: dict[str, PropertyChange] = Field(min_length=1)
    note: str | None = None  # why (an issue code, a reason); a card carries it in its notes


class RoadwayDeletion(_Model):
    """Delete links and/or nodes by id (ProjectCard ``roadway_deletion``).

    Deleting a link also deletes the rows whose foreign key points at it (lanes, time-of-day rows).
    ``clean_nodes`` also deletes end nodes of the deleted links that no remaining link uses.
    """

    type: Literal["roadway_deletion"] = "roadway_deletion"
    links: list[Id] = Field(default_factory=list)
    nodes: list[Id] = Field(default_factory=list)
    clean_nodes: bool = False
    note: str | None = None

    @model_validator(mode="after")
    def _something(self) -> RoadwayDeletion:
        if not self.links and not self.nodes:
            raise ValueError("give links and/or nodes to delete")
        return self


_REQUIRED = {"links": ("link_id", "from_node_id", "to_node_id"), "nodes": ("node_id", "x_coord", "y_coord")}


class RoadwayAddition(_Model):
    """Add GMNS link and/or node records (ProjectCard ``roadway_addition``); nodes are added before links."""

    type: Literal["roadway_addition"] = "roadway_addition"
    links: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _records(self) -> RoadwayAddition:
        if not self.links and not self.nodes:
            raise ValueError("give links and/or nodes to add")
        for kind, required in _REQUIRED.items():
            for record in getattr(self, kind):
                missing = [k for k in required if record.get(k) is None]
                if missing:
                    raise ValueError(f"every added {kind[:-1]} needs {', '.join(missing)}")
        return self


class _Transit(_Model):
    """A transit change: declared now so the union is stable; its fields arrive with the transit component (P6)."""

    body: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class TransitPropertyChange(_Transit):
    """ProjectCard ``transit_property_change`` (not yet supported)."""

    type: Literal["transit_property_change"] = "transit_property_change"


class TransitRoutingChange(_Transit):
    """ProjectCard ``transit_routing_change`` (not yet supported)."""

    type: Literal["transit_routing_change"] = "transit_routing_change"


class TransitRouteAddition(_Transit):
    """ProjectCard ``transit_route_addition`` (not yet supported)."""

    type: Literal["transit_route_addition"] = "transit_route_addition"


class TransitServiceDeletion(_Transit):
    """ProjectCard ``transit_service_deletion`` (not yet supported)."""

    type: Literal["transit_service_deletion"] = "transit_service_deletion"


NetworkChange = Annotated[
    RoadwayPropertyChange
    | RoadwayDeletion
    | RoadwayAddition
    | TransitPropertyChange
    | TransitRoutingChange
    | TransitRouteAddition
    | TransitServiceDeletion,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[NetworkChange] = TypeAdapter(NetworkChange)

#: Every change type, as ProjectCard names them.
CHANGE_TYPES: tuple[str, ...] = (
    "roadway_property_change",
    "roadway_deletion",
    "roadway_addition",
    "transit_property_change",
    "transit_routing_change",
    "transit_route_addition",
    "transit_service_deletion",
)
ROADWAY_TYPES = frozenset(t for t in CHANGE_TYPES if t.startswith("roadway_"))
TRANSIT_TYPES = frozenset(t for t in CHANGE_TYPES if t.startswith("transit_"))


def parse_change(data: dict[str, Any]) -> NetworkChange:
    """Validate a JSON dict into a :data:`NetworkChange` (raises ``pydantic.ValidationError``)."""
    return _ADAPTER.validate_python(data)


def change_json_schema() -> dict[str, Any]:
    """JSON schema of the :data:`NetworkChange` union."""
    return _ADAPTER.json_schema()
```

Extend `changes/__init__.py`: import every name in `types.__all__` and add them to `__all__`, sorted the way
ruff's `RUF022` wants (uppercase constants first).

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_types.py -q`
Expected: all pass.

If `test_union_mirrors_the_vendored_schema_change_types` fails, the vendored tag names a type differently from
`main`. Rename that model's `type` literal and its `CHANGE_TYPES` entry to the tag's name.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/changes packages/netstead/tests/test_changes_types.py
git commit -m "feat(changes): NetworkChange union (roadway types, transit declared)"
```

---

### Task 6: `apply_change` for property changes, lowered to corral `update_rows`

**Files:**
- Create: `packages/netstead/netstead/changes/apply.py`
- Modify: `packages/netstead/netstead/changes/__init__.py`
- Test: `packages/netstead/tests/test_changes_apply.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_changes_apply.py`:

```python
"""apply_change / reverse_change: ProjectCard changes executed as atomic, reversible corral edits."""

import time

import pandas as pd
import pyarrow as pa
import pytest
from corral.dataset import Package, Table
from corral.engines.ibis_engine import IbisEngine
from netstead import Network
from netstead.changes import (
    ChangeConflict,
    ChangeError,
    ChangeNotSupported,
    PropertyChange,
    RoadwayPropertyChange,
    Selection,
    TransitPropertyChange,
    apply_change,
    reverse_change,
)
from netstead.fixtures import leavenworth


@pytest.fixture
def net():
    return Network.from_source(leavenworth.parquet_dir())  # per test: changes mutate it


def frame(net, table="link", key="link_id"):
    return net.tables[table].to_pandas().sort_values(key).reset_index(drop=True)


def value(net, link_id, column, table="link", key="link_id"):
    df = net.tables[table].to_pandas()
    return df.loc[df[key] == link_id, column].tolist()


def speed(ids, **kwargs):
    return RoadwayPropertyChange(facility=Selection(ids=ids), property_changes={"free_speed": PropertyChange(**kwargs)})


def test_set_is_one_update_and_reverses_exactly(net):
    before = frame(net)
    result = apply_change(net, speed([1, 2], set=30))
    assert value(net, 1, "free_speed") == [30.0] and value(net, 2, "free_speed") == [30.0]
    assert result.rows == 2 and len(result.edits) == 1 and result.summary()["type"] == "roadway_property_change"
    reverse_change(net, result)
    pd.testing.assert_frame_equal(frame(net), before)


def test_existing_mismatch_is_a_conflict_and_changes_nothing(net):
    before = frame(net)
    with pytest.raises(ChangeConflict, match="free_speed"):
        apply_change(net, speed([1, 2], existing=40, set=30))  # link 2 is 40.23
    pd.testing.assert_frame_equal(frame(net), before)


def test_existing_conflict_can_warn_or_skip(net):
    warned = apply_change(net, speed([2], existing=40, set=30, existing_value_conflict="warn"))
    assert warned.warnings and value(net, 2, "free_speed") == [30.0]
    change = RoadwayPropertyChange(
        facility=Selection(ids=[1]),
        property_changes={
            "free_speed": PropertyChange(existing=99, set=30, existing_value_conflict="skip"),
            "lanes": PropertyChange(set=2),
        },
    )
    skipped = apply_change(net, change)
    assert skipped.skipped and value(net, 1, "free_speed") == [40.0] and value(net, 1, "lanes") == [2]


def test_a_delta_groups_rows_by_their_current_value(net):
    apply_change(net, RoadwayPropertyChange(facility=Selection(ids=[1]), property_changes={"lanes": PropertyChange(set=2)}))
    result = apply_change(
        net, RoadwayPropertyChange(facility=Selection(ids=[1, 2]), property_changes={"lanes": PropertyChange(change=1)})
    )
    assert value(net, 1, "lanes") == [3] and value(net, 2, "lanes") == [2]
    assert len(result.edits) == 2  # one update per distinct current value


def test_values_are_coerced_to_the_column_type(net):
    apply_change(net, speed([1], set="45"))
    assert value(net, 1, "free_speed") == [45.0]
    with pytest.raises(ChangeError, match="does not fit"):
        apply_change(net, speed([1], set="fast"))
    with pytest.raises(ChangeError, match="does not fit"):
        apply_change(net, RoadwayPropertyChange(facility=Selection(ids=[1]), property_changes={"lanes": PropertyChange(set=1.5)}))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (RoadwayPropertyChange(facility=Selection(ids=[999999]), property_changes={"lanes": PropertyChange(set=2)}), "not found"),
        (RoadwayPropertyChange(facility=Selection(ids=[1]), property_changes={"nope": PropertyChange(set=2)}), "no column"),
        (RoadwayPropertyChange(facility=Selection(ids=[1]), property_changes={"link_id": PropertyChange(set=2)}), "key"),
    ],
)
def test_bad_targets_are_refused(net, change, message):
    with pytest.raises(ChangeError, match=message):
        apply_change(net, change)


def test_a_node_property(net):
    change = RoadwayPropertyChange(
        facility=Selection(table="node", ids=[1]), property_changes={"ctrl_type": PropertyChange(set="signal")}
    )
    result = apply_change(net, change)
    assert value(net, 1, "ctrl_type", table="node", key="node_id") == ["signal"]
    reverse_change(net, result)
    assert value(net, 1, "ctrl_type", table="node", key="node_id") == ["stop_2_way"]


def test_a_query_selection_applies_to_its_resolved_ids(net):
    sel = Selection(query={"links": {"name": ["Benton Street"], "ignore_missing": True}}, resolved=[1])
    apply_change(net, RoadwayPropertyChange(facility=sel, property_changes={"lanes": PropertyChange(set=2)}))
    assert value(net, 1, "lanes") == [2]


def test_transit_is_not_supported_yet(net):
    with pytest.raises(ChangeNotSupported, match="P6"):
        apply_change(net, TransitPropertyChange())


@pytest.mark.perf
def test_one_update_and_its_undo_on_200k_links_stay_interactive():
    n, e = 200_000, IbisEngine()
    arrow = pa.table(
        {
            "link_id": pa.array(range(1, n + 1), pa.int64()),
            "free_speed": pa.array([40.0] * n),
            "name": pa.array([None] * n, pa.string()),  # all-null: exercises the null-safe reverse join
        }
    )
    pkg = Package.from_tables({"link": Table(name="link", expr=e.from_arrow(arrow), engine=e)})
    start = time.perf_counter()
    reverse_change(pkg, apply_change(pkg, speed([5], set=30)))
    assert time.perf_counter() - start < 5.0
    assert pkg.tables["link"].count() == n
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_apply.py -q -m ""`
Expected: FAIL with `ImportError: cannot import name 'apply_change'`.

- [ ] **Step 3: Implement**

Create `packages/netstead/netstead/changes/apply.py`. Task 7 adds the deletion and addition appliers to `_APPLIERS`.

```python
"""Apply a :data:`~netstead.changes.types.NetworkChange` to a network, and reverse it.

One change becomes one atomic group of corral edits (``update_rows``, ``delete_rows``, ``add_rows``), added inside a corral editing :class:`~corral.editing.Session`: if any step fails, the session
reverses what was already applied before the error propagates. The network is mutated in place. corral reads
an edited table to Arrow and swaps in an in-memory table on the same engine; untouched tables stay lazy.
:func:`reverse_change` undoes a :class:`ChangeResult` in LIFO order.

Values are coerced to their column's type first: integers take integral numbers or numeric text, floats take
numbers or numeric text, text takes any scalar, booleans take ``true/false/1/0``. Other types (geometry, dates)
cannot be edited yet.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from corral.editing import Edit, EditingError, EditResult, Session
from corral.editing.apply import reverse_edit

from .types import TRANSIT_TYPES, NetworkChange, PropertyChange, RoadwayPropertyChange

__all__ = ["KEYS", "ChangeConflict", "ChangeError", "ChangeNotSupported", "ChangeResult", "apply_change", "reverse_change"]

#: The key column of each table a roadway change edits (GMNS names).
KEYS = {"link": "link_id", "node": "node_id"}


class ChangeError(ValueError):
    """A change cannot be applied to this network; the message says why."""


class ChangeConflict(ChangeError):
    """An ``existing`` value does not match the network (``existing_value_conflict="error"``)."""


class ChangeNotSupported(ChangeError):
    """The change type is declared, but its applier ships later (transit: phase P6)."""


@dataclass
class ChangeResult:
    """An applied change: the corral edits that carried it (for :func:`reverse_change`) and what happened."""

    change: NetworkChange
    edits: list[EditResult]
    rows: int
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """JSON-safe: type, records touched, edit count, warnings and skipped properties."""
        return {
            "type": self.change.type,
            "rows": self.rows,
            "edits": len(self.edits),
            "warnings": list(self.warnings),
            "skipped": list(self.skipped),
        }


@dataclass
class _Outcome:
    rows: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def apply_change(net: Any, change: NetworkChange) -> ChangeResult:
    """Apply ``change`` to ``net`` (a :class:`~netstead.network.Network`, mutated in place), all or nothing.

    Raises:
        ChangeNotSupported: a transit change (phase P6).
        ChangeConflict: an ``existing`` value does not match and the change says ``error``.
        ChangeError: a missing record, column or table, or a value that does not fit its column.

    Examples:
        >>> from netstead import Network
        >>> from netstead.fixtures import leavenworth
        >>> from netstead.changes import PropertyChange, RoadwayPropertyChange, Selection
        >>> net = Network.from_source(leavenworth.parquet_dir())
        >>> change = RoadwayPropertyChange(
        ...     facility=Selection(ids=[1]), property_changes={"free_speed": PropertyChange(existing=40, set=30)}
        ... )
        >>> result = apply_change(net, change)
        >>> result.rows, net.links.filter(lambda t: t.link_id == 1).to_pandas().free_speed.tolist()
        (1, [30.0])
        >>> reverse_change(net, result)
    """
    if change.type in TRANSIT_TYPES:
        raise ChangeNotSupported(f"{change.type} arrives with the transit component (phase P6)")
    applier = _APPLIERS[change.type]
    try:
        with Session(net) as session:
            outcome = applier(net, change, session)
    except EditingError as exc:  # corral's own refusal (unknown table, bad payload): the user's to fix
        raise ChangeError(f"{change.type} failed: {exc}") from exc
    return ChangeResult(change, list(session.results), outcome.rows, outcome.warnings, outcome.skipped)


def reverse_change(net: Any, result: ChangeResult) -> None:
    """Undo an applied change (its edits in reverse order). Call it on changes in LIFO order."""
    for edit in reversed(result.edits):
        reverse_edit(net, edit)


# ---------------------------------------------------------------- helpers


def _few(ids: Sequence[Any], n: int = 5) -> str:
    shown = ", ".join(str(i) for i in list(ids)[:n])
    return shown + (f" (+{len(ids) - n} more)" if len(ids) > n else "")


def _py(value: Any) -> Any:
    """A pandas/numpy cell as a plain Python value (NA -> None)."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def _table(net: Any, name: str) -> Any:
    table = net.tables.get(name)
    if table is None:
        raise ChangeError(f"the network has no {name} table")
    return table


def _dtype(table: Any, column: str) -> Any:
    schema = table.expr.schema()
    if column not in schema:
        raise ChangeError(f"{table.name} has no column {column!r}")
    return schema[column]


def _in(column: str, values: Sequence[Any]) -> Callable[[Any], Any]:
    frozen = list(values)
    return lambda t: t[column].isin(frozen)


def _coerce(value: Any, dtype: Any, column: str) -> Any:
    """``value`` as ``column``'s ibis ``dtype``, or :class:`ChangeError`."""
    if value is None:
        return None
    try:
        if dtype.is_boolean():
            text = str(value).strip().lower()
            if text in ("true", "1"):
                return True
            if text in ("false", "0"):
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
        if dtype.is_string():
            return str(value)
    except (TypeError, ValueError):
        raise ChangeError(f"{column} is {dtype}; {value!r} does not fit it") from None
    raise ChangeError(f"{column} ({dtype}) cannot be edited yet")


def _same(current: Any, existing: Any, dtype: Any, column: str) -> bool:
    if current is None:
        return False
    want = _coerce(existing, dtype, column)
    if isinstance(want, float) or isinstance(current, float):
        return math.isclose(float(current), float(want), rel_tol=1e-9, abs_tol=1e-9)
    return current == want


def _keys(table: Any, pk: str, ids: Sequence[Any]) -> list[Any]:
    dtype = _dtype(table, pk)
    return [_coerce(i, dtype, pk) for i in ids]


def _rows(table: Any, pk: str, ids: Sequence[Any], columns: Sequence[str]) -> dict[Any, dict[str, Any]]:
    """``{key: {column: value}}`` for the rows of ``table`` whose ``pk`` is in ``ids``."""
    wanted = list(dict.fromkeys([pk, *columns]))
    df = table.filter(_in(pk, ids)).select(*wanted).to_pandas()
    return {_py(r[pk]): {c: _py(r[c]) for c in columns} for r in df.to_dict("records")}


# ---------------------------------------------------------------- appliers


def _property_change(net: Any, change: RoadwayPropertyChange, session: Session) -> _Outcome:
    sel = change.facility
    table, pk = _table(net, sel.table), KEYS[sel.table]
    for prop in change.property_changes:
        if prop == pk:
            raise ChangeError(f"{prop} is the {sel.table} key; it cannot be changed")
        _dtype(table, prop)
    ids = _keys(table, pk, sel.target_ids())
    current = _rows(table, pk, ids, list(change.property_changes))
    missing = [i for i in ids if i not in current]
    if missing:
        raise ChangeError(f"{sel.table} {_few(missing)} not found")
    out = _Outcome(rows=len(ids))
    for prop, pc in change.property_changes.items():
        dtype = _dtype(table, prop)
        if pc.existing is not None:
            bad = [i for i in ids if not _same(current[i][prop], pc.existing, dtype, prop)]
            if bad:
                msg = f"{prop}: expected {pc.existing!r} on {sel.table} {_few(bad)}, found {current[bad[0]][prop]!r}"
                if pc.existing_value_conflict == "error":
                    raise ChangeConflict(msg)
                if pc.existing_value_conflict == "skip":
                    out.skipped.append(msg)
                    continue
                out.warnings.append(msg)
        for value, group in _groups(pc, ids, current, prop, dtype).items():
            payload = {"predicate": _in(pk, group), "set": {prop: value}}
            session.add_edit(Edit(op="update_rows", table=sel.table, payload=payload, metadata={"change": change.type}))
    return out


def _groups(pc: PropertyChange, ids: list[Any], current: dict, prop: str, dtype: Any) -> dict[Any, list[Any]]:
    """New value -> the ids that get it: one group for ``set``; one per distinct current value for ``change``."""
    if pc.set is not None:
        return {_coerce(pc.set, dtype, prop): list(ids)}
    if not dtype.is_numeric():
        raise ChangeError(f"{prop} is {dtype}: only numbers change by a delta")
    groups: dict[Any, list[Any]] = defaultdict(list)
    for i in ids:
        now = current[i][prop]
        if now is None:
            raise ChangeError(f"{prop} on {i} is empty: set it rather than changing it by {pc.change}")
        groups[_coerce(now + pc.change, dtype, prop)].append(i)
    return dict(groups)


_APPLIERS: dict[str, Callable[[Any, Any, Session], _Outcome]] = {
    "roadway_property_change": _property_change,
}
```

Add `apply.__all__` to `changes/__init__.py`.

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_apply.py -q -m ""`
Expected: all pass, the `perf` test included. `test_set_is_one_update_and_reverses_exactly` depends on Task 1:
undo puts the row back at the end, so the test compares key-sorted frames.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass. The doctest in
`apply_change` runs here.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/changes packages/netstead/tests/test_changes_apply.py
git commit -m "feat(changes): apply_change for property changes, lowered to corral edits"
```

---

### Task 7: Roadway deletion (cascading through the spec's foreign keys) and addition

**Files:**
- Create: `packages/netstead/netstead/spec/keys.py`
- Modify: `packages/netstead/netstead/workbench/related.py`
- Modify: `packages/netstead/netstead/changes/apply.py`
- Test: `packages/netstead/tests/test_changes_apply.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_changes_apply.py`. Add `RoadwayAddition` and `RoadwayDeletion` to the
`netstead.changes` import.

```python
def refs(net, link_id):
    """Rows pointing at ``link_id`` in every table with a link_id column, besides link itself."""
    out = {}
    for name, table in net.tables.items():
        if name != "link" and "link_id" in table.columns():
            df = table.to_pandas()
            out[name] = int((df.link_id == link_id).sum())
    return out


def counts(net):
    return {name: table.count() for name, table in net.tables.items()}


def test_deleting_a_link_deletes_what_points_at_it_and_reverses(net):
    before, pointing = counts(net), refs(net, 1)
    assert pointing.get("lane", 0) > 0  # Leavenworth link 1 has lanes
    result = apply_change(net, RoadwayDeletion(links=[1]))
    after = counts(net)
    assert after["link"] == before["link"] - 1
    for name, n in pointing.items():
        assert after[name] == before[name] - n
    reverse_change(net, result)
    assert counts(net) == before


def test_a_node_still_used_by_a_link_is_not_deleted(net):
    before = counts(net)
    with pytest.raises(ChangeError, match="still used"):
        apply_change(net, RoadwayDeletion(nodes=[1]))
    assert counts(net) == before


def test_missing_ids_are_refused(net):
    with pytest.raises(ChangeError, match="not found"):
        apply_change(net, RoadwayDeletion(links=[999999]))


NEW_NODE = {"node_id": 9001, "x_coord": -120.66, "y_coord": 47.60, "node_type": "intersection"}
NEW_LINK = {"link_id": 9001, "from_node_id": 1, "to_node_id": 9001, "name": "New Street", "facility_type": "residential",
            "lanes": 1, "free_speed": 25.0, "allowed_uses": "auto,walk,bike", "directed": False}


def test_adding_a_node_and_a_link_and_reversing(net):
    before = counts(net)
    result = apply_change(net, RoadwayAddition(nodes=[NEW_NODE], links=[NEW_LINK]))
    assert result.rows == 2
    assert value(net, 9001, "name") == ["New Street"]
    assert value(net, 9001, "x_coord", table="node", key="node_id") == [-120.66]
    reverse_change(net, result)
    assert counts(net) == before


def test_clean_nodes_removes_end_nodes_nothing_else_uses(net):
    apply_change(net, RoadwayAddition(nodes=[NEW_NODE], links=[NEW_LINK]))
    nodes = counts(net)["node"]
    apply_change(net, RoadwayDeletion(links=[9001], clean_nodes=True))
    assert counts(net)["node"] == nodes - 1  # 9001 went; node 1 is used by other links and stays
    assert value(net, 1, "node_id", table="node", key="node_id") == [1]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (RoadwayAddition(links=[{**NEW_LINK, "link_id": 1}]), "already exist"),
        (RoadwayAddition(links=[{**NEW_LINK, "to_node_id": 424242}]), "not in the network"),
        (RoadwayAddition(links=[{**NEW_LINK, "colour": "red"}], nodes=[NEW_NODE]), "no column"),
    ],
)
def test_bad_additions_are_refused_and_leave_nothing_behind(net, change, message):
    before = counts(net)
    with pytest.raises(ChangeError, match=message):
        apply_change(net, change)
    assert counts(net) == before
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_apply.py -q`
Expected: the new tests FAIL with `KeyError: 'roadway_deletion'` / `'roadway_addition'` (no applier yet).

- [ ] **Step 3: Move the FK reader to core**

Create `packages/netstead/netstead/spec/keys.py`, and move `ForeignKey`, `_single`, `_schemas` and
`foreign_keys` into it **verbatim** from `workbench/related.py`. Give it this module docstring:

```python
"""Single-column foreign keys between a GMNS network's tables, read from its spec (never hard-coded).

Shared by the workbench's related-records view and by :mod:`netstead.changes` (a deleted link takes the rows that
point at it). Self-references and composite keys are not followed.
"""
```

Set `__all__ = ["ForeignKey", "foreign_keys"]`. In `workbench/related.py`, delete the moved definitions and add
`from netstead.spec.keys import ForeignKey, _schemas, foreign_keys`, because `primary_keys` still uses `_schemas`.
Keep both names in its `__all__`, so `test_workbench_related.py` passes unchanged.

- [ ] **Step 4: Implement the appliers**

In `packages/netstead/netstead/changes/apply.py`:
- extend the `.types` import with `RoadwayAddition, RoadwayDeletion`;
- add `from netstead.spec.keys import foreign_keys`;
- add before `_APPLIERS`:

```python
def _present(table: Any, pk: str, ids: list[Any], name: str) -> None:
    missing = [i for i in ids if i not in _rows(table, pk, ids, [])]
    if missing:
        raise ChangeError(f"{name} {_few(missing)} not found")


def _end_nodes(links: Any, link_ids: list[Any]) -> set[Any]:
    df = links.filter(_in("link_id", link_ids)).select("from_node_id", "to_node_id").to_pandas()
    return {_py(v) for v in [*df.from_node_id, *df.to_node_id]} - {None}


def _used(links: Any, nodes: Sequence[Any]) -> set[Any]:
    """The nodes among ``nodes`` that some link still starts or ends at."""
    vals = list(nodes)
    df = links.filter(lambda t: t.from_node_id.isin(vals) | t.to_node_id.isin(vals))
    df = df.select("from_node_id", "to_node_id").to_pandas()
    return ({_py(v) for v in df.from_node_id} | {_py(v) for v in df.to_node_id}) & set(vals)


def _delete(net: Any, session: Session, table: str, ids: list[Any]) -> int:
    """Delete ``ids`` from ``table``, first deleting every row whose foreign key points at them (lanes, ...)."""
    pk = KEYS[table]
    fks = foreign_keys(net.spec, {name: t.columns() for name, t in net.tables.items()})
    for fk in fks:
        # link.from_node_id/to_node_id -> node is not cascaded: deleting a used node is refused instead.
        if fk.ref_table == table and fk.ref_column == pk and fk.table not in KEYS:
            session.add_edit(Edit(op="delete_rows", table=fk.table, payload={"predicate": _in(fk.column, ids)}))
    return session.add_edit(Edit(op="delete_rows", table=table, payload={"predicate": _in(pk, ids)})).diff.rows_removed


def _deletion(net: Any, change: RoadwayDeletion, session: Session) -> _Outcome:
    out = _Outcome()
    links_table = _table(net, "link")
    links = _keys(links_table, "link_id", change.links)
    nodes = _keys(_table(net, "node"), "node_id", change.nodes)
    _present(links_table, "link_id", links, "link")
    _present(_table(net, "node"), "node_id", nodes, "node")
    ends = _end_nodes(links_table, links) if change.clean_nodes and links else set()
    if links:
        out.rows += _delete(net, session, "link", links)
    if ends:  # read the link table again: it no longer has the deleted links
        nodes = list(dict.fromkeys([*nodes, *sorted(ends - _used(_table(net, "link"), ends), key=str)]))
    if nodes:
        used = _used(_table(net, "link"), nodes)
        if used:
            raise ChangeError(f"node {_few(sorted(used, key=str))} is still used by links; delete those links in the same change")
        out.rows += _delete(net, session, "node", nodes)
    return out


def _addition(net: Any, change: RoadwayAddition, session: Session) -> _Outcome:
    out = _Outcome()
    for name, records in (("node", change.nodes), ("link", change.links)):  # nodes first: links need their ends
        if not records:
            continue
        table, pk = _table(net, name), KEYS[name]
        unknown = sorted({k for r in records for k in r} - set(table.columns()))
        if unknown:
            raise ChangeError(f"{name} has no column(s) {unknown}")
        rows = [{k: _coerce(v, _dtype(table, k), k) for k, v in r.items()} for r in records]
        ids = [r[pk] for r in rows]
        if len(set(ids)) != len(ids):
            raise ChangeError(f"{name} ids repeat within the change")
        clash = _rows(table, pk, ids, [])
        if clash:
            raise ChangeError(f"{name} {_few(sorted(clash, key=str))} already exist")
        out.rows += session.add_edit(Edit(op="add_rows", table=name, payload={"rows": rows})).diff.rows_added
    if change.links:
        node_table = _table(net, "node")
        ends = {_coerce(r[c], _dtype(node_table, "node_id"), c) for r in change.links for c in ("from_node_id", "to_node_id")}
        missing = sorted(ends - set(_rows(node_table, "node_id", list(ends), [])), key=str)
        if missing:  # raised inside the session: the rows just added are reversed
            raise ChangeError(f"added links use node(s) {_few(missing)}, not in the network; add them in the same change")
    return out
```

Then register both appliers:

```python
_APPLIERS: dict[str, Callable[[Any, Any, Session], _Outcome]] = {
    "roadway_property_change": _property_change,
    "roadway_deletion": _deletion,
    "roadway_addition": _addition,
}
```

Wrap any line over 120 characters as ruff format does.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_apply.py packages/netstead/tests/test_workbench_related.py packages/netstead/tests/test_workbench_related_routes.py -q`
Expected: all pass.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q`, the ruff pair and `uv run lint-imports`.
Expected: all pass. `netstead.changes` imports only `netstead.spec` and corral, so the contract still holds.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/spec/keys.py packages/netstead/netstead/workbench/related.py packages/netstead/netstead/changes/apply.py packages/netstead/tests/test_changes_apply.py
git commit -m "feat(changes): roadway deletion (FK cascade from the spec) and addition"
```

---

### Task 8: `DraftCard`, `ChangeLog`, and ProjectCard YAML in and out

**Files:**
- Create: `packages/netstead/netstead/changes/card.py`
- Create: `packages/netstead/netstead/changes/log.py`
- Modify: `packages/netstead/netstead/changes/__init__.py`
- Test: `packages/netstead/tests/test_changes_card.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_changes_card.py`:

```python
"""Draft cards: ProjectCard dicts and YAML in and out, provenance in notes, and the change log (undo, commit)."""

import pytest

pytest.importorskip("yaml")
pytest.importorskip("jsonschema")

from netstead import Network  # noqa: E402
from netstead.changes import (  # noqa: E402
    ChangeError,
    ChangeLog,
    ChangeNotSupported,
    DraftCard,
    PropertyChange,
    RoadwayAddition,
    RoadwayDeletion,
    RoadwayPropertyChange,
    Selection,
    TransitPropertyChange,
    card_errors,
    read_card,
)
from netstead.fixtures import leavenworth  # noqa: E402

PICK = RoadwayPropertyChange(
    facility=Selection(ids=[1]),
    property_changes={"free_speed": PropertyChange(existing=40, set=30), "facility_type": PropertyChange(set="tertiary")},
    note="quality.high_speed_residential: link 1",
)
QUERY = RoadwayPropertyChange(
    facility=Selection(query={"links": {"name": ["Benton Street"], "ignore_missing": True}}, resolved=[1, 3]),
    property_changes={"lanes": PropertyChange(change=1)},
)
ADD = RoadwayAddition(
    nodes=[{"node_id": 9001, "x_coord": -120.66, "y_coord": 47.6}],
    links=[{"link_id": 9001, "from_node_id": 1, "to_node_id": 9001, "name": "New Street",
            "facility_type": "residential", "lanes": 1, "allowed_uses": "auto,walk"}],
)


def draft(*changes):
    return DraftCard(project="speed fixes", tags=["fixes"], changes=list(changes))


def test_a_pick_writes_wrangler_names_and_validates():
    card = draft(PICK).to_card()
    assert card["changes"] == [
        {
            "roadway_property_change": {
                "facility": {"links": {"model_link_id": [1], "ignore_missing": False}},
                "property_changes": {
                    "free_speed": {"existing": 40, "existing_value_conflict": "error", "set": 30},
                    "roadway": {"set": "tertiary"},
                },
            }
        }
    ]
    assert "netstead.note[0]: quality.high_speed_residential: link 1" in card["notes"]
    assert card_errors(card) == []


def test_a_query_keeps_its_query_and_records_what_it_resolved_to():
    card = draft(QUERY).to_card()
    assert card["changes"][0]["roadway_property_change"]["facility"] == QUERY.facility.query
    assert "netstead.resolved[0]: model_link_id=[1, 3]" in card["notes"]
    assert card_errors(card) == []
    back = DraftCard.from_card(card)
    assert back.changes[0].facility == QUERY.facility


def test_deletion_and_addition_cards_validate():
    card = draft(RoadwayDeletion(links=[1], clean_nodes=True), ADD).to_card()
    deletion, addition = (c.popitem()[1] for c in card["changes"])
    assert deletion == {"links": {"model_link_id": [1], "ignore_missing": False}, "clean_nodes": True}
    link = addition["links"][0]
    assert (link["A"], link["B"], link["roadway"]) == (1, 9001, "residential")
    assert (link["walk_access"], link["bike_access"], link["drive_access"]) == (1, 0, 1)
    assert addition["nodes"][0] == {"model_node_id": 9001, "X": -120.66, "Y": 47.6}
    assert card_errors(card) == []


def test_yaml_round_trip(tmp_path):
    original = draft(PICK, QUERY, RoadwayDeletion(links=[2]), ADD)
    path = tmp_path / "card.yml"
    path.write_text(original.to_yaml(), encoding="utf-8")
    assert read_card(path) == original


def test_the_offline_reports_edit_log_imports(tmp_path):
    from netstead.map.edits import Edit, EditLog, dump_edit_log

    path = tmp_path / "edits.yaml"
    dump_edit_log(EditLog(edits=[Edit(id="e1", kind="fix", table="link", pk={"link_id": 7}, column="lanes",
                                      from_value=1, to_value=2, reason="too few")]), path)
    (change,) = read_card(path).changes
    assert change.facility.ids == [7] and change.property_changes["lanes"] == PropertyChange(existing=1, set=2)
    assert "too few" in change.note


def test_a_query_without_provenance_is_not_supported_yet():
    card = {"project": "p", "changes": [{"roadway_property_change": {
        "facility": {"links": {"name": ["Main"], "ignore_missing": True}}, "property_changes": {"lanes": {"set": 2}}}}]}
    with pytest.raises(ChangeNotSupported, match="apply_card"):
        DraftCard.from_card(card)


def test_transit_cannot_be_written_yet():
    with pytest.raises(ChangeNotSupported):
        draft(TransitPropertyChange()).to_card()


@pytest.fixture
def log():
    return ChangeLog(Network.from_source(leavenworth.parquet_dir()))


def speed(log):
    df = log.net.tables["link"].to_pandas()
    return df.loc[df.link_id == 1, "free_speed"].tolist()


def test_apply_undo_commit(log):
    log.apply(PICK)
    assert speed(log) == [30.0] and len(log.draft.changes) == 1
    assert log.undo() == PICK and speed(log) == [40.0] and not log.draft.changes
    with pytest.raises(ChangeError, match="nothing to undo"):
        log.undo()
    log.apply(PICK)
    card_id = log.commit("Speed fixes", tags=["fixes"])
    assert card_id == "speed-fixes" and log.committed[0][1].changes == [PICK]
    assert not log.draft.changes and not log.applied  # a new draft; the committed card is not undone
    with pytest.raises(ChangeError):
        log.undo()
    log.apply(RoadwayPropertyChange(facility=Selection(ids=[2]), property_changes={"lanes": PropertyChange(set=2)}))
    assert log.commit("Speed fixes") == "speed-fixes-2"


def test_apply_all_is_all_or_nothing(log):
    bad = RoadwayPropertyChange(facility=Selection(ids=[999999]), property_changes={"lanes": PropertyChange(set=2)})
    with pytest.raises(ChangeError, match="change 2 of 2"):
        log.apply_all([PICK, bad])
    assert speed(log) == [40.0] and not log.draft.changes


def test_a_card_we_write_loads_in_projectcard(tmp_path):
    projectcard = pytest.importorskip("projectcard")  # dev group only: the interop check
    path = tmp_path / "card.yml"
    path.write_text(draft(PICK, QUERY, RoadwayDeletion(links=[2]), ADD).to_yaml(), encoding="utf-8")
    card = projectcard.read_card(path, validate=True)
    assert card.project == "speed fixes"
```

If `projectcard.read_card`'s signature differs in v0.3.3, use the package's documented loader. The assertion is
"it loads and validates with the package's own validator".

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_card.py -q`
Expected: FAIL with `ImportError: cannot import name 'ChangeLog'`.

- [ ] **Step 3: Implement `card.py`**

Create `packages/netstead/netstead/changes/card.py`:

```python
"""Draft ProjectCards: group changes, and translate them to and from card dicts and YAML files.

``DraftCard.to_card()`` writes ProjectCard names through the maintained mapping (``link_id`` ->
``model_link_id``, ``from_node_id`` -> ``A``, ...). A change cannot carry extra fields in the ProjectCard schema,
so netstead's provenance travels in the card-level ``notes``, one ``netstead.<what>[<i>]: <value>`` line per item:
``resolved`` (the link ids a query selection resolved to) and ``note`` (why change ``i`` was made).
:func:`read_card` reads those back. It also reads the offline report's edit-log YAML (``netstead.map.edits``),
whose facility puts ``model_link_id`` at the top level and whose changes carry their own ``notes``.
YAML needs the ``[projectcard]`` extra.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .apply import ChangeNotSupported
from .mapping import FieldMap, load_mapping
from .types import (
    CHANGE_TYPES,
    TRANSIT_TYPES,
    NetworkChange,
    PropertyChange,
    RoadwayAddition,
    RoadwayDeletion,
    RoadwayPropertyChange,
    Selection,
)

__all__ = ["Dependencies", "DraftCard", "read_card"]

_PROVENANCE = re.compile(r"^netstead\.(resolved|note)\[(\d+)\]: (.*)$")
_PROP_KEYS = ("existing", "set", "change", "existing_value_conflict")


class Dependencies(BaseModel):
    """A card's ProjectCard ``dependencies``: other projects, by name."""

    model_config = ConfigDict(extra="forbid")
    prerequisites: list[str] = Field(default_factory=list)
    corequisites: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    def to_card(self) -> dict[str, list[str]]:
        """Only the non-empty lists (the schema has no required keys)."""
        return {k: list(v) for k, v in self.model_dump().items() if v}


class DraftCard(BaseModel):
    """A ProjectCard being built (or committed): project, tags, dependencies, notes and its changes."""

    model_config = ConfigDict(extra="forbid")
    project: str = ""
    tags: list[str] = Field(default_factory=list)
    dependencies: Dependencies = Field(default_factory=Dependencies)
    notes: str | None = None
    changes: list[NetworkChange] = Field(default_factory=list)

    def to_card(self, mapping: FieldMap | None = None) -> dict[str, Any]:
        """The ProjectCard dict, in Wrangler names (raises :class:`ChangeNotSupported` for a transit change)."""
        m = mapping or load_mapping()
        card: dict[str, Any] = {"project": self.project or "untitled netstead card"}
        if self.tags:
            card["tags"] = list(self.tags)
        if deps := self.dependencies.to_card():
            card["dependencies"] = deps
        notes = ([self.notes] if self.notes else []) + _provenance(self.changes)
        if notes:
            card["notes"] = "\n".join(notes)
        card["changes"] = [{c.type: _body(c, m)} for c in self.changes]
        return card

    def to_yaml(self, mapping: FieldMap | None = None) -> str:
        """The card as YAML text, in the field order ProjectCard documents use."""
        return _yaml().safe_dump(self.to_card(mapping), sort_keys=False, default_flow_style=False, allow_unicode=True)

    @classmethod
    def from_card(cls, data: Mapping[str, Any], mapping: FieldMap | None = None) -> DraftCard:
        """Read a ProjectCard dict, with a ``changes`` array or one top-level change, back into GMNS names.

        Raises:
            ValueError: not a ProjectCard (no ``project``), or a malformed change.
            ChangeNotSupported: transit, ``pycode``, or a query selection without netstead provenance.
        """
        m = mapping or load_mapping()
        if not isinstance(data, Mapping) or "project" not in data:
            raise ValueError("not a ProjectCard: expected a top-level 'project'")
        raw = data.get("changes")
        if raw is None:
            raw = [{k: data[k]} for k in (*CHANGE_TYPES, "pycode") if k in data]
        notes, resolved, why = _split_notes(data.get("notes"))
        changes = []
        for i, item in enumerate(raw):
            if not isinstance(item, Mapping) or len(item) != 1:
                raise ValueError(f"change {i + 1}: expected exactly one change type")
            ((kind, body),) = item.items()
            changes.append(_change(kind, body or {}, m, resolved.get(i), why.get(i)))
        deps = {k: list(v) for k, v in (data.get("dependencies") or {}).items()}
        tags = data.get("tags") or []
        return cls(
            project=str(data["project"]),
            tags=[str(t) for t in tags],
            dependencies=Dependencies(**deps),
            notes=notes,
            changes=changes,
        )


def read_card(path: str | Path, mapping: FieldMap | None = None) -> DraftCard:
    """Read a ProjectCard YAML file (or an offline-report edit log) as a :class:`DraftCard`."""
    data = _yaml().safe_load(Path(path).read_text(encoding="utf-8"))
    return DraftCard.from_card(data or {}, mapping)


# ---------------------------------------------------------------- writing


def _yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("ProjectCard files need the [projectcard] extra: pip install 'netstead[projectcard]'") from exc
    return yaml


def _provenance(changes: list[Any]) -> list[str]:
    lines = []
    for i, c in enumerate(changes):
        if isinstance(c, RoadwayPropertyChange) and c.facility.query is not None:
            lines.append(f"netstead.resolved[{i}]: model_link_id={json.dumps(c.facility.resolved)}")
        if c.note:
            lines.append(f"netstead.note[{i}]: {' '.join(c.note.split())}")
    return lines


def _ids(ids: list[Any], table: str, m: FieldMap) -> dict[str, Any]:
    _, key = m.selector(table)
    return {key: list(ids), "ignore_missing": False}


def _facility(sel: Selection, m: FieldMap) -> dict[str, Any]:
    if sel.query is not None:
        query = copy.deepcopy(sel.query)
        query.setdefault("links", {}).setdefault("ignore_missing", True)  # required by the schema
        return query
    return {"links" if sel.table == "link" else "nodes": _ids(list(sel.ids or []), sel.table, m)}


def _prop(name: str, pc: PropertyChange, m: FieldMap) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if pc.existing is not None:
        out["existing"] = m.card_value(name, pc.existing)
        out["existing_value_conflict"] = pc.existing_value_conflict
    if pc.set is not None:
        out["set"] = m.card_value(name, pc.set)
    else:
        out["change"] = pc.change
    return out


def _record(record: dict[str, Any], table: str, m: FieldMap, *, derive: bool = False) -> dict[str, Any]:
    out = {}
    for column, value in record.items():
        if value is not None:
            name = m.to_card(table, column)
            out[name] = m.card_value(name, value)
    return {**m.derive(record), **out} if derive else out


def _body(c: Any, m: FieldMap) -> dict[str, Any]:
    if isinstance(c, RoadwayPropertyChange):
        table = c.facility.table
        props = {m.to_card(table, p): _prop(m.to_card(table, p), pc, m) for p, pc in c.property_changes.items()}
        return {"facility": _facility(c.facility, m), "property_changes": props}
    if isinstance(c, RoadwayDeletion):
        body: dict[str, Any] = {}
        if c.links:
            body["links"] = _ids(c.links, "link", m)
        if c.nodes:
            body["nodes"] = _ids(c.nodes, "node", m)
        if c.clean_nodes:
            body["clean_nodes"] = True
        return body
    if isinstance(c, RoadwayAddition):
        body = {}
        if c.links:
            body["links"] = [_record(r, "link", m, derive=True) for r in c.links]
        if c.nodes:
            body["nodes"] = [_record(r, "node", m) for r in c.nodes]
        return body
    raise ChangeNotSupported(f"{c.type} cannot be written to a card yet (transit arrives in phase P6)")


# ---------------------------------------------------------------- reading


def _split_notes(notes: Any) -> tuple[str | None, dict[int, list[Any]], dict[int, str]]:
    """``(the user's notes, {i: resolved ids}, {i: note})`` from a card's ``notes`` text."""
    if not isinstance(notes, str):
        return None, {}, {}
    kept, resolved, why = [], {}, {}
    for line in notes.splitlines():
        match = _PROVENANCE.match(line.strip())
        if match is None:
            kept.append(line)
        elif match[1] == "resolved":
            resolved[int(match[2])] = json.loads(match[3].split("=", 1)[1])
        else:
            why[int(match[2])] = match[3]
    text = "\n".join(kept).strip()
    return text or None, resolved, why


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else [value]


def _selector_ids(selector: Any, table: str, m: FieldMap) -> list[Any]:
    if not selector:
        return []
    _, key = m.selector(table)
    if key not in selector:
        raise ChangeNotSupported(f"only {key} selections can be read for a deletion in this version")
    return _as_list(selector[key])


def _selection(facility: Mapping[str, Any], m: FieldMap, resolved: list[Any] | None) -> Selection:
    for table in ("link", "node"):  # the offline report's edit log: {model_link_id: [...]} at the top level
        _, key = m.selector(table)
        if key in facility:
            return Selection(table=table, ids=_as_list(facility[key]))
    if facility.get("nodes") is not None:
        return Selection(table="node", ids=_selector_ids(facility["nodes"], "node", m))
    links = facility.get("links")
    if links is None:
        raise ValueError("a property change needs a facility with links or nodes")
    _, key = m.selector("link")
    by_id = key in links and set(links) <= {key, "ignore_missing"} and "from" not in facility and "to" not in facility
    if by_id:
        return Selection(ids=_as_list(links[key]))
    if resolved is None:
        raise ChangeNotSupported(
            "this card selects links by a query (name/ref/...) with no netstead provenance; "
            "re-resolving a query arrives with apply_card"
        )
    return Selection(query=dict(facility), resolved=resolved)


def _from_record(record: Mapping[str, Any], table: str, m: FieldMap) -> dict[str, Any]:
    return {m.from_card(table, k): m.gmns_value(k, v) for k, v in record.items() if k not in m.derived}


def _change(kind: str, body: Mapping[str, Any], m: FieldMap, resolved: list[Any] | None, note: str | None) -> Any:
    if kind in TRANSIT_TYPES or kind not in CHANGE_TYPES:
        raise ChangeNotSupported(f"{kind} changes are not supported yet")
    if note is None and isinstance(body.get("notes"), str):  # the offline report's per-change notes
        note = body["notes"]
    if kind == "roadway_property_change":
        sel = _selection(body.get("facility") or {}, m, resolved)
        props = {
            m.from_card(sel.table, name): PropertyChange(
                **{k: (m.gmns_value(name, v) if k in ("existing", "set") else v) for k, v in spec.items() if k in _PROP_KEYS}
            )
            for name, spec in (body.get("property_changes") or {}).items()
        }
        return RoadwayPropertyChange(facility=sel, property_changes=props, note=note)
    if kind == "roadway_deletion":
        return RoadwayDeletion(
            links=_selector_ids(body.get("links"), "link", m),
            nodes=_selector_ids(body.get("nodes"), "node", m),
            clean_nodes=bool(body.get("clean_nodes")),
            note=note,
        )
    return RoadwayAddition(
        links=[_from_record(r, "link", m) for r in body.get("links") or []],
        nodes=[_from_record(r, "node", m) for r in body.get("nodes") or []],
        note=note,
    )
```

The map/edits writer puts `existing` before `set`, while ours writes `existing_value_conflict` too.
`test_the_offline_reports_edit_log_imports` compares the parsed `PropertyChange(existing=1, set=2)`, so both shapes
read the same.

- [ ] **Step 4: Implement `log.py`**

Create `packages/netstead/netstead/changes/log.py`:

```python
"""A network's change log: the draft card being built, the results that undo it, and the committed cards.

Undo works on the draft only, last change first. Committing freezes the draft under an id derived from its
project name, and starts a new, empty draft. A committed card's changes stay applied; reverting one is a later
feature (apply its inverse as a new card).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .apply import ChangeError, ChangeResult, apply_change, reverse_change
from .card import Dependencies, DraftCard
from .types import NetworkChange

__all__ = ["ChangeLog"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "card"


class ChangeLog:
    """Changes applied to one network, grouped into a draft card until committed."""

    def __init__(self, net: Any) -> None:
        """Start an empty draft for ``net`` (a :class:`~netstead.network.Network`, mutated by :meth:`apply`)."""
        self.net = net
        self.draft = DraftCard()
        self.applied: list[ChangeResult] = []  # parallel to draft.changes
        self.committed: list[tuple[str, DraftCard]] = []

    def apply(self, change: NetworkChange) -> ChangeResult:
        """Apply ``change`` and append it to the draft (raises :class:`ChangeError`; nothing changes then)."""
        result = apply_change(self.net, change)
        self.applied.append(result)
        self.draft = self.draft.model_copy(update={"changes": [*self.draft.changes, change]})
        return result

    def apply_all(self, changes: Sequence[NetworkChange]) -> list[ChangeResult]:
        """Apply ``changes`` in order, all or nothing: on a failure, the ones already applied are undone."""
        done: list[ChangeResult] = []
        try:
            for k, change in enumerate(changes, start=1):
                try:
                    done.append(self.apply(change))
                except ChangeError as exc:
                    raise type(exc)(f"change {k} of {len(changes)}: {exc}") from exc
        except ChangeError:
            for _ in done:
                self.undo()
            raise
        return done

    def undo(self) -> NetworkChange:
        """Reverse the draft's last change, drop it from the draft, and return it."""
        if not self.applied:
            raise ChangeError("nothing to undo: the draft card has no changes (committed cards are not undone)")
        result = self.applied.pop()
        reverse_change(self.net, result)
        self.draft = self.draft.model_copy(update={"changes": self.draft.changes[:-1]})
        return result.change

    def describe(
        self,
        *,
        project: str | None = None,
        tags: Iterable[str] | None = None,
        dependencies: Mapping[str, list[str]] | None = None,
    ) -> None:
        """Name the draft; arguments left ``None`` are unchanged."""
        update: dict[str, Any] = {}
        if project is not None:
            update["project"] = project
        if tags is not None:
            update["tags"] = list(tags)
        if dependencies is not None:
            update["dependencies"] = Dependencies(**dependencies)
        self.draft = self.draft.model_copy(update=update)

    def commit(
        self,
        project: str,
        *,
        tags: Iterable[str] = (),
        dependencies: Mapping[str, list[str]] | None = None,
        notes: str | None = None,
    ) -> str:
        """Freeze the draft as a card named ``project``, start a new draft, and return the card's id."""
        if not self.draft.changes:
            raise ChangeError("the draft card has no changes to commit")
        card = self.draft.model_copy(
            update={"project": project, "tags": list(tags), "dependencies": Dependencies(**(dependencies or {})),
                    "notes": notes}
        )
        taken = {cid for cid, _ in self.committed}
        base = card_id = _slug(project)
        n = 2
        while card_id in taken:
            card_id, n = f"{base}-{n}", n + 1
        self.committed.append((card_id, card))
        self.draft, self.applied = DraftCard(), []
        return card_id

    def card(self, which: str = "draft") -> DraftCard:
        """The draft, or the committed card with id ``which`` (``KeyError`` if none)."""
        if which == "draft":
            return self.draft
        for card_id, card in self.committed:
            if card_id == which:
                return card
        raise KeyError(f"no committed card {which!r}")

    def summary(self) -> dict[str, Any]:
        """JSON-safe counts for the session state."""
        return {
            "draft": len(self.draft.changes),
            "committed": len(self.committed),
            "can_undo": bool(self.applied),
            "project": self.draft.project,
        }
```

Add `Dependencies`, `DraftCard`, `read_card` and `ChangeLog` to `changes/__init__.py`. Also add `KEYS` and
`apply.__all__` there if Task 6 has not already.

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_changes_card.py packages/netstead/tests/test_changes_apply.py -q`
Expected: all pass, `test_a_card_we_write_loads_in_projectcard` included (the dev group installs `projectcard`).

If `projectcard` rejects the addition record because a required Wrangler field is missing, add that field to
`ADD` in the test **and** to the mapping's `derived` rules when it can be derived. Do not loosen the check.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/changes packages/netstead/tests/test_changes_card.py
git commit -m "feat(changes): DraftCard, ChangeLog (undo, commit) and ProjectCard YAML in and out"
```

---

### Task 9: `RunValidation`: a background job, with issues located by key and anchor

**Files:**
- Create: `packages/netstead/netstead/workbench/issues.py`
- Modify: `packages/netstead/netstead/config.py` (`RuleSettings.severity_override`)
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py`
- Test: `packages/netstead/tests/test_workbench_issues.py`; modify `packages/netstead/tests/test_workbench_session.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_issues.py`:

```python
"""Validation in the workbench: RunValidation as a recorded job; issues tied to record keys and map anchors."""

import json

import pytest
from corral.reports import Category, Issue, Severity, ValidationReport
from netstead import Network
from netstead.config import ValidationSettings
from netstead.fixtures import leavenworth
from netstead.workbench import Session
from netstead.workbench.actions import RunValidation, SetSetting
from netstead.workbench.issues import locate_issues, rule_configs
from pydantic import ValidationError

SRC = str(leavenworth.parquet_dir())


@pytest.fixture
def session(tmp_path):
    env = {"NETSTEAD_CONFIG_DIR": str(tmp_path / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([SRC, str(tmp_path)])}
    s = Session(project_dir=tmp_path, environ=env)
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
    assert lane["fixable"] is False  # only link and node records are editable in P2
    assert xy["anchor"] == {"lonlat": [-120.6, 47.6]} and xy["key"] is None


def test_a_new_version_makes_the_issue_set_stale(session):
    session.dispatch(RunValidation())
    session.registry.get("leavenworth").bump()  # Task 11's tests use a real ApplyEdit
    assert session.state()["issues"]["leavenworth"]["stale"] is True


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

from .related import primary_keys

__all__ = ["MAX_MARKERS", "SEVERITIES", "IssueSet", "locate_issues", "rule_configs", "run_validation"]

SEVERITIES = ("error", "warning", "info")
#: Located issues sent to the map; beyond this the markers answer says ``truncated``.
MAX_MARKERS = 50_000
#: Tables whose records the P2 editor can change.
_EDITABLE = ("link", "node")
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
        fixable = (
            table in _EDITABLE
            and key is not None
            and issue.column not in (None, pk)
            and issue.column in tables[table].columns()
        )
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
    if table in _EDITABLE:
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
class RunValidation(_Action):
    """Validate a network (spec, keys, structure, and the quality rules in Settings → validation) as a background job."""

    type: Literal["run_validation"] = "run_validation"
    runs_as_job: ClassVar[bool] = True
    net_id: str | None = None
    quality: bool = True

    def job_label(self) -> str:
        """``validate <network>``."""
        return f"validate {self.net_id or 'network'}"
```

Add it to `Action`, `__all__` and `workbench/__init__.py` (import and `__all__`).

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

   Rename its parameter from `loaded: _Loaded` to `outcome: _Outcome`. Define, after the outcome classes,
   `_Outcome = _Loaded | _Validated` (Task 12 adds `_Saved`).
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

7. In `_do_close_network`, after the examples line: `self.issues.pop(action.net_id, None)`.
8. In `_SECTION_NOTES`, delete the `"validation"` entry.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_issues.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_jobs.py packages/netstead/tests/test_workbench_actions.py -q`
Expected: all pass. The `_commit` refactor is covered by the existing open/build job tests.

- [ ] **Step 8: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add packages/netstead/netstead/config.py packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_issues.py packages/netstead/tests/test_workbench_session.py
git commit -m "feat(workbench): RunValidation job; issues located by record key and map anchor"
```

---

### Task 10: Issues, markers and report routes

**Files:**
- Create: `packages/netstead/netstead/workbench/routes/common.py`
- Create: `packages/netstead/netstead/workbench/routes/edit.py`
- Modify: `packages/netstead/netstead/workbench/routes/network.py`, `server.py`
- Test: `packages/netstead/tests/test_workbench_edit_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_edit_routes.py`:

```python
"""Validation and change-log routes: read-only views of what actions produced (never recorded)."""

import json

import pytest
from fastapi.testclient import TestClient
from netstead.fixtures import leavenworth
from netstead.workbench import Session, build_app

BASE = "/api/n/leavenworth/roadway"
SRC = str(leavenworth.parquet_dir())


def _session(tmp):
    env = {"NETSTEAD_CONFIG_DIR": str(tmp / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([SRC, str(tmp)])}
    s = Session(project_dir=tmp, environ=env)
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

Create `packages/netstead/netstead/workbench/routes/edit.py`. Task 13 adds the change-log routes to it.

```python
"""Validation and change-log views of one network: ``/api/n/{net_id}/{component}/issues``, ``/report.html``, ...

Read-only: they show what actions produced (``RunValidation``; in Task 13 ``ApplyEdit``, ``CommitCard``, ...).
Nothing here is recorded in the session history.
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
    """Build the validation and change-log routes bound to ``session``."""
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

### Task 11: Edit actions on the change log

`ApplyEdit` is the UI's action (picked ids or the current selection, `set` or `delete`). `ApplyChange` takes any
`NetworkChange` as-is, for Python, the assistant (P3) and additions. Both go through one `Session._apply_change`.
`UndoChange`, `CommitCard` and `ImportCard` complete the log.

**Files:**
- Create: `packages/netstead/netstead/workbench/editing.py`
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py`
- Test: `packages/netstead/tests/test_workbench_changes.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/netstead/tests/test_workbench_changes.py`:

```python
"""Edits in the workbench compile to ProjectCard changes; the session history and the change log stay separate."""

import json

import pytest
from netstead.changes import (
    DraftCard,
    PropertyChange,
    RoadwayAddition,
    RoadwayPropertyChange,
    Selection,
    TransitPropertyChange,
)
from netstead.fixtures import leavenworth
from netstead.select.intent import Facility, SelectionIntent
from netstead.select.result import SelectionResult
from netstead.workbench import Session
from netstead.workbench.actions import (
    ApplyChange,
    ApplyEdit,
    CommitCard,
    ImportCard,
    OpenNetwork,
    RunValidation,
    Select,
    Style,
    UndoChange,
)
from netstead.workbench.editing import compile_edit
from netstead.workbench.errors import ActionError, NotSupportedYet, PathNotAllowed

SRC = str(leavenworth.parquet_dir())


@pytest.fixture
def session(tmp_path):
    env = {"NETSTEAD_CONFIG_DIR": str(tmp_path / "u"), "NETSTEAD_IO__ALLOWED_ROOTS": json.dumps([SRC, str(tmp_path)])}
    s = Session(project_dir=tmp_path, environ=env)
    s.dispatch(OpenNetwork(source=SRC))
    return s


def handle(session):
    return session.registry.get("leavenworth")


def cell(session, link_id, column="free_speed"):
    df = handle(session).links_df()
    return df.loc[df.link_id == link_id, column].tolist()


def test_a_fix_is_one_action_and_one_change(session):
    result = session.dispatch(ApplyEdit(ids=[1], set={"free_speed": 30}, note="signed 30 mph"))
    assert cell(session, 1) == [30.0] and result["version"] == 1 and result["draft_changes"] == 1
    change = result["change"]
    assert change["facility"] == {"table": "link", "ids": [1], "query": None, "resolved": None}
    assert change["property_changes"]["free_speed"]["existing"] == 40.0 and change["note"] == "signed 30 mph"
    assert session.history[-1].python == "app.do(ApplyEdit(ids=[1], set={'free_speed': 30}, note='signed 30 mph'))"
    assert session.state()["changes"]["leavenworth"] == {"draft": 1, "committed": 0, "can_undo": True, "project": ""}


def test_existing_is_left_out_when_the_targets_differ(session):
    change = session.dispatch(ApplyEdit(ids=[1, 2], set={"free_speed": 30}))["change"]
    assert change["property_changes"]["free_speed"]["existing"] is None  # 40.0 and 40.23


def test_the_two_logs_stay_separate(session):
    session.dispatch(Style(show_legend=False))
    session.dispatch(ApplyEdit(ids=[1], set={"lanes": 2}))
    session.dispatch(UndoChange())
    assert [e.action["type"] for e in session.history[-3:]] == ["style", "apply_edit", "undo_change"]
    assert session.changes["leavenworth"].draft.changes == []  # the change log holds what is applied now
    assert cell(session, 1, "lanes") == [1] and handle(session).version == 2


def test_undo_with_nothing_is_a_recorded_failure(session):
    with pytest.raises(ActionError, match="nothing to undo"):
        session.dispatch(UndoChange())
    assert not session.history[-1].ok


def test_commit_names_the_card_and_extends_the_lineage(session):
    session.dispatch(ApplyEdit(ids=[1], set={"lanes": 2}))
    result = session.dispatch(CommitCard(project="Lane fixes", tags=["fixes"]))
    assert result == {"net_id": "leavenworth", "card_id": "lane-fixes", "changes": 1, "lineage": ["lane-fixes"]}
    assert session.state()["networks"][0]["lineage"] == ["lane-fixes"]
    with pytest.raises(ActionError, match="nothing to undo"):
        session.dispatch(UndoChange())  # a committed card is not undone
    with pytest.raises(ActionError, match="no changes"):
        session.dispatch(CommitCard(project="Empty"))


def test_a_picked_selection_stores_ids_only(session):
    session.dispatch(Select(link_ids=[1, 2]))
    change = session.dispatch(ApplyEdit(use_selection=True, set={"lanes": 2}))["change"]
    assert change["facility"]["ids"] == [1, 2] and change["facility"]["query"] is None


def test_a_query_selection_keeps_its_query_and_the_ids_it_resolved_to(session):
    result = SelectionResult(status="resolved", intent=SelectionIntent(facility=Facility(name=["Benton Street"])), link_ids=[1])
    change = compile_edit(ApplyEdit(use_selection=True, set={"lanes": 2}), handle(session), result)
    assert change.facility.query["links"]["name"] == ["Benton Street"]
    assert change.facility.query["links"]["ignore_missing"] is True
    assert change.facility.resolved == [1]


def test_use_selection_needs_one(session):
    with pytest.raises(ActionError, match="nothing is selected"):
        session.dispatch(ApplyEdit(use_selection=True, set={"lanes": 2}))


def test_deleting_a_selected_link_clears_the_selection(session):
    session.dispatch(Select(link_ids=[1, 2]))
    session.dispatch(ApplyEdit(ids=[1], delete=True))
    assert 1 not in set(handle(session).links_df().link_id) and session.selection is None


def test_apply_change_takes_any_network_change(session):
    node = {"node_id": 9001, "x_coord": -120.66, "y_coord": 47.6}
    link = {"link_id": 9001, "from_node_id": 1, "to_node_id": 9001, "name": "New Street"}
    session.dispatch(ApplyChange(change=RoadwayAddition(nodes=[node], links=[link])))
    assert cell(session, 9001, "name") == ["New Street"]
    assert session.history[-1].python.startswith("app.do(ApplyChange(change={'type': 'roadway_addition'")


def test_transit_edits_are_not_supported_yet(session):
    with pytest.raises(NotSupportedYet):
        session.dispatch(ApplyEdit(component="transit", ids=[1], set={"lanes": 2}))
    with pytest.raises(NotSupportedYet):
        session.dispatch(ApplyChange(change=TransitPropertyChange()))


def test_a_value_that_does_not_fit_is_refused_and_changes_nothing(session):
    with pytest.raises(ActionError, match="does not fit"):
        session.dispatch(ApplyEdit(ids=[1], set={"free_speed": "fast"}))
    assert cell(session, 1) == [40.0] and handle(session).version == 0


def test_an_edit_makes_the_issues_stale(session):
    session.dispatch(RunValidation())
    session.dispatch(ApplyEdit(ids=[1], set={"free_speed": 30}))
    assert session.state()["issues"]["leavenworth"]["stale"] is True
    assert session.dispatch(RunValidation())["counts"]["warning"] == 271  # link 1 no longer flagged


def write(card, path):
    path.write_text(card.to_yaml(), encoding="utf-8")
    return str(path)


def lanes(link_id, value):
    return RoadwayPropertyChange(facility=Selection(ids=[link_id]), property_changes={"lanes": PropertyChange(set=value)})


def test_import_applies_a_card_and_names_the_draft(session, tmp_path):
    path = write(DraftCard(project="Imported", tags=["x"], changes=[lanes(1, 3)]), tmp_path / "card.yml")
    result = session.dispatch(ImportCard(path=path))
    assert result["imported"] == 1 and cell(session, 1, "lanes") == [3]
    assert session.changes["leavenworth"].draft.project == "Imported"


def test_import_is_all_or_nothing(session, tmp_path):
    path = write(DraftCard(project="Bad", changes=[lanes(1, 3), lanes(999999, 3)]), tmp_path / "bad.yml")
    with pytest.raises(ActionError, match="change 2 of 2"):
        session.dispatch(ImportCard(path=path))
    assert cell(session, 1, "lanes") == [1] and handle(session).version == 0


def test_import_stays_inside_the_allowed_roots(session):
    with pytest.raises(PathNotAllowed):
        session.dispatch(ImportCard(path="/etc/card.yml"))


def test_a_replayed_history_reproduces_the_edits(session, tmp_path):
    session.dispatch(ApplyEdit(ids=[1], set={"free_speed": 30}))
    session.dispatch(ApplyEdit(ids=[2], set={"lanes": 2}))
    session.dispatch(UndoChange())
    import netstead.workbench as wb

    other = Session(project_dir=tmp_path, environ=session._environ)
    namespace = {"app": other, **{name: getattr(wb, name) for name in wb.__all__}}
    for entry in session.history:
        exec(entry.python, namespace)  # replaying our own recorded snippets
    df = other.registry.get("leavenworth").links_df()
    assert df.loc[df.link_id == 1, "free_speed"].tolist() == [30.0] and df.loc[df.link_id == 2, "lanes"].tolist() == [1]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_changes.py -q`
Expected: FAIL with `ImportError: cannot import name 'ApplyChange'`.

- [ ] **Step 3: The actions**

In `packages/netstead/netstead/workbench/actions.py`, add `from netstead.changes import NetworkChange`.

Hoist the build-name pattern so `SaveNetwork` (Task 12) can share it. Put it next to `_OUTPUT_SUFFIXES`:

```python
#: A file or folder name: letters, digits, ``_ . -``; no path separator, no leading dot.
_NAME_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?$"
```

Make `BuildNetwork.name` use `Field(pattern=_NAME_PATTERN, max_length=100)`. Then add, after `SetSetting`:

```python
Scalar = int | float | str


class ApplyEdit(_Action):
    """Edit roadway records: set properties of picked ids (or of the current selection), or delete them.

    Compiles to a ProjectCard change (``roadway_property_change`` or ``roadway_deletion``) that is applied and
    appended to the network's draft card. ``existing`` is filled in from the network when all targets agree.
    """

    type: Literal["apply_edit"] = "apply_edit"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    component: Component = "roadway"
    table: Literal["link", "node"] = "link"
    ids: list[int | str] | None = None
    use_selection: bool = False
    set: dict[str, Scalar] | None = None
    delete: bool = False
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_target_one_edit(self) -> ApplyEdit:
        if self.use_selection == (self.ids is not None):
            raise ValueError("give exactly one of ids or use_selection")
        if self.ids is not None and not self.ids:
            raise ValueError("ids must not be empty")
        if self.use_selection and self.table != "link":
            raise ValueError("use_selection edits links (a selection is links)")
        if (self.set is None) == (not self.delete):
            raise ValueError("give exactly one of set={...} or delete=True")
        if self.set is not None and not self.set:
            raise ValueError("set at least one property")
        return self


class ApplyChange(_Action):
    """Apply one ProjectCard-shaped change as-is (Python, the assistant, additions); it joins the draft card."""

    type: Literal["apply_change"] = "apply_change"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    change: NetworkChange


class UndoChange(_Action):
    """Reverse the last change of the network's draft card (committed cards are not undone)."""

    type: Literal["undo_change"] = "undo_change"
    mutates: ClassVar[bool] = True
    net_id: str | None = None


class CommitCard(_Action):
    """Name the draft card and freeze it; a new, empty draft starts. The card's id joins the network's lineage."""

    type: Literal["commit_card"] = "commit_card"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    project: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)
    dependencies: dict[Literal["prerequisites", "corequisites", "conflicts"], list[str]] = Field(default_factory=dict)
    notes: str | None = None


class ImportCard(_Action):
    """Apply every change of a ProjectCard YAML file (inside ``io.allowed_roots``) to the draft, all or nothing.

    Also reads the offline validation report's edit log (``netstead.map.edits``).
    """

    type: Literal["import_card"] = "import_card"
    mutates: ClassVar[bool] = True
    net_id: str | None = None
    path: str
```

Add the five to `Action`, `__all__`, and `workbench/__init__.py`.

`ApplyEdit.set` shadows the builtin `set` inside the class body only. Nothing in the class calls `set()`, so leave
it, and keep the JSON name.

- [ ] **Step 4: `workbench/editing.py`**

```python
"""Workbench edits as ProjectCard changes: compile an ``ApplyEdit``, and describe a change log for the UI."""

from __future__ import annotations

import json
from typing import Any

from netstead.changes import (
    ChangeLog,
    ChangeResult,
    DraftCard,
    NetworkChange,
    PropertyChange,
    RoadwayAddition,
    RoadwayDeletion,
    RoadwayPropertyChange,
    Selection,
)
from netstead.select.emit import to_projectcard
from netstead.viz.styling import json_scalar

from .actions import ApplyEdit
from .errors import ActionError
from .registry import NetworkHandle

__all__ = ["change_view", "changes_payload", "compile_edit"]

_KEYS = {"link": "link_id", "node": "node_id"}


def _plain(obj: Any) -> Any:
    """``obj`` with numpy/pandas scalars made plain (a query built from a resolved selection may hold them)."""
    return json.loads(json.dumps(obj, default=json_scalar))


def compile_edit(action: ApplyEdit, handle: NetworkHandle, selection: Any | None) -> NetworkChange:
    """The ProjectCard change an :class:`~netstead.workbench.actions.ApplyEdit` stands for.

    Picked ids become an id selection. ``use_selection`` uses the session's resolved ``SelectionResult``: one made
    by picking ids stays ids only; one made from a query (an utterance, a name or ref) keeps the query in card
    form plus the ids it resolved to. ``existing`` is read from the network when every target holds one value.
    """
    facility = _facility(action, selection)
    if action.delete:
        ids = facility.target_ids()
        if action.table == "link":
            return RoadwayDeletion(links=ids, note=action.note)
        return RoadwayDeletion(nodes=ids, note=action.note)
    frame = handle.links_df() if action.table == "link" else handle.nodes_df()
    targets = facility.target_ids()
    props = {
        column: PropertyChange(existing=_existing(frame, _KEYS[action.table], targets, column), set=value)
        for column, value in (action.set or {}).items()
    }
    return RoadwayPropertyChange(facility=facility, property_changes=props, note=action.note)


def _facility(action: ApplyEdit, selection: Any | None) -> Selection:
    if not action.use_selection:
        return Selection(table=action.table, ids=list(action.ids or []))
    if selection is None or selection.status != "resolved":
        raise ActionError("the selection is not resolved: pick links, or fix the request first")
    ids = [json_scalar(i) for i in selection.link_ids]
    if selection.intent.link_ids:  # picked by id ("Set as selection"): a click-pick stores ids only
        return Selection(ids=ids)
    return Selection(query=_plain(to_projectcard(selection, form="query")), resolved=ids)


def _existing(frame: Any, pk: str, ids: list[Any], column: str) -> Any:
    if column not in frame.columns:
        return None  # apply_change names the unknown column
    values = {json_scalar(v) for v in frame.loc[frame[pk].isin(ids), column]}
    if len(values) != 1:
        return None
    (value,) = values
    return value if isinstance(value, int | float | str) and not isinstance(value, bool) else None


def change_view(change: NetworkChange, result: ChangeResult | None) -> dict[str, Any]:
    """One change for the Changes tab: type, selection, properties (existing -> set / change) and outcome."""
    view: dict[str, Any] = {
        "type": change.type,
        "note": change.note,
        "rows": result.rows if result else None,
        "warnings": list(result.warnings) if result else [],
        "skipped": list(result.skipped) if result else [],
    }
    if isinstance(change, RoadwayPropertyChange):
        f = change.facility
        view["selection"] = {"table": f.table, "ids": f.ids, "query": f.query, "resolved": len(f.resolved or [])}
        view["properties"] = [
            {"name": name, "existing": p.existing, "set": p.set, "change": p.change}
            for name, p in change.property_changes.items()
        ]
    elif isinstance(change, RoadwayDeletion):
        view.update(links=list(change.links), nodes=list(change.nodes), clean_nodes=change.clean_nodes)
    elif isinstance(change, RoadwayAddition):
        view.update(links=[r.get("link_id") for r in change.links], nodes=[r.get("node_id") for r in change.nodes])
    return view


def changes_payload(handle: NetworkHandle, log: ChangeLog | None) -> dict[str, Any]:
    """The Changes tab's data: the draft card (with its changes), what can be undone, and the committed cards."""
    draft = log.draft if log else DraftCard()
    applied = log.applied if log else []
    return {
        "net_id": handle.id,
        "version": handle.version,
        "lineage": list(handle.lineage),
        "draft": {
            "project": draft.project,
            "tags": list(draft.tags),
            "dependencies": draft.dependencies.model_dump(),
            "notes": draft.notes,
            "changes": [change_view(c, r) for c, r in zip(draft.changes, applied, strict=True)],
        },
        "can_undo": bool(applied),
        "committed": [
            {"id": card_id, "project": card.project, "tags": list(card.tags), "changes": len(card.changes)}
            for card_id, card in (log.committed if log else [])
        ],
    }
```

- [ ] **Step 5: The session handlers**

In `packages/netstead/netstead/workbench/session.py`:

1. Imports:
   - `from netstead.changes import ChangeError, ChangeLog, ChangeNotSupported, DraftCard, NetworkChange, read_card`;
   - add `ApplyChange, ApplyEdit, CommitCard, ImportCard, UndoChange` to the `.actions` import;
   - `from .editing import changes_payload, compile_edit`;
   - add `resolve_allowed` to the `.paths` import.
2. In `__init__`:
   - `self.changes: dict[str, ChangeLog] = {}  # net_id -> its change log (the ProjectCard audit trail)`;
   - `self._selection_result: Any = None  # the SelectionResult behind self.selection (ApplyEdit use_selection)`.
3. Keep `_selection_result` in step with `self.selection`. In `_do_select`:
   - set `self._selection_result = result` in the link-ids branch;
   - set `self._selection_result = None` in the `prepared.error` branch;
   - set `self._selection_result = prepared.result` in the final branch.

   In `_do_clear_selection`, set it to `None`. In `_do_close_network`, set it to `None` where the selection is
   cleared, and add `self.changes.pop(action.net_id, None)`.
4. In `state()`, add `"changes": {nid: log.summary() for nid, log in self.changes.items()},`.
5. Add the public views, after `issue_set`:

```python
    def changes_payload(self, handle: NetworkHandle) -> dict[str, Any]:
        """The Changes tab's data for ``handle`` (a snapshot taken under the lock)."""
        with self._lock:
            return changes_payload(handle, self.changes.get(handle.id))

    def card(self, handle: NetworkHandle, which: str = "draft") -> DraftCard:
        """A copy of the draft card, or of the committed card with id ``which`` (``KeyError`` if none)."""
        with self._lock:
            log = self.changes.get(handle.id)
            if log is None:
                if which == "draft":
                    return DraftCard()
                raise KeyError(f"no committed card {which!r}")
            return log.card(which).model_copy(deep=True)
```

6. Add the handlers after `_do_set_setting`:

```python
    def _log(self, handle: NetworkHandle) -> ChangeLog:
        return self.changes.setdefault(handle.id, ChangeLog(handle.roadway))

    def _apply_change(self, handle: NetworkHandle, change: NetworkChange) -> dict[str, Any]:
        """Apply one change through the network's change log, bump its version, and describe the result."""
        log = self._log(handle)
        try:
            result = log.apply(change)
        except ChangeNotSupported as exc:
            raise NotSupportedYet(str(exc)) from exc
        except ChangeError as exc:
            raise ActionError(str(exc)) from exc
        handle.bump()
        if change.type == "roadway_deletion" and self.selection and self.selection["net_id"] == handle.id:
            if set(self.selection["link_ids"]) & set(change.links):  # it would point at deleted links
                self.selection, self._selection_result = None, None
        return {
            "net_id": handle.id,
            "version": handle.version,
            "change": change.model_dump(mode="json"),
            **result.summary(),
            "draft_changes": len(log.draft.changes),
        }

    def _do_apply_edit(self, action: ApplyEdit) -> dict[str, Any]:
        if action.component != "roadway":
            raise NotSupportedYet("transit edits arrive with the transit component (phase P6)")
        handle = self._handle(action.net_id)
        selection = None
        if action.use_selection:
            if not self.selection or self.selection["net_id"] != handle.id or self._selection_result is None:
                raise ActionError("nothing is selected on this network: select links first")
            selection = self._selection_result
        return self._apply_change(handle, compile_edit(action, handle, selection))

    def _do_apply_change(self, action: ApplyChange) -> dict[str, Any]:
        return self._apply_change(self._handle(action.net_id), action.change)

    def _do_undo_change(self, action: UndoChange) -> dict[str, Any]:
        handle = self._handle(action.net_id)
        log = self._log(handle)
        try:
            change = log.undo()
        except ChangeError as exc:
            raise ActionError(str(exc)) from exc
        handle.bump()
        return {
            "net_id": handle.id,
            "version": handle.version,
            "undone": change.model_dump(mode="json"),
            "draft_changes": len(log.draft.changes),
        }

    def _do_commit_card(self, action: CommitCard) -> dict[str, Any]:
        handle = self._handle(action.net_id)
        log = self._log(handle)
        try:
            card_id = log.commit(action.project, tags=action.tags, dependencies=action.dependencies, notes=action.notes)
        except ChangeError as exc:
            raise ActionError(str(exc)) from exc
        handle.lineage.append(card_id)
        return {
            "net_id": handle.id,
            "card_id": card_id,
            "changes": len(log.card(card_id).changes),
            "lineage": list(handle.lineage),
        }

    def _do_import_card(self, action: ImportCard) -> dict[str, Any]:
        handle = self._handle(action.net_id)
        path = resolve_allowed(action.path, self.settings)  # PathNotAllowed outside io.allowed_roots
        try:
            card = read_card(path)
        except ChangeNotSupported as exc:
            raise NotSupportedYet(str(exc)) from exc
        except ImportError as exc:  # the [projectcard] extra is missing: say how to install it
            raise ActionError(str(exc)) from exc
        except Exception as exc:  # boundary: unreadable file, bad YAML (yaml.YAMLError), not a card
            raise ActionError(f"could not read {action.path}: {exc}") from exc
        if not card.changes:
            raise ActionError(f"{action.path} has no changes")
        log = self._log(handle)
        try:
            log.apply_all(card.changes)
        except ChangeNotSupported as exc:
            raise NotSupportedYet(str(exc)) from exc
        except ChangeError as exc:
            raise ActionError(str(exc)) from exc
        if card.project and not log.draft.project:
            log.describe(project=card.project, tags=card.tags, dependencies=card.dependencies.model_dump())
        handle.bump()
        return {
            "net_id": handle.id,
            "version": handle.version,
            "imported": len(card.changes),
            "project": card.project,
            "draft_changes": len(log.draft.changes),
        }
```

`_do_*` handlers run under the session lock (`dispatch_recorded`), so a change and its version bump are one step for
every reader that takes the lock. Readers of cached frames see the old version until `bump`, then rebuild.

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_changes.py packages/netstead/tests/test_workbench_session.py packages/netstead/tests/test_workbench_actions.py -q`
Expected: all pass.

`test_workbench_actions.py` may pin the action-schema type list. If so, add the new types to its expectation:
that is the schema growing by design.

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_changes.py packages/netstead/tests/test_workbench_actions.py
git commit -m "feat(workbench): ApplyEdit/ApplyChange/UndoChange/CommitCard/ImportCard on the change log"
```

---

### Task 12: `SaveNetwork`: write the edited network as a new local copy

**Files:**
- Modify: `packages/netstead/netstead/workbench/build.py` (`output_path`)
- Modify: `packages/netstead/netstead/workbench/actions.py`, `session.py`, `__init__.py`
- Test: `packages/netstead/tests/test_workbench_changes.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_changes.py`. Add `SaveNetwork` to the actions import, and
`from netstead import Network` and `from pathlib import Path` at the top:

```python
def test_save_writes_a_new_copy_and_never_the_source(session, tmp_path):
    session.dispatch(ApplyEdit(ids=[1], set={"free_speed": 30}))
    out = tmp_path / "out"
    out.mkdir()
    result = session.dispatch(SaveNetwork(output_dir=str(out), name="edited", output_format="parquet"))
    assert Path(result["output"]).parent == out and result["uncommitted_changes"] == 1
    assert result["edited_while_saving"] is False
    assert any("stale" in w for w in result["warnings"])  # corral's OutOfSyncWarning: kept as text, not raised
    back = Network.from_source(result["output"]).tables["link"].to_pandas()
    assert back.loc[back.link_id == 1, "free_speed"].tolist() == [30.0]
    source = Network.from_source(SRC).tables["link"].to_pandas()
    assert source.loc[source.link_id == 1, "free_speed"].tolist() == [40.0]
    with pytest.raises(ActionError, match="already exists"):
        session.dispatch(SaveNetwork(output_dir=str(out), name="edited", output_format="parquet"))


def test_save_stays_inside_the_allowed_roots(session):
    with pytest.raises(PathNotAllowed):
        session.dispatch(SaveNetwork(output_dir="/etc", name="x", output_format="parquet"))
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_changes.py -q -k save`
Expected: FAIL with `ImportError: cannot import name 'SaveNetwork'`.

- [ ] **Step 3: Implement**

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

Then replace the matching lines in `plan_build` (from `out_dir = _local(...)` through the `dest.exists()` check)
with `dest = output_path(action.output_dir, action.name, action.output_format, settings)`. Add `output_path` to
`__all__` if `build.py` declares one.

In `actions.py`, factor `BuildNetwork`'s suffix check into a function both actions call:

```python
def _check_name(name: str, output_format: str) -> None:
    suffix = PurePath(name).suffix.lower()
    if suffix in _OUTPUT_SUFFIXES and suffix != f".{output_format}":
        raise ValueError(f"name {name!r} ends in {suffix} but output_format is {output_format!r}")
```

Then add:

```python
class SaveNetwork(_Action):
    """Write the open network, with its edits, as a new copy in ``output_dir``. The source is never written to."""

    type: Literal["save_network"] = "save_network"
    mutates: ClassVar[bool] = True
    runs_as_job: ClassVar[bool] = True
    net_id: str | None = None
    output_dir: str
    output_format: Literal["parquet", "csv", "duckdb", "zip"]
    name: str = Field(pattern=_NAME_PATTERN, max_length=100)

    @model_validator(mode="after")
    def _name_matches_format(self) -> SaveNetwork:
        _check_name(self.name, self.output_format)
        return self

    def job_label(self) -> str:
        """``save <name>``."""
        return f"save {self.name}"
```

Add it to `Action`, `__all__` and `workbench/__init__.py`.

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
    warnings: list[str]
    uncommitted: int

    def commit(self, session: Session) -> dict[str, Any]:
        """Describe the saved copy (nothing to register: the open network is unchanged)."""
        return {
            "net_id": self.handle.id,
            "output": self.output,
            "version": self.version,
            "edited_while_saving": self.handle.version != self.version,
            "uncommitted_changes": self.uncommitted,
            "warnings": self.warnings,
        }
```

Then add the job:

```python
    def _job_save_network(self, action: SaveNetwork, ctx: JobContext) -> _Saved:
        with self._lock:
            handle = self._handle(action.net_id)
            version, settings = handle.version, self.settings
            log = self.changes.get(handle.id)
            uncommitted = len(log.draft.changes) if log else 0
        dest = build.output_path(action.output_dir, action.name, action.output_format, settings, what="saves")
        build.remove_stale_partials(dest.parent)
        # Writing an edited network warns OutOfSyncWarning ("FK validations may be out of date"): keep the
        # text for the result instead of letting the warning escape. (catch_warnings is process-global; jobs
        # are few and short, and other warnings keep their configured behaviour.)
        with build.staging(dest) as tmp, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", OutOfSyncWarning)
            build.write_output(handle.roadway, tmp, action.output_format, ctx)
            ctx.stage("save", progress=0.95)  # last cancellation checkpoint
            build.promote(tmp, dest)
        notes = [scrub(str(w.message), limit=None) for w in caught if issubclass(w.category, OutOfSyncWarning)]
        return _Saved(handle, version, str(dest), notes, uncommitted)
```

The source in the warning may be a presigned URL, so `scrub` it.

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_changes.py packages/netstead/tests/test_workbench_session.py -q`
Then the build job tests: `uv run --all-extras pytest packages/netstead/tests -q -k "build or wizard or estimate"`.
Expected: all pass. The `plan_build` refactor keeps its messages, because `what` defaults to "builds".

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_changes.py
git commit -m "feat(workbench): SaveNetwork writes the edited network as a new local copy"
```

---

### Task 13: Change-log routes, and card files in the file browser

**Files:**
- Modify: `packages/netstead/netstead/workbench/routes/edit.py`
- Modify: `packages/netstead/netstead/workbench/files.py`
- Test: `packages/netstead/tests/test_workbench_edit_routes.py`, `packages/netstead/tests/test_workbench_files.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/netstead/tests/test_workbench_edit_routes.py`:

```python
yaml = pytest.importorskip("yaml")


@pytest.fixture
def edited(tmp_path):
    s = _session(tmp_path)
    s.dispatch({"type": "apply_edit", "ids": [1], "set": {"free_speed": 30}, "note": "signed 30"})
    return s, TestClient(build_app(s))


def test_the_changes_view(edited):
    _, c = edited
    j = c.get(f"{BASE}/changes").json()
    (change,) = j["draft"]["changes"]
    assert change["properties"] == [{"name": "free_speed", "existing": 40.0, "set": 30, "change": None}]
    assert change["selection"]["ids"] == [1] and change["note"] == "signed 30" and change["rows"] == 1
    assert j["can_undo"] is True and j["committed"] == [] and j["version"] == 1


def test_the_draft_downloads_as_a_valid_card(edited):
    _, c = edited
    r = c.get(f"{BASE}/changes/card.yml")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    card = yaml.safe_load(r.text)
    assert card["changes"][0]["roadway_property_change"]["facility"]["links"]["model_link_id"] == [1]
    v = c.get(f"{BASE}/changes/validate").json()
    assert v["valid"] is True and v["errors"] == [] and v["schema"] == "v0.3.3"


def test_committed_cards_download_by_id(edited):
    s, c = edited
    s.dispatch({"type": "commit_card", "project": "Speed"})
    assert c.get(f"{BASE}/changes/card.yml?card=speed").status_code == 200
    assert c.get(f"{BASE}/changes/card.yml?card=nope").status_code == 404
    assert c.get(f"{BASE}/changes/card.yml").status_code == 409  # the new draft is empty
    assert c.get(f"{BASE}/changes").json()["committed"][0]["id"] == "speed"


def test_change_reads_are_not_recorded(edited):
    s, c = edited
    before = len(s.history)
    c.get(f"{BASE}/changes")
    c.get(f"{BASE}/changes/validate")
    assert len(s.history) == before
```

Append to `packages/netstead/tests/test_workbench_files.py`:

```python
def test_projectcard_files_are_recognised(tmp_path):
    from netstead.workbench.files import detect_kind

    for name in ("card.yml", "card.YAML"):
        (tmp_path / name).write_text("project: x\n")
        assert detect_kind(tmp_path / name) == "card"
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py packages/netstead/tests/test_workbench_files.py -q`
Expected: the new route tests 404; the files test gets `None`.

- [ ] **Step 3: Implement**

In `routes/edit.py`:
- add `from fastapi.responses import Response`;
- add `from netstead.changes import SCHEMA_VERSION, ChangeNotSupported, DraftCard, card_errors`;
- add `from ..registry import NetworkHandle`;
- add these before `return router`:

```python
    def card_of(h: NetworkHandle, which: str) -> DraftCard:
        try:
            card = session.card(h, which)
        except KeyError as exc:
            raise HTTPException(404, exc.args[0]) from exc
        if not card.changes:
            raise HTTPException(409, "the draft card has no changes yet")
        return card

    @router.get("/changes")
    def changes(net_id: str, component: str) -> dict[str, Any]:
        """The change log: the draft card (its changes, existing -> set, selections), undo state, committed cards."""
        return session.changes_payload(network_handle(session, net_id, component))

    @router.get("/changes/card.yml")
    def card_yml(net_id: str, component: str, card: str = "draft") -> Response:
        """A card as a ProjectCard YAML download (the draft, or a committed card by id)."""
        h = network_handle(session, net_id, component)
        try:
            text = card_of(h, card).to_yaml()
        except ImportError as exc:
            raise HTTPException(501, str(exc)) from exc
        except ChangeNotSupported as exc:
            raise HTTPException(409, str(exc)) from exc
        disposition = f'attachment; filename="{h.id}-{card}.yml"'
        return Response(text, media_type="application/yaml", headers={"Content-Disposition": disposition})

    @router.get("/changes/validate")
    def validate(net_id: str, component: str, card: str = "draft") -> dict[str, Any]:
        """Check a card against the vendored ProjectCard schema."""
        h = network_handle(session, net_id, component)
        try:
            errors = card_errors(card_of(h, card).to_card())
        except ImportError as exc:
            raise HTTPException(501, str(exc)) from exc
        except ChangeNotSupported as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"card": card, "valid": not errors, "errors": errors[:200], "schema": SCHEMA_VERSION}
```

The `card` id is a slug or `draft`, so it is safe in the filename.

In `files.py`:
- extend the suffix map in `detect_kind` with `".yml": "card", ".yaml": "card"`;
- add ``card`` (a ProjectCard ``.yml``/``.yaml``, for Changes → Import) to its docstring's list of kinds.

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_edit_routes.py packages/netstead/tests/test_workbench_files.py packages/netstead/tests/test_workbench_io_routes.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench packages/netstead/tests/test_workbench_edit_routes.py packages/netstead/tests/test_workbench_files.py
git commit -m "feat(workbench): change-log routes (view, .yml download, schema check); card files in the browser"
```

---

### Task 14: Pure front-end rules: `issuelist.js`, `editmodel.js`, and two `linking.js` additions

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
    [("45", 40, 45), ("45", "40", 45), ("abc", 40, "abc"), ("true", True, 1), ("0", False, 0), (" x ", "y", "x")],
)
def test_coerce_likely(node_module, raw, sample, want):
    got = node_module("editmodel.js", ["coerceLikely"], f"coerceLikely({json.dumps(raw)}, {json.dumps(sample)})")
    assert got == want


def test_an_empty_value_is_refused(node_module):
    expr = '(() => { try { coerceLikely("  ", 1); return "accepted"; } catch (e) { return e.message; } })()'
    assert "cannot set a property to empty" in node_module("editmodel.js", ["coerceLikely"], expr)


def test_fix_and_delete_actions(node_module):
    fix = node_module(
        "editmodel.js",
        ["fixAction"],
        'fixAction({table: "link", id: 1, column: "free_speed", raw: "30", current: 40, note: "why"})',
    )
    assert fix == {"type": "apply_edit", "table": "link", "set": {"free_speed": 30}, "ids": [1], "note": "why"}
    sel = node_module(
        "editmodel.js",
        ["fixAction"],
        'fixAction({table: "link", id: 1, column: "lanes", raw: "2", current: 1, useSelection: true})',
    )
    assert sel == {"type": "apply_edit", "table": "link", "set": {"lanes": 2}, "use_selection": True}
    gone = node_module("editmodel.js", ["deleteAction"], 'deleteAction("link", [1])')
    assert gone == {"type": "apply_edit", "table": "link", "ids": [1], "delete": True}


def test_change_display_helpers(node_module):
    lines = node_module(
        "editmodel.js",
        ["propertyLine"],
        '[propertyLine({name: "free_speed", existing: 40, set: 30, change: null}),'
        ' propertyLine({name: "lanes", existing: null, set: null, change: 1})]',
    )
    assert lines == ["free_speed: 40 → 30", "lanes: ? → +1"]
    labels = node_module(
        "editmodel.js",
        ["selectionLabel"],
        '[selectionLabel({table: "link", ids: [1, 2, 3, 4, 5]}),'
        ' selectionLabel({table: "link", ids: null, query: {links: {name: ["Benton Street"]}}, resolved: 2})]',
    )
    assert labels == ["link 1, 2, 3 (+2)", "name Benton Street → 2 links"]
    assert node_module("editmodel.js", ["splitList"], 'splitList(" a, b ,, c")') == ["a", "b", "c"]
    cols = node_module("editmodel.js", ["editableColumns"], 'editableColumns({link_id: 1, name: "a", geometry: "x", lanes: 2}, "link_id")')
    assert cols == ["name", "lanes"]


@pytest.mark.parametrize(
    ("prev", "nxt", "want"),
    [("a@1", "a@2", "edited"), ("a@1", "b@1", "switched"), (None, "a@0", "switched"), ("a@1", None, "switched"),
     ("a@1", "a@1", "same"), ("a-2@1", "a@2", "switched")],
)
def test_net_change(node_module, prev, nxt, want):
    assert node_module("linking.js", ["netChange"], f"netChange({json.dumps(prev)}, {json.dumps(nxt)})") == want


def test_row_marks_flag_records_with_issues(node_module):
    expr = 'rowMarks({table: "link", id: 1, selection: null, highlights: new Set(), focus: null, via: null, issues: 2})'
    assert node_module("linking.js", ["rowMarks"], expr) == ["iss"]
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_js.py -q`
Expected: the new tests FAIL. The modules don't exist yet; `netChange` is not exported; `rowMarks` ignores
`issues`.

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
// Fix-editor and change-log display rules, ported from the offline report's "Fix locally" editor
// (map/templates/map_component.js: coerceLikely, pickPk). Import-free and DOM-free: unit-tested under node.

// The typed text as the value to set: a number when the current value is (or looks) numeric, 1/0 for a yes/no
// value, else the text. Empty input is refused: a ProjectCard cannot set a property to empty. The server
// coerces to the column's real type and says when a value does not fit.
export function coerceLikely(input, sample) {
  const text = input == null ? "" : String(input).trim();
  if (text === "") throw new Error("Enter a value: a ProjectCard cannot set a property to empty.");
  if (typeof sample === "boolean") {
    if (/^(true|1|yes)$/i.test(text)) return 1;
    if (/^(false|0|no)$/i.test(text)) return 0;
    throw new Error(`Enter true or false (got "${text}").`);
  }
  if (typeof sample === "number" || (typeof sample === "string" && /^-?\d+(\.\d+)?$/.test(sample))) {
    const n = Number(text);
    if (Number.isFinite(n)) return n;
  }
  return text;
}

// The ApplyEdit action for one fix: one property of one record, or of every selected link.
export function fixAction({ table, id, column, raw, current, note = null, useSelection = false }) {
  const action = { type: "apply_edit", table, set: { [column]: coerceLikely(raw, current) } };
  if (useSelection) action.use_selection = true; else action.ids = [id];
  if (note) action.note = note;
  return action;
}

export function deleteAction(table, ids, note = null) {
  const action = { type: "apply_edit", table, ids: [...ids], delete: true };
  if (note) action.note = note;
  return action;
}

// The columns the editor offers for a record: everything but its key and its geometry.
export const editableColumns = (attributes, pk) => Object.keys(attributes).filter(k => k !== pk && k !== "geometry");

export const splitList = text => String(text || "").split(",").map(s => s.trim()).filter(Boolean);

// One property change as "name: existing → set" ("?" when the card does not record the existing value).
export function propertyLine(p) {
  const to = p.set != null ? p.set : `${p.change >= 0 ? "+" : ""}${p.change}`;
  return `${p.name}: ${p.existing != null ? p.existing : "?"} → ${to}`;
}

// What a change selected: picked ids, or a query and how many links it resolved to.
export function selectionLabel(sel) {
  if (!sel) return "";
  if (sel.ids) {
    const extra = sel.ids.length > 3 ? ` (+${sel.ids.length - 3})` : "";
    return `${sel.table} ${sel.ids.slice(0, 3).join(", ")}${extra}`;
  }
  const q = (sel.query && sel.query.links) || {};
  const what = q.name ? `name ${q.name.join(" / ")}` : q.ref ? `ref ${q.ref.join(" / ")}` : q.all ? "all links" : "query";
  return `${what} → ${sel.resolved} link${sel.resolved === 1 ? "" : "s"}`;
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

- change `rowMarks` to accept `issues = 0`, and add before its `return`:
  `if (issues) marks.push("iss");`
- extend its comment: `` `issues`: how many issues the last validation recorded against this record.``

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_js.py packages/netstead/tests/test_workbench_static.py -q`
Expected: all pass.

- [ ] **Step 5: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/netstead/workbench/static/js packages/netstead/tests/test_workbench_js.py
git commit -m "feat(workbench): issue-list and fix-editor rules as unit-tested modules"
```

---

### Task 15: Drawer tabs, and an edit keeps the view

**Files:**
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`
- Modify: `packages/netstead/netstead/workbench/static/js/store.js`, `side.js`, `main.js`, `table.js`

- [ ] **Step 1: The drawer**

In `index.html`, replace the opening `<aside id="side">` line with the lines below, and put a `</section>`
immediately before the existing `</aside>`. The Issues and Changes panes are filled by Tasks 16 and 17. They are
added now so the tab bar is complete.

```html
  <aside id="side">
    <nav id="side-tabs" role="tablist" aria-label="Drawer">
      <button role="tab" data-tab="details" class="on" aria-selected="true">Details</button>
      <button role="tab" data-tab="issues" aria-selected="false">Issues <span id="issues-count" class="pcount">0</span></button>
      <button role="tab" data-tab="changes" aria-selected="false">Changes <span id="changes-count" class="pcount">0</span></button>
    </nav>
    <section class="side-pane" data-pane="details" role="tabpanel">
```

Then, between that `</section>` and `</aside>`, add two empty panes:

```html
    <section class="side-pane" data-pane="issues" role="tabpanel" hidden></section>
    <section class="side-pane" data-pane="changes" role="tabpanel" hidden></section>
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
  drawerTab: "details",       // details | issues | changes (per tab, never recorded)
  issues: null,               // /issues/markers for the active network: {net_id, version, markers, records}
  issueFilter: { severity: [], table: "", code: "", located: "", thisRecord: false },
  issueFocus: null,           // the issue number last picked in the list or on the map
  showIssues: true,           // the map's issue-marker layer (Layers panel; view state only)
  changes: null,              // GET /changes for the active network (the change log)
```

- [ ] **Step 3: Tabs**

In `side.js`, add:

```js
// The drawer's tabs (Details | Issues | Changes): which pane shows is per-tab view state.
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

- [ ] **Step 5: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass. Every new id is in `index.html`, and every import resolves.

- [ ] **Step 6: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): drawer tabs; an edit keeps focus, highlights and the table"
```

---

### Task 16: The Issues tab, map markers and row marks

**Files:**
- Create: `packages/netstead/netstead/workbench/static/js/issues.js`
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`
- Modify: `packages/netstead/netstead/workbench/static/js/map.js`, `table.js`, `main.js`

`issues.js` imports `openFixEditor` from `fixeditor.js` (Task 17). To keep this task's module graph complete, this
task creates `fixeditor.js` with only that export as a stub, and Task 17 fills it in:

```js
// The fix editor (Task 17).
export async function openFixEditor() {}
```

- [ ] **Step 1: The pane**

In `index.html`, fill `<section class="side-pane" data-pane="issues" …>`:

```html
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
// Issues tab: run validation (a background job), list issues by filter, and link issue <-> map marker <-> row.
// The list, markers and report are read-only views of the last RunValidation; nothing here is recorded.
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
  $("issues-count").textContent = meta ? SEVERITIES.reduce((n, s) => n + (meta.counts[s] || 0), 0) : 0;
  $("iss-run").textContent = meta && meta.stale ? "Re-run validation" : "Run validation";
  $("iss-report").classList.toggle("off", !current);
  $("iss-report").href = current && id ? netPath(id, "report.html") : "#";
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

- import `{ markFocusedIssue, onIssueMarker, onIssuesState, reloadIssues, wireIssues }` from `./issues.js`;
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
```

- [ ] **Step 6: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass.

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): Issues tab linked to map markers and table rows; export report"
```

---

### Task 17: The fix editor, the Changes tab, card import and Save a copy

**Files:**
- Modify (fill the stub): `packages/netstead/netstead/workbench/static/js/fixeditor.js`
- Create: `packages/netstead/netstead/workbench/static/js/changes.js`
- Modify: `packages/netstead/netstead/workbench/static/index.html`, `app.css`
- Modify: `packages/netstead/netstead/workbench/static/js/side.js`, `main.js`, `history.js`, `filebrowser.js`

- [ ] **Step 1: `fixeditor.js`**

Replace the stub:

```js
// The fix editor, ported from the offline report's "Fix locally" mini-editor (map_component.js): one property of
// one record, applied as an ApplyEdit action. The server compiles it into a ProjectCard change on the draft card.
import { dispatch, getJSON, netPath } from "./api.js";
import { esc, toast } from "./dom.js";
import { deleteAction, editableColumns, fixAction } from "./editmodel.js";
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
    `<input class="fx-val grow" aria-label="New value"></div>` +
    `<div class="row"><input class="fx-note grow" aria-label="Note" placeholder="Why (kept in the card's notes)" value="${esc(note || "")}"></div>` +
    (many ? `<label class="row"><input type="checkbox" class="fx-sel"> all ${sel.link_ids.length} selected links</label>` : "") +
    `<div class="row"><button class="mini fx-apply">Apply</button><button class="mini ghost fx-cancel">Cancel</button>` +
    `<span class="diag fx-now"></span></div>`;
  const current = () => rec.attributes[el.querySelector(".fx-col").value];
  const showCurrent = () => {
    const v = current();
    el.querySelector(".fx-now").textContent = `now: ${v == null || v === "" ? "empty" : v}`;
    el.querySelector(".fx-val").value = v == null ? "" : String(v);
  };
  el.querySelector(".fx-col").onchange = showCurrent;
  el.querySelector(".fx-cancel").onclick = () => el.remove();
  el.querySelector(".fx-apply").onclick = async () => {
    try {
      const box = el.querySelector(".fx-sel");
      await dispatch(fixAction({ table, id, column: el.querySelector(".fx-col").value, raw: el.querySelector(".fx-val").value,
        current: current(), note: el.querySelector(".fx-note").value.trim() || null, useSelection: Boolean(box && box.checked) }));
      el.remove();
    } catch (e) { toast(e.message); }
  };
  host.appendChild(el);
  showCurrent();
  el.querySelector(".fx-val").focus();
}

export async function deleteRecord(table, id) {
  const msg = `Delete ${table} ${id}? Rows that point at it (lanes, time-of-day rows) go too. Undo is in the Changes tab.`;
  if (!window.confirm(msg)) return;
  try { await dispatch(deleteAction(table, [id])); } catch (e) { toast(e.message); }
}
```

- [ ] **Step 2: Edit and delete from Details**

In `side.js`:
- import `{ deleteRecord, openFixEditor }` from `./fixeditor.js`;
- in `showDetails`, replace `el.innerHTML = \`${head}<table>${rows}</table>\`;` with:

```js
    const editable = table === "link" || table === "node";
    const actions = editable ? `<div class="row det-actions"><button class="mini ghost" data-act="edit">Edit…</button>` +
      (table === "link" ? `<button class="mini ghost" data-act="delete">Delete link</button>` : "") + "</div>" : "";
    el.innerHTML = `${head}${actions}<table>${rows}</table>`;
    const edit = el.querySelector('[data-act="edit"]'), del = el.querySelector('[data-act="delete"]');
    if (edit) edit.onclick = () => openFixEditor(el.querySelector(".det-actions"), { table, id }).catch(e => toast(e.message));
    if (del) del.onclick = () => deleteRecord(table, id);
```

- [ ] **Step 3: The Changes pane**

In `index.html`, fill `<section class="side-pane" data-pane="changes" …>`:

```html
      <p class="diag">The draft ProjectCard: every edit lands here as a change. The strip at the bottom is the
        session history (every action, edits included).</p>
      <div class="form">
        <label for="chg-project">Project</label><input id="chg-project" placeholder="Front Street speed fixes">
        <label for="chg-tags">Tags</label><input id="chg-tags" placeholder="fixes, 2026">
        <label for="chg-prereq">Prerequisites</label><input id="chg-prereq" placeholder="other projects, comma-separated">
      </div>
      <div class="row wrap">
        <button class="mini" id="chg-commit" disabled>Commit card</button>
        <button class="mini ghost" id="chg-undo" disabled>Undo last</button>
        <button class="mini ghost" id="chg-validate" disabled>Validate</button>
        <a class="btn mini ghost off" id="chg-export" href="#" download>Export .yml</a>
        <button class="mini ghost" id="chg-import">Import…</button>
      </div>
      <div class="fb" id="chg-import-fb" hidden></div>
      <div id="chg-valid" class="diag"></div>
      <div id="chg-list"><span class="empty">No changes yet.</span></div>
      <div class="label">Committed cards</div>
      <div id="chg-committed"><span class="empty">None yet.</span></div>
      <div class="label">Save a copy</div>
      <div class="row wrap"><input id="chg-save-name" placeholder="leavenworth-fixed" aria-label="Copy name">
        <select id="chg-save-format" aria-label="Format"><option value="parquet">Parquet folder</option>
          <option value="csv">CSV folder</option><option value="duckdb">DuckDB file</option><option value="zip">Zip</option></select>
        <button class="mini ghost" id="chg-save">Choose folder…</button></div>
      <div class="fb" id="chg-save-fb" hidden></div>
```

Append to `app.css`:

```css
  .chg { padding:7px 0; border-bottom:1px solid var(--edge); font-size:12.5px; }
  .chg.last { box-shadow:inset 3px 0 0 var(--accent); padding-left:8px; }
  .chg-type { font-weight:600; } .chg-prop { font-family:ui-monospace, monospace; color:var(--ink); }
  .diag.warn { color:rgb(240,170,60); }
  .fix-editor { margin:6px 0; padding:8px; border:1px solid var(--edge); border-radius:8px; background:#0c0e12; }
  .fix-editor .row { display:flex; gap:6px; align-items:center; margin:4px 0; }
  .row.wrap { flex-wrap:wrap; }
```

- [ ] **Step 4: `changes.js`**

```js
// Changes tab: the draft ProjectCard (its changes, existing → set, selections), with commit, undo, export .yml,
// schema check, import and "save a copy". This is the change log; the strip at the bottom is the session history.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { propertyLine, selectionLabel, splitList } from "./editmodel.js";
import { createFileBrowser } from "./filebrowser.js";
import { store } from "./store.js";

let seq = 0, importer = null, saver = null;
const fail = e => toast(e.message);
const activeId = () => { const s = store.get().server; return s && s.active; };

export async function loadChanges() {
  const id = activeId(), mine = ++seq;
  if (!id) { store.set({ changes: null }); return; }
  const j = await getJSON(netPath(id, "changes"));
  if (mine === seq) store.set({ changes: j });
}

function changeHTML(ch, last) {
  const head = `<div><span class="chg-type">${esc(ch.type.replaceAll("_", " "))}</span>` +
    (ch.selection ? ` · ${esc(selectionLabel(ch.selection))}` : "") + "</div>";
  const props = (ch.properties || []).map(p => `<div class="chg-prop">${esc(propertyLine(p))}</div>`).join("");
  const ids = ch.properties ? "" : [ch.links && ch.links.length ? `links ${ch.links.join(", ")}` : "",
    ch.nodes && ch.nodes.length ? `nodes ${ch.nodes.join(", ")}` : ""].filter(Boolean).join(" · ");
  const note = ch.note ? `<div class="diag">${esc(ch.note)}</div>` : "";
  const warn = [...(ch.warnings || []), ...(ch.skipped || [])].map(w => `<div class="diag warn">${esc(w)}</div>`).join("");
  return `<div class="chg${last ? " last" : ""}">${head}${props}${ids ? `<div class="chg-prop">${esc(ids)}</div>` : ""}${note}${warn}</div>`;
}

export function renderChanges(c) {
  const id = activeId(), draft = c && c.net_id === id ? c.draft : null, n = draft ? draft.changes.length : 0;
  $("changes-count").textContent = n;
  $("chg-undo").disabled = !(draft && c.can_undo);
  $("chg-commit").disabled = $("chg-validate").disabled = !n;
  $("chg-export").classList.toggle("off", !n);
  $("chg-export").href = n ? netPath(id, "changes/card.yml") : "#";
  if (draft && document.activeElement !== $("chg-project")) $("chg-project").value = draft.project || "";
  if (draft && document.activeElement !== $("chg-tags")) $("chg-tags").value = (draft.tags || []).join(", ");
  $("chg-list").innerHTML = n ? draft.changes.map((ch, k) => changeHTML(ch, k === n - 1)).join("")
    : '<span class="empty">No changes yet. Fix an issue, or edit a record from Details.</span>';
  const done = draft ? c.committed : [];
  $("chg-committed").innerHTML = done.length ? done.map(card =>
    `<div class="chg"><b>${esc(card.project)}</b> · ${card.changes} change(s) ` +
    `<a href="${netPath(id, `changes/card.yml?card=${encodeURIComponent(card.id)}`)}" download>.yml</a></div>`).join("")
    : '<span class="empty">None yet.</span>';
}

async function commit() {
  const project = $("chg-project").value.trim();
  if (!project) { toast("Name the card (Project) before committing it."); $("chg-project").focus(); return; }
  const prerequisites = splitList($("chg-prereq").value);
  try {
    await dispatch({ type: "commit_card", project, tags: splitList($("chg-tags").value),
      dependencies: prerequisites.length ? { prerequisites } : {} });
    $("chg-prereq").value = "";
    toast(`Committed “${project}”. A new draft card has started.`);
  } catch (e) { toast(e.message); }
}

async function validate() {
  $("chg-valid").textContent = "Checking…";
  try {
    const j = await getJSON(netPath(activeId(), "changes/validate"));
    $("chg-valid").innerHTML = j.valid ? `A valid ProjectCard (schema ${esc(j.schema)}).`
      : `${j.errors.length} problem(s):<br>${j.errors.map(esc).join("<br>")}`;
  } catch (e) { $("chg-valid").textContent = e.message; }
}

function toggleBrowser(elId, make) {
  const el = $(elId);
  el.hidden = !el.hidden;
  if (el.hidden) return null;
  const fb = make(el);
  fb.show();
  return fb;
}

export function wireChanges() {
  $("chg-undo").onclick = () => dispatch({ type: "undo_change" }).catch(fail);
  $("chg-commit").onclick = () => commit();
  $("chg-validate").onclick = () => validate();
  $("chg-import").onclick = () => {
    importer = toggleBrowser("chg-import-fb", el => importer || createFileBrowser(el, { kinds: ["card"], onPick: async e => {
      $("chg-import-fb").hidden = true;
      try { const r = await dispatch({ type: "import_card", path: e.path }); toast(`Imported ${r.imported} change(s).`); } catch (err) { toast(err.message); }
    } })) || importer;
  };
  $("chg-save").onclick = () => {
    const name = $("chg-save-name").value.trim();
    if (!name) { toast("Name the copy first."); $("chg-save-name").focus(); return; }
    saver = toggleBrowser("chg-save-fb", el => saver || createFileBrowser(el, { kinds: [], pickFolder: true, onPick: e => {
      $("chg-save-fb").hidden = true;
      dispatch({ type: "save_network", output_dir: e.path, name: $("chg-save-name").value.trim(),
        output_format: $("chg-save-format").value }).then(() => toast("Saving a copy… (see Jobs)")).catch(fail);
    } })) || saver;
  };
}
```

`toggleBrowser` returns `null` when it hides the browser. The `|| importer` / `|| saver` keeps the existing browser
for the next toggle. `save_network` is a job: the request answers 202 at once, and the outcome arrives as a `job`
event in the Jobs panel.
- [ ] **Step 5: Wire it**

In `main.js`:
- import `{ loadChanges, renderChanges, wireChanges }` from `./changes.js`;
- call `wireChanges()` in `boot()`;
- add to `wireStore()`:

```js
  // The change log moves with the active network's version, lineage, or change summary (a commit bumps no version).
  let changesKey = null;
  store.subscribe(["server"], s => {
    const id = s.server.active, h = s.server.networks.find(n => n.id === id);
    const key = JSON.stringify([id, h && h.version, h && h.lineage, s.server.changes && s.server.changes[id]]);
    if (key !== changesKey) { changesKey = key; loadChanges().catch(e => toast(e.message)); }
  });
  store.subscribe(["changes"], s => renderChanges(s.changes));
```

In `filebrowser.js`, add `card: "ProjectCard"` to `KIND_LABEL`.

In `history.js`, extend the import line in `sessionScript` to the full action list:

```js
    "from netstead.workbench import Session, OpenNetwork, BuildNetwork, CloseNetwork, SetActiveNetwork, Select, " +
      "ClearSelection, Style, Navigate, SetSetting, RunValidation, ApplyEdit, ApplyChange, UndoChange, CommitCard, " +
      "ImportCard, SaveNetwork",
```
- [ ] **Step 6: Run the static and JS tests**

Run: `uv run --all-extras pytest packages/netstead/tests/test_workbench_static.py packages/netstead/tests/test_workbench_js.py -q`
Expected: all pass.

- [ ] **Step 7: Before commit**

Run: `uv run --all-extras pytest packages -n auto -q` and the ruff pair. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add packages/netstead/netstead/workbench/static
git commit -m "feat(workbench): fix editor, Changes tab, card import and save a copy"
```

---

### Task 18: Docs, the full suite, lint, and the browser walk-through

**Files:**
- Create: `packages/netstead/docs/cookbook/project-cards.md`
- Modify: `packages/netstead/docs/cookbook/workbench.md`, `packages/netstead/docs/cookbook/index.md`
- Modify: `docs/design/2026-10-02-netstead-workbench-design.md`

- [ ] **Step 1: The ProjectCard cookbook page**

Create `packages/netstead/docs/cookbook/project-cards.md`. Its `python` blocks run in
`test_documented_python_contract.py`, so they must work as written.

````markdown
# Edit a network as ProjectCard changes

Every edit netstead makes through `netstead.changes` is a ProjectCard change: the same
`roadway_property_change` / `roadway_deletion` / `roadway_addition` records that
[network_wrangler](https://github.com/network-wrangler/network_wrangler) reads. A change log groups
them into a draft card that you can undo, commit, write to `.yml` and check against the ProjectCard
schema. Card files need the `[projectcard]` extra: `pip install 'netstead[projectcard]'`.

## Apply, undo and commit

```python
from netstead import Network
from netstead.changes import ChangeLog, PropertyChange, RoadwayPropertyChange, Selection
from netstead.fixtures import leavenworth

net = Network.from_source(leavenworth.parquet_dir())
log = ChangeLog(net)
log.apply(
    RoadwayPropertyChange(
        facility=Selection(ids=[1]),
        property_changes={"free_speed": PropertyChange(existing=40, set=30)},
        note="signed 30 mph",
    )
)
log.undo()  # the last change of the draft, reversed
log.apply(
    RoadwayPropertyChange(facility=Selection(ids=[1]), property_changes={"free_speed": PropertyChange(set=30)})
)
card_id = log.commit("Front Street speed fixes", tags=["fixes"])
```

- `existing` is checked before anything changes. A mismatch raises `ChangeConflict`, unless the change says
  `existing_value_conflict="warn"` or `"skip"`.
- A change is all or nothing. Deleting a link also deletes the rows that point at it, such as its lanes.
- Only the draft can be undone. A committed card is frozen.

## Write and check the card

```python
from netstead.changes import card_errors

card = log.card(card_id)
print(card.to_yaml())
assert card_errors(card.to_card()) == []
```

Names follow Wrangler in the file (`link_id` → `model_link_id`, `from_node_id` → `A`, …). The mapping
is the maintained data file `netstead/changes/mappings/gmns_to_wrangler.yaml`. The schema is
projectcard's own, vendored and pinned (`netstead.changes.SCHEMA_VERSION`).

## Read a card back

`netstead.changes.read_card(path)` reads a ProjectCard file, or the offline validation report's edit
log, as a draft card. A selection made by a query (a street name, a route ref) keeps the query, and
records the link ids it resolved to in the card's `notes`. Re-resolving a query on another network
version arrives with `apply_card`.
````

Add a line for it to `packages/netstead/docs/cookbook/index.md`, next to the `fix-findings.md` entry, in the same
format as its neighbours.

- [ ] **Step 2: The Workbench cookbook**

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
- **Fix** opens an editor for the issue's property; **Details → Edit…** opens it for any link or node
  property, and **Delete link** deletes a link (and the rows that point at it).
- After an edit the issue list says it is stale: **Re-run validation** to check again. **Export report**
  downloads the offline HTML report for a current validation.

## The change log (ProjectCards)

Every edit is recorded twice, on purpose:

- the **session history** (the strip at the bottom) records every action, for replay and "copy as Python";
- the **Changes** tab is the ProjectCard change log: the draft card's changes, each with its selection
  and `existing → set` values.

**Undo last** reverses the draft's last change. **Commit card** names and freezes the draft, and starts a
new one. **Export .yml** downloads the card, **Validate** checks it against the ProjectCard schema, and
**Import…** applies a card file (or an offline report's edit log) to the draft. **Save a copy** writes the
edited network to a new folder or file; the network you opened, local or remote, is never written to.
See [Edit a network as ProjectCard changes](project-cards.md) for the Python side.
```

- [ ] **Step 3: The design doc**

In `docs/design/2026-10-02-netstead-workbench-design.md`:
- in the Transit section's **NetworkChange** bullet, replace `add_transit_routes` with `transit_route_addition`
  (the schema's name);
- below the P1b plan line under the phasing table, add:

```markdown
P2 plan: [2026-10-07-workbench-p2-plan.md](2026-10-07-workbench-p2-plan.md): the vendored projectcard v0.3.3 schema,
deletion with FK cascade and addition without a drawing UI, draft-only undo, and `SaveNetwork` for edited copies.
```

- [ ] **Step 4: The full tier, before merge**

Run: `uv run --all-extras pytest packages -n auto -q -m ""`
Expected: all pass, including `slow` (the doc contract test runs the new cookbook page) and `perf` (Task 6's
200k-link check).

Run: `uv run ruff check packages && uv run ruff format --check packages && uv run lint-imports && uv run python scripts/lint_no_sql.py`
Expected: clean. `lint-imports` keeps every contract, `netstead.changes` included.

- [ ] **Step 5: Browser walk-through**

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
3. **Fix.**
   - Click **Fix** on link 1's issue. The editor shows `free_speed`, now 40. Enter `30` and Apply.
   - The row shows 30, and the focus and table page are unchanged (no reset).
   - The Changes tab shows `free_speed: 40 → 30 · link 1`, and the bottom strip shows `app.do(ApplyEdit(...))`.
   - The Issues tab says the network changed since. **Re-run validation** gives 271 warnings, and **Export
     report** downloads `leavenworth-validation.html`.
4. **Undo.** Changes → **Undo last**. The value is back to 40, the draft is empty, and the history has
   `UndoChange`.
5. **Selection edit.** Select links 1 and 2 (Highlight → Set as selection). Edit `lanes` on link 1 with
   **all 2 selected links**. The change's selection reads `link 1, 2`.
6. **Delete.** Details for a link → **Delete link** → confirm. The link disappears from the map, and the lane
   count in the rail drops. **Undo last** brings both back.
7. **Card.** Apply a fix, then **Validate**: it reports a valid ProjectCard (schema v0.3.3). **Export .yml**
   downloads a card with `model_link_id`. **Commit card** with a project name: the committed list shows it, and
   a new draft starts.
8. **Import.** **Import…** → pick the exported `.yml` from an allowed folder. The change applies again and
   appears in the draft.
9. **Save a copy.** Name it, choose a folder inside the allowed roots, and the job writes the copy. The opened
   fixture is unchanged (re-open it to check).
10. **Network.** Nothing goes to a non-local host except the basemap tiles and the CDN.

Fix anything that fails before opening the PR. Reset the viewport afterwards (`preset: "desktop"`) if you changed
it.

- [ ] **Step 6: Commit**

```bash
git add packages/netstead/docs/cookbook docs/design/2026-10-02-netstead-workbench-design.md
git commit -m "docs(workbench): validate, fix and the ProjectCard change log"
```

---

## Self-review (against the design)

**Spec coverage:**

| Spec item (design "Two audit logs", §b Validation and Fixing, Transit, phasing P2) | Where |
|---|---|
| Validation + quality checks as a job, rule config from Settings | Task 9 (`RunValidation`, `run_validation`, `rule_configs`; `severity_override` checked at load) |
| Issues panel: issue ↔ map marker ↔ table row | Task 9 (keys and anchors), 10 (`/issues`, `/issues/markers`), 16 (list, markers, row marks, `onIssueMarker`) |
| Filter by severity, table, code | Task 10 (`query`, facets), 16 (selects, "This record") |
| Unlocated issues listed separately | Task 9 (`anchor: None`), 10 (`located=no`, `unlocated`), 16 (Unlocated list) |
| Re-validation after edits | Task 9/11 (`stale` in state), 16 ("Re-run validation"); Open question 8 |
| `NetworkChange` union mirroring ProjectCard: `roadway_property_change` (facility + `property_changes {existing, set \| change}`), `roadway_addition`, `roadway_deletion` | Task 5, pinned to the vendored schema's list |
| Transit variants declared now, "not yet supported" | Task 5 (types), 6 (`ChangeNotSupported`), 8 (cards), 11 (`NotSupportedYet`) |
| `apply_change(net, change) -> ChangeResult`, lowered to corral `apply_edit` / `reverse_edit` | Task 6 (via corral `Session`), 7; corral fix in Task 1 |
| `DraftCard` (project, tags, dependencies, `changes[]`) | Task 8 |
| Undo reverses the last change | Task 8 (`ChangeLog.undo`), 11 (`UndoChange`), 17 (button) |
| Commit card starts a new draft | Task 8 (`commit`), 11 (`CommitCard`, lineage), 17 |
| Export `.yml`; validate against the projectcard schema through an optional extra; lean base | Task 3 (vendored schema, `[projectcard]`), 8 (`to_yaml`), 13 (routes), 17 (buttons) |
| Selection encoding reuses `to_projectcard`; query keeps its query + resolved ids; clicks store ids | Task 2 (`ignore_missing`), 11 (`compile_edit`), 8 (provenance in notes) |
| Field mapping in `changes/mappings/gmns_to_wrangler.yaml` | Task 4 |
| Version bump and `lineage` on the handle | Task 11 (`handle.bump()`, `lineage.append`) |
| No network_wrangler dependency; cards load in Wrangler's tools | Task 3 (no runtime dep), 8 (`projectcard.read_card` interop test, dev group) |
| Fix editor ported to an ES module; each fix dispatches `ApplyEdit` → `NetworkChange` | Task 14 (`editmodel.js`, ported `coerceLikely`), 17 (`fixeditor.js`), 11 |
| Changes drawer tab: changes, existing → set, selection; commit, export, validate | Task 13 (`/changes`), 15 (tabs), 17 (`changes.js`) |
| Import a `map/edits` YAML as NetworkChanges | Task 8 (tolerant `read_card`), 11 (`ImportCard`), 13 (`card` kind), 17 |
| Export report via `render_validation_html` | Task 10 (`/report.html`, refused when stale), 16 (button) |
| Two separate logs | Task 11 (`test_the_two_logs_stay_separate`), 17 (Changes tab text), 18 (docs) |
| Where an edited remote network is saved | Task 12 (`SaveNetwork`); Open question 6 |
| No new heavy deps, no build step | `[projectcard]` = pyyaml + jsonschema (both already in other extras); native ES modules |

**Placeholder scan:**
- No "TBD" and no "similar to Task N".
- New files are given in full, except two that are listed as edits: `fixeditor.js` is created as a one-line stub
  in Task 16 and given in full in Task 17, and `__init__.py` grows by name lists.
- Conditional instructions remain only where the plan cannot know an external fact. Each says what to check and
  what to do:
  - the vendored tag's tree and change names (Tasks 3 and 5);
  - `projectcard.read_card`'s signature (Task 8);
  - pydantic's handling of `bool` in a union (Task 5);
  - `Issue` positional arguments (Task 9);
  - a pinned action-type list in `test_workbench_actions.py` (Task 11).

**Name consistency:**
- Python:
  - `apply_change`, `reverse_change`, `ChangeResult.summary()`, `ChangeLog.apply/apply_all/undo/commit/card/describe/summary`,
    `DraftCard.to_card/to_yaml/from_card`, `read_card` and `card_errors` are used the same way in Tasks 6–13;
  - `Session.issue_set`, `Session.changes_payload` and `Session.card` are what `routes/edit.py` calls;
  - `IssueSet.query/facets/by_record/counts` match the routes.
- Action `type`s: `run_validation`, `apply_edit`, `apply_change`, `undo_change`, `commit_card`, `import_card`,
  `save_network`. These are what the front end dispatches (`issues.js`, `fixeditor.js`/`editmodel.js`,
  `changes.js`).
- Store keys (`drawerTab`, `issues`, `issueFilter`, `issueFocus`, `showIssues`, `changes`) are the same across
  `store.js`, `main.js`, `issues.js`, `map.js`, `table.js` and `changes.js`.
- Ids added to `index.html`: `side-tabs`, `issues-count`, `changes-count`, `iss-*`, `tg-issues`, `chg-*`. None
  were removed. The static tests enforce both directions.

**Risks:**
- **Edits on large networks.** Each edit to a big table round-trips that table through Arrow, and every edit
  re-packs `network.bin`. The `perf` test bounds one update at 200k links. Regional networks with 1M+ links will
  feel it; the follow-up is a DuckDB-native `update_rows` (Open question 4).
- **Issue positions.** They assume DuckDB returns a table in the same order to `to_pandas()` and to
  `select(pk).to_pandas()` (insertion order is preserved by default). Task 9 pins this on Leavenworth, whose tables
  happen to be sorted by key. A multi-file parquet source could break it; the symptom would be issue keys that
  don't match the rule's message. The longer-term fix is for rules to report keys in `Issue.extra`.
- **`best_match` for schema errors** narrows a failed `oneOf` to the closest branch. On an odd card it can name
  the wrong branch's problem; the card is still reported invalid.
- **`warnings.catch_warnings` in `SaveNetwork`** is process-global. A warning raised on another thread during a
  save could be swallowed into the save's notes. Jobs are few and short; noted in the code.
- **Concurrent validation and edits.** An edit while a validation job runs can give the job a mix of versions. The
  result is stored with the version it started on, so it shows as stale and the UI offers a re-run.
