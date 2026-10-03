# Workbench P1a (Open / Import wizard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the header's path box with an **Open / Import…** wizard. It opens GMNS networks from a
server-side file browser or a URL, and builds networks from OpenStreetMap or Overture: by a drawn
rectangle, typed coordinates, a place search, or a local `.osm` / Overpass JSON file or Overture snapshot.
Every build writes to a chosen folder and format first and then opens the result from disk. Before a
build runs, the wizard shows an estimate, and anything over `app.approve_above_s` needs an explicit click.
Opens and builds run as cancellable background jobs that push progress over SSE.

**Architecture:**
- `gmnspy.workbench.paths` enforces `io.allowed_roots` (empty = home) for every local read and write.
- `gmnspy.workbench.jobs.JobRunner` runs one daemon thread per job, publishes `job` events, and cancels
  cooperatively at stage boundaries.
- `OpenNetwork` and the new `BuildNetwork` are **job actions**:
  - their load/build runs on the job thread without the session lock;
  - only registering the network and recording history take the lock;
  - `Session.dispatch` waits for the job (Python, CLI), while `POST /api/actions` answers `202` at once.
- `gmnspy.workbench.build` stages a build: plan → estimate → query → convert → write. It runs on a private
  DuckDB connection.
- `gmnspy.workbench.estimate` turns a cheap pre-query count into seconds and bytes. Its coefficients live in
  the maintained data file `workbench/data/build_cost.toml`.
- New read-only routes (`routes/io.py`): file listing, URL check, place search, estimate, jobs list and cancel.
- The front end gains `wizard.js`, `filebrowser.js`, `areapicker.js` and `jobs.js` (no build step).

**Tech Stack:**
- Python 3.11 (`tomllib`, `xml.etree`), pydantic v2, FastAPI, `threading`, fsspec (already a datagrove dependency).
- DuckDB via ibis for the Overture count.
- MapLibre GL 4.7.1 for the area map (already loaded from the CDN). No new dependencies.

**Spec:** [2026-10-02-gmnspy-workbench-design.md](2026-10-02-gmnspy-workbench-design.md), section
"Open / Import wizard (P1a, agreed 2026-10-02)", plus "Core idea", "Two audit logs" and "Transit".

**Branch:** implement on a new branch `feat/workbench-p1a`, cut from `feat/workbench-p0` (P0 is done there).

**Conventions:**
- Run commands from the repo root.
- Run tests with `uv run --all-extras pytest <path> -q`.
- Lint with `uv run ruff check packages && uv run ruff format --check packages`.
- CI also runs `uv run lint-imports` and `uv run python scripts/lint_no_sql.py`. Task 17 runs both.
- Ruff enforces Google-style docstrings (`D`) on every public module-level function, class and method outside
  `tests/` and `__init__.py`. Each code block below already has them. Line length is 120.
- `--doctest-modules` is on, so every `>>>` example below is a test, and each one was checked.
- Tests never touch the network:
  - HTTP goes through an injected fake (`Session(http=...)`, `session=` on the OSM helpers);
  - the URL check takes an injectable `url_to_fs`;
  - Overture reads use the committed GeoParquet fixture `tests/fixtures/overture`.
- Never write under `gmnspy/fixtures`: the conftest guard fails the session. New committed test inputs go
  under `packages/gmnspy/tests/fixtures/`, and all outputs go to `tmp_path`.
- Every code block in this plan was run against a copy of `feat/workbench-p0`. The expected test counts are
  from that run.

---

## Decisions

These are the choices the design doc leaves open, each with a one-line rationale.

1. **`OpenNetwork` always runs as a background job, like `BuildNetwork`.** One rule for both. A slow open never holds the session lock. `Session.dispatch` waits for the job, so Python and the `gmnspy app` CLI keep their blocking behaviour unchanged.
2. **A job action's history entry is recorded when the job ends**, whether it succeeds, fails, is cancelled, or needs approval. `seq` follows completion order. The audit log records outcomes, not intents.
3. **The approval gate runs inside the build job, in its `estimate` stage.** The pre-query is network I/O, so it must not run under the lock. The job re-runs the cheap count rather than trusting an estimate sent by the client.
4. **A Python replay counts as approval.** `to_python(BuildNetwork(...))` always emits `approved=True` via a `replay_overrides` class variable. A fresh Python call without `approved=True` raises `ApprovalRequired`, which carries `.estimate`.
5. **The gate is a plain comparison, not datagrove's `gate()`:** approval is needed when `seconds is None or seconds > app.approve_above_s`. `OperationCost` has no latency term and no injectable coefficients, so wrapping it would cost more code than the one-line comparison. The semantics (an approve flag and a typed exception) are the same.
6. **Cost model: `seconds = latency_s + links * s_per_link`, with `links = n_elements * links_per_element`.** It lives in `workbench/data/build_cost.toml`, read with `tomllib`. It is seeded from the single measured RDU run (about 27 s for 269k links), and the file says which numbers are guesses.
7. **Each source has its own pre-query unit:**
   - OSM: matching **ways** (Overpass `out count;`, without recursing to nodes).
   - Overture: road **segments** (`COUNT(*)` with the read's bbox and class predicate).
   - Local OSM file: **bytes**, because counting would mean parsing the whole file.
   - Local Overture snapshot: segments, by `COUNT(*)`.
8. **`Area` stores what it resolved to.** A place keeps its bbox and its polygon simplified by Nominatim (`polygon_threshold=0.001`, about 100 m), so a replay never re-geocodes. OSM uses the polygon; Overture uses the bbox only, as the design doc says.
9. **`area` and `input_file` are mutually exclusive.** A local file is imported whole. To clip a large local Overture snapshot, set `overture.data_root` to it and give an area.
10. **The output path is `output_dir / name` (plus `.duckdb` for DuckDB).** `name` is required and must be a plain file name. A build never overwrites an existing output, and removes a partial output if the write fails. The output folder must exist inside the allowed roots.
11. **`output_format="zip"` stays in the schema but raises `NotSupportedYet`.** `Network.write` has no zip format, and `Network.from_source` cannot reopen a `.csv.zip`: DuckDB fails on the `::member` path, and this was reproduced on the bundled Leavenworth zip. "Write, then open from disk" is therefore impossible for zip today (see Open questions).
    > **SUPERSEDED (2026-10-02):** zip read/write was fixed in 4b743fb; zip is a normal output format.
12. **`io.allowed_roots` is enforced everywhere a local path enters:** `OpenNetwork` (local paths only; URLs bypass it), the file listing, and build inputs and outputs, including from Python. Paths are fully resolved before the containment check, so neither `..` nor a symlink can escape a root. One rule means a replay behaves the same in Python as in the UI.
13. **Paths named on the `gmnspy app` command line are trusted.** The CLI adds exactly those resolved paths to `io.allowed_roots` as a session-layer override, prints a note, and records no extra history entry. The user typed the path in their own shell, and `gmnspy app /data/net` must keep working.
14. **Recents live in the browser's `localStorage`**, the same pattern as the remembered view mode. They are a per-user convenience that needs no server code. A recent is only a shortcut: opening one is a normal `open_network`, checked against the allowed roots. They are remembered from every successful history entry, including opens made from Python.
15. **Jobs:**
    - one daemon thread per job, with no queue or limit;
    - jobs are kept in memory for the life of the session;
    - cancellation is cooperative at stage boundaries, and a download or read already in progress is not interrupted.
16. **Builds run on a private `IbisEngine`**, closed after the write, so a build never shares a DuckDB connection with the networks the browser is reading. Opening from disk uses the default engine, as P0 does.
17. **The open job materialises the link and node frames before taking the lock**, and seeds them with the new `NetworkHandle.prime()`. That keeps `state()`, which runs under the lock, cheap.
18. **Optional extras are imported at run time** via `workbench.extras.optional_module`. A static import of `gmnspy.osm` from anything `gmnspy.cli` imports breaks the import-linter contract. The Overture snapshot layout lives in the dependency-free `gmnspy.overture.layout` for the same reason.
19. **New settings:**
    - `app.approve_above_s` (default 90, must be ≥ 0);
    - a `build` section (`network_type`, `buffer_m`, `extra_tags`) that the wizard pre-fills from.

    The wizard always sends explicit values, so a replay does not depend on later settings. `spec_version=None` means `io.spec_version`. `overture_release=None` means `overture.release`, then the pinned default.
20. **Local OSM files are read with stdlib `ElementTree.iterparse` or `json`.**
    - The highway filter runs locally: a way is kept if it has a `highway` tag and `tags.accepts_highway` accepts it.
    - A way that references a missing node is dropped, with one warning, rather than failing the import.
21. **The URL check uses `fsspec.core.url_to_fs` and a new `datagrove.io.credentials.credential_source(host)`**, which returns only the layer's name. It is a `POST` (as specified). Tables are the `csv`/`parquet` stems directly inside the folder.
22. **The read-only routes live in a new `routes/io.py`.** They sit behind the existing loopback Host/Origin middleware and are never recorded. Place search runs only on an explicit Search, because Nominatim's usage policy allows about one request per second.
23. **The area picker has its own small MapLibre map inside the modal**, not the main map. That avoids fighting the network layers and the highlight box-select. The editable corners are four draggable `maplibregl.Marker`s.
24. **No estimate or gate code is shared with `gmnspy build` in P1a.** Adding a gate to the CLI would change its behaviour and is out of scope. Recommended follow-up: `gmnspy build --estimate/--yes`, reusing `workbench.build.plan_build` and `estimate_for` (neither imports FastAPI).
25. **`network_type` stays a free string**, validated against `osm_network_filters.yaml` / `overture_network_filters.yaml` at build time, because the mapping file is the source of truth. The wizard offers `drive`, `walk`, `bike` and `all`.
26. **`BuildNetwork` mutates the session, but it is not a `NetworkChange`.** It creates a network rather than editing one, so it goes only to session history, never to the draft ProjectCard. The new handle's `source` is the output path, and its `lineage` stays empty.
27. **Transit:** a build produces the `roadway` component only, and `BuildNetwork` has no `component` field. Attaching GTFS is a later, separate action, as the Transit section plans.

---

## Scope notes (P1a vs later)

- **In P1a:**
  - settings (`app.approve_above_s`, `build.*`);
  - allowed-roots enforcement;
  - local OSM file reader;
  - Overture segment count and snapshot layout;
  - `geocode_candidates`;
  - `credential_source` and the URL check;
  - `Area`, the estimate model, `JobRunner`;
  - `OpenNetwork` and `BuildNetwork` as job actions;
  - the read-only routes;
  - the wizard UI (file browser, area picker, jobs panel, recents);
  - trusted CLI sources;
  - docs.
- **Deferred:**
  - zip output and opening a `.zip` (blocked on the zip read path, see Open questions);
  - `.pbf` input (optional pyosmium extra);
  - upload;
  - polygon clipping and a divisions lookup for Overture;
  - attaching GTFS;
  - a `gmnspy build --estimate/--yes` CLI gate;
  - pruning the in-memory job list.
- **Unchanged:** `gmnspy build` behaviour, the P0 actions, and the per-network data routes.

## File structure

| Path | Responsibility |
|---|---|
| `packages/gmnspy/gmnspy/config.py` (modify) | `AppSettings.approve_above_s`, new `BuildSettings` section |
| `packages/gmnspy/gmnspy/workbench/errors.py` (new) | `ActionError` (moved from `session.py`), `NotSupportedYet`, `PathNotAllowed`, `JobCancelled`, `ApprovalRequired` |
| `packages/gmnspy/gmnspy/workbench/paths.py` (new) | `is_url`, `allowed_roots`, `is_allowed`, `resolve_allowed` |
| `packages/gmnspy/gmnspy/workbench/files.py` (new) | `detect_kind`, `list_dir`, `open_target`: the server-side file browser |
| `packages/gmnspy/gmnspy/overture/layout.py` (new) | Dependency-free `LOCAL_SNAPSHOT_FILES` and `is_local_snapshot`, with the documented layout |
| `packages/gmnspy/gmnspy/osm/local.py` (new) | `read_osm_file` for `.osm` XML and Overpass JSON, with the highway filter applied locally |
| `packages/gmnspy/gmnspy/osm/build.py`, `osm/__init__.py` (modify) | `build_network_from_osm_file` |
| `packages/gmnspy/gmnspy/osm/query.py` (modify) | `build_overpass_query(out="count")`, `geocode_candidates` |
| `packages/gmnspy/gmnspy/overture/query.py`, `overture/__init__.py` (modify) | `count_segments` (predicate shared with `read_segments`) |
| `packages/datagrove/datagrove/io/credentials.py` (modify) | `credential_source(host)`: the layer name, never the value |
| `packages/gmnspy/gmnspy/workbench/urlcheck.py` (new) | `check_url`: reachable, credential source, tables |
| `packages/gmnspy/gmnspy/workbench/area.py` (new) | `Area` = `BboxArea \| PointArea \| PlaceArea` |
| `packages/gmnspy/gmnspy/workbench/extras.py` (new) | `optional_module`: run-time import of `[osm]`/`[overture]` modules |
| `packages/gmnspy/gmnspy/workbench/estimate.py` (new) | `Estimate`, `estimate_build`, `count_osm`, `count_overture`, `needs_approval`, `fit_s_per_link` |
| `packages/gmnspy/gmnspy/workbench/data/build_cost.toml` (new) | Maintained cost-model coefficients |
| `packages/gmnspy/gmnspy/workbench/jobs.py` (new) | `Job`, `JobContext`, `JobRunner` |
| `packages/gmnspy/gmnspy/workbench/build.py` (new) | `plan_build`, `estimate_for`, `fetch_and_convert`, `write_output` |
| `packages/gmnspy/gmnspy/workbench/actions.py` (modify) | `runs_as_job`/`replay_overrides`, `BuildNetwork`, top-level-default `to_python` |
| `packages/gmnspy/gmnspy/workbench/registry.py` (modify) | Public `as_pandas`, `NetworkHandle.prime` |
| `packages/gmnspy/gmnspy/workbench/session.py` (modify) | Job actions: `submit`, `_finish`, `_record`, `_job_open_network`, `_job_build_network`; `http=` |
| `packages/gmnspy/gmnspy/workbench/__init__.py` (modify) | Export `BuildNetwork`, the areas, and the errors |
| `packages/gmnspy/gmnspy/workbench/routes/io.py` (new) | `/api/fs/list`, `/api/check-url`, `/api/geocode`, `/api/estimate`, `/api/jobs`, `/api/jobs/{id}/cancel` |
| `packages/gmnspy/gmnspy/workbench/routes/core.py`, `server.py` (modify) | Job actions answer `202`; mount the io router |
| `packages/gmnspy/gmnspy/workbench/static/index.html`, `app.css` (modify) | Header buttons, jobs panel, wizard modal |
| `packages/gmnspy/gmnspy/workbench/static/js/{api,header,main,store,history}.js` (modify) | `postJSON`, recents, jobs/wizard wiring, basemap in store |
| `packages/gmnspy/gmnspy/workbench/static/js/{jobs,filebrowser,areapicker,wizard}.js` (new) | Wizard UI |
| `packages/gmnspy/gmnspy/cli/commands/workbench.py` (modify) | Trust command-line sources for the session |
| `packages/gmnspy/pyproject.toml` (modify) | Wheel includes `workbench/data/*.toml` |
| `packages/gmnspy/docs/cookbook/workbench.md` (modify) | Open / Import section |
| `packages/gmnspy/tests/conftest.py`, `test_workbench_network_routes.py` (modify) | Allowed roots pinned in test environments |
| `packages/gmnspy/tests/fixtures/osm/tiny.osm`, `tiny_overpass.json` (new) | Hand-written local OSM inputs |
| `packages/gmnspy/tests/test_*.py` (new/modify) | Tests listed per task |

---

### Task 0: Branch and test environments with pinned allowed roots

`io.allowed_roots` is enforced from Task 12 on. With an empty list, the allowed root is the home folder, and
pytest's `tmp_path` (on macOS, `/private/var/folders/...`) is outside it. Pin the roots in the shared test
environment now, so the suite behaves the same wherever the repo is checked out.

**Files:**
- Modify: `packages/gmnspy/tests/conftest.py`
- Modify: `packages/gmnspy/tests/test_workbench_network_routes.py`

- [ ] **Step 1: Cut the branch**

```bash
git checkout feat/workbench-p0 && git checkout -b feat/workbench-p1a
```

- [ ] **Step 2: Pin allowed roots in `isolated_env`**

In `packages/gmnspy/tests/conftest.py`, add `import json` after `import hashlib`. Then replace:

```python
@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environ whose gmnspy user-config dir lives under ``tmp_path``, never the real ``~/.config``."""
    return {"GMNSPY_CONFIG_DIR": str(tmp_path / "user")}
```

with:

```python
#: Committed test-only fixture files (tests/fixtures), e.g. the local OSM/Overture inputs.
TEST_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environ isolated from the real machine.

    The gmnspy user-config dir lives under ``tmp_path`` (never the real ``~/.config``), and
    ``io.allowed_roots`` is pinned to ``tmp_path`` plus the two read-only fixture trees, so the
    workbench's allowed-roots policy behaves the same wherever the repo is checked out.
    """
    roots = [str(tmp_path.resolve()), str(_FIXTURES_ROOT.resolve()), str(TEST_FIXTURES)]
    return {"GMNSPY_CONFIG_DIR": str(tmp_path / "user"), "GMNSPY_IO__ALLOWED_ROOTS": json.dumps(roots)}
```

- [ ] **Step 3: Give the module-scoped network-routes client the same policy**

`test_workbench_network_routes.py` builds its own environment and already does `import json`. In its `client`
fixture, replace:

```python
    s = Session(project_dir=tmp, environ={"GMNSPY_CONFIG_DIR": str(tmp / "user")}, parser=StubParser())
```

with:

```python
    env = {"GMNSPY_CONFIG_DIR": str(tmp / "user"), "GMNSPY_IO__ALLOWED_ROOTS": json.dumps([rdu_source])}
    s = Session(project_dir=tmp, environ=env, parser=StubParser())
```

- [ ] **Step 4: Confirm the workbench suite is unchanged**

Run: `uv run --all-extras pytest packages/gmnspy/tests -q -k "workbench or config"`
Expected: all pass. Nothing enforces roots yet, so the extra environment variable has no effect.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/tests/conftest.py packages/gmnspy/tests/test_workbench_network_routes.py
git commit -m "test(gmnspy): pin io.allowed_roots in workbench test environments"
```

---

### Task 1: Settings: `app.approve_above_s` and the `build` section

**Files:**
- Modify: `packages/gmnspy/gmnspy/config.py`
- Test: `packages/gmnspy/tests/test_config.py`

- [ ] **Step 1: Append the failing tests to `packages/gmnspy/tests/test_config.py`**

```python
def test_approval_threshold_and_build_defaults(tmp_path, isolated_env):
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert s.app.approve_above_s == 90.0
    assert (s.build.network_type, s.build.buffer_m, s.build.extra_tags) == ("drive", 1000.0, [])


def test_negative_approval_threshold_rejected(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[app]\napprove_above_s = -1\n")
    with pytest.raises(SettingsError, match="approve_above_s"):
        load_settings(project_dir=tmp_path, environ=isolated_env)
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py -q`
Expected: `1 failed, 17 passed`. The failure is `AttributeError: 'AppSettings' object has no attribute
'approve_above_s'`. The negative-threshold test already passes, because an unknown key is rejected too; it guards
the `ge=0` bound once the field exists.

- [ ] **Step 3: Implement in `packages/gmnspy/gmnspy/config.py`**

Insert this class directly above `class RuleSettings(_Section):`:

```python
class BuildSettings(_Section):
    """Defaults the Open / Import wizard prefills for OSM and Overture builds."""

    network_type: str = "drive"
    buffer_m: float = Field(default=1000.0, gt=0)
    extra_tags: list[str] = Field(default_factory=list)
```

In `AppSettings`, add a field after `console: bool = False`:

```python
    approve_above_s: float = Field(default=90.0, ge=0)
```

In `Settings`, add a field after `overture: OvertureSettings = Field(default_factory=OvertureSettings)`:

```python
    build: BuildSettings = Field(default_factory=BuildSettings)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_config.py -q`
Expected: `18 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/config.py packages/gmnspy/tests/test_config.py
git commit -m "feat(config): app.approve_above_s and build.* wizard defaults"
```

---

### Task 2: Typed errors and the allowed-roots path policy

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/errors.py`
- Create: `packages/gmnspy/gmnspy/workbench/paths.py`
- Modify: `packages/gmnspy/gmnspy/workbench/session.py` (import the errors from their new home)
- Test: `packages/gmnspy/tests/test_workbench_paths.py`

- [ ] **Step 1: Write the failing tests in `packages/gmnspy/tests/test_workbench_paths.py`**

```python
"""Tests for the workbench allowed-roots path policy."""

import os
from pathlib import Path

import pytest
from gmnspy.config import Settings
from gmnspy.workbench.errors import PathNotAllowed
from gmnspy.workbench.paths import allowed_roots, is_allowed, is_url, resolve_allowed


def _settings(*roots: Path) -> Settings:
    return Settings.model_validate({"io": {"allowed_roots": [str(r) for r in roots]}})


@pytest.mark.parametrize(
    ("source", "expected"),
    [("s3://b/k", True), ("https://x.org/n.zip", True), ("/data/net", False), ("C:\\data\\net", False), ("net", False)],
)
def test_is_url(source, expected):
    assert is_url(source) is expected


def test_empty_roots_means_home():
    assert allowed_roots(Settings()) == [Path.home().resolve()]


def test_inside_root_resolves(tmp_path):
    (tmp_path / "net").mkdir()
    assert resolve_allowed(tmp_path / "net", _settings(tmp_path)) == (tmp_path / "net").resolve()
    assert resolve_allowed(tmp_path, _settings(tmp_path)) == tmp_path.resolve()


def test_missing_path_inside_root_is_allowed(tmp_path):
    assert is_allowed(tmp_path / "not-yet" / "out", _settings(tmp_path))


def test_dotdot_escape_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        resolve_allowed(root / ".." / "elsewhere", _settings(root))


def test_sibling_with_shared_prefix_rejected(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data-private").mkdir()
    assert not is_allowed(tmp_path / "data-private", _settings(tmp_path / "data"))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathNotAllowed):
        resolve_allowed(root / "link", _settings(root))
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_paths.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.workbench.errors'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/errors.py`**

`ApprovalRequired` is added in Task 10, once `Estimate` exists.

```python
"""Typed, user-facing workbench errors (shared by the session, jobs, paths, and estimates).

Every subclass of :class:`ActionError` is recorded in the session history with
its class name as ``error_type``; ``payload`` (when set) becomes the entry's
``result`` so the UI can act on it (e.g. show the estimate an approval needs).
"""

from __future__ import annotations

from typing import Any

__all__ = ["ActionError", "JobCancelled", "NotSupportedYet", "PathNotAllowed"]


class ActionError(Exception):
    """An action could not be applied; the message is shown to the user."""

    payload: dict[str, Any] | None = None


class NotSupportedYet(ActionError):
    """The action is in the schema but its handler ships in a later phase."""


class PathNotAllowed(ActionError):
    """A local path resolved outside ``io.allowed_roots``."""


class JobCancelled(ActionError):
    """A background job stopped at a checkpoint because cancellation was requested."""
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/paths.py`**

```python
"""Local-path policy for the workbench: every local read or write stays under ``io.allowed_roots``.

An empty ``io.allowed_roots`` means "the user's home directory". Paths are
resolved (``~`` expanded, symlinks followed, ``..`` collapsed) *before* the
containment check, so neither a symlink nor a ``..`` segment can escape a root.
URLs are not local paths and are never checked here.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from gmnspy.config import Settings

from .errors import PathNotAllowed

__all__ = ["allowed_roots", "is_allowed", "is_url", "resolve_allowed"]


def is_url(source: str) -> bool:
    """Whether ``source`` is a URL: it has a scheme of two or more letters (a Windows drive letter is not one)."""
    return len(urlsplit(str(source)).scheme) > 1


def allowed_roots(settings: Settings) -> list[Path]:
    """The resolved allowed roots (``io.allowed_roots``, or ``[home]`` when that list is empty)."""
    return [Path(r).expanduser().resolve() for r in settings.io.allowed_roots or [str(Path.home())]]


def _inside(candidate: Path, roots: list[Path]) -> bool:
    return any(candidate.is_relative_to(root) for root in roots)


def is_allowed(path: str | Path, settings: Settings) -> bool:
    """Whether ``path`` resolves inside an allowed root."""
    return _inside(Path(path).expanduser().resolve(), allowed_roots(settings))


def resolve_allowed(path: str | Path, settings: Settings) -> Path:
    """Return ``path`` fully resolved, or raise :class:`PathNotAllowed` if it falls outside every allowed root."""
    candidate = Path(path).expanduser().resolve()
    roots = allowed_roots(settings)
    if not _inside(candidate, roots):
        shown = ", ".join(str(r) for r in roots)
        raise PathNotAllowed(
            f"{path} is outside the allowed folders ({shown}); add a parent folder to io.allowed_roots"
        )
    return candidate
```

- [ ] **Step 5: Make `session.py` import the moved errors**

In `packages/gmnspy/gmnspy/workbench/session.py`, delete:

```python
class ActionError(Exception):
    """An action could not be applied; the message is shown to the user."""


class NotSupportedYet(ActionError):
    """The action is in the schema but its handler ships in a later phase."""
```

and add this import directly after `from .actions import (...)`:

```python
from .errors import ActionError, NotSupportedYet
```

`session.__all__` still lists both names, so `from gmnspy.workbench.session import ActionError` (used by tests and
`__init__.py`) keeps working.

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_paths.py packages/gmnspy/tests/test_workbench_session.py -q`
Expected: `33 passed`.

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/errors.py packages/gmnspy/gmnspy/workbench/paths.py \
  packages/gmnspy/gmnspy/workbench/session.py packages/gmnspy/tests/test_workbench_paths.py
git commit -m "feat(workbench): typed errors module + io.allowed_roots path policy (resolve before contain)"
```

---

### Task 3: `gmnspy app` trusts the sources named on its command line

This lands before enforcement (Task 12), so `gmnspy app <path outside home>` never breaks in between.

**Files:**
- Modify: `packages/gmnspy/gmnspy/cli/commands/workbench.py`
- Test: `packages/gmnspy/tests/test_cli_workbench.py`

- [ ] **Step 1: Write the failing tests**

In `packages/gmnspy/tests/test_cli_workbench.py`, add `import json` above `from pathlib import Path`, then append:

```python
def test_cli_sources_outside_allowed_roots_are_trusted_for_the_session(served, monkeypatch, rdu_source, tmp_path):
    """A path typed on the command line is the user's explicit choice: the CLI allows exactly that path."""
    monkeypatch.setenv("GMNSPY_IO__ALLOWED_ROOTS", json.dumps([str(tmp_path / "elsewhere")]))
    result = runner.invoke(app, ["app", rdu_source])
    assert result.exit_code == 0, result.output
    (session,) = served
    roots = session.settings.io.allowed_roots
    assert str(Path(rdu_source).resolve()) in roots and str((tmp_path / "elsewhere").resolve()) in roots
    assert session.loaded.sources["io.allowed_roots"] == "session" and "allowing" in result.output
    assert session.registry.ids() == ["rdu-i40"]


def test_cli_does_not_widen_roots_when_already_allowed(served, monkeypatch, rdu_source):
    monkeypatch.setenv("GMNSPY_IO__ALLOWED_ROOTS", json.dumps([str(Path(rdu_source).parent)]))
    result = runner.invoke(app, ["app", rdu_source])
    assert result.exit_code == 0 and "allowing" not in result.output
    assert served[0].loaded.sources["io.allowed_roots"] == "env"
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_workbench.py -q`
Expected: `1 failed, 12 passed`. `test_cli_sources_outside_allowed_roots_are_trusted_for_the_session` fails with
`AssertionError` because the fixture path is not in `allowed_roots`.

- [ ] **Step 3: Implement in `packages/gmnspy/gmnspy/cli/commands/workbench.py`**

In `run_workbench`, replace:

```python
    from gmnspy import workbench
    from gmnspy.config import SettingsError
    from gmnspy.workbench.actions import OpenNetwork

    flags = {"select.provider": provider, "viz.basemap": basemap, "app.host": host, "app.port": port}
    try:
        session = workbench.Session(overrides={k: v for k, v in flags.items() if v is not None})
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for source in sources:
        resolved = str(source)
        path = Path(resolved)
        if path.exists():
            resolved = str(path.resolve())
        try:
            session.dispatch(OpenNetwork(source=resolved))
```

with:

```python
    from gmnspy import workbench
    from gmnspy.config import SettingsError
    from gmnspy.workbench.actions import OpenNetwork
    from gmnspy.workbench.paths import allowed_roots, is_allowed, is_url

    flags = {"select.provider": provider, "viz.basemap": basemap, "app.host": host, "app.port": port}
    overrides = {k: v for k, v in flags.items() if v is not None}
    resolved = [s if is_url(s) else str(Path(s).resolve()) for s in map(str, sources)]
    try:
        session = workbench.Session(overrides=overrides)
        # Sources named on the command line are trusted: allow exactly those paths for this session.
        extra = [s for s in resolved if not is_url(s) and not is_allowed(s, session.settings)]
        if extra:
            roots = [str(r) for r in allowed_roots(session.settings)] + extra
            session = workbench.Session(overrides={**overrides, "io.allowed_roots": roots})
            typer.echo(f"note: allowing {', '.join(extra)} for this session (io.allowed_roots)", err=True)
    except SettingsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    for source in resolved:
        try:
            session.dispatch(OpenNetwork(source=source))
```

All local sources are now resolved to absolute paths, whether or not they exist. A missing path still fails
later with `could not open ...` (exit 1), as `test_app_bad_source_exits_1` expects.

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_cli_workbench.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/cli/commands/workbench.py packages/gmnspy/tests/test_cli_workbench.py
git commit -m "feat(cli): gmnspy app allows its command-line sources for the session"
```

---

### Task 4: The Overture snapshot layout and the server-side file browser

**Files:**
- Create: `packages/gmnspy/gmnspy/overture/layout.py`
- Modify: `packages/gmnspy/gmnspy/overture/__init__.py` (docstring pointer)
- Create: `packages/gmnspy/gmnspy/workbench/files.py`
- Test: `packages/gmnspy/tests/test_workbench_files.py`, `packages/gmnspy/tests/test_overture_query.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/gmnspy/tests/test_workbench_files.py`:

```python
"""Tests for the workbench server-side file browser."""

import pytest
from gmnspy.config import Settings
from gmnspy.workbench.errors import PathNotAllowed
from gmnspy.workbench.files import detect_kind, list_dir


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "gmns_csv").mkdir()
    (tmp_path / "gmns_csv" / "link.csv").write_text("link_id\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "datapackage.json").write_text("{}")
    (tmp_path / "ovt").mkdir()
    for name in ("segment.parquet", "connector.parquet"):
        (tmp_path / "ovt" / name).write_bytes(b"")
    (tmp_path / "plain").mkdir()
    for name in ("net.zip", "net.duckdb", "extract.osm", "export.json", "notes.txt", ".hidden"):
        (tmp_path / name).write_text("")
    return tmp_path


def _settings(root):
    return Settings.model_validate({"io": {"allowed_roots": [str(root)]}})


def test_detect_kind(tree):
    kinds = {p.name: detect_kind(p) for p in tree.iterdir()}
    assert kinds == {
        "gmns_csv": "gmns",
        "pkg": "gmns",
        "ovt": "overture",
        "plain": None,
        "net.zip": "zip",
        "net.duckdb": "duckdb",
        "extract.osm": "osm",
        "export.json": "json",
        "notes.txt": None,
        ".hidden": None,
    }
    assert detect_kind(tree / "pkg" / "datapackage.json") == "datapackage"


def test_list_dir_folders_first_hidden_skipped(tree):
    listing = list_dir(str(tree), _settings(tree))
    names = [e["name"] for e in listing["entries"]]
    assert names == [
        "gmns_csv",
        "ovt",
        "pkg",
        "plain",
        "export.json",
        "extract.osm",
        "net.duckdb",
        "net.zip",
        "notes.txt",
    ]
    assert listing["parent"] is None and listing["truncated"] is False


def test_datapackage_file_targets_its_folder(tree):
    (entry,) = list_dir(str(tree / "pkg"), _settings(tree))["entries"]
    assert entry["kind"] == "datapackage" and entry["target"] == str((tree / "pkg").resolve())


def test_subfolder_has_parent(tree):
    assert list_dir(str(tree / "plain"), _settings(tree))["parent"] == str(tree.resolve())


def test_no_path_lists_roots(tree):
    listing = list_dir(None, _settings(tree))
    assert [e["path"] for e in listing["entries"]] == [str(tree.resolve())]


def test_outside_roots_rejected(tree, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    with pytest.raises(PathNotAllowed):
        list_dir(str(other), _settings(tree))


def test_missing_and_file_paths(tree):
    with pytest.raises(FileNotFoundError):
        list_dir(str(tree / "nope"), _settings(tree))
    with pytest.raises(NotADirectoryError):
        list_dir(str(tree / "net.zip"), _settings(tree))
```

In `packages/gmnspy/tests/test_overture_query.py`, add `from gmnspy.overture.layout import is_local_snapshot` below
`from gmnspy.overture import query`, then append:

```python
class TestLocalSnapshotLayout:
    def test_fixture_is_a_local_snapshot(self):
        assert is_local_snapshot(FIXTURE_ROOT)

    def test_needs_both_files(self, tmp_path):
        (tmp_path / "segment.parquet").write_bytes(b"")
        assert not is_local_snapshot(tmp_path)
        assert not is_local_snapshot(tmp_path / "segment.parquet")
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_files.py packages/gmnspy/tests/test_overture_query.py -q`
Expected: collection errors, `ModuleNotFoundError: No module named 'gmnspy.workbench.files'` and
`... 'gmnspy.overture.layout'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/overture/layout.py`**

It must import nothing from `gmnspy.overture`. Importing that package's `__init__` would pull in `build` and then
`gmnspy.osm`, and break the import-linter contract that `gmnspy.cli` (which imports the workbench) must not
require optional extras.

```python
"""The local Overture snapshot layout, dependency-free so the workbench's file browser can detect it.

A **local snapshot** (``data_root=`` on the builder, the ``overture.data_root`` setting, or a
folder picked in the workbench's Open / Import wizard) is one flat folder holding exactly
:data:`LOCAL_SNAPSHOT_FILES`:

* ``segment.parquet``: Overture ``transportation/segment`` features, as published (GeoParquet with
  WKB ``geometry`` and the ``bbox`` struct column);
* ``connector.parquet``: the matching ``transportation/connector`` features.

Any bbox subset of one release works (for example the output of the ``overturemaps`` CLI or a
DuckDB ``COPY`` of a release filtered on ``bbox``). Remote ``s3://`` / ``az://`` / ``https://``
roots use the release's hive layout instead (``theme=transportation/type=<type>/*``).
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["LOCAL_SNAPSHOT_FILES", "is_local_snapshot"]

#: Files a flat local Overture snapshot folder must hold.
LOCAL_SNAPSHOT_FILES: tuple[str, ...] = ("segment.parquet", "connector.parquet")


def is_local_snapshot(path: str | Path) -> bool:
    """Whether ``path`` is a folder laid out as a local Overture snapshot."""
    folder = Path(path)
    return folder.is_dir() and all((folder / name).is_file() for name in LOCAL_SNAPSHOT_FILES)
```

In `packages/gmnspy/gmnspy/overture/__init__.py`, extend the paragraph that ends
`so importing this package is cheap and the import-linter boundary stays static.` with two more lines:

```text
The flat local-snapshot folder layout (``segment.parquet`` + ``connector.parquet``)
is documented in :mod:`gmnspy.overture.layout`.
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/files.py`**

```python
"""Server-side file browser for the Open / Import wizard: list a folder, tag what each entry can be opened as.

Listing never leaves ``io.allowed_roots`` (see :mod:`gmnspy.workbench.paths`), skips hidden entries, and
reads no file contents: a kind is decided from names alone, so browsing a large folder stays cheap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gmnspy.config import Settings
from gmnspy.overture.layout import is_local_snapshot

from .paths import allowed_roots, resolve_allowed

__all__ = ["MAX_ENTRIES", "detect_kind", "list_dir", "open_target"]

#: Cap on entries returned for one folder (the response says ``truncated`` when it is hit).
MAX_ENTRIES = 2000

_GMNS_TABLE_FILES = ("link.csv", "link.parquet")


def detect_kind(path: Path) -> str | None:
    """What ``path`` can be opened as, or ``None`` for a plain folder / unrecognised file.

    Kinds: ``gmns`` (a folder with ``link.csv``/``link.parquet`` or a ``datapackage.json``),
    ``overture`` (a folder holding ``segment.parquet`` + ``connector.parquet``), ``zip``,
    ``duckdb``, ``datapackage`` (the ``datapackage.json`` file itself), ``osm`` (``.osm`` XML),
    and ``json`` (a candidate Overpass JSON export).
    """
    if path.is_dir():
        if is_local_snapshot(path):
            return "overture"
        if (path / "datapackage.json").is_file() or any((path / n).is_file() for n in _GMNS_TABLE_FILES):
            return "gmns"
        return None
    name = path.name.lower()
    if name == "datapackage.json":
        return "datapackage"
    return {".zip": "zip", ".duckdb": "duckdb", ".osm": "osm", ".json": "json"}.get(path.suffix.lower())


def open_target(path: Path, kind: str | None) -> str:
    """The source string to hand to ``OpenNetwork`` / ``BuildNetwork`` for an entry of ``kind``."""
    return str(path.parent if kind == "datapackage" else path)


def _entry(path: Path) -> dict[str, Any]:
    kind = detect_kind(path)
    return {
        "name": path.name,
        "path": str(path),
        "is_dir": path.is_dir(),
        "kind": kind,
        "target": open_target(path, kind),
    }


def list_dir(path: str | None, settings: Settings) -> dict[str, Any]:
    """List ``path`` (or, when ``None``, the allowed roots themselves) as tagged entries, folders first.

    Raises:
        PathNotAllowed: ``path`` resolves outside ``io.allowed_roots``.
        FileNotFoundError: ``path`` does not exist.
        NotADirectoryError: ``path`` is a file.
    """
    if path is None:
        roots = [r for r in allowed_roots(settings) if r.is_dir()]
        return {"path": None, "parent": None, "entries": [_entry(r) for r in roots], "truncated": False}
    folder = resolve_allowed(path, settings)
    if not folder.exists():
        raise FileNotFoundError(f"no such folder: {path}")
    if not folder.is_dir():
        raise NotADirectoryError(f"not a folder: {path}")
    children = sorted(
        (p for p in folder.iterdir() if not p.name.startswith(".")),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    parent = folder.parent if folder not in allowed_roots(settings) else None
    return {
        "path": str(folder),
        "parent": str(parent) if parent is not None else None,
        "entries": [_entry(p) for p in children[:MAX_ENTRIES]],
        "truncated": len(children) > MAX_ENTRIES,
    }
```

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_files.py packages/gmnspy/tests/test_overture_query.py -q`
Expected: `19 passed`.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/overture/layout.py packages/gmnspy/gmnspy/overture/__init__.py \
  packages/gmnspy/gmnspy/workbench/files.py packages/gmnspy/tests/test_workbench_files.py \
  packages/gmnspy/tests/test_overture_query.py
git commit -m "feat(workbench): server-side file listing with kind tags; document the Overture snapshot layout"
```

---

### Task 5: Read local OSM files (`.osm` XML, Overpass JSON) and build from them

**Files:**
- Create: `packages/gmnspy/tests/fixtures/osm/tiny.osm`, `packages/gmnspy/tests/fixtures/osm/tiny_overpass.json`
- Create: `packages/gmnspy/gmnspy/osm/local.py`
- Modify: `packages/gmnspy/gmnspy/osm/build.py`, `packages/gmnspy/gmnspy/osm/__init__.py`
- Test: `packages/gmnspy/tests/test_osm_local.py`

- [ ] **Step 1: Add the hand-written fixtures**

Both files hold the same 4 nodes and 4 ways:
- a residential street, which is kept;
- a footway, kept only for `all`;
- a residential way that references the missing node 99, so it is dropped;
- a building, which is not a highway.

`packages/gmnspy/tests/fixtures/osm/tiny.osm`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!-- Hand-written test fixture for gmnspy.osm.local (not real OSM data). -->
<osm version="0.6" generator="gmnspy-tests">
  <bounds minlat="42.0" minlon="-71.002" maxlat="42.002" maxlon="-71.0"/>
  <node id="1" lat="42.000" lon="-71.000"/>
  <node id="2" lat="42.001" lon="-71.000"/>
  <node id="3" lat="42.002" lon="-71.000"/>
  <node id="4" lat="42.002" lon="-71.002"/>
  <way id="100">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Main St"/>
  </way>
  <way id="101">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="footway"/>
  </way>
  <way id="102">
    <nd ref="4"/><nd ref="99"/>
    <tag k="highway" v="residential"/>
  </way>
  <way id="103">
    <nd ref="1"/><nd ref="2"/><nd ref="4"/><nd ref="1"/>
    <tag k="building" v="yes"/>
  </way>
</osm>
```

`packages/gmnspy/tests/fixtures/osm/tiny_overpass.json`:

```json
{
  "version": 0.6,
  "generator": "gmnspy-tests (hand-written fixture, not real OSM data)",
  "elements": [
    {"type": "node", "id": 1, "lat": 42.000, "lon": -71.000},
    {"type": "node", "id": 2, "lat": 42.001, "lon": -71.000},
    {"type": "node", "id": 3, "lat": 42.002, "lon": -71.000},
    {"type": "node", "id": 4, "lat": 42.002, "lon": -71.002},
    {"type": "way", "id": 100, "nodes": [1, 2, 3], "tags": {"highway": "residential", "name": "Main St"}},
    {"type": "way", "id": 101, "nodes": [3, 4], "tags": {"highway": "footway"}},
    {"type": "way", "id": 102, "nodes": [4, 99], "tags": {"highway": "residential"}},
    {"type": "way", "id": 103, "nodes": [1, 2, 4, 1], "tags": {"building": "yes"}}
  ]
}
```

- [ ] **Step 2: Write the failing tests in `packages/gmnspy/tests/test_osm_local.py`**

```python
"""Tests for gmnspy.osm.local + build_network_from_osm_file (local files only, no network)."""

import logging
from pathlib import Path

import pytest
from gmnspy.osm import build_network_from_osm_file
from gmnspy.osm.local import read_osm_file

OSM_DIR = Path(__file__).resolve().parent / "fixtures" / "osm"
OSM_XML = OSM_DIR / "tiny.osm"
OVERPASS_JSON = OSM_DIR / "tiny_overpass.json"


@pytest.mark.parametrize("path", [OSM_XML, OVERPASS_JSON], ids=["xml", "json"])
def test_reads_nodes_and_filters_ways_for_drive(path, caplog):
    with caplog.at_level(logging.WARNING, logger="gmnspy.osm.local"):
        nodes, ways = read_osm_file(path, network_type="drive")
    assert nodes == {1: (-71.0, 42.0), 2: (-71.0, 42.001), 3: (-71.0, 42.002), 4: (-71.002, 42.002)}
    assert [w["id"] for w in ways] == [100]  # footway filtered, incomplete 102 dropped, building 103 not a highway
    assert ways[0] == {"id": 100, "nodes": [1, 2, 3], "tags": {"highway": "residential", "name": "Main St"}}
    assert "dropped 1 way(s)" in caplog.text


@pytest.mark.parametrize("path", [OSM_XML, OVERPASS_JSON], ids=["xml", "json"])
def test_all_keeps_every_highway_but_not_buildings(path):
    _, ways = read_osm_file(path, network_type="all")
    assert [w["id"] for w in ways] == [100, 101]


def test_unsupported_suffix(tmp_path):
    with pytest.raises(ValueError, match="unsupported OSM file"):
        read_osm_file(tmp_path / "x.pbf")


def test_json_without_elements(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text('{"features": []}')
    with pytest.raises(ValueError, match="not an Overpass JSON export"):
        read_osm_file(bad)


def test_malformed_xml(tmp_path):
    bad = tmp_path / "x.osm"
    bad.write_text("<osm><node id='1'")
    with pytest.raises(ValueError, match="could not parse"):
        read_osm_file(bad)


def test_unknown_network_type():
    with pytest.raises(ValueError, match="unknown network_type"):
        read_osm_file(OSM_XML, network_type="boat")


def test_build_from_file_makes_links_both_ways():
    net = build_network_from_osm_file(OSM_XML)
    links = net.links.to_pandas()
    assert sorted(zip(links.from_node_id, links.to_node_id, strict=True)) == [(1, 3), (3, 1)]
    assert set(links.name) == {"Main St"} and set(links.osm_way_id) == {100}


def test_build_from_file_with_no_matching_ways(tmp_path):
    only_foot = tmp_path / "foot.json"
    only_foot.write_text(
        '{"elements": [{"type": "node", "id": 1, "lat": 0, "lon": 0}, {"type": "node", "id": 2, "lat": 0, "lon": 1},'
        ' {"type": "way", "id": 9, "nodes": [1, 2], "tags": {"highway": "footway"}}]}'
    )
    with pytest.raises(ValueError, match=r"no OSM ways in foot\.json"):
        build_network_from_osm_file(only_foot)
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_osm_local.py -q`
Expected: collection error, `ImportError: cannot import name 'build_network_from_osm_file' from 'gmnspy.osm'`.

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/osm/local.py`**

```python
"""Read a local OSM extract (``.osm`` XML or an Overpass JSON export) into the ``(nodes, ways)`` contract.

The Overpass path filters ``highway`` ways on the server; a local file holds whatever its exporter
kept, so this reader applies the same ``network_type`` allow-list itself via
:func:`gmnspy.osm.tags.accepts_highway`, and keeps only ways that carry a ``highway`` tag.

Ways that reference a node missing from the file (typical where an extract cuts a road at its
edge) are dropped, with one warning naming how many, rather than failing the whole import.

Stdlib only (``xml.etree.ElementTree.iterparse`` + ``json``): no new dependency. ``.pbf`` is not
supported yet.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import tags
from .query import parse_overpass_elements

__all__ = ["SUPPORTED_SUFFIXES", "read_osm_file"]

logger = logging.getLogger(__name__)

#: File suffixes :func:`read_osm_file` understands.
SUPPORTED_SUFFIXES = (".osm", ".json")


def _parse_xml(path: Path) -> tuple[dict[int, tuple[float, float]], list[dict[str, Any]]]:
    nodes: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for _event, elem in ET.iterparse(path, events=("end",)):
        if elem.tag == "node":
            nodes[int(elem.attrib["id"])] = (float(elem.attrib["lon"]), float(elem.attrib["lat"]))
            elem.clear()
        elif elem.tag == "way":
            ways.append(
                {
                    "id": int(elem.attrib["id"]),
                    "nodes": [int(nd.attrib["ref"]) for nd in elem.iter("nd")],
                    "tags": {t.attrib["k"]: t.attrib["v"] for t in elem.iter("tag")},
                }
            )
            elem.clear()
    return nodes, ways


def _parse_json(path: Path) -> tuple[dict[int, tuple[float, float]], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise ValueError(f"{path} is not an Overpass JSON export (no top-level 'elements' list)")
    return parse_overpass_elements(data["elements"])


def read_osm_file(
    path: str | Path, *, network_type: str = "drive"
) -> tuple[dict[int, tuple[float, float]], list[dict[str, Any]]]:
    """Read ``path`` and return ``(nodes, ways)`` for :func:`gmnspy.osm.convert.build_node_link_tables`.

    Args:
        path: An ``.osm`` XML file or an Overpass ``[out:json]`` export (``.json``).
        network_type: One of the keys in ``osm_network_filters.yaml`` (``drive``/``walk``/``bike``/``all``).

    Returns:
        ``(nodes, ways)``: ``{osm_node_id: (lon, lat)}`` for every node in the file, and the
        ``{"id", "nodes", "tags"}`` ways that pass the ``network_type`` filter and are complete.

    Raises:
        ValueError: Unsupported suffix, malformed content, or unknown ``network_type``.
        FileNotFoundError: ``path`` does not exist.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported OSM file {path.name!r}; expected one of {', '.join(SUPPORTED_SUFFIXES)}")
    try:
        nodes, ways = _parse_xml(path) if suffix == ".osm" else _parse_json(path)
    except (ET.ParseError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"could not parse {path.name}: {exc}") from exc
    tags.allowed_highways(network_type)  # fail fast on an unknown network_type, even for an empty file
    kept = [w for w in ways if "highway" in w["tags"] and tags.accepts_highway(network_type, w["tags"]["highway"])]
    complete = [w for w in kept if all(n in nodes for n in w["nodes"])]
    if len(complete) < len(kept):
        logger.warning(
            "%s: dropped %d way(s) that reference nodes missing from the file", path.name, len(kept) - len(complete)
        )
    return nodes, complete
```

- [ ] **Step 5: Add `build_network_from_osm_file` to `packages/gmnspy/gmnspy/osm/build.py`**

Add `from pathlib import Path` to the imports. Change `from . import convert, query` to
`from . import convert, local, query`. Change `__all__` to
`["build_network_from_osm", "build_network_from_osm_file", "network_from_records"]`. Then append:

```python
def build_network_from_osm_file(
    path: str | Path,
    *,
    network_type: str = "drive",
    extra_tags: list[str] | None = None,
    spec_version: str = DEFAULT_SPEC,
    engine: Any = None,
) -> Network:
    """Build a GMNS network from a local ``.osm`` XML file or Overpass JSON export (no network access).

    Args:
        path: The local OSM file (see :func:`gmnspy.osm.local.read_osm_file` for formats).
        network_type: One of ``drive``/``walk``/``bike``/``all``; applied locally to the ``highway`` tag.
        extra_tags: OSM tag keys to carry onto each link as extra columns.
        spec_version: GMNS spec version (default :data:`gmnspy.spec.DEFAULT_SPEC`).
        engine: Engine to materialise through (default: datagrove ibis).

    Returns:
        A populated :class:`~gmnspy.network.Network`.

    Raises:
        ValueError: Unsupported/malformed file, or no ways match ``network_type``.
    """
    nodes, ways = local.read_osm_file(path, network_type=network_type)
    node_records, link_records = convert.build_node_link_tables(nodes, ways, extra_tags=extra_tags)
    if not link_records:
        raise ValueError(f"no OSM ways in {Path(path).name} matched network_type={network_type!r}")
    return network_from_records(node_records, link_records, spec_version=spec_version, engine=engine)
```

- [ ] **Step 6: Expose it lazily in `packages/gmnspy/gmnspy/osm/__init__.py`**

Make three edits:
- In the `TYPE_CHECKING` block, import `build_network_from_osm_file` alongside `build_network_from_osm`.
- Add `"build_network_from_osm_file",` to `__all__`, after `"build_network_from_osm",`.
- In `__getattr__`, change the name set to `{"build_network_from_osm", "build_network_from_osm_file", "network_from_records"}`.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_osm_local.py packages/gmnspy/tests/test_osm_build.py -q`
Expected: all pass (`test_osm_local.py`: `10 passed`).

- [ ] **Step 8: Commit**

```bash
git add packages/gmnspy/gmnspy/osm/local.py packages/gmnspy/gmnspy/osm/build.py packages/gmnspy/gmnspy/osm/__init__.py \
  packages/gmnspy/tests/fixtures/osm packages/gmnspy/tests/test_osm_local.py
git commit -m "feat(osm): read local .osm XML / Overpass JSON with the highway filter applied locally"
```

---

### Task 6: Count Overture segments with the read's own predicate

**Files:**
- Modify: `packages/gmnspy/gmnspy/overture/query.py`
- Test: `packages/gmnspy/tests/test_overture_query.py`

- [ ] **Step 1: Append the failing tests to `packages/gmnspy/tests/test_overture_query.py`**

```python
class TestCountSegments:
    def test_count_matches_read(self, engine):
        n = query.count_segments(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine)
        assert n > 0
        assert n == len(query.read_segments(WORLD_BBOX, network_type="drive", data_root=FIXTURE_ROOT, engine=engine))

    def test_empty_bbox_counts_zero(self, engine):
        assert query.count_segments((10.0, 10.0, 11.0, 11.0), data_root=FIXTURE_ROOT, engine=engine) == 0
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_overture_query.py -q -k Count`
Expected: `2 failed`, `AttributeError: module 'gmnspy.overture.query' has no attribute 'count_segments'`.

- [ ] **Step 3: Implement in `packages/gmnspy/gmnspy/overture/query.py`**

Add `"count_segments",` to `__all__`, after `"OVERTURE_RELEASE",`. Insert these two functions directly above
`def read_segments(`:

```python
def _matching_segments(
    bbox: tuple[float, float, float, float],
    network_type: str,
    overture_release: str,
    data_root: str | None,
    engine: Any,
) -> Any:
    """The lazy ibis table of road segments in ``bbox`` allowed for ``network_type`` (bbox + class pushed down)."""
    source = _type_source(overture_data_root(overture_release, data_root), "segment")
    _prepare_backend(engine, source)
    table = engine.read_parquet(source, hive_partitioning=source.endswith("/*"))
    available = set(table.columns)
    predicate = _bbox_intersects(table, bbox)
    if "subtype" in available:
        predicate = predicate & (table.subtype == _ROAD_SUBTYPE)
    allowed = attrs.allowed_classes(network_type)
    if allowed and "class" in available:
        predicate = predicate & table["class"].isin(sorted(allowed))
    return table.filter(predicate)


def count_segments(
    bbox: tuple[float, float, float, float],
    *,
    network_type: str = "drive",
    overture_release: str = OVERTURE_RELEASE,
    data_root: str | None = None,
    engine: Any = None,
) -> int:
    """Count the road segments :func:`read_segments` would return, without reading their geometry.

    The same bbox + ``class`` predicates as the read, so it is the cheap pre-query the workbench's
    build estimate sizes a request with.

    Args:
        bbox: ``(west, south, east, north)`` in EPSG:4326.
        network_type: One of ``drive``/``walk``/``bike``/``all``.
        overture_release: Pinned release string (ignored when ``data_root`` set).
        data_root: Override base URI (Azure mirror / local snapshot dir).
        engine: Compute engine (default: datagrove ibis/duckdb).

    Returns:
        The number of matching segments.
    """
    return int(
        _matching_segments(bbox, network_type, overture_release, data_root, engine or get_engine()).count().execute()
    )
```

In `read_segments`, replace the predicate-building block:

```python
    engine = engine or get_engine()
    root = overture_data_root(overture_release, data_root)
    source = _type_source(root, "segment")
    _prepare_backend(engine, source)

    table = engine.read_parquet(source, hive_partitioning=source.endswith("/*"))
    available = set(table.columns)
    predicate = _bbox_intersects(table, bbox)
    if "subtype" in available:
        predicate = predicate & (table.subtype == _ROAD_SUBTYPE)
    allowed = attrs.allowed_classes(network_type)
    if allowed and "class" in available:
        predicate = predicate & table["class"].isin(sorted(allowed))
    filtered = table.filter(predicate)
```

with:

```python
    filtered = _matching_segments(bbox, network_type, overture_release, data_root, engine or get_engine())
    available = set(filtered.columns)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_overture_query.py packages/gmnspy/tests/test_overture_build.py -q`
Expected: all pass (`test_overture_query.py`: `14 passed`). The build tests prove `read_segments` is unchanged.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/overture/query.py packages/gmnspy/tests/test_overture_query.py
git commit -m "feat(overture): count_segments, sharing the bbox+class predicate with read_segments"
```

---

### Task 7: Overpass `out count` and multi-candidate place search

**Files:**
- Modify: `packages/gmnspy/gmnspy/osm/query.py`
- Test: `packages/gmnspy/tests/test_osm_query.py`

- [ ] **Step 1: Append the failing tests to `packages/gmnspy/tests/test_osm_query.py`**

They reuse that file's `_FakeSession`, `_FakeResponse` and `_NO_SLEEP` helpers.

```python
class TestCountQuery:
    def test_count_query_counts_ways_without_recursing(self):
        q = query.build_overpass_query(bbox=(-71.1, 42.0, -71.0, 42.1), network_type="drive", out="count")
        assert q.endswith("(42.0,-71.1,42.1,-71.0);out count;")
        assert "(._;>;)" not in q

    def test_body_is_still_the_default(self):
        assert query.build_overpass_query(bbox=(-71.1, 42.0, -71.0, 42.1)).endswith("(._;>;);out body;")


_DURHAM = {
    "display_name": "Durham, Durham County, North Carolina, United States",
    "type": "administrative",
    "boundingbox": ["35.86", "36.14", "-79.01", "-78.75"],
    "geojson": {"type": "Polygon", "coordinates": [[[-79.0, 35.9], [-78.8, 35.9], [-78.8, 36.1], [-79.0, 35.9]]]},
}
_DURHAM_ST = {"display_name": "Durham Street", "type": "residential", "boundingbox": ["1", "2", "3", "4"]}


class TestGeocodeCandidates:
    def test_returns_every_hit_with_bbox_and_outline(self):
        session = _FakeSession([_FakeResponse(200, [_DURHAM, _DURHAM_ST, {"display_name": "no bbox"}])])
        got = query.geocode_candidates("Durham", session=session, sleep=_NO_SLEEP)
        assert [c["display_name"] for c in got] == [_DURHAM["display_name"], "Durham Street"]
        assert got[0]["bbox"] == (-79.01, 35.86, -78.75, 36.14)
        assert got[0]["polygon"][0] == (35.9, -79.0)  # (lat, lon), like geocode_area
        assert got[1]["polygon"] is None and got[1]["type"] == "residential"

    def test_sends_limit_and_simplification(self):
        session = _FakeSession([_FakeResponse(200, [])])
        assert query.geocode_candidates("nowhere", limit=3, session=session, sleep=_NO_SLEEP) == []
        _method, _url, params = session.calls[0]
        assert params["limit"] == 3 and params["polygon_threshold"] == 0.001 and params["polygon_geojson"] == 1
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_osm_query.py -q`
Expected: `3 failed, 20 passed`. The failures are:
- `TypeError: build_overpass_query() got an unexpected keyword argument 'out'`;
- `AttributeError: ... 'geocode_candidates'` (twice).

- [ ] **Step 3: Add `out=` to `build_overpass_query`**

In `packages/gmnspy/gmnspy/osm/query.py`:
- Change `from typing import Any` to `from typing import Any, Literal`.
- Add `"geocode_candidates",` to `__all__`, after `"geocode_area",`.
- Add a keyword parameter after `timeout: int = 180,`:

```python
    out: Literal["body", "count"] = "body",
```

In its docstring, replace:

```text
    The query recurses to member nodes (``(._;>;)``) so whole ways are
    returned.
```

with:

```text
    With ``out="body"`` the query recurses to member nodes (``(._;>;)``) so
    whole ways are returned; ``out="count"`` asks only for the number of
    matching ways (one ``count`` element), the cheap pre-query a build
    estimate uses.
```

and add this line to its `Args:` section, after `timeout`:

```text
        out: ``"body"`` for the full ways + nodes, ``"count"`` for the way count only.
```

Replace its final `return` with:

```python
    if out == "count":
        return f"[out:json][timeout:{timeout}];way{way_filter}{area_filter};out count;"
    return f"[out:json][timeout:{timeout}];way{way_filter}{area_filter};(._;>;);out body;"
```

- [ ] **Step 4: Add `geocode_candidates` directly above `def resolve_area(`**

`geocode_area` is left as it is.

```python
def geocode_candidates(
    q: str,
    *,
    limit: int = 8,
    base_url: str = NOMINATIM_URL,
    session: Any = None,
    user_agent: str = USER_AGENT,
    timeout: int = 30,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    polygon_threshold: float = 0.001,
) -> list[dict[str, Any]]:
    """Search Nominatim and return up to ``limit`` candidate areas for the user to choose from.

    Unlike :func:`geocode_area` (first hit only, raises on a miss), this returns every hit that has a
    bounding box, in Nominatim's ranking order, and an empty list on a miss. Outlines are simplified
    server-side (``polygon_threshold``, in degrees) so they stay small enough to preview and to store
    on a recorded action.

    Args:
        q: Free-text place query.
        limit: Maximum number of candidates (Nominatim caps this at 40).
        base_url: Nominatim search endpoint.
        session: An object exposing ``get(url, params, headers, timeout)``. Defaults to :mod:`requests`.
        user_agent: ``User-Agent`` header value (required by Nominatim policy).
        timeout: Per-request timeout, seconds.
        retries: Number of retries on transient status codes.
        sleep: Sleep function used between retries (injectable for tests).
        polygon_threshold: Outline simplification tolerance, degrees (``0.001`` is roughly 100 m).

    Returns:
        ``[{"display_name", "type", "bbox": (west, south, east, north), "polygon": [(lat, lon), ...] | None}]``.
    """
    http = session or requests
    params = {
        "q": q,
        "format": "json",
        "polygon_geojson": 1,
        "polygon_threshold": polygon_threshold,
        "limit": limit,
    }
    response = _with_retry(
        lambda: http.get(base_url, params=params, headers={"User-Agent": user_agent}, timeout=timeout),
        retries=retries,
        sleep=sleep,
    )
    candidates = []
    for hit in response.json():
        if "boundingbox" not in hit:
            continue
        south, north, west, east = (float(v) for v in hit["boundingbox"])
        geojson = hit.get("geojson")
        candidates.append(
            {
                "display_name": hit.get("display_name", ""),
                "type": hit.get("type", ""),
                "bbox": (west, south, east, north),
                "polygon": _geojson_to_latlon(geojson) if geojson else None,
            }
        )
    return candidates
```

- [ ] **Step 5: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_osm_query.py -q`
Expected: `23 passed`.

- [ ] **Step 6: Commit**

```bash
git add packages/gmnspy/gmnspy/osm/query.py packages/gmnspy/tests/test_osm_query.py
git commit -m "feat(osm): Overpass out-count query and multi-candidate geocode_candidates"
```

---

### Task 8: Credential source names and the URL check

**Files:**
- Modify: `packages/datagrove/datagrove/io/credentials.py`
- Test: `packages/datagrove/tests/io/test_credentials.py`
- Create: `packages/gmnspy/gmnspy/workbench/urlcheck.py`
- Test: `packages/gmnspy/tests/test_workbench_urlcheck.py`

- [ ] **Step 1: Write the failing tests**

Append to `packages/datagrove/tests/io/test_credentials.py`:

```python
# ---------------------------------------------------------------------------
# credential_source: names the layer, never the value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "keyring_value", "netrc_value", "expected"),
    [
        ({"token": "t"}, {"token": "k"}, {"username": "u"}, "env"),
        ({}, {"token": "k"}, {"username": "u"}, "keyring"),
        ({}, {}, {"username": "u", "password": "p"}, "netrc"),
        ({}, {}, {}, "none"),
    ],
)
def test_credential_source_names_the_first_layer(
    monkeypatch: pytest.MonkeyPatch, env: dict, keyring_value: dict, netrc_value: dict, expected: str
) -> None:
    from datagrove.io import credentials as creds_mod

    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: env)
    monkeypatch.setattr(creds_mod, "_lookup_keyring", lambda host: keyring_value)
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: netrc_value)
    assert creds_mod.credential_source("data.example.com") == expected
```

Create `packages/gmnspy/tests/test_workbench_urlcheck.py`. It uses an in-memory filesystem, so it never touches
the network:

```python
"""Tests for the wizard's URL check (in-memory filesystem; never touches the network)."""

import uuid

import pytest
from datagrove.io import credentials as creds_mod
from fsspec.implementations.memory import MemoryFileSystem
from gmnspy.workbench.urlcheck import check_url


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_keyring", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: {})


@pytest.fixture
def memfs():
    fs, root = MemoryFileSystem(), f"/wbcheck-{uuid.uuid4().hex}"
    fs.pipe({f"{root}/net/link.parquet": b"x", f"{root}/net/node.parquet": b"x", f"{root}/net/notes.txt": b"x"})
    fs.pipe({f"{root}/net.zip": b"x"})
    yield fs, root
    fs.rm(root, recursive=True)


def _factory(fs, path, seen=None):
    def url_to_fs(url, **storage_options):
        if seen is not None:
            seen.append(storage_options)
        return fs, path

    return url_to_fs


def test_folder_lists_tables(memfs):
    fs, root = memfs
    report = check_url("s3://bucket/net", url_to_fs=_factory(fs, f"{root}/net"))
    assert report["reachable"] and report["kind"] == "folder" and report["tables"] == ["link", "node"]
    assert report["credential_source"] == "none" and report["error"] is None


def test_file_has_no_tables(memfs):
    fs, root = memfs
    report = check_url("https://example.org/net.zip", url_to_fs=_factory(fs, f"{root}/net.zip"))
    assert report["reachable"] and report["kind"] == "file" and report["tables"] == []


def test_missing_is_unreachable(memfs):
    fs, root = memfs
    report = check_url("s3://bucket/gone", url_to_fs=_factory(fs, f"{root}/gone"))
    assert report["reachable"] is False and report["error"] == "not found"


def test_reports_source_name_never_the_secret(memfs, monkeypatch):
    fs, root = memfs
    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: {"token": "s3cr3t"})
    seen: list[dict] = []
    report = check_url("s3://bucket/net", url_to_fs=_factory(fs, f"{root}/net", seen))
    assert report["credential_source"] == "env"
    assert seen == [{"token": "s3cr3t"}]  # the secret goes to the filesystem...
    assert "s3cr3t" not in repr(report)  # ...and never into the report


def test_unsupported_scheme():
    report = check_url("ftp://example.org/net")
    assert report["reachable"] is False and "unsupported URL scheme" in report["error"]


def test_backend_error_is_reported_not_raised():
    def boom(url, **_):
        raise PermissionError("access denied")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False and report["error"] == "PermissionError: access denied"
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/datagrove/tests/io/test_credentials.py packages/gmnspy/tests/test_workbench_urlcheck.py -q`
Expected:
- `4 failed`: `AttributeError: module 'datagrove.io.credentials' has no attribute 'credential_source'`;
- a collection error: `ModuleNotFoundError: No module named 'gmnspy.workbench.urlcheck'`.

- [ ] **Step 3: Add `credential_source` to `packages/datagrove/datagrove/io/credentials.py`**

Change `__all__` to `["credential_source", "resolve_credentials"]`. Then insert directly above the
`# Layer helpers` banner comment:

```python
def credential_source(host: str) -> str:
    """Name the cascade layer that would supply credentials for ``host``, never the values.

    Walks the same env → keyring → netrc order as :func:`resolve_credentials`
    (there is no ``explicit`` layer: callers that pass one already know).
    Safe to show in a UI ("credentials from: env").

    Args:
        host: Network host (port suffixes are ignored, as in the resolver).

    Returns:
        ``"env"``, ``"keyring"``, ``"netrc"``, or ``"none"``.

    Examples:
        >>> credential_source("no.such.host.example")
        'none'
    """
    if _lookup_env(_sanitize_host(host)):
        return "env"
    if _lookup_keyring(host):
        return "keyring"
    if _lookup_netrc(host):
        return "netrc"
    return "none"
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/urlcheck.py`**

```python
"""The wizard's URL **Check**: is a remote GMNS source reachable, which credential layer applies, what's in it.

Read-only and never records an action. It reports the *name* of the credential source
(``env``/``keyring``/``netrc``/``none``, from :func:`datagrove.io.credentials.credential_source`),
never a credential value, and lists table names only (no data is read).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import fsspec
from datagrove.io.credentials import credential_source, resolve_credentials

__all__ = ["REMOTE_SCHEMES", "check_url"]

logger = logging.getLogger(__name__)

#: URL schemes the wizard accepts for "GMNS at a URL" (the datagrove remote adapter's schemes).
REMOTE_SCHEMES = ("http", "https", "s3", "gs", "gcs", "az", "abfs", "abfss")

_TABLE_SUFFIXES = (".csv", ".parquet")


def _tables(fs: Any, path: str) -> list[str]:
    names = (PurePosixPath(str(p)).name for p in fs.ls(path, detail=False))
    return sorted({n.split(".", 1)[0] for n in names if n.lower().endswith(_TABLE_SUFFIXES)})


def check_url(url: str, *, url_to_fs: Callable[..., tuple[Any, str]] = fsspec.core.url_to_fs) -> dict[str, Any]:
    """Probe ``url`` and describe it for the wizard.

    Args:
        url: An ``http(s)``/``s3``/``gs``/``az``/... URL to a GMNS folder or file.
        url_to_fs: ``fsspec.core.url_to_fs``-compatible factory (injectable for tests).

    Returns:
        ``{"url", "reachable", "credential_source", "kind", "tables", "error"}`` where ``kind`` is
        ``"folder"``, ``"file"``, or ``None`` when unreachable, and ``tables`` lists the table names
        found directly inside a folder (``link``, ``node``, ...).
    """
    parts = urlsplit(url)
    report: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "credential_source": "none",
        "kind": None,
        "tables": [],
        "error": None,
    }
    if parts.scheme.lower() not in REMOTE_SCHEMES:
        report["error"] = f"unsupported URL scheme {parts.scheme!r}; use one of {', '.join(REMOTE_SCHEMES)}"
        return report
    report["credential_source"] = credential_source(parts.netloc)
    try:
        fs, path = url_to_fs(url, **resolve_credentials(parts.netloc))
        if not fs.exists(path):
            report["error"] = "not found"
            return report
        report["reachable"] = True
        if fs.isdir(path):
            report["kind"], report["tables"] = "folder", _tables(fs, path)
        else:
            report["kind"] = "file"
    except ImportError as exc:
        report["error"] = f"missing filesystem support for {parts.scheme}:// ({exc})"
    except Exception as exc:  # boundary: any remote failure is reported to the user, not raised
        logger.info("check_url %s failed: %s", parts.netloc, type(exc).__name__)
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report
```

- [ ] **Step 5: Run the tests (including the new doctest)**

Run: `uv run --all-extras pytest packages/datagrove/tests/io/test_credentials.py packages/datagrove/datagrove/io/credentials.py packages/gmnspy/tests/test_workbench_urlcheck.py -q`
Expected: all pass (`19` credential tests, `2` doctests, `6` URL-check tests).

- [ ] **Step 6: Commit**

```bash
git add packages/datagrove/datagrove/io/credentials.py packages/datagrove/tests/io/test_credentials.py \
  packages/gmnspy/gmnspy/workbench/urlcheck.py packages/gmnspy/tests/test_workbench_urlcheck.py
git commit -m "feat: credential_source (layer name only) + workbench URL check"
```

---

### Task 9: The `Area` union

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/area.py`
- Test: `packages/gmnspy/tests/test_workbench_area.py`

- [ ] **Step 1: Write the failing tests in `packages/gmnspy/tests/test_workbench_area.py`**

```python
"""Tests for the build Area union."""

import pytest
from gmnspy.osm.query import point_buffer_bbox
from gmnspy.workbench.area import Area, BboxArea, PlaceArea, PointArea
from pydantic import TypeAdapter, ValidationError

AREA = TypeAdapter(Area)


def test_discriminates_on_kind():
    assert isinstance(AREA.validate_python({"kind": "bbox", "bbox": [-79, 35, -78, 36]}), BboxArea)
    assert isinstance(AREA.validate_python({"kind": "point", "lat": 35.9, "lon": -78.9, "buffer_m": 500}), PointArea)
    with pytest.raises(ValidationError):
        AREA.validate_python({"kind": "county", "name": "Durham"})


def test_bbox_must_be_ordered_and_in_range():
    assert BboxArea(bbox=(-79, 35, -78, 36)).to_bbox() == (-79, 35, -78, 36)
    with pytest.raises(ValidationError, match="west<east"):
        BboxArea(bbox=(-78, 35, -79, 36))
    with pytest.raises(ValidationError):
        BboxArea(bbox=(-79, 35, -78, 91))


def test_point_bbox_matches_the_osm_builder():
    area = PointArea(lat=35.9, lon=-78.9, buffer_m=800)
    assert area.to_bbox() == pytest.approx(point_buffer_bbox(35.9, -78.9, 800))
    assert area.to_polygon() is None
    with pytest.raises(ValidationError):
        PointArea(lat=35.9, lon=-78.9, buffer_m=0)


def test_place_keeps_polygon_for_overpass():
    ring = [(35.9, -79.0), (35.9, -78.8), (36.1, -78.8), (35.9, -79.0)]
    area = PlaceArea(name="Durham", bbox=(-79.01, 35.86, -78.75, 36.14), polygon=ring)
    assert area.to_bbox() == (-79.01, 35.86, -78.75, 36.14) and area.to_polygon() == ring
    with pytest.raises(ValidationError, match="at least 3"):
        PlaceArea(name="x", bbox=(-79, 35, -78, 36), polygon=[(35, -79)])
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_area.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.workbench.area'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/area.py`**

```python
"""Build areas: the one shape every Area-step tab (draw, coordinates, place) produces.

``Area`` is a discriminated union on ``kind``. Every variant reduces to one
``(west, south, east, north)`` bbox (EPSG:4326) for preview, estimate, and the
Overture read; a place may also carry its (simplified) boundary polygon, which
the OSM build passes to Overpass. Storing the resolved bbox/polygon on the
action (rather than the place name alone) keeps a replay from re-geocoding.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["Area", "BboxArea", "PlaceArea", "PointArea"]

BBox = tuple[float, float, float, float]
#: Metres per degree of latitude (the same spherical approximation the OSM/Overture builders use).
_M_PER_DEG_LAT = 111320.0


def _check_bbox(bbox: BBox) -> BBox:
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(f"bbox must be (west, south, east, north) with west<east and south<north, got {bbox}")
    return bbox


class _Area(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_bbox(self) -> BBox:
        """The area's ``(west, south, east, north)`` bbox."""
        raise NotImplementedError

    def to_polygon(self) -> list[tuple[float, float]] | None:
        """Boundary as ``(lat, lon)`` vertices, or ``None`` when the bbox is the whole area."""
        return None


class BboxArea(_Area):
    """A rectangle, drawn on the map or typed as ``W,S,E,N``."""

    kind: Literal["bbox"] = "bbox"
    bbox: BBox

    @model_validator(mode="after")
    def _valid(self) -> BboxArea:
        _check_bbox(self.bbox)
        return self

    def to_bbox(self) -> BBox:
        """The rectangle itself."""
        return self.bbox


class PointArea(_Area):
    """A centre point plus a buffer (metres) on every side."""

    kind: Literal["point"] = "point"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    buffer_m: float = Field(gt=0)

    def to_bbox(self) -> BBox:
        """The square ``buffer_m`` out from the point (``gmnspy.osm.query.point_buffer_bbox`` maths)."""
        dlat = self.buffer_m / _M_PER_DEG_LAT
        cos_lat = math.cos(math.radians(self.lat))
        dlon = self.buffer_m / (_M_PER_DEG_LAT * cos_lat) if cos_lat else dlat
        return (self.lon - dlon, self.lat - dlat, self.lon + dlon, self.lat + dlat)


class PlaceArea(_Area):
    """A geocoded place chosen from the candidate list: its name, bbox, and optional outline."""

    kind: Literal["place"] = "place"
    name: str = Field(min_length=1)
    bbox: BBox
    polygon: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def _valid(self) -> PlaceArea:
        _check_bbox(self.bbox)
        if self.polygon is not None and len(self.polygon) < 3:
            raise ValueError("a place polygon needs at least 3 vertices")
        return self

    def to_bbox(self) -> BBox:
        """The place's bounding box."""
        return self.bbox

    def to_polygon(self) -> list[tuple[float, float]] | None:
        """The place outline as ``(lat, lon)`` vertices (what Overpass ``poly:`` expects), if known."""
        return self.polygon


Area = Annotated[BboxArea | PointArea | PlaceArea, Field(discriminator="kind")]
```

- [ ] **Step 4: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_area.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/area.py packages/gmnspy/tests/test_workbench_area.py
git commit -m "feat(workbench): Area union (bbox / point+buffer / place with polygon)"
```

---

### Task 10: The build estimate, its data file, and `ApprovalRequired`

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/data/build_cost.toml`
- Create: `packages/gmnspy/gmnspy/workbench/extras.py`
- Create: `packages/gmnspy/gmnspy/workbench/estimate.py`
- Modify: `packages/gmnspy/gmnspy/workbench/errors.py` (add `ApprovalRequired`)
- Modify: `packages/gmnspy/pyproject.toml` (ship the data file in the wheel)
- Test: `packages/gmnspy/tests/test_workbench_estimate.py`

- [ ] **Step 1: Write the failing tests in `packages/gmnspy/tests/test_workbench_estimate.py`**

The last test is the opt-in calibration path. It is skipped unless `GMNSPY_CALIBRATE=1`, and it is the only test
in this plan that touches the network.

```python
"""Tests for the build estimate: pre-query counts (faked HTTP / local fixture) and the cost model."""

import os
import time
from pathlib import Path

import pytest
from datagrove.engines.ibis_engine import IbisEngine
from gmnspy.workbench.area import BboxArea, PlaceArea
from gmnspy.workbench.estimate import (
    Estimate,
    count_osm,
    count_overture,
    estimate_build,
    fit_s_per_link,
    load_coefficients,
    needs_approval,
)

OVERTURE_DIR = str(Path(__file__).resolve().parent / "fixtures" / "overture")


class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


class _Http:
    def __init__(self, payload):
        self.payload, self.posts = payload, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append(data)
        return _Resp(self.payload)


_COUNT = {"elements": [{"type": "count", "id": 0, "tags": {"nodes": "0", "ways": "1234", "total": "1234"}}]}


def test_coefficients_cover_every_source_and_format():
    coeffs = load_coefficients()
    assert set(coeffs["sources"]) == {"osm", "overture", "osm_file", "overture_file"}
    for model in coeffs["sources"].values():
        assert {"latency_s", "links_per_element", "s_per_link"} <= set(model)
    for table in ("bytes_per_link", "fixed_bytes"):
        assert set(coeffs["output"][table]) == {"parquet", "csv", "duckdb", "zip"}


def test_seed_reproduces_the_one_measured_run():
    """~269k links in ~27 s (RDU metro): the seeded rate must reproduce it, latency aside."""
    osm = load_coefficients()["sources"]["osm"]
    assert 269_000 * osm["s_per_link"] == pytest.approx(27, rel=0.05)


def test_estimate_build_is_linear():
    coeffs = {
        "sources": {"osm": {"latency_s": 2.0, "links_per_element": 2.0, "s_per_link": 0.5}},
        "output": {"bytes_per_link": {"csv": 10}, "fixed_bytes": {"csv": 100}},
    }
    est = estimate_build("osm", 3, output_format="csv", coefficients=coeffs)
    assert est == Estimate(seconds=5.0, out_bytes=160, n_elements=3, basis=est.basis)
    assert "3 ways" in est.basis and "~6 links" in est.basis


def test_round_trips_through_dict():
    est = estimate_build("overture", 500)
    assert Estimate(**est.to_dict()) == est


@pytest.mark.parametrize(("seconds", "expected"), [(None, True), (89.0, False), (90.0, False), (90.5, True)], ids=str)
def test_needs_approval(seconds, expected):
    assert needs_approval(Estimate(seconds=seconds, out_bytes=None, n_elements=None, basis="x"), 90.0) is expected


def test_count_osm_uses_out_count_and_polygon():
    http = _Http(_COUNT)
    area = PlaceArea(name="x", bbox=(-79, 35, -78, 36), polygon=[(35.0, -79.0), (35.0, -78.0), (36.0, -78.0)])
    n = count_osm(area, network_type="drive", endpoint="https://overpass.test", http=http, user_agent="t")
    assert n == 1234
    assert http.posts[0].endswith("out count;") and 'poly:"35.0 -79.0 35.0 -78.0 36.0 -78.0"' in http.posts[0]


def test_count_osm_bbox():
    http = _Http(_COUNT)
    count_osm(BboxArea(bbox=(-79, 35, -78, 36)), network_type="all", endpoint="e", http=http, user_agent="t")
    assert '["highway"](35.0,-79.0,36.0,-78.0);out count;' in http.posts[0]


def test_count_overture_on_local_snapshot():
    engine = IbisEngine()
    try:
        bbox = (-0.5, -0.5, 0.5, 0.5)
        n = count_overture(bbox, network_type="drive", overture_release="x", data_root=OVERTURE_DIR, engine=engine)
    finally:
        engine.close()
    assert n > 0


def test_fit_s_per_link():
    assert fit_s_per_link([(100_000, 15.0), (200_000, 25.0)], latency_s=5.0) == pytest.approx(1e-4)
    with pytest.raises(ValueError, match="links > 0"):
        fit_s_per_link([], latency_s=1.0)


@pytest.mark.skipif(not os.environ.get("GMNSPY_CALIBRATE"), reason="opt-in live calibration (GMNSPY_CALIBRATE=1)")
def test_calibrate_osm_live(tmp_path):  # pragma: no cover - live network, run by hand
    """Time real OSM builds for a few bboxes and print a fitted ``s_per_link`` for data/build_cost.toml.

    Run from the repo root:
    ``GMNSPY_CALIBRATE=1 uv run --all-extras pytest packages/gmnspy/tests/test_workbench_estimate.py -k calibrate -s``
    """
    from gmnspy.osm import build_network_from_osm

    bboxes = [(-78.65, 35.77, -78.62, 35.80), (-78.70, 35.74, -78.60, 35.82)]  # downtown Raleigh, small to medium
    latency = load_coefficients()["sources"]["osm"]["latency_s"]
    samples = []
    for bbox in bboxes:
        start = time.perf_counter()
        net = build_network_from_osm(bbox)
        samples.append((int(net.links.count().execute()), time.perf_counter() - start))
    print(f"\nsamples (links, s): {samples}\nfitted s_per_link = {fit_s_per_link(samples, latency_s=latency):.3e}")
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_estimate.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.workbench.estimate'`.

- [ ] **Step 3: Create the maintained coefficients file `packages/gmnspy/gmnspy/workbench/data/build_cost.toml`**

```toml
# Build-cost model for the workbench's Open / Import wizard (gmnspy.workbench.estimate).
#
#   links   = n_elements * links_per_element
#   seconds = latency_s + links * s_per_link
#   bytes   = fixed_bytes[format] + links * bytes_per_link[format]
#
# n_elements is what the cheap pre-query returns for each source:
#   osm           ways matching the filter (Overpass `out count`)
#   overture      road segments in the bbox (DuckDB COUNT(*), same predicate as the read)
#   osm_file      size of the local .osm / .json file in bytes (no pre-query)
#   overture_file road segments in the local snapshot (COUNT(*))
#
# HONESTY NOTE: these numbers are seeded from ONE measured data point and some guesses.
#   * Measured: an OSM drive build of the RDU metro area produced ~269k links in ~27 s
#     (docs/design/benchmarking-suite-scope.md). That run used a cached Overpass extract,
#     so download time is NOT in it, and the time to write and re-open the output is not either.
#     s_per_link = 27 / 269_000 ~ 1.0e-4 is used for every source.
#   * Guessed, not measured: every latency_s, every links_per_element, and the Overture rates.
#   * Output sizes: measured on the 178-link RDU I-40 fixture, where fixed per-file overhead
#     dominates; expect real per-link sizes to be smaller.
# Re-fit with the opt-in calibration test (GMNSPY_CALIBRATE=1, see
# packages/gmnspy/tests/test_workbench_estimate.py) and replace these values.

[sources.osm]
latency_s = 5.0            # guess: Overpass queueing + transfer start
links_per_element = 2.5    # guess: ways split at intersections, x2 for two-way streets
s_per_link = 1.0e-4        # measured once (RDU metro, see above)

[sources.overture]
latency_s = 15.0           # guess: remote GeoParquet footer/row-group reads before any rows arrive
links_per_element = 1.6    # guess: segments split at connectors, two-way for most classes
s_per_link = 1.0e-4        # borrowed from OSM; not measured for Overture

[sources.osm_file]
latency_s = 1.0            # guess
links_per_element = 0.0015 # guess: roughly one link per ~700 bytes of OSM XML/JSON
s_per_link = 1.0e-4        # borrowed from OSM

[sources.overture_file]
latency_s = 1.0            # guess: local parquet, no network
links_per_element = 1.6    # same guess as overture
s_per_link = 1.0e-4        # borrowed from OSM

[output.bytes_per_link]    # measured on the RDU I-40 fixture (links + nodes files / links)
parquet = 200
csv = 320
duckdb = 300
zip = 110

[output.fixed_bytes]       # per-output overhead independent of size
parquet = 0
csv = 0
duckdb = 800000            # an empty DuckDB file is ~0.8 MB of preallocated blocks
zip = 0
```

Add it to the wheel. In `packages/gmnspy/pyproject.toml`, under `[tool.hatch.build.targets.wheel] include`,
directly after `"gmnspy/workbench/static/js/*.js",`, add:

```toml
    # Maintained build-cost coefficients for the Open / Import wizard's estimate.
    "gmnspy/workbench/data/*.toml",
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/extras.py`**

```python
"""Import an optional-extra module at runtime (``[osm]``, ``[overture]``), as a user-facing error if missing.

Runtime :func:`importlib.import_module` rather than a static import keeps the import-linter contract
"gmnspy core (incl. ``gmnspy.cli``, which imports the workbench) must not require optional extras".
"""

from __future__ import annotations

import importlib
from types import ModuleType

from .errors import ActionError

__all__ = ["optional_module"]


def optional_module(name: str, extra: str) -> ModuleType:
    """Return module ``name``, or raise :class:`ActionError` naming the extra to install."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise ActionError(f"this needs the [{extra}] extra: pip install 'gmnspy[{extra}]' ({exc})") from exc
```

- [ ] **Step 5: Create `packages/gmnspy/gmnspy/workbench/estimate.py`**

```python
"""Size a build before running it: a cheap pre-query count, then a calibrated linear cost model.

``seconds = latency_s + links * s_per_link`` with ``links = n_elements * links_per_element``; the
coefficients live in the maintained data file ``data/build_cost.toml`` (read with ``tomllib``), which
says plainly which numbers are measured and which are guesses. The pre-queries are:

* :func:`count_osm`: the build's own Overpass query with ``out count;`` (ways only, no geometry);
* :func:`count_overture`: DuckDB ``COUNT(*)`` over the same bbox + class predicate as the read.

An estimate is advice for the approval gate, not a guarantee.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

from .area import BboxArea, PlaceArea, PointArea
from .extras import optional_module

__all__ = [
    "Estimate",
    "SourceKind",
    "count_osm",
    "count_overture",
    "estimate_build",
    "fit_s_per_link",
    "load_coefficients",
    "needs_approval",
]

SourceKind = Literal["osm", "overture", "osm_file", "overture_file"]
#: Overpass timeout for the count pre-query (seconds); a count that slow means "unavailable".
COUNT_TIMEOUT_S = 25


@dataclass(frozen=True)
class Estimate:
    """A build-size estimate. ``seconds is None`` means the pre-query failed (``basis`` says why)."""

    seconds: float | None
    out_bytes: int | None
    n_elements: int | None
    basis: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy (round-trips through ``Estimate(**d)``)."""
        return asdict(self)


@cache
def load_coefficients() -> dict[str, Any]:
    """The parsed ``data/build_cost.toml`` (cached; edit the file, not this module, to re-tune)."""
    text = resources.files("gmnspy.workbench").joinpath("data", "build_cost.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def estimate_build(
    source: SourceKind,
    n_elements: int,
    *,
    output_format: str = "parquet",
    coefficients: dict[str, Any] | None = None,
) -> Estimate:
    """Turn a pre-query count into time and output-size estimates.

    Args:
        source: Which build path (each has its own coefficients and ``n_elements`` unit).
        n_elements: The pre-query result (ways, segments, or file bytes; see the data file).
        output_format: ``parquet``/``csv``/``duckdb``/``zip``, for the output-size estimate.
        coefficients: Override the data file (tests, calibration).

    Returns:
        An :class:`Estimate` whose ``basis`` names the count and the model.

    Examples:
        >>> est = estimate_build("osm", 10_000)
        >>> round(est.seconds, 1), est.n_elements
        (7.5, 10000)
    """
    coeffs = coefficients or load_coefficients()
    model = coeffs["sources"][source]
    links = n_elements * model["links_per_element"]
    seconds = model["latency_s"] + links * model["s_per_link"]
    out = coeffs["output"]
    out_bytes = int(out["fixed_bytes"][output_format] + links * out["bytes_per_link"][output_format])
    unit = "bytes of file" if source == "osm_file" else ("ways" if source == "osm" else "segments")
    basis = f"{source}: {n_elements:,} {unit} -> ~{links:,.0f} links (model from data/build_cost.toml)"
    return Estimate(seconds=seconds, out_bytes=out_bytes, n_elements=n_elements, basis=basis)


def needs_approval(estimate: Estimate, threshold_s: float) -> bool:
    """Whether running needs an explicit approval: over the threshold, or no estimate at all."""
    return estimate.seconds is None or estimate.seconds > threshold_s


def count_osm(
    area: BboxArea | PointArea | PlaceArea,
    *,
    network_type: str,
    endpoint: str,
    http: Any,
    user_agent: str,
    retries: int = 1,
) -> int:
    """Number of OSM ways the build's Overpass query would return (Overpass ``out count;``).

    Raises whatever the HTTP layer raises; :func:`gmnspy.workbench.build.estimate_for` turns any
    failure into an "unavailable" estimate.
    """
    osm_query = optional_module("gmnspy.osm.query", "osm")
    q = osm_query.build_overpass_query(
        bbox=area.to_bbox(), polygon=area.to_polygon(), network_type=network_type, timeout=COUNT_TIMEOUT_S, out="count"
    )
    elements = osm_query.fetch_osm(
        q, endpoint=endpoint, session=http, user_agent=user_agent, timeout=COUNT_TIMEOUT_S + 5, retries=retries
    )
    return int(elements[0]["tags"]["ways"])


def count_overture(
    bbox: tuple[float, float, float, float],
    *,
    network_type: str,
    overture_release: str,
    data_root: str | None,
    engine: Any = None,
) -> int:
    """Number of Overture road segments the build would read (``COUNT(*)``, same predicate as the read)."""
    overture_query = optional_module("gmnspy.overture.query", "overture")
    return overture_query.count_segments(
        bbox, network_type=network_type, overture_release=overture_release, data_root=data_root, engine=engine
    )


def fit_s_per_link(samples: Sequence[tuple[float, float]], *, latency_s: float) -> float:
    """Least-squares ``s_per_link`` through a fixed ``latency_s`` from ``(links, seconds)`` samples.

    Examples:
        >>> fit_s_per_link([(100_000, 15.0), (200_000, 25.0)], latency_s=5.0)
        0.0001
    """
    num = sum(links * (seconds - latency_s) for links, seconds in samples)
    den = sum(links * links for links, _ in samples)
    if den == 0:
        raise ValueError("need at least one sample with links > 0")
    return num / den
```

- [ ] **Step 6: Add `ApprovalRequired` to `packages/gmnspy/gmnspy/workbench/errors.py`**

Replace `from typing import Any` with:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .estimate import Estimate
```

Add `"ApprovalRequired"` to `__all__`, keeping it sorted, and append:

```python
class ApprovalRequired(ActionError):
    """A build's estimate is over ``app.approve_above_s`` (or unavailable) and ``approved`` was false."""

    def __init__(self, estimate: Estimate, threshold_s: float) -> None:
        """Keep the estimate (``.estimate``) and expose it as the history payload."""
        self.estimate = estimate
        self.threshold_s = threshold_s
        self.payload = {"estimate": estimate.to_dict(), "threshold_s": threshold_s}
        if estimate.seconds is None:
            detail = f"the size estimate is unavailable ({estimate.basis})"
        else:
            detail = f"estimated ~{estimate.seconds:.0f} s, over the {threshold_s:.0f} s approval threshold"
        super().__init__(f"approval required: {detail}; re-run with approved=True")
```

- [ ] **Step 7: Run the tests (including the module's doctests)**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_estimate.py packages/gmnspy/gmnspy/workbench/estimate.py -q`
Expected: `14 passed, 1 skipped` (12 tests, 2 doctests, 1 opt-in calibration test).

- [ ] **Step 8: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/data/build_cost.toml packages/gmnspy/gmnspy/workbench/extras.py \
  packages/gmnspy/gmnspy/workbench/estimate.py packages/gmnspy/gmnspy/workbench/errors.py \
  packages/gmnspy/pyproject.toml packages/gmnspy/tests/test_workbench_estimate.py
git commit -m "feat(workbench): build estimate (pre-query count + data-file cost model) and ApprovalRequired"
```

---

### Task 11: `JobRunner`: threads, stages, cancellation, failure

Thread safety is the main risk here. The tests pin the cancellation checkpoint semantics, failure capture, a
broken callback, and real concurrency, which uses a `Barrier` that deadlocks unless the two jobs run at once.

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/jobs.py`
- Test: `packages/gmnspy/tests/test_workbench_jobs.py`

- [ ] **Step 1: Write the failing tests in `packages/gmnspy/tests/test_workbench_jobs.py`**

```python
"""Tests for the background JobRunner: lifecycle, events, cancellation, failure, concurrency."""

import threading

import pytest
from gmnspy.workbench.errors import ActionError
from gmnspy.workbench.jobs import JobRunner

WAIT = 5.0  # generous upper bound; every wait below normally returns in milliseconds


@pytest.fixture
def events():
    return []


@pytest.fixture
def runner(events):
    lock = threading.Lock()

    def publish(event):
        with lock:
            events.append(event)

    return JobRunner(publish)


def test_success_runs_stages_and_finishes(runner, events):
    def fn(ctx):
        ctx.stage("query", progress=0.5, eta_s=3.0)
        return {"answer": 42}

    finished = []
    job = runner.submit("build_network", "build x", fn, on_finish=finished.append)
    assert job.wait(WAIT)
    snap = runner.snapshot(job)
    assert (snap["status"], snap["stage"], snap["progress"], snap["eta_s"]) == ("done", "done", 1.0, None)
    assert snap["result"] == {"answer": 42} and snap["finished"] is not None
    assert finished == [job]
    stages = [e["job"]["stage"] for e in events if e["type"] == "job"]
    assert stages[0] == "starting" and "query" in stages and stages[-1] == "done"
    assert "_cancel" not in snap and "_done" not in snap


def test_cancel_takes_effect_at_next_stage(runner):
    entered, release = threading.Event(), threading.Event()

    def fn(ctx):
        ctx.stage("query")
        entered.set()
        release.wait(WAIT)  # simulate an uninterruptible download
        ctx.stage("convert")  # checkpoint: raises JobCancelled
        raise AssertionError("must not get here")

    job = runner.submit("build_network", "build x", fn)
    assert entered.wait(WAIT)
    assert runner.cancel(job.id)["cancel_requested"] is True
    assert runner.snapshot(job)["status"] == "running"  # still inside the stage
    release.set()
    assert job.wait(WAIT)
    snap = runner.snapshot(job)
    assert snap["status"] == "cancelled" and snap["error_type"] == "JobCancelled" and snap["stage"] == "query"


def test_cancel_finished_job_is_a_noop(runner):
    job = runner.submit("open_network", "open x", lambda ctx: None)
    assert job.wait(WAIT)
    assert runner.cancel(job.id)["status"] == "done"


def test_action_error_is_a_failure_with_payload(runner):
    class Gate(ActionError):
        pass

    def fn(ctx):
        exc = Gate("approval required")
        exc.payload = {"estimate": {"seconds": 999}}
        raise exc

    job = runner.submit("build_network", "b", fn)
    assert job.wait(WAIT)
    snap = runner.snapshot(job)
    assert (snap["status"], snap["error"], snap["error_type"]) == ("failed", "approval required", "Gate")
    assert snap["payload"] == {"estimate": {"seconds": 999}}


def test_crash_is_an_internal_error_not_a_dead_thread(runner):
    def fn(ctx):
        raise KeyError("boom")

    job = runner.submit("open_network", "o", fn)
    assert job.wait(WAIT)
    snap = runner.snapshot(job)
    assert snap["status"] == "failed" and snap["error_type"] == "InternalError" and "KeyError" in snap["error"]


def test_broken_on_finish_still_releases_waiters(runner):
    def on_finish(job):
        raise RuntimeError("callback bug")

    job = runner.submit("open_network", "o", lambda ctx: 1, on_finish=on_finish)
    assert job.wait(WAIT) and runner.snapshot(job)["status"] == "done"


def test_jobs_run_concurrently_and_list_newest_first(runner):
    both_running = threading.Barrier(2, timeout=WAIT)

    def fn(ctx):
        both_running.wait()  # deadlocks (BrokenBarrierError) unless both jobs run at once
        return "ok"

    a = runner.submit("open_network", "a", fn)
    b = runner.submit("open_network", "b", fn)
    assert a.wait(WAIT) and b.wait(WAIT)
    assert [j["status"] for j in runner.snapshots()] == ["done", "done"]
    assert [j["id"] for j in runner.snapshots()] == [b.id, a.id]


def test_unknown_job():
    with pytest.raises(KeyError, match="unknown job"):
        JobRunner(lambda e: None).get("job-99")
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_jobs.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'gmnspy.workbench.jobs'`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/jobs.py`**

```python
"""Background jobs: one thread per job, staged progress pushed as ``job`` events, cooperative cancel.

A job function receives a :class:`JobContext`. It calls ``ctx.stage(name, ...)`` at each stage
boundary; that publishes progress and is also the cancellation checkpoint (it raises
:class:`~gmnspy.workbench.errors.JobCancelled` once :meth:`JobRunner.cancel` was called). Work
inside one stage (an Overpass download, a DuckDB read) is not interrupted, so a cancel takes
effect at the next boundary.

Thread-safety: every mutation of a :class:`Job` and every snapshot of it (``to_dict``) happens
under the runner's lock. The runner never touches session state; the ``on_finish`` callback
(run on the job thread, before the job is marked finished for :meth:`Job.wait`) is where the
session records history.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .errors import ActionError, JobCancelled

__all__ = ["Job", "JobContext", "JobRunner", "JobStatus"]

logger = logging.getLogger(__name__)

JobStatus = Literal["running", "done", "failed", "cancelled"]


@dataclass
class Job:
    """One background job's observable state."""

    id: str
    kind: str
    label: str
    status: JobStatus = "running"
    stage: str = "starting"
    progress: float | None = None
    eta_s: float | None = None
    error: str | None = None
    error_type: str | None = None
    payload: dict[str, Any] | None = None
    result: Any = None
    history_seq: int | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    cancel_requested: bool = False
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe public fields (call through :meth:`JobRunner.snapshot` for a consistent view)."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job finished (and ``on_finish`` ran); ``False`` on timeout."""
        return self._done.wait(timeout)


class JobContext:
    """What a job function sees: stage reporting and the cancellation checkpoint."""

    def __init__(self, job: Job, runner: JobRunner) -> None:
        """Bind to ``job`` on ``runner``."""
        self._job = job
        self._runner = runner

    @property
    def cancelled(self) -> bool:
        """Whether cancellation was requested."""
        return self._job._cancel.is_set()

    def check(self) -> None:
        """Raise :class:`JobCancelled` if cancellation was requested."""
        if self.cancelled:
            raise JobCancelled(f"{self._job.label}: cancelled")

    def stage(self, name: str, *, progress: float | None = None, eta_s: float | None = None) -> None:
        """Enter stage ``name`` (a cancellation checkpoint) and publish the job's new state."""
        self.check()
        self._runner.update(self._job, stage=name, progress=progress, eta_s=eta_s)


class JobRunner:
    """Start, track, and cancel background jobs; publish ``{"type": "job", "job": ...}`` events."""

    def __init__(self, publish: Callable[[dict[str, Any]], None]) -> None:
        """Publish job events through ``publish`` (the session's ``EventBus.publish``)."""
        self._publish = publish
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def submit(
        self,
        kind: str,
        label: str,
        fn: Callable[[JobContext], Any],
        *,
        on_finish: Callable[[Job], None] | None = None,
    ) -> Job:
        """Start ``fn(ctx)`` on a new daemon thread and return its :class:`Job` immediately."""
        with self._lock:
            job = Job(id=f"job-{next(self._ids)}", kind=kind, label=label)
            self._jobs[job.id] = job
        self._emit(job)
        threading.Thread(target=self._run, args=(job, fn, on_finish), name=f"gmnspy-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job:
        """The job with ``job_id`` (``KeyError("unknown job ...")`` if none)."""
        with self._lock:
            try:
                return self._jobs[job_id]
            except KeyError:
                raise KeyError(f"unknown job {job_id!r}") from None

    def snapshot(self, job: Job) -> dict[str, Any]:
        """A consistent JSON-safe copy of ``job``."""
        with self._lock:
            return job.to_dict()

    def snapshots(self) -> list[dict[str, Any]]:
        """Snapshots of every job, newest first."""
        with self._lock:
            return [j.to_dict() for j in reversed(self._jobs.values())]

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Request cancellation (no-op for a finished job) and return the job's snapshot."""
        job = self.get(job_id)
        with self._lock:
            if job.finished is None:
                job.cancel_requested = True
                job._cancel.set()
        self._emit(job)
        return self.snapshot(job)

    def update(self, job: Job, **changes: Any) -> None:
        """Set fields on ``job`` under the lock and publish it (used by stages and by ``on_finish``)."""
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
        self._emit(job)

    # ------------------------------------------------------------------ internals

    def _emit(self, job: Job) -> None:
        self._publish({"type": "job", "job": self.snapshot(job)})

    def _run(self, job: Job, fn: Callable[[JobContext], Any], on_finish: Callable[[Job], None] | None) -> None:
        outcome: dict[str, Any]
        try:
            result = fn(JobContext(job, self))
            outcome = {"status": "done", "stage": "done", "progress": 1.0, "result": result}
        except JobCancelled as exc:
            outcome = {"status": "cancelled", "error": str(exc), "error_type": "JobCancelled"}
        except ActionError as exc:
            outcome = {"status": "failed", "error": str(exc), "error_type": type(exc).__name__, "payload": exc.payload}
        except Exception as exc:  # boundary: a crashed job is a reported failure, never a dead thread
            logger.exception("workbench job %s (%s) crashed", job.id, job.kind)
            outcome = {"status": "failed", "error": f"internal error: {type(exc).__name__}: {exc}"}
            outcome["error_type"] = "InternalError"
        with self._lock:
            for key, value in outcome.items():
                setattr(job, key, value)
            job.eta_s = None
            job.finished = time.time()
        try:
            if on_finish is not None:
                on_finish(job)
        except Exception:  # boundary: a broken callback must not leave waiters blocked forever
            logger.exception("workbench job %s on_finish failed", job.id)
        finally:
            job._done.set()
            self._emit(job)
```

- [ ] **Step 4: Run the tests three times to shake out timing flakiness**

Run: `for i in 1 2 3; do uv run --all-extras pytest packages/gmnspy/tests/test_workbench_jobs.py -q || break; done`
Expected: `8 passed` on each of the 3 runs.

- [ ] **Step 5: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/jobs.py packages/gmnspy/tests/test_workbench_jobs.py
git commit -m "feat(workbench): JobRunner (thread per job, staged progress events, cooperative cancel)"
```

---

### Task 12: `OpenNetwork` runs as a job, enforces allowed roots, and loads off the lock

This is the central concurrency change.
- `Session.submit(action)` starts a job and returns the `Job` at once.
- `dispatch_recorded` submits and then waits, so the CLI and Python callers see the same blocking behaviour as
  before.
- The job resolves the path against `io.allowed_roots`, then loads the network and materialises its frames, all
  without the lock. Only `_register` and the history record (`_finish`) take the lock.

**Files:**
- Modify: `packages/gmnspy/gmnspy/workbench/registry.py` (`as_pandas`, `NetworkHandle.prime`)
- Modify: `packages/gmnspy/gmnspy/workbench/actions.py` (`runs_as_job`, `replay_overrides`, `to_python`)
- Modify: `packages/gmnspy/gmnspy/workbench/session.py` (replace the whole file)
- Test: `packages/gmnspy/tests/test_workbench_session_jobs.py` (new), `packages/gmnspy/tests/test_workbench_actions.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/gmnspy/tests/test_workbench_session_jobs.py`. Task 13 extends it with the build tests.

```python
"""Session job actions: OpenNetwork / BuildNetwork run off the session lock, with approval and cancel."""

import threading

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench.actions import OpenNetwork
from gmnspy.workbench.errors import ActionError, PathNotAllowed
from gmnspy.workbench.session import Session

WAIT = 10.0


@pytest.fixture
def make_session(tmp_path, isolated_env):
    def make(**kwargs):
        return Session(project_dir=tmp_path, environ=isolated_env, parser=StubParser(), **kwargs)

    return make


# ------------------------------------------------------------------ OpenNetwork as a job


def test_open_outside_allowed_roots_is_recorded_path_not_allowed(make_session, tmp_path_factory):
    session = make_session()
    elsewhere = tmp_path_factory.mktemp("not-allowed")
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        session.dispatch(OpenNetwork(source=str(elsewhere)))
    assert session.history[-1].error_type == "PathNotAllowed" and len(session.registry) == 0


def test_url_sources_skip_the_roots_check(make_session, monkeypatch):
    def fake_from_source(source, **kw):
        raise OSError(f"offline: {source}")

    monkeypatch.setattr(Network, "from_source", fake_from_source)
    with pytest.raises(ActionError, match="could not open s3://bucket/net: offline"):
        make_session().dispatch(OpenNetwork(source="s3://bucket/net"))


def test_submit_returns_at_once_and_records_on_finish(make_session, rdu_source):
    session = make_session()
    events = []
    session.events.publish = events.append
    job = session.submit(OpenNetwork(source=rdu_source))
    assert job.wait(WAIT)
    snap = session.jobs.snapshot(job)
    assert snap["status"] == "done" and snap["result"] == {"net_id": "rdu-i40"} and snap["history_seq"] == 1
    assert session.history[0].ok and session.active == "rdu-i40"
    kinds = [e["type"] for e in events]
    assert kinds[0] == "job" and kinds.index("history") < kinds.index("state") and kinds[-1] == "job"


def test_submit_rejects_non_job_actions(make_session):
    with pytest.raises(ValueError, match="not a job action"):
        make_session().submit({"type": "clear_selection"})


def test_load_runs_without_holding_the_session_lock(make_session, rdu_source, monkeypatch):
    session = make_session()
    loading, release = threading.Event(), threading.Event()
    real = Network.from_source

    def slow_from_source(source, **kw):
        loading.set()
        release.wait(WAIT)
        return real(source, **kw)

    monkeypatch.setattr(Network, "from_source", slow_from_source)
    job = session.submit(OpenNetwork(source=rdu_source))
    assert loading.wait(WAIT)
    got = []
    reader = threading.Thread(target=lambda: got.append(session.state()))
    reader.start()
    reader.join(2.0)
    assert got and got[0]["networks"] == []  # state() took the lock while the open was mid-load
    release.set()
    assert job.wait(WAIT) and session.active == "rdu-i40"


def test_cancel_open_before_register(make_session, rdu_source, monkeypatch):
    session = make_session()
    loading, release = threading.Event(), threading.Event()
    real = Network.from_source

    def slow_from_source(source, **kw):
        loading.set()
        release.wait(WAIT)
        return real(source, **kw)

    monkeypatch.setattr(Network, "from_source", slow_from_source)
    job = session.submit(OpenNetwork(source=rdu_source))
    assert loading.wait(WAIT)
    session.jobs.cancel(job.id)
    release.set()
    assert job.wait(WAIT)
    assert session.jobs.snapshot(job)["status"] == "cancelled"
    assert session.history[-1].error_type == "JobCancelled" and len(session.registry) == 0
```

Append to `packages/gmnspy/tests/test_workbench_actions.py`:

```python
def test_open_network_is_a_job_action():
    assert OpenNetwork.runs_as_job and not Select.runs_as_job and not OpenNetwork.mutates
    assert OpenNetwork.replay_overrides == {}
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session_jobs.py packages/gmnspy/tests/test_workbench_actions.py -q`
Expected: failures with `AttributeError: 'Session' object has no attribute 'submit'` and
`AttributeError: type object 'OpenNetwork' has no attribute 'runs_as_job'`.

- [ ] **Step 3: Make the registry's pandas helper public and add `NetworkHandle.prime`**

In `packages/gmnspy/gmnspy/workbench/registry.py`:
- rename `_as_pandas` to `as_pandas`, in its definition and its two call sites in `links_df`/`nodes_df`;
- give it the docstring `"""Materialise an ibis/datagrove table (or pass a pandas frame through) as pandas."""`;
- add `"as_pandas"` to `__all__`, keeping it sorted;
- insert this method directly above `def bump(`:

```python
    def prime(self, **artifacts: Any) -> None:
        """Seed the current version's cache with artifacts built elsewhere (e.g. frames loaded off the lock)."""
        with self._lock:
            for key, value in artifacts.items():
                self._cache[(key, self.version)] = value
```

- [ ] **Step 4: Add the job flags to `packages/gmnspy/gmnspy/workbench/actions.py`**

Replace the end of the module docstring:

```python
code. ``mutates`` marks actions the assistant must draft-before-apply.
"""
```

with:

```python
code. ``mutates`` marks actions the assistant must draft-before-apply;
``runs_as_job`` marks actions whose slow work runs on a background job thread
(see :mod:`gmnspy.workbench.jobs`); ``replay_overrides`` are fields forced in
the ``to_python`` replay snippet.
"""
```

Replace:

```python
class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutates: ClassVar[bool] = False


class OpenNetwork(_Action):
    """Load a GMNS network from a local path or URL and make it active."""

    type: Literal["open_network"] = "open_network"
```

with:

```python
class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mutates: ClassVar[bool] = False
    runs_as_job: ClassVar[bool] = False
    replay_overrides: ClassVar[dict[str, Any]] = {}


class OpenNetwork(_Action):
    """Load a GMNS network from a local path (inside ``io.allowed_roots``) or URL and make it active."""

    type: Literal["open_network"] = "open_network"
    runs_as_job: ClassVar[bool] = True
```

Replace the head of `to_python`, keeping its last two lines (`args = ...` and `return ...`):

```python
def to_python(action: _Action) -> str:
    """The Python call that replays ``action`` against a live workbench handle named ``app``."""
    fields = action.model_dump(exclude_defaults=True, exclude={"type"})
```

with:

```python
def to_python(action: _Action) -> str:
    """The Python call that replays ``action`` against a live workbench handle named ``app``.

    Top-level fields equal to their default are omitted; nested models (an ``area``) are written
    in full, so their discriminator survives. ``replay_overrides`` are applied last.
    """
    defaults = {name: f.get_default(call_default_factory=True) for name, f in type(action).model_fields.items()}
    fields = {k: v for k, v in action.model_dump(exclude={"type"}).items() if v != defaults[k]}
    fields.update(type(action).replay_overrides)
```

This omits top-level defaults exactly as before, so every existing snippet is unchanged. Nested models (Task 13's
`area`) are now written in full, so their `kind` discriminator survives a replay.

- [ ] **Step 5: Replace `packages/gmnspy/gmnspy/workbench/session.py` with**

```python
"""Workbench session: the one place state changes, via :meth:`Session.dispatch`.

UI clicks (``POST /api/actions``), Python (``session.dispatch(...)``), and, in
P3, the NL assistant all funnel through ``dispatch``. Each call is recorded as a
:class:`HistoryEntry` carrying its ``to_python`` replay snippet, and publishes
``history`` + ``state`` events for the browser. Network *edits* are not actions
here yet: in P2 they become ProjectCard-shaped ``NetworkChange`` objects.

Actions marked ``runs_as_job`` (``OpenNetwork``, ``BuildNetwork``) do their slow
work on a background job thread *without* the session lock; only registering the
result (and recording history) takes the lock. :meth:`Session.submit` starts one
and returns immediately (the HTTP path); :meth:`Session.dispatch` starts one and
waits (Python, the CLI), so callers see the same blocking behaviour as before.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from gmnspy import Network
from gmnspy.config import LoadedSettings, Settings, SettingsError, get_value, load_settings, save_setting
from gmnspy.select.intent import SelectionIntent
from gmnspy.select.parse import ClaudeParser, StubParser
from gmnspy.select.resolve import resolve_frames
from gmnspy.viz.styling import styleable_columns

from .actions import (
    Action,
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
    parse_action,
    to_python,
)
from .errors import ActionError, JobCancelled, NotSupportedYet, PathNotAllowed
from .events import EventBus
from .jobs import Job, JobContext, JobRunner
from .paths import is_url, resolve_allowed
from .registry import NetworkHandle, NetworkRegistry, as_pandas, default_label
from .selection import selection_payload, unparsed_payload

__all__ = ["DEFAULT_STYLE", "ActionError", "HistoryEntry", "NotSupportedYet", "Session"]

logger = logging.getLogger(__name__)

DEFAULT_STYLE: dict[str, Any] = {
    "color_by": "none",
    "ramp": "YlOrRd",
    "offset": True,
    "show_direction": False,
    "show_legend": True,
    "show": {"links": True, "nodes": True, "labels": True, "selection": True},
    "colors": {"links": [46, 64, 110], "nodes": [70, 90, 120], "selection": [255, 140, 59]},
}


@dataclass
class HistoryEntry:
    """One dispatched action, successful or not."""

    seq: int
    action: dict[str, Any]
    python: str
    ok: bool
    error: str | None
    error_type: str | None
    result: Any
    ts: float

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe copy."""
        return asdict(self)


class Session:
    """Live workbench state: open networks, selection, style, settings, history."""

    def __init__(
        self,
        *,
        project_dir: str | Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        parser: Any = None,
        environ: Mapping[str, str] | None = None,
        http: Any = None,
    ) -> None:
        """Load settings (raises :class:`~gmnspy.config.SettingsError` on bad config) and start empty.

        ``http`` is the HTTP session for Overpass/Nominatim (anything with ``get``/``post`` like
        :mod:`requests`); ``None`` means ``requests`` itself. Tests inject a fake.
        """
        self.project_dir = project_dir
        self._environ = environ
        self._overrides: dict[str, Any] = dict(overrides or {})
        self.loaded: LoadedSettings = load_settings(project_dir=project_dir, overrides=self._overrides, environ=environ)
        self.registry = NetworkRegistry()
        self.events = EventBus()
        self.active: str | None = None
        self.selection: dict[str, Any] | None = None
        self.style: dict[str, Any] = copy.deepcopy(DEFAULT_STYLE)
        self.history: list[HistoryEntry] = []
        self._injected_parser = parser
        self._parser = parser
        self.http = http
        self.jobs = JobRunner(lambda event: self.events.publish(event))  # late-bound, like every other publish
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ public API

    @property
    def settings(self) -> Settings:
        """The currently resolved settings."""
        return self.loaded.settings

    def parser(self) -> Any:
        """The NL parser chosen by ``select.provider`` (built lazily; an injected parser wins)."""
        if self._parser is None:
            sel = self.settings.select
            self._parser = ClaudeParser(model=sel.model) if sel.provider == "claude" else StubParser()
        return self._parser

    def dispatch(self, action: Action | dict[str, Any]) -> Any:
        """Apply ``action`` (waiting for a job action to finish) and return its result.

        Raises the recorded failure's type: :class:`~gmnspy.workbench.errors.ApprovalRequired` (with
        ``.estimate``), :class:`NotSupportedYet`, :class:`~gmnspy.workbench.errors.PathNotAllowed`,
        :class:`~gmnspy.workbench.errors.JobCancelled`, else :class:`ActionError`.
        """
        entry = self.dispatch_recorded(action)
        if entry.ok:
            return entry.result
        raise _ERROR_TYPES.get(entry.error_type or "", ActionError)(entry.error)

    do = dispatch

    def dispatch_recorded(self, action: Action | dict[str, Any]) -> HistoryEntry:
        """Apply ``action``, record and publish it, and return the entry (never raises ``ActionError``).

        A ``runs_as_job`` action is submitted as a background job and this call waits for it.
        """
        if isinstance(action, dict):
            action = parse_action(action)
        if action.runs_as_job:
            job = self.submit(action)
            job.wait()
            if job.history_seq is None:  # on_finish itself failed (already logged by the runner)
                raise RuntimeError(f"job {job.id} finished without a history entry")
            return self.history[job.history_seq - 1]
        handler = getattr(self, f"_do_{action.type}")
        with self._lock:
            try:
                result, ok, error, error_type = handler(action), True, None, None
            except ActionError as exc:  # includes NotSupportedYet
                result, ok, error, error_type = exc.payload, False, str(exc), type(exc).__name__
            except Exception as exc:  # boundary: an unexpected handler failure is still a recorded, user-facing error
                logger.exception("workbench action %s failed", action.type)
                error = f"internal error: {type(exc).__name__}: {exc}"
                result, ok, error_type = None, False, "InternalError"
            return self._record(action, ok=ok, result=result, error=error, error_type=error_type)

    def submit(self, action: Action | dict[str, Any]) -> Job:
        """Start a ``runs_as_job`` action on a background job and return the :class:`Job` at once.

        The history entry is recorded when the job finishes (so ``seq`` follows completion order).
        """
        if isinstance(action, dict):
            action = parse_action(action)
        if not action.runs_as_job:
            raise ValueError(f"{action.type} is not a job action; use dispatch()")
        run = getattr(self, f"_job_{action.type}")
        label = f"open {default_label(action.source)}"
        return self.jobs.submit(
            action.type, label, lambda ctx: run(action, ctx), on_finish=lambda job: self._finish(action, job)
        )

    def _finish(self, action: Action, job: Job) -> None:
        """Job callback: record the outcome as a history entry (under the lock) and link it to the job."""
        ok = job.status == "done"
        with self._lock:
            entry = self._record(
                action,
                ok=ok,
                result=job.result if ok else job.payload,
                error=job.error,
                error_type=job.error_type,
            )
        self.jobs.update(job, history_seq=entry.seq)

    def _record(
        self, action: Action, *, ok: bool, result: Any, error: str | None, error_type: str | None
    ) -> HistoryEntry:
        """Append and publish a history entry (then a ``state`` event on success). Call with the lock held."""
        entry = HistoryEntry(
            seq=len(self.history) + 1,
            action=action.model_dump(mode="json"),
            python=to_python(action),
            ok=ok,
            error=error,
            error_type=error_type,
            result=copy.deepcopy(result),
            ts=time.time(),
        )
        self.history.append(entry)
        self.events.publish({"type": "history", "entry": entry.to_dict()})
        if ok:
            self.events.publish({"type": "state", "state": self.state()})
        return entry

    def add_network(
        self, net: Network, *, source: str = "<python>", label: str | None = None, net_id: str | None = None
    ) -> NetworkHandle:
        """Register an already-loaded ``Network`` (the Python path; not an Action because it isn't JSON)."""
        with self._lock:
            handle = self.registry.add(net, source=source, label=label, net_id=net_id)
            self.active = self.active or handle.id
            self.events.publish({"type": "state", "state": self.state()})
        return handle

    def state(self) -> dict[str, Any]:
        """JSON-safe snapshot pushed to the browser."""
        with self._lock:
            return {
                "networks": [h.summary() for h in self.registry],
                "active": self.active,
                "selection": copy.deepcopy(self.selection),
                "style": copy.deepcopy(self.style),
            }

    def settings_payload(self) -> dict[str, Any]:
        """Settings values, per-key sources, JSON schema, and file paths (for the Settings UI)."""
        return {
            "values": self.settings.model_dump(mode="json"),
            "sources": dict(self.loaded.sources),
            "schema": Settings.model_json_schema(),
            "paths": {"user": str(self.loaded.user_path), "project": str(self.loaded.project_path)},
        }

    # ------------------------------------------------------------------ handlers (run under the lock)

    def _handle(self, net_id: str | None) -> NetworkHandle:
        target = net_id or self.active
        if target is None:
            raise ActionError("no network is open")
        try:
            return self.registry.get(target)
        except KeyError as exc:
            raise ActionError(exc.args[0]) from exc

    # -------------------------------------------------- job actions (run on a job thread, lock only to register)

    def _load(self, source: str, spec_version: str) -> tuple[Network, dict[str, Any]]:
        """Load ``source`` and materialise its link/node frames, all without the session lock."""
        try:
            net = Network.from_source(source, spec_version=spec_version)
            frames = {"links_df": as_pandas(net.links), "nodes_df": as_pandas(net.nodes)}
        except Exception as exc:  # boundary: any load failure is a user-facing error, not a crash
            raise ActionError(f"could not open {source}: {exc}") from exc
        return net, frames

    def _register(
        self, net: Network, frames: dict[str, Any], *, source: str, label: str | None, net_id: str | None = None
    ) -> NetworkHandle:
        """Add a loaded network to the registry and make it active (takes the lock briefly)."""
        with self._lock:
            handle = self.registry.add(net, source=source, label=label, net_id=net_id)
            handle.prime(**frames)
            self.active = handle.id
        return handle

    def _job_open_network(self, action: OpenNetwork, ctx: JobContext) -> dict[str, Any]:
        settings = self.settings
        source = action.source if is_url(action.source) else str(resolve_allowed(action.source, settings))
        ctx.stage("open", progress=0.1)
        net, frames = self._load(source, settings.io.spec_version)
        ctx.stage("register", progress=0.9)  # last cancellation checkpoint
        handle = self._register(net, frames, source=source, label=action.label, net_id=action.net_id)
        return {"net_id": handle.id}

    def _do_close_network(self, action: CloseNetwork) -> None:
        self._handle(action.net_id)
        self.registry.remove(action.net_id)
        if self.selection and self.selection["net_id"] == action.net_id:
            self.selection = None
        if self.active == action.net_id:
            ids = self.registry.ids()
            self.active = ids[0] if ids else None

    def _do_set_active_network(self, action: SetActiveNetwork) -> None:
        self.active = self._handle(action.net_id).id

    def _do_select(self, action: Select) -> dict[str, Any]:
        if action.component != "roadway":
            raise NotSupportedYet("transit selection arrives with the transit component (phase P6)")
        handle = self._handle(action.net_id)
        if action.utterance is not None:
            try:
                intent = self.parser().parse(action.utterance)
            except Exception as exc:  # any parse failure is a normal "not_found" selection
                self.selection = unparsed_payload(handle, action.utterance, exc)
                return self.selection
        else:
            intent = SelectionIntent(link_ids=list(action.link_ids or []))
        result = resolve_frames(intent, handle.links_df(), handle.nodes_df())
        self.selection = selection_payload(handle, result, utterance=action.utterance)
        return self.selection

    def _do_clear_selection(self, action: ClearSelection) -> None:
        self.selection = None

    def _do_style(self, action: Style) -> dict[str, Any]:
        patch = action.model_dump(exclude_none=True, exclude={"type"})
        color_by = patch.get("color_by")
        if color_by not in (None, "none"):
            names = {c["name"] for c in styleable_columns(self._handle(None).links_df())}
            if color_by not in names:
                raise ActionError(f"cannot color by {color_by!r}; choose one of {sorted(names)}")
        for key, value in patch.items():
            self.style[key] = {**self.style[key], **value} if isinstance(value, dict) else value
        return copy.deepcopy(self.style)

    def _do_navigate(self, action: Navigate) -> None:
        if action.to_selection and not self.selection:
            raise ActionError("nothing is selected")
        self.events.publish({"type": "navigate", **action.model_dump(mode="json", exclude={"type"})})

    def _do_set_setting(self, action: SetSetting) -> dict[str, Any]:
        try:
            if action.scope == "session":
                overrides = {**self._overrides, action.key: action.value}
                loaded = load_settings(project_dir=self.project_dir, overrides=overrides, environ=self._environ)
                self._overrides = overrides
            else:
                save_setting(
                    action.key, action.value, scope=action.scope, project_dir=self.project_dir, environ=self._environ
                )
                loaded = load_settings(project_dir=self.project_dir, overrides=self._overrides, environ=self._environ)
            value = get_value(loaded.settings, action.key)
        except SettingsError as exc:
            raise ActionError(str(exc)) from exc
        self.loaded = loaded
        if action.key.startswith("select.") and self._injected_parser is None:
            self._parser = None  # rebuilt from the new provider/model on next use
        return {"key": action.key, "value": value, "source": loaded.sources.get(action.key)}


#: Recorded ``error_type`` -> the exception :meth:`Session.dispatch` re-raises (anything else: ActionError).
_ERROR_TYPES: dict[str, type[ActionError]] = {
    cls.__name__: cls for cls in (NotSupportedYet, JobCancelled, PathNotAllowed)
}
```

- [ ] **Step 6: Run the session, action, server and CLI suites**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session_jobs.py packages/gmnspy/tests/test_workbench_session.py packages/gmnspy/tests/test_workbench_actions.py packages/gmnspy/tests/test_workbench_server.py packages/gmnspy/tests/test_workbench_network_routes.py packages/gmnspy/tests/test_cli_workbench.py -q`
Expected: all pass:
- `test_workbench_session_jobs.py`: 6
- `test_workbench_session.py`: 22, unchanged (including `test_history_python_replays_to_same_state` and the publish-ordering test)
- `test_workbench_actions.py`: 10
- `test_workbench_server.py`: 22
- `test_workbench_network_routes.py`: 8
- `test_cli_workbench.py`: 13

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/registry.py packages/gmnspy/gmnspy/workbench/actions.py \
  packages/gmnspy/gmnspy/workbench/session.py packages/gmnspy/tests/test_workbench_session_jobs.py \
  packages/gmnspy/tests/test_workbench_actions.py
git commit -m "feat(workbench): OpenNetwork runs as a job off the session lock; enforce io.allowed_roots"
```

---

### Task 13: `BuildNetwork`: plan → estimate → (approval) → query → convert → write → open

**Files:**
- Modify: `packages/gmnspy/gmnspy/workbench/actions.py` (`BuildNetwork`, union)
- Create: `packages/gmnspy/gmnspy/workbench/build.py`
- Modify: `packages/gmnspy/gmnspy/workbench/session.py` (build job, typed `ApprovalRequired` re-raise, job label)
- Modify: `packages/gmnspy/gmnspy/workbench/__init__.py` (exports)
- Test: `packages/gmnspy/tests/test_workbench_session_jobs.py`, `packages/gmnspy/tests/test_workbench_actions.py`

- [ ] **Step 1: Write the failing tests**

In `packages/gmnspy/tests/test_workbench_session_jobs.py`, replace the import block (everything from
`import threading` to `from gmnspy.workbench.session import Session`) with:

```python
import threading
from pathlib import Path

import pytest
from gmnspy import Network
from gmnspy.select.parse import StubParser
from gmnspy.workbench.actions import BuildNetwork, OpenNetwork
from gmnspy.workbench.errors import ActionError, ApprovalRequired, JobCancelled, NotSupportedYet, PathNotAllowed
from gmnspy.workbench.session import Session
```

and append:

```python
# ------------------------------------------------------------------ BuildNetwork

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OSM_FILE = str(FIXTURES / "osm" / "tiny.osm")
OVERTURE_DIR = str(FIXTURES / "overture")
#: What Overpass returns for the tiny area: its server-side highway filter already dropped the footway.
OVERPASS_BODY = [
    {"type": "node", "id": 1, "lat": 42.000, "lon": -71.000},
    {"type": "node", "id": 2, "lat": 42.001, "lon": -71.000},
    {"type": "node", "id": 3, "lat": 42.002, "lon": -71.000},
    {"type": "way", "id": 100, "nodes": [1, 2, 3], "tags": {"highway": "residential", "name": "Main St"}},
]


class _Resp:
    def __init__(self, payload):
        self.status_code, self._payload = 200, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeOverpass:
    """Answers the count pre-query and the body query; never touches the network."""

    def __init__(self, ways=10, fail_count=False):
        self.ways, self.fail_count, self.queries = ways, fail_count, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.queries.append(data)
        if data.endswith("out count;"):
            if self.fail_count:
                raise OSError("overpass unreachable")
            return _Resp({"elements": [{"type": "count", "id": 0, "tags": {"ways": str(self.ways)}}]})
        return _Resp({"elements": OVERPASS_BODY})


@pytest.fixture
def out_dir(tmp_path):
    path = tmp_path / "out"
    path.mkdir()
    return str(path)


def _bbox_build(out_dir, **kw):
    return BuildNetwork(
        source="osm",
        area={"kind": "bbox", "bbox": (-71.01, 41.99, -70.99, 42.01)},
        output_dir=out_dir,
        output_format="parquet",
        name="tiny",
        **kw,
    )


def test_build_from_local_osm_writes_then_opens_from_disk(make_session, out_dir):
    session = make_session()
    result = session.dispatch(
        BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="parquet", name="tiny")
    )
    dest = Path(out_dir) / "tiny"
    assert result["output"] == str(dest.resolve()) and (dest / "link.parquet").is_file()
    assert result["estimate"]["basis"].startswith("osm_file:") and result["estimate"]["seconds"] > 0
    handle = session.registry.get(result["net_id"])
    assert handle.source == str(dest.resolve()) and handle.label == "tiny" and len(handle.links_df()) == 2
    entry = session.history[-1]
    assert entry.ok and entry.result["estimate"] == result["estimate"]
    assert "approved=True" in entry.python and "input_file=" in entry.python


def test_build_from_local_overture_snapshot_to_duckdb(make_session, out_dir):
    session = make_session()
    result = session.dispatch(
        BuildNetwork(source="overture", input_file=OVERTURE_DIR, output_dir=out_dir, output_format="duckdb", name="ovt")
    )
    assert Path(result["output"]).name == "ovt.duckdb" and Path(result["output"]).is_file()
    assert result["estimate"]["basis"].startswith("overture_file:")
    assert len(session.registry.get(result["net_id"]).links_df()) > 0


def test_build_by_area_uses_count_then_body_query(make_session, out_dir):
    http = FakeOverpass(ways=10)
    session = make_session(http=http)
    result = session.dispatch(_bbox_build(out_dir))
    assert [q.endswith("out count;") for q in http.queries] == [True, False]
    assert result["estimate"]["n_elements"] == 10
    assert len(session.registry.get(result["net_id"]).links_df()) == 2


def test_over_threshold_needs_approval_and_writes_nothing(make_session, out_dir):
    session = make_session(http=FakeOverpass(ways=10), overrides={"app.approve_above_s": 1})
    with pytest.raises(ApprovalRequired) as caught:
        session.dispatch(_bbox_build(out_dir))
    assert caught.value.estimate.seconds > 1 and caught.value.threshold_s == 1
    entry = session.history[-1]
    assert entry.error_type == "ApprovalRequired" and entry.result["estimate"]["n_elements"] == 10
    assert not (Path(out_dir) / "tiny").exists() and len(session.registry) == 0


def test_approved_build_runs_over_threshold(make_session, out_dir):
    session = make_session(http=FakeOverpass(ways=10), overrides={"app.approve_above_s": 1})
    assert session.dispatch(_bbox_build(out_dir, approved=True))["net_id"]


def test_unavailable_estimate_needs_approval(make_session, out_dir):
    session = make_session(http=FakeOverpass(fail_count=True))
    with pytest.raises(ApprovalRequired, match="unavailable") as caught:
        session.dispatch(_bbox_build(out_dir))
    assert caught.value.estimate.seconds is None and "overpass unreachable" in caught.value.estimate.basis


def test_zip_output_not_supported_yet(make_session, out_dir):
    with pytest.raises(NotSupportedYet, match="zip"):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="zip", name="z")
        )


def test_existing_destination_is_never_overwritten(make_session, out_dir):
    (Path(out_dir) / "tiny").mkdir()
    with pytest.raises(ActionError, match="already exists"):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=out_dir, output_format="csv", name="tiny")
        )


def test_output_outside_roots_rejected(make_session, tmp_path_factory):
    elsewhere = str(tmp_path_factory.mktemp("not-allowed"))
    with pytest.raises(PathNotAllowed):
        make_session().dispatch(
            BuildNetwork(source="osm", input_file=OSM_FILE, output_dir=elsewhere, output_format="csv", name="x")
        )


def test_wrong_input_kind_rejected(make_session, out_dir):
    with pytest.raises(ActionError, match="not a local Overture snapshot"):
        make_session().dispatch(
            BuildNetwork(source="overture", input_file=OSM_FILE, output_dir=out_dir, output_format="csv", name="x")
        )


def test_cancel_build_during_query_leaves_no_output(make_session, out_dir):
    entered, release = threading.Event(), threading.Event()

    class SlowOverpass(FakeOverpass):
        def post(self, url, data=None, headers=None, timeout=None):
            if not data.endswith("out count;"):
                entered.set()
                release.wait(WAIT)
            return super().post(url, data, headers, timeout)

    session = make_session(http=SlowOverpass(ways=10))
    raised = []

    def blocking_dispatch():
        try:
            session.dispatch(_bbox_build(out_dir))
        except ActionError as exc:
            raised.append(exc)

    caller = threading.Thread(target=blocking_dispatch)
    caller.start()
    assert entered.wait(WAIT)
    (job,) = session.jobs.snapshots()
    session.jobs.cancel(job["id"])
    release.set()
    caller.join(WAIT)
    assert len(raised) == 1 and isinstance(raised[0], JobCancelled)  # dispatch re-raises the recorded type
    assert session.history[-1].error_type == "JobCancelled" and not (Path(out_dir) / "tiny").exists()
```

In `packages/gmnspy/tests/test_workbench_actions.py`, add `BuildNetwork,` to the `from gmnspy.workbench.actions import (...)`
list (first, keeping it sorted), and append:

```python
_BUILD = {"source": "osm", "output_dir": "/out", "output_format": "parquet", "name": "durham"}


def test_build_network_is_a_mutating_job_action():
    assert BuildNetwork.runs_as_job and BuildNetwork.mutates and BuildNetwork.replay_overrides == {"approved": True}


def test_build_network_needs_exactly_one_of_area_or_input_file():
    with pytest.raises(ValidationError, match="exactly one of area or input_file"):
        BuildNetwork(**_BUILD)
    with pytest.raises(ValidationError, match="exactly one of area or input_file"):
        BuildNetwork(**_BUILD, input_file="/x.osm", area={"kind": "bbox", "bbox": (-79, 35, -78, 36)})
    assert BuildNetwork(**_BUILD, input_file="/x.osm").approved is False


def test_build_network_name_is_a_plain_file_name():
    for bad in ("../escape", "a/b", ".hidden", ""):
        with pytest.raises(ValidationError):
            BuildNetwork(**{**_BUILD, "name": bad}, input_file="/x.osm")


def test_overture_release_only_with_overture():
    with pytest.raises(ValidationError, match="overture_release"):
        BuildNetwork(**_BUILD, input_file="/x.osm", overture_release="2025-12-17.0")


def test_build_network_parses_from_json_with_area_union():
    a = parse_action(
        {"type": "build_network", **_BUILD, "area": {"kind": "point", "lat": 36, "lon": -79, "buffer_m": 500}}
    )
    assert isinstance(a, BuildNetwork) and a.area.kind == "point"


def test_build_snippet_keeps_area_kind_and_forces_approval():
    a = BuildNetwork(**_BUILD, area={"kind": "bbox", "bbox": (-79, 35, -78, 36)})
    py = to_python(a)
    assert py == (
        "app.do(BuildNetwork(source='osm', area={'kind': 'bbox', 'bbox': (-79.0, 35.0, -78.0, 36.0)}, "
        "output_dir='/out', output_format='parquet', name='durham', approved=True))"
    )
    replayed = eval(py.removeprefix("app.do(").removesuffix(")"), {"BuildNetwork": BuildNetwork})
    assert replayed == a.model_copy(update={"approved": True})
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session_jobs.py packages/gmnspy/tests/test_workbench_actions.py -q`
Expected: collection errors, `ImportError: cannot import name 'BuildNetwork' from 'gmnspy.workbench.actions'`.

- [ ] **Step 3: Add `BuildNetwork` to `packages/gmnspy/gmnspy/workbench/actions.py`**

Add `from .area import Area` above `from .registry import Component`. Add `"BuildNetwork",` to `__all__`, after
`"Action",`. Insert this class directly above `Action = Annotated[`:

```python
class BuildNetwork(_Action):
    """Build a GMNS network from OSM or Overture, write it to ``output_dir``, then open it from disk.

    Give exactly one of ``area`` (fetch from the service) or ``input_file`` (a local ``.osm`` /
    Overpass ``.json`` for OSM, or a local snapshot folder for Overture). Without ``approved``, a
    build whose estimate is over ``app.approve_above_s``, or cannot be estimated, fails with
    :class:`~gmnspy.workbench.errors.ApprovalRequired` (carrying the estimate). A replayed snippet
    always passes ``approved=True``: re-running a recorded build counts as approval.
    """

    type: Literal["build_network"] = "build_network"
    mutates: ClassVar[bool] = True
    runs_as_job: ClassVar[bool] = True
    replay_overrides: ClassVar[dict[str, Any]] = {"approved": True}
    source: Literal["osm", "overture"]
    area: Area | None = None
    input_file: str | None = None
    output_dir: str
    output_format: Literal["parquet", "csv", "duckdb", "zip"]
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=100)
    network_type: str = "drive"
    extra_tags: list[str] | None = None
    spec_version: str | None = None
    overture_release: str | None = None
    label: str | None = None
    approved: bool = False

    @model_validator(mode="after")
    def _one_input(self) -> BuildNetwork:
        if (self.area is None) == (self.input_file is None):
            raise ValueError("give exactly one of area or input_file")
        if self.overture_release is not None and self.source != "overture":
            raise ValueError("overture_release only applies to source='overture'")
        return self
```

Replace the union:

```python
Action = Annotated[
    OpenNetwork | CloseNetwork | SetActiveNetwork | Select | ClearSelection | Style | Navigate | SetSetting,
    Field(discriminator="type"),
]
```

with:

```python
Action = Annotated[
    OpenNetwork
    | BuildNetwork
    | CloseNetwork
    | SetActiveNetwork
    | Select
    | ClearSelection
    | Style
    | Navigate
    | SetSetting,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Create `packages/gmnspy/gmnspy/workbench/build.py`**

```python
"""The ``BuildNetwork`` pipeline, staged for a background job: plan → estimate → query → convert → write.

The session's job function calls these in order and owns the final open + register (which needs the
session lock). Each stage boundary is a :class:`~gmnspy.workbench.jobs.JobContext` checkpoint, so a
cancel stops the build between stages. Query, convert, and write run on a private
:class:`~datagrove.engines.ibis_engine.IbisEngine` that the caller closes afterwards, so a build never
shares a DuckDB connection with the networks the browser is reading.

The OSM/Overture modules are imported at run time via :func:`~gmnspy.workbench.extras.optional_module`:
they need the ``[osm]`` / ``[overture]`` extras.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datagrove.engines.ibis_engine import IbisEngine

from gmnspy._network_build import network_from_records
from gmnspy.config import Settings
from gmnspy.network import Network
from gmnspy.overture.layout import LOCAL_SNAPSHOT_FILES, is_local_snapshot

from .actions import BuildNetwork
from .errors import ActionError, NotSupportedYet
from .estimate import Estimate, SourceKind, count_osm, count_overture, estimate_build
from .extras import optional_module
from .jobs import JobContext
from .paths import resolve_allowed

__all__ = ["WORLD_BBOX", "BuildPlan", "estimate_for", "fetch_and_convert", "plan_build", "write_output"]

#: The whole world: the Overture read bbox when a local snapshot is imported in full.
WORLD_BBOX = (-180.0, -90.0, 180.0, 90.0)
_SUFFIX = {"parquet": "", "csv": "", "duckdb": ".duckdb", "zip": ".zip"}
_FILE_KIND: dict[str, SourceKind] = {"osm": "osm_file", "overture": "overture_file"}
_OSM_FILE_SUFFIXES = (".osm", ".json")
Records = tuple[list[dict[str, Any]], list[dict[str, Any]]]
Tick = Callable[[str, float], None]


@dataclass(frozen=True)
class BuildPlan:
    """Resolved, checked locations for one build."""

    kind: SourceKind
    dest: Path
    input_path: Path | None


def plan_build(action: BuildNetwork, settings: Settings) -> BuildPlan:
    """Check the action against the filesystem before any work: allowed roots, inputs, a free destination.

    Raises:
        NotSupportedYet: ``output_format="zip"`` (gmnspy cannot re-open a zip it wrote yet).
        PathNotAllowed: the output folder or input file is outside ``io.allowed_roots``.
        ActionError: missing output folder, existing destination, or an input of the wrong kind.
    """
    if action.output_format == "zip":
        raise NotSupportedYet("zip output is not supported yet (gmnspy cannot re-open a zip it wrote); use parquet")
    out_dir = resolve_allowed(action.output_dir, settings)
    if not out_dir.is_dir():
        raise ActionError(f"output folder does not exist: {action.output_dir}")
    dest = out_dir / f"{action.name}{_SUFFIX[action.output_format]}"
    if dest.exists():
        raise ActionError(f"{dest} already exists; choose another name (builds never overwrite)")
    if action.input_file is None:
        return BuildPlan(kind=action.source, dest=dest, input_path=None)
    src = resolve_allowed(action.input_file, settings)
    if action.source == "osm" and not (src.is_file() and src.suffix.lower() in _OSM_FILE_SUFFIXES):
        raise ActionError(f"{action.input_file} is not a local .osm or Overpass .json file")
    if action.source == "overture" and not is_local_snapshot(src):
        raise ActionError(f"{action.input_file} is not a local Overture snapshot ({' + '.join(LOCAL_SNAPSHOT_FILES)})")
    return BuildPlan(kind=_FILE_KIND[action.source], dest=dest, input_path=src)


def _osm_options(settings: Settings) -> dict[str, Any]:
    osm_query = optional_module("gmnspy.osm.query", "osm")
    return {
        "endpoint": settings.osm.endpoint or osm_query.OVERPASS_URL,
        "user_agent": settings.osm.user_agent or osm_query.USER_AGENT,
    }


def _overture_read(action: BuildNetwork, plan: BuildPlan, settings: Settings) -> dict[str, Any]:
    """bbox, release, and data root for an Overture read (a local snapshot is read in full)."""
    overture_query = optional_module("gmnspy.overture.query", "overture")
    if plan.input_path is not None:
        bbox, data_root = WORLD_BBOX, str(plan.input_path)
    else:
        assert action.area is not None  # guaranteed by BuildNetwork's validator
        bbox, data_root = action.area.to_bbox(), settings.overture.data_root
    release = action.overture_release or settings.overture.release or overture_query.OVERTURE_RELEASE
    return {"bbox": bbox, "overture_release": release, "data_root": data_root}


def _count(action: BuildNetwork, plan: BuildPlan, settings: Settings, http: Any, engine: Any) -> int:
    if plan.input_path is not None and plan.kind == "osm_file":
        return plan.input_path.stat().st_size
    if plan.kind == "osm":
        assert action.area is not None
        return count_osm(action.area, network_type=action.network_type, http=http, **_osm_options(settings))
    read = _overture_read(action, plan, settings)
    return count_overture(read.pop("bbox"), network_type=action.network_type, engine=engine, **read)


def estimate_for(
    action: BuildNetwork, plan: BuildPlan, settings: Settings, *, http: Any = None, engine: Any = None
) -> Estimate:
    """Pre-query + cost model. Any failure becomes ``Estimate(seconds=None, basis="unavailable: ...")``."""
    own_engine = engine is None and plan.kind in ("overture", "overture_file")
    if own_engine:
        engine = IbisEngine()
    try:
        n = _count(action, plan, settings, http, engine)
    except Exception as exc:  # boundary: a failed pre-query is reported; the user may still choose to run
        return Estimate(
            seconds=None, out_bytes=None, n_elements=None, basis=f"unavailable: {type(exc).__name__}: {exc}"
        )
    finally:
        if own_engine:
            engine.close()
    return estimate_build(plan.kind, n, output_format=action.output_format)


def _osm_records(action: BuildNetwork, plan: BuildPlan, settings: Settings, http: Any, tick: Tick) -> Records:
    convert = optional_module("gmnspy.osm.convert", "osm")
    local = optional_module("gmnspy.osm.local", "osm")
    query = optional_module("gmnspy.osm.query", "osm")
    if plan.input_path is not None:
        nodes, ways = local.read_osm_file(plan.input_path, network_type=action.network_type)
    else:
        assert action.area is not None
        q = query.build_overpass_query(
            bbox=action.area.to_bbox(),
            polygon=action.area.to_polygon(),
            network_type=action.network_type,
            timeout=settings.osm.timeout,
        )
        options = {"timeout": settings.osm.timeout, "retries": settings.osm.retries, **_osm_options(settings)}
        nodes, ways = query.parse_overpass_elements(query.fetch_osm(q, session=http, **options))
    tick("convert", 0.5)
    return convert.build_node_link_tables(nodes, ways, extra_tags=action.extra_tags)


def _overture_records(action: BuildNetwork, plan: BuildPlan, settings: Settings, engine: Any, tick: Tick) -> Records:
    convert = optional_module("gmnspy.overture.convert", "overture")
    query = optional_module("gmnspy.overture.query", "overture")
    read = _overture_read(action, plan, settings)
    bbox = read.pop("bbox")
    segments = query.read_segments(
        bbox, network_type=action.network_type, extra_tags=action.extra_tags, engine=engine, **read
    )
    connectors = query.read_connectors(bbox, engine=engine, **read)
    tick("convert", 0.5)
    return convert.build_node_link_tables(segments, connectors, extra_tags=action.extra_tags)


def fetch_and_convert(
    action: BuildNetwork,
    plan: BuildPlan,
    settings: Settings,
    ctx: JobContext,
    *,
    estimate: Estimate,
    http: Any,
    engine: Any,
) -> Network:
    """Stages ``query`` and ``convert``: read the source and assemble the GMNS network on ``engine``.

    Raises:
        ActionError: the fetch/read failed, or nothing matched ``network_type`` in the area.
    """
    started = time.time()

    def tick(stage: str, progress: float) -> None:
        eta = None if estimate.seconds is None else max(estimate.seconds - (time.time() - started), 0.0)
        ctx.stage(stage, progress=progress, eta_s=eta)

    try:
        tick("query", 0.1)
        if action.source == "osm":
            node_records, link_records = _osm_records(action, plan, settings, http, tick)
        else:
            node_records, link_records = _overture_records(action, plan, settings, engine, tick)
    except (ValueError, LookupError, OSError) as exc:
        # The same set `gmnspy build` reports: bad network_type / malformed input / missing connector
        # (ValueError, LookupError) and Overpass or object-store I/O (requests' errors subclass OSError).
        raise ActionError(f"build failed: {exc}") from exc
    if not link_records:
        raise ActionError(f"nothing in this {action.source} area matched network_type={action.network_type!r}")
    return network_from_records(
        node_records,
        link_records,
        spec_version=action.spec_version or settings.io.spec_version,
        engine=engine,
        dataset_name=f"{action.source}_export",
    )


def write_output(net: Network, plan: BuildPlan, output_format: str, ctx: JobContext) -> None:
    """Stage ``write``: persist ``net`` at ``plan.dest``; on failure remove the partial output and re-raise."""
    ctx.stage("write", progress=0.75)
    try:
        net.write(plan.dest, format=output_format)
    except BaseException:
        if plan.dest.is_dir():
            shutil.rmtree(plan.dest)
        elif plan.dest.exists():
            plan.dest.unlink()
        raise
```

- [ ] **Step 5: Wire the build job into `packages/gmnspy/gmnspy/workbench/session.py`**

Make these edits:
- Above `from gmnspy import Network`, add `from datagrove.engines.ibis_engine import IbisEngine` followed by a blank line.
- Above `from .actions import (`, add `from . import build`.
- In the `from .actions import (...)` list, add `BuildNetwork,` after `Action,`.
- Replace `from .errors import ActionError, JobCancelled, NotSupportedYet, PathNotAllowed` with these two lines:

```python
from .errors import ActionError, ApprovalRequired, JobCancelled, NotSupportedYet, PathNotAllowed
from .estimate import Estimate, needs_approval
```

- Add `"ApprovalRequired"` to `__all__`, after `"ActionError"`.
- In `dispatch`, directly after `return entry.result`, insert:

```python
        if entry.error_type == "ApprovalRequired":
            raise ApprovalRequired(Estimate(**entry.result["estimate"]), entry.result["threshold_s"])
```

- In `submit`, replace `label = f"open {default_label(action.source)}"` with:

```python
        label = f"build {action.name}" if isinstance(action, BuildNetwork) else f"open {default_label(action.source)}"
```

- Insert this method directly above `def _do_close_network(`:

```python
    def _job_build_network(self, action: BuildNetwork, ctx: JobContext) -> dict[str, Any]:
        settings = self.settings
        plan = build.plan_build(action, settings)
        engine = IbisEngine()  # private connection: never shared with the networks the browser reads
        try:
            ctx.stage("estimate", progress=0.0)
            estimate = build.estimate_for(action, plan, settings, http=self.http, engine=engine)
            threshold = settings.app.approve_above_s
            if not action.approved and needs_approval(estimate, threshold):
                raise ApprovalRequired(estimate, threshold)
            net = build.fetch_and_convert(action, plan, settings, ctx, estimate=estimate, http=self.http, engine=engine)
            build.write_output(net, plan, action.output_format, ctx)
        finally:
            engine.close()
        ctx.stage("open", progress=0.9)
        loaded, frames = self._load(str(plan.dest), action.spec_version or settings.io.spec_version)
        ctx.stage("register", progress=0.95)
        handle = self._register(loaded, frames, source=str(plan.dest), label=action.label or action.name)
        return {"net_id": handle.id, "output": str(plan.dest), "estimate": estimate.to_dict()}
```

- [ ] **Step 6: Export the new public names from `packages/gmnspy/gmnspy/workbench/__init__.py`**

Replace everything from `from .actions import (` up to (not including) `if TYPE_CHECKING:` with:

```python
from .actions import (
    BuildNetwork,
    ClearSelection,
    CloseNetwork,
    Navigate,
    OpenNetwork,
    Select,
    SetActiveNetwork,
    SetSetting,
    Style,
)
from .area import BboxArea, PlaceArea, PointArea
from .errors import ActionError, ApprovalRequired, JobCancelled, NotSupportedYet, PathNotAllowed
from .session import Session
```

and replace `__all__` with:

```python
__all__ = [
    "ActionError",
    "ApprovalRequired",
    "BboxArea",
    "BuildNetwork",
    "ClearSelection",
    "CloseNetwork",
    "JobCancelled",
    "Navigate",
    "NotSupportedYet",
    "OpenNetwork",
    "PathNotAllowed",
    "PlaceArea",
    "PointArea",
    "Select",
    "Session",
    "SetActiveNetwork",
    "SetSetting",
    "Style",
    "build_app",
    "serve",
]
```

`test_history_python_replays_to_same_state` builds its exec namespace from `__all__`, so `BuildNetwork` must be
listed for a recorded build to replay.

- [ ] **Step 7: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_session_jobs.py packages/gmnspy/tests/test_workbench_actions.py packages/gmnspy/tests/test_workbench_session.py -q`
Expected: `55 passed` (17 + 16 + 22).

- [ ] **Step 8: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/actions.py packages/gmnspy/gmnspy/workbench/build.py \
  packages/gmnspy/gmnspy/workbench/session.py packages/gmnspy/gmnspy/workbench/__init__.py \
  packages/gmnspy/tests/test_workbench_session_jobs.py packages/gmnspy/tests/test_workbench_actions.py
git commit -m "feat(workbench): BuildNetwork job: estimate + approval gate, always write then open from disk"
```

---

### Task 14: Read-only wizard routes, jobs routes, and `202` for job actions

**Files:**
- Create: `packages/gmnspy/gmnspy/workbench/routes/io.py`
- Modify: `packages/gmnspy/gmnspy/workbench/routes/core.py`, `packages/gmnspy/gmnspy/workbench/server.py`
- Test: `packages/gmnspy/tests/test_workbench_io_routes.py`

- [ ] **Step 1: Write the failing tests in `packages/gmnspy/tests/test_workbench_io_routes.py`**

```python
"""Tests for the wizard's read-only routes, the jobs routes, and job actions over HTTP (no network)."""

from pathlib import Path

import pytest
from datagrove.io import credentials as creds_mod
from fastapi.testclient import TestClient
from gmnspy.select.parse import StubParser
from gmnspy.workbench import Session, build_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OSM_FILE = str(FIXTURES / "osm" / "tiny.osm")
WAIT = 10.0


class FakeNominatim:
    def __init__(self, hits=None, error=None):
        self.hits, self.error = hits or [], error

    def get(self, url, params=None, headers=None, timeout=None):
        if self.error:
            raise self.error
        hits = self.hits

        class R:
            status_code = 200

            def json(self):
                return hits

            def raise_for_status(self):
                pass

        return R()


@pytest.fixture
def make_client(tmp_path, isolated_env):
    def make(http=None, **overrides):
        session = Session(
            project_dir=tmp_path, environ=isolated_env, parser=StubParser(), http=http, overrides=overrides
        )
        return session, TestClient(build_app(session))

    return make


@pytest.fixture
def out_dir(tmp_path):
    (tmp_path / "out").mkdir()
    return str(tmp_path / "out")


def _build_body(out_dir, **kw):
    return {
        "type": "build_network",
        "source": "osm",
        "input_file": OSM_FILE,
        "output_dir": out_dir,
        "output_format": "parquet",
        "name": "tiny",
        **kw,
    }


def test_fs_list_tags_entries(make_client):
    _, client = make_client()
    listing = client.get("/api/fs/list", params={"path": str(FIXTURES)}).json()
    kinds = {e["name"]: e["kind"] for e in listing["entries"]}
    assert kinds["overture"] == "overture" and kinds["osm"] is None


def test_fs_list_without_path_lists_roots(make_client, tmp_path):
    _, client = make_client()
    paths = [e["path"] for e in client.get("/api/fs/list").json()["entries"]]
    assert str(tmp_path.resolve()) in paths


def test_fs_list_outside_roots_is_403(make_client, tmp_path_factory):
    _, client = make_client()
    r = client.get("/api/fs/list", params={"path": str(tmp_path_factory.mktemp("other"))})
    assert r.status_code == 403 and "outside the allowed folders" in r.json()["detail"]


def test_fs_list_missing_is_404(make_client, tmp_path):
    _, client = make_client()
    assert client.get("/api/fs/list", params={"path": str(tmp_path / "nope")}).status_code == 404


def test_check_url_reports_without_network(make_client, monkeypatch):
    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_keyring", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: {})
    _, client = make_client()
    r = client.post("/api/check-url", json={"url": "ftp://example.org/x"})
    assert r.status_code == 200 and r.json()["reachable"] is False and r.json()["credential_source"] == "none"
    assert client.post("/api/check-url", json={}).status_code == 422


def test_check_url_respects_the_origin_guard(make_client):
    _, client = make_client()
    r = client.post("/api/check-url", json={"url": "s3://b/k"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_reads_respect_the_host_guard(make_client):
    _, client = make_client()
    assert client.get("/api/fs/list", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 400


def test_geocode_returns_candidates(make_client):
    hit = {"display_name": "Durham", "type": "city", "boundingbox": ["35.8", "36.1", "-79.0", "-78.7"]}
    _, client = make_client(http=FakeNominatim([hit]))
    (cand,) = client.get("/api/geocode", params={"q": "Durham"}).json()["candidates"]
    assert cand["bbox"] == [-79.0, 35.8, -78.7, 36.1] and cand["polygon"] is None


def test_geocode_failure_is_502(make_client):
    _, client = make_client(http=FakeNominatim(error=OSError("nominatim down")))
    r = client.get("/api/geocode", params={"q": "Durham"})
    assert r.status_code == 502 and "nominatim down" in r.json()["detail"]


def test_estimate_local_osm(make_client, out_dir):
    _, client = make_client()
    j = client.post("/api/estimate", json=_build_body(out_dir)).json()
    assert j["estimate"]["basis"].startswith("osm_file:") and j["needs_approval"] is False and j["threshold_s"] == 90.0


def test_estimate_over_threshold_flags_approval(make_client, out_dir):
    _, client = make_client(**{"app.approve_above_s": 0})
    assert client.post("/api/estimate", json=_build_body(out_dir)).json()["needs_approval"] is True


def test_estimate_invalid_and_unplannable(make_client, out_dir):
    _, client = make_client()
    assert client.post("/api/estimate", json={"source": "osm"}).status_code == 422
    r = client.post("/api/estimate", json=_build_body(out_dir, output_format="zip"))
    assert r.status_code == 400 and r.json()["error_type"] == "NotSupportedYet"


def test_estimate_is_not_recorded(make_client, out_dir):
    session, client = make_client()
    client.post("/api/estimate", json=_build_body(out_dir))
    assert session.history == []


def test_job_action_answers_202_then_finishes(make_client, out_dir):
    session, client = make_client()
    r = client.post("/api/actions", json=_build_body(out_dir))
    assert r.status_code == 202
    job_id = r.json()["result"]["job_id"]
    assert r.json()["job"]["id"] == job_id and r.json()["job"]["kind"] == "build_network"
    assert session.jobs.get(job_id).wait(WAIT)
    (listed,) = client.get("/api/jobs").json()["jobs"]
    assert listed["status"] == "done" and listed["history_seq"] == 1
    assert session.history[0].ok and len(session.registry) == 1


def test_cancel_route(make_client, out_dir):
    session, client = make_client()
    job_id = client.post("/api/actions", json=_build_body(out_dir)).json()["result"]["job_id"]
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["id"] == job_id
    assert session.jobs.get(job_id).wait(WAIT)
    assert client.post("/api/jobs/job-404/cancel").status_code == 404
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_io_routes.py -q`
Expected: most tests fail with `404 Not Found` on the new routes. `test_job_action_answers_202_then_finishes`
fails with `assert 200 == 202`.

- [ ] **Step 3: Create `packages/gmnspy/gmnspy/workbench/routes/io.py`**

```python
"""Read-only helpers for the Open / Import wizard, plus the jobs list and cancel.

None of these are recorded as actions: browsing, checking a URL, searching for a place, and
estimating a build change no session state. (Cancel acts on a job, not on the session; the
cancelled action is recorded when its job ends.) All of them sit behind the app-wide loopback
Host/Origin guard in :mod:`gmnspy.workbench.server`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .. import build
from ..actions import BuildNetwork
from ..errors import ActionError, PathNotAllowed
from ..estimate import needs_approval
from ..extras import optional_module
from ..files import list_dir
from ..session import Session
from ..urlcheck import check_url

__all__ = ["io_router"]


def io_router(session: Session) -> APIRouter:
    """Build the wizard/jobs router bound to ``session``."""
    router = APIRouter(prefix="/api")

    @router.get("/fs/list")
    def fs_list(path: str | None = None) -> dict[str, Any]:
        """List a folder inside ``io.allowed_roots`` (no ``path``: the roots themselves)."""
        try:
            return list_dir(path, session.settings)
        except PathNotAllowed as exc:
            raise HTTPException(403, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except NotADirectoryError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/check-url")
    def check(body: dict = Body(...)) -> dict[str, Any]:  # noqa: B008  (FastAPI Body default)
        """Reachability, credential *source* name, and tables for a remote GMNS URL."""
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            raise HTTPException(422, 'body must be {"url": "..."}')
        return check_url(url.strip())

    @router.get("/geocode")
    def geocode(q: str, limit: int = 8) -> dict[str, Any]:
        """Nominatim place candidates (bbox + simplified outline) for the Area step."""
        try:
            osm_query = optional_module("gmnspy.osm.query", "osm")
        except ActionError as exc:
            raise HTTPException(501, str(exc)) from exc
        osm = session.settings.osm
        try:
            found = osm_query.geocode_candidates(
                q, limit=max(1, min(limit, 20)), session=session.http, user_agent=osm.user_agent or osm_query.USER_AGENT
            )
        except Exception as exc:  # boundary: a geocoder failure is shown to the user, not a 500
            raise HTTPException(502, f"place search failed: {type(exc).__name__}: {exc}") from exc
        return {"candidates": found}

    @router.post("/estimate")
    def estimate(body: dict = Body(...)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
        """Size a ``build_network`` request (pre-query + model) without running it."""
        try:
            action = BuildNetwork.model_validate({k: v for k, v in body.items() if k != "type"})
        except ValidationError as exc:
            detail = exc.errors(include_url=False, include_context=False)
            return JSONResponse({"error": "invalid build", "detail": jsonable_encoder(detail)}, status_code=422)
        settings = session.settings
        try:
            plan = build.plan_build(action, settings)
        except ActionError as exc:
            return JSONResponse({"error": str(exc), "error_type": type(exc).__name__}, status_code=400)
        est = build.estimate_for(action, plan, settings, http=session.http)
        threshold = settings.app.approve_above_s
        return JSONResponse(
            {"estimate": est.to_dict(), "needs_approval": needs_approval(est, threshold), "threshold_s": threshold}
        )

    @router.get("/jobs")
    def jobs() -> dict[str, Any]:
        """Every background job this session started, newest first."""
        return {"jobs": jsonable_encoder(session.jobs.snapshots())}

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        """Request cancellation; it takes effect at the job's next stage boundary."""
        try:
            return jsonable_encoder(session.jobs.cancel(job_id))
        except KeyError as exc:
            raise HTTPException(404, exc.args[0]) from exc

    return router
```

- [ ] **Step 4: Answer job actions with `202` in `packages/gmnspy/gmnspy/workbench/routes/core.py`**

Add `from ..actions import parse_action` above `from ..events import sse_format`. Replace:

```python
    @router.post("/actions")
    def actions(body: dict = Body(...)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
        try:
            entry = session.dispatch_recorded(body)
        except ValidationError as exc:
            detail = exc.errors(include_url=False, include_context=False)
            return JSONResponse({"error": "invalid action", "detail": jsonable_encoder(detail)}, status_code=422)
```

with:

```python
    @router.post("/actions")
    def actions(body: dict = Body(...)) -> JSONResponse:  # noqa: B008  (FastAPI Body default)
        """Apply an action. A job action (open/build) answers 202 with its job; the outcome arrives over SSE."""
        try:
            action = parse_action(body)
        except ValidationError as exc:
            detail = exc.errors(include_url=False, include_context=False)
            return JSONResponse({"error": "invalid action", "detail": jsonable_encoder(detail)}, status_code=422)
        if action.runs_as_job:
            job = session.submit(action)
            payload = {"ok": True, "result": {"job_id": job.id}, "job": session.jobs.snapshot(job)}
            return JSONResponse(jsonable_encoder(payload), status_code=202)
        entry = session.dispatch_recorded(action)
```

The `payload = ...` and `return JSONResponse(...)` lines that follow are unchanged.

- [ ] **Step 5: Mount the router in `packages/gmnspy/gmnspy/workbench/server.py`**

Add `from .routes.io import io_router` after `from .routes.core import core_router`, and
`app.include_router(io_router(session))` after `app.include_router(core_router(session))`.

- [ ] **Step 6: Run the tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_io_routes.py packages/gmnspy/tests/test_workbench_server.py -q`
Expected: `37 passed` (15 + 22).

- [ ] **Step 7: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/routes/io.py packages/gmnspy/gmnspy/workbench/routes/core.py \
  packages/gmnspy/gmnspy/workbench/server.py packages/gmnspy/tests/test_workbench_io_routes.py
git commit -m "feat(workbench): fs/check-url/geocode/estimate/jobs routes; job actions answer 202"
```

---

### Task 15: Front-end shell: header buttons, Recent, the jobs panel, the wizard markup

This task removes `#open-src`/`#open-go` and adds the **Open / Import…** button (wired in Task 16), the
**Recent** dropdown, and the **Jobs** indicator and panel, plus the static markup for the wizard modal.

**Files:**
- Modify: `packages/gmnspy/gmnspy/workbench/static/index.html` (replace the whole file), `static/app.css`
- Modify: `static/js/api.js` (replace), `static/js/header.js` (replace), `static/js/main.js` (replace),
  `static/js/store.js`, `static/js/history.js`
- Create: `static/js/jobs.js`
- Test: `packages/gmnspy/tests/test_workbench_static.py`

- [ ] **Step 1: Append the failing test to `packages/gmnspy/tests/test_workbench_static.py`**

```python
def test_header_has_open_import_recent_and_jobs_not_the_path_box():
    html = (STATIC_DIR / "index.html").read_text()
    for element_id in ("open-wizard", "recent", "jobs-btn", "jobs-panel", "wizard"):
        assert f'id="{element_id}"' in html
    assert 'id="open-src"' not in html and 'id="open-go"' not in html
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: `1 failed, 16 passed`, `AssertionError` on `id="open-wizard"`.

- [ ] **Step 3: Replace `packages/gmnspy/gmnspy/workbench/static/index.html` with**

Every element id that the Task 16 modules look up is already here. `test_every_element_id_used_by_js_exists_in_index`
enforces that from then on.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>GMNSpy Workbench</title>
<link href="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
<link href="/static/app.css" rel="stylesheet" />
<script src="https://cdn.jsdelivr.net/npm/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://cdn.jsdelivr.net/npm/deck.gl@9.0.38/dist.min.js"></script>
<script type="module" src="/static/js/main.js"></script>
</head>
<body>
<div id="app">
  <header>
    <h1>GMNSpy Workbench</h1>
    <select id="net-select" aria-label="Active network"></select>
    <button id="open-wizard" class="mini">Open / Import…</button>
    <select id="recent" aria-label="Recent networks"></select>
    <div id="viewmode">
      <button data-mode="map" class="on">Map</button>
      <button data-mode="split">Split</button>
      <button data-mode="table">Table</button>
    </div>
    <input id="utterance" placeholder='e.g. "I-40 EB between South Miami Boulevard and Airport Boulevard"' aria-label="Selection utterance" />
    <button id="go">Select</button>
    <span id="count"></span>
    <button id="jobs-btn" class="mini ghost" aria-label="Background jobs">Jobs <span id="jobs-count" class="pcount">0</span></button>
  </header>
  <div id="stage" data-mode="map">
    <div id="map">
      <div id="map-btns">
        <button class="iconbtn" id="btn-highlight" data-tip="Highlight links (click; shift-drag box)" aria-label="Highlight links">&#9647;</button>
        <button class="iconbtn" id="btn-fitnet" data-tip="Zoom to full network" aria-label="Zoom to full network">&#9974;</button>
        <button class="iconbtn" id="btn-fitsel" data-tip="Zoom to selection" aria-label="Zoom to selection">&#9673;</button>
        <button class="iconbtn" id="btn-layers" data-tip="Layers" aria-label="Layers">&#9635;</button>
        <button class="iconbtn" id="btn-settings" data-tip="Map settings" aria-label="Map settings">&#9881;</button>
      </div>
      <div class="panel" id="layers-panel">
        <h4>Layers</h4>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-links"><span></span></label>
          <span class="lbl">Links</span><input type="color" class="swatch" id="col-links"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-nodes"><span></span></label>
          <span class="lbl">Nodes</span><input type="color" class="swatch" id="col-nodes"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-selection"><span></span></label>
          <span class="lbl">Selection</span><input type="color" class="swatch" id="col-selection"></div>
        <div class="row"><label class="sw"><input type="checkbox" id="tg-labels"><span></span></label>
          <span class="lbl">Basemap labels</span></div>
        <h4 style="margin-top:14px">Color links by</h4>
        <div class="row"><select id="colorby"><option value="none">None (single color)</option></select></div>
        <div class="row" id="ramp-row" style="display:none"><span class="lbl">Ramp</span>
          <select id="ramp"><option>YlOrRd</option><option>Blues</option><option>Viridis</option></select></div>
      </div>
      <div class="panel" id="settings-panel">
        <h4>Map settings</h4>
        <div class="row"><span class="lbl">Offset directions</span>
          <label class="sw"><input type="checkbox" id="tg-offset"><span></span></label></div>
        <div class="row"><span class="lbl">Show direction</span>
          <label class="sw"><input type="checkbox" id="tg-direction"><span></span></label></div>
        <div class="row"><span class="lbl">Show legend</span>
          <label class="sw"><input type="checkbox" id="tg-legend"><span></span></label></div>
      </div>
      <div id="legend"></div>
      <div id="boxsel"></div>
    </div>
    <div id="tablepane">
      <div id="tbl-rail"></div>
      <div id="tbl-main">
        <div id="tbl-bar"><span class="tname" id="tbl-name">—</span><span id="tbl-total"></span>
          <label class="sw" style="margin-left:auto"><input type="checkbox" id="tbl-tosel"><span></span></label>
          <span>Filter to map selection</span></div>
        <div id="tbl-grid-wrap"><table id="tbl-grid"></table></div>
        <div id="tbl-pager"><button id="tbl-prev">&#8592; Prev</button>
          <span id="tbl-range">—</span><button id="tbl-next">Next &#8594;</button></div>
      </div>
    </div>
  </div>
  <aside id="side">
    <div id="status-wrap"></div>
    <div class="label">Highlighted links <span id="hl-count" class="pcount">0</span></div>
    <div id="hl-wrap">
      <span class="empty" id="hl-hint">Turn on <b>Highlight links</b> (&#9647;), then click links or shift-drag a box.</span>
      <div id="hl-actions" style="display:none">
        <button class="mini" id="hl-set">Set as selection</button>
        <button class="mini ghost" id="hl-clear">Clear highlights</button>
      </div>
    </div>
    <div class="label">Link details</div>
    <div id="details"><span class="empty">Click a link on the map.</span></div>
    <div class="label">Anchors</div>
    <div id="anchors"><span class="empty">—</span></div>
    <div class="label">Fragment</div>
    <pre id="fragment">—</pre>
    <div class="label">Diagnostics</div>
    <div id="diag"><span class="empty">—</span></div>
  </aside>
  <footer id="history">
    <span id="hist-seq">—</span>
    <code id="hist-py">No actions yet.</code>
    <button class="mini ghost" id="hist-copy">Copy</button>
    <button class="mini ghost" id="hist-all">Session as Python</button>
  </footer>
</div>
<div class="panel" id="hist-panel">
  <h4>Session as Python</h4>
  <pre id="hist-script"></pre>
  <div class="row"><button class="mini" id="hist-copy-all">Copy all</button></div>
</div>
<div class="panel" id="jobs-panel">
  <h4>Jobs</h4>
  <div id="jobs-list"><span class="empty">No jobs yet.</span></div>
</div>
<div id="wizard" class="modal" role="dialog" aria-modal="true" aria-labelledby="wz-title" hidden>
  <div class="modal-card">
    <div class="modal-head">
      <h3 id="wz-title">Open / Import</h3>
      <button class="mini ghost" id="wz-close" aria-label="Close">&#10005;</button>
    </div>
    <div class="modal-body">
      <section class="wz-step" data-step="source">
        <button class="wz-choice" data-src="local"><b>GMNS on this machine</b><span>A folder, .zip, .duckdb, or datapackage.json</span></button>
        <button class="wz-choice" data-src="url"><b>GMNS at a URL</b><span>s3://, gs://, az://, or https://</span></button>
        <button class="wz-choice" data-src="osm"><b>Build from OpenStreetMap</b><span>Draw an area, search a place, or use a local .osm / Overpass .json file</span></button>
        <button class="wz-choice" data-src="overture"><b>Build from Overture</b><span>Draw an area, search a place, or use a local snapshot folder</span></button>
      </section>
      <section class="wz-step" data-step="local" hidden>
        <p class="wz-note">Pick a GMNS folder, .zip, .duckdb, or datapackage.json. It opens in place; nothing is uploaded.</p>
        <div class="fb" id="wz-local-fb"></div>
      </section>
      <section class="wz-step" data-step="url" hidden>
        <div class="row">
          <input id="wz-url" class="grow" placeholder="s3://bucket/network/" aria-label="Network URL" />
          <button class="mini" id="wz-check">Check</button>
        </div>
        <div id="wz-url-result" class="wz-note"></div>
      </section>
      <section class="wz-step" data-step="area" hidden>
        <div class="tabs" id="ap-tabs">
          <button data-tab="draw" class="on">Draw</button><button data-tab="coords">Coordinates</button><button
            data-tab="place">Place</button><button data-tab="file">Local file</button>
        </div>
        <div class="ap-pane" data-pane="draw">
          <button class="mini" id="ap-draw">Draw</button>
          <span class="wz-note">then drag a rectangle on the map; drag a corner to adjust it.</span>
        </div>
        <div class="ap-pane" data-pane="coords" hidden>
          <div class="row"><label for="ap-bbox">W,S,E,N</label>
            <input id="ap-bbox" class="grow" placeholder="-78.95,35.95,-78.85,36.05" /></div>
          <div class="row"><label for="ap-point">or lat,lon</label>
            <input id="ap-point" class="grow" placeholder="35.99,-78.90" />
            <input id="ap-buffer" type="number" min="1" step="100" aria-label="Buffer in metres" /> m</div>
          <button class="mini" id="ap-apply">Preview</button>
        </div>
        <div class="ap-pane" data-pane="place" hidden>
          <div class="row"><input id="ap-q" class="grow" placeholder="Durham, North Carolina" aria-label="Place" />
            <button class="mini" id="ap-search">Search</button></div>
          <div id="ap-cands"></div>
        </div>
        <div class="ap-pane" data-pane="file" hidden>
          <p class="wz-note" id="ap-file-note"></p>
          <div class="fb" id="ap-file-fb"></div>
        </div>
        <div id="ap-map"></div>
        <div id="ap-summary" class="wz-note"></div>
      </section>
      <section class="wz-step" data-step="options" hidden>
        <div class="form">
          <label for="opt-network-type">Network type</label>
          <select id="opt-network-type"><option>drive</option><option>walk</option><option>bike</option><option>all</option></select>
          <label for="opt-extra-tags">Extra tags</label><input id="opt-extra-tags" placeholder="surface, maxheight" />
          <label for="opt-spec">GMNS spec version</label><input id="opt-spec" />
          <label for="opt-release" class="ovt-only">Overture release</label><input id="opt-release" class="ovt-only" />
          <label for="opt-name">Output name</label><input id="opt-name" placeholder="durham-osm" />
          <label for="opt-format">Output format</label>
          <select id="opt-format"><option value="parquet">Parquet folder</option><option value="csv">CSV folder</option>
            <option value="duckdb">DuckDB file</option><option value="zip" disabled>Zip (not yet)</option></select>
          <label>Output folder</label><code id="opt-outdir">choose below</code>
        </div>
        <div class="fb" id="opt-out-fb"></div>
      </section>
      <section class="wz-step" data-step="run" hidden>
        <div id="wz-estimate" class="wz-note"></div>
      </section>
    </div>
    <div class="modal-foot">
      <button class="mini ghost" id="wz-back">Back</button>
      <button class="mini" id="wz-next">Next</button>
    </div>
  </div>
</div>
<div id="toast" role="status"></div>
</body>
</html>
```

- [ ] **Step 4: Update `packages/gmnspy/gmnspy/workbench/static/app.css`**

Replace:

```css
  #open-src { width:220px; padding:8px 10px; border:1px solid var(--edge); border-radius:8px;
              background:#0c0e12; color:var(--ink); }
```

with:

```css
  #recent { background:#0c0e12; color:var(--ink); border:1px solid var(--edge); border-radius:8px;
            padding:7px 8px; max-width:160px; }
```

and append:

```css
  /* ---- P1a: jobs + Open / Import wizard ---- */
  [hidden] { display:none !important; }
  #jobs-btn.busy { color:var(--hl); border-color:var(--hl); }
  #jobs-panel { position:fixed; top:56px; right:12px; width:340px; max-height:60vh; overflow:auto; z-index:6; }
  .job { display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid var(--edge); }
  .job-text { flex:1; min-width:0; }
  .job-label { font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .job-detail { color:var(--muted); font-size:12px; }
  .job.failed .job-detail, .job.cancelled .job-detail { color:var(--to); }
  .modal { position:fixed; inset:0; z-index:20; background:rgba(0,0,0,.55); display:flex;
           align-items:center; justify-content:center; }
  .modal-card { width:min(760px, calc(100vw - 32px)); max-height:calc(100vh - 32px); display:flex; flex-direction:column;
                background:var(--panel); border:1px solid var(--edge); border-radius:12px; }
  .modal-head, .modal-foot { display:flex; align-items:center; gap:10px; padding:12px 16px; }
  .modal-head { border-bottom:1px solid var(--edge); }
  .modal-head h3 { margin:0; font-size:15px; flex:1; }
  .modal-foot { border-top:1px solid var(--edge); justify-content:space-between; }
  .modal-body { padding:14px 16px; overflow:auto; }
  .modal input, .modal select { background:#0c0e12; color:var(--ink); border:1px solid var(--edge); border-radius:6px;
                                padding:6px 8px; font-size:13px; }
  .wz-choice { display:flex; flex-direction:column; align-items:flex-start; gap:2px; width:100%; margin:0 0 8px;
               background:#0c0e12; color:var(--ink); border:1px solid var(--edge); text-align:left; }
  .wz-choice:hover { border-color:var(--accent); }
  .wz-choice span, .wz-note, .muted { color:var(--muted); font-size:12.5px; font-weight:400; }
  .err { color:var(--to); }
  .tabs { display:flex; gap:4px; margin-bottom:10px; }
  .tabs button { background:#0c0e12; color:var(--muted); border:1px solid var(--edge); padding:6px 12px; font-size:12.5px; }
  .tabs button.on { background:var(--accent); color:#11151a; }
  #ap-draw.on { background:var(--hl); }
  #ap-buffer { width:90px; }
  #ap-map { height:320px; margin-top:10px; border:1px solid var(--edge); border-radius:8px; }
  #ap-cands { max-height:150px; overflow:auto; margin-top:6px; }
  .cand { padding:5px 8px; cursor:pointer; border-radius:6px; font-size:12.5px; }
  .cand:hover, .cand.on { background:#20242e; }
  .form { display:grid; grid-template-columns:150px 1fr; gap:8px 12px; align-items:center; margin-bottom:12px; }
  .fb { border:1px solid var(--edge); border-radius:8px; }
  .fb-bar { display:flex; align-items:center; gap:8px; padding:6px 8px; border-bottom:1px solid var(--edge); }
  .fb-path { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; color:var(--muted); }
  .fb-list { max-height:260px; overflow:auto; }
  .fb-row { display:flex; align-items:center; gap:8px; padding:5px 10px; cursor:pointer; font-size:12.5px; color:var(--muted); }
  .fb-row:hover { background:#20242e; }
  .fb-row.ok { color:var(--ink); }
  .fb-row.on { background:rgba(255,140,59,.16); }
  .fb-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .fb-kind { font-size:11px; padding:1px 7px; border-radius:999px; background:#20242e; color:var(--hl); }
```

- [ ] **Step 5: Replace `static/js/api.js` with**

This adds `postJSON` and documents that a job action resolves to `{job_id}`.

```javascript
// Fetch + SSE client for the workbench API. Every state change goes through dispatch().
async function readJSON(r) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    // FastAPI's own 422 `detail` is an array of error objects, not a string;
    // stringify it so the toast shows something readable instead of "[object Object]".
    const detail = typeof j.detail === "string" ? j.detail : j.detail != null ? JSON.stringify(j.detail) : undefined;
    throw new Error(j.error || detail || r.statusText);
  }
  return j;
}

export const getJSON = path => fetch(path).then(readJSON);

export async function postJSON(path, body) {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return readJSON(r);
}

export async function getBuffer(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.arrayBuffer();
}

// Resolves to the action's result. A job action (open/build) resolves at once to {job_id};
// its outcome arrives later as `job` + `history` + `state` SSE events.
export async function dispatch(action) {
  return (await postJSON("/api/actions", action)).result;
}

export const netPath = (netId, rest) => `/api/n/${encodeURIComponent(netId)}/roadway/${rest}`;

export function subscribe(handlers) {
  const source = new EventSource("/api/events");
  for (const [type, fn] of Object.entries(handlers)) source.addEventListener(type, e => fn(JSON.parse(e.data)));
  return source;
}
```

- [ ] **Step 6: Create `static/js/jobs.js`**

```javascript
// Background jobs: header indicator + panel, kept live by SSE `job` events; Cancel posts to the jobs route.
import { getJSON, postJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";

const jobs = new Map();

function row(j) {
  const pct = j.progress == null ? "" : ` ${Math.round(j.progress * 100)}%`;
  const eta = j.eta_s ? ` · ~${Math.ceil(j.eta_s)} s left` : "";
  const detail = j.status === "running" ? `${esc(j.stage)}${pct}${eta}${j.cancel_requested ? " · cancelling" : ""}`
    : j.status === "done" ? "done" : `${esc(j.status)}: ${esc(j.error || "")}`;
  const cancel = j.status === "running" && !j.cancel_requested
    ? `<button class="mini ghost" data-cancel="${esc(j.id)}">Cancel</button>` : "";
  return `<div class="job ${esc(j.status)}"><div class="job-text"><div class="job-label">${esc(j.label)}</div>` +
    `<div class="job-detail">${detail}</div></div>${cancel}</div>`;
}

function render() {
  const list = [...jobs.values()].sort((a, b) => b.started - a.started);
  const running = list.filter(j => j.status === "running").length;
  $("jobs-count").textContent = running;
  $("jobs-btn").classList.toggle("busy", running > 0);
  $("jobs-list").innerHTML = list.length ? list.map(row).join("") : '<span class="empty">No jobs yet.</span>';
}

export function onJob(job) {
  const before = jobs.get(job.id);
  jobs.set(job.id, job);
  render();
  const newlyEnded = !before || before.status === "running";
  if (newlyEnded && job.status === "failed") toast(`${job.label}: ${job.error}`);
}

export function openJobsPanel() { $("jobs-panel").classList.add("open"); }

export async function loadJobs() {
  for (const j of (await getJSON("/api/jobs")).jobs) jobs.set(j.id, j);
  render();
}

export function wireJobs() {
  $("jobs-btn").onclick = () => $("jobs-panel").classList.toggle("open");
  $("jobs-list").onclick = async e => {
    const id = e.target.dataset && e.target.dataset.cancel;
    if (!id) return;
    try { onJob(await postJSON(`/api/jobs/${encodeURIComponent(id)}/cancel`, {})); } catch (err) { toast(err.message); }
  };
}
```

- [ ] **Step 7: Replace `static/js/header.js` with**

This version drops the path box and adds Recent. Task 16 adds the wizard button's handler.

```javascript
// Header: network switcher, Open / Import… and Recent, and the utterance box. All via actions.
import { dispatch } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { fitLinks } from "./map.js";

// Recents live in this browser's localStorage: a per-user convenience that needs no server code.
// They are only shortcuts: re-opening one is a normal open_network action, checked against io.allowed_roots.
const RECENT_KEY = "gmnspy.workbench.recent";
const RECENT_MAX = 10;

async function run(action, after) {
  try { const result = await dispatch(action); if (after) after(result); } catch (e) { toast(e.message); }
}

function loadRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch (e) { return []; }
}

function saveRecent(list) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (e) { /* storage unavailable: recents aren't kept */ }
}

export function renderRecent() {
  const list = loadRecent();
  $("recent").innerHTML = '<option value="">Recent…</option>' +
    list.map((r, i) => `<option value="${i}" title="${esc(r.source)}">${esc(r.label)}</option>`).join("");
  $("recent").disabled = !list.length;
}

// Called for every history entry (from the UI, Python, or the CLI): remember successful opens and builds.
export function rememberRecent(entry) {
  if (!entry.ok) return;
  const a = entry.action;
  const source = a.type === "open_network" ? a.source : a.type === "build_network" ? entry.result.output : null;
  if (!source) return;
  const label = a.label || (a.type === "build_network" ? a.name : source.replace(/[\\/]+$/, "").split(/[\\/]/).pop());
  saveRecent([{ source, label }, ...loadRecent().filter(r => r.source !== source)].slice(0, RECENT_MAX));
  renderRecent();
}

export function renderHeader(server) {
  const sel = $("net-select");
  sel.innerHTML = server.networks.length
    ? server.networks.map(n => `<option value="${esc(n.id)}"${n.id === server.active ? " selected" : ""}>${esc(n.label)}</option>`).join("")
    : '<option value="">No network open</option>';
  sel.disabled = !server.networks.length;
  const h = server.networks.find(n => n.id === server.active);
  $("count").textContent = h ? `${h.links.toLocaleString()} links · ${h.nodes.toLocaleString()} nodes` : "";
}

export function wireHeader() {
  $("net-select").onchange = e => run({ type: "set_active_network", net_id: e.target.value });
  $("recent").onchange = e => {
    const r = loadRecent()[Number(e.target.value)];
    e.target.value = "";
    if (r) run({ type: "open_network", source: r.source, label: r.label });
  };
  const select = async () => {
    const utterance = $("utterance").value.trim();
    if (!utterance) return;
    $("go").disabled = true;
    await run({ type: "select", utterance }, sel => fitLinks(sel.link_ids));
    $("go").disabled = false;
  };
  $("go").onclick = select;
  $("utterance").onkeydown = e => { if (e.key === "Enter") select(); };
}
```

- [ ] **Step 8: Add the basemap to the store, and `BuildNetwork` to the session script**

In `static/js/store.js`, add this line to the `createStore({...})` initial state, after the `server:` line:

```javascript
  basemap: null,              // MapLibre style URL from /api/config (shared with the wizard's area map)
```

In `static/js/history.js`, replace:

```javascript
    "from gmnspy.workbench import Session, OpenNetwork, CloseNetwork, SetActiveNetwork, Select, ClearSelection, Style, Navigate, SetSetting",
```

with:

```javascript
    "from gmnspy.workbench import Session, OpenNetwork, BuildNetwork, CloseNetwork, SetActiveNetwork, Select, ClearSelection, Style, Navigate, SetSetting",
```

- [ ] **Step 9: Replace `static/js/main.js` with**

This version wires jobs and recents, keeps the basemap, and subscribes to `job` events.

```javascript
// Workbench boot: wire modules to the store and the server's SSE stream.
import { getBuffer, getJSON, netPath, subscribe } from "./api.js";
import { $, toast } from "./dom.js";
import { rememberRecent, renderHeader, renderRecent, wireHeader } from "./header.js";
import { showEntry, wireHistory } from "./history.js";
import { loadJobs, onJob, wireJobs } from "./jobs.js";
import { fitBbox, fitLinks, fitNetwork, initMap, render } from "./map.js";
import { decodeNetwork } from "./netbuf.js";
import { populateColorby, renderLegend, syncControls, wirePanels } from "./panels.js";
import { clearDetails, renderHighlights, renderSelection, showLinkDetails, wireSide } from "./side.js";
import { activeSelection, store } from "./store.js";
import { onNetworkChanged, onSelectionChanged, restoreViewMode, wireTable } from "./table.js";

const netKeyFor = server => {
  const h = server.networks.find(n => n.id === server.active);
  return h ? { h, key: `${h.id}@${h.version}` } : { h: null, key: null };
};
const inFlight = new Set();

async function loadActiveNetwork() {
  const { server, netKey } = store.get();
  const { h, key } = netKeyFor(server);
  if (key === netKey || inFlight.has(key)) return;
  if (!h) { store.set({ netKey: null, net: null, attrs: null, properties: [], prop: null, marker: null }); return; }
  inFlight.add(key);
  try {
    const [buf, attrs, props] = await Promise.all([
      getBuffer(netPath(h.id, "network.bin")), getJSON(netPath(h.id, "network.attrs.json")), getJSON(netPath(h.id, "properties")),
    ]);
    if (netKeyFor(store.get().server).key !== key) return; // superseded while fetching
    const switched = !netKey || !netKey.startsWith(`${h.id}@`);
    store.set({ netKey: key, net: decodeNetwork(buf), attrs, properties: props.properties, prop: null, marker: null });
    if (switched) fitNetwork();
  } finally {
    inFlight.delete(key);
  }
}

async function loadColorProperty() {
  const { server, net, netKey, prop } = store.get();
  const name = server.style.color_by;
  if (!net || name === "none" || (prop && prop.name === name && prop.netKey === netKey)) return;
  const p = await getJSON(netPath(server.active, `property/${encodeURIComponent(name)}`));
  const now = store.get();
  if (now.server.style.color_by === name && now.netKey === netKey) store.set({ prop: { ...p, netKey } });
}

async function onState(server) {
  store.set({ server });
  try { await loadActiveNetwork(); await loadColorProperty(); } catch (e) { toast(e.message); }
}

function onNavigate(ev) {
  if (ev.bbox) fitBbox(ev.bbox);
  else if (ev.to_network) fitNetwork();
  else if (ev.to_selection) { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); }
}

function onLinkClick(linkId) {
  const s = store.get();
  if (!s.highlightMode) { showLinkDetails(linkId); return; }
  const highlights = new Set(s.highlights);
  if (highlights.has(linkId)) highlights.delete(linkId); else highlights.add(linkId);
  store.set({ highlights });
}

function wireMapButtons() {
  $("btn-fitnet").onclick = () => fitNetwork();
  $("btn-fitsel").onclick = () => { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); };
  $("btn-highlight").onclick = () => store.set({ highlightMode: !store.get().highlightMode });
}

function wireStore() {
  store.subscribe(["server", "net", "prop", "highlights", "marker"], () => render());
  store.subscribe(["server"], s => {
    renderHeader(s.server); syncControls(s.server.style); renderSelection(activeSelection(s)); onSelectionChanged();
  });
  store.subscribe(["server", "prop"], s => renderLegend(s.server.style, s.prop));
  store.subscribe(["properties"], s => { populateColorby(s.properties); syncControls(s.server.style); });
  store.subscribe(["netKey"], () => { onNetworkChanged(); store.set({ highlights: new Set() }); clearDetails(); });
  store.subscribe(["highlights"], s => renderHighlights(s.highlights));
  store.subscribe(["highlightMode"], s => { $("btn-highlight").classList.toggle("on", s.highlightMode); $("map").classList.toggle("highlighting", s.highlightMode); });
}

async function boot() {
  wireStore(); wirePanels(); wireSide(); wireTable(); wireHeader(); wireHistory(); wireMapButtons(); wireJobs();
  renderRecent();
  const [cfg, server, history] = await Promise.all([getJSON("/api/config"), getJSON("/api/state"), getJSON("/api/history")]);
  store.set({ server, basemap: cfg.style });
  await loadJobs();
  restoreViewMode();
  if (history.entries.length) showEntry(history.entries[history.entries.length - 1]);
  initMap(cfg.style, {
    onLinkClick,
    onReady: async () => {
      await onState(store.get().server);
      subscribe({
        state: e => onState(e.state),
        history: e => { showEntry(e.entry); rememberRecent(e.entry); },
        navigate: onNavigate,
        job: e => onJob(e.job),
      });
    },
  });
}

boot().catch(e => toast(e.message));
```

- [ ] **Step 10: Run the static checks**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: `18 passed`. The import/export graph check, the ids-exist check, and `node --check` all cover the new
and changed modules.

- [ ] **Step 11: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/static packages/gmnspy/tests/test_workbench_static.py
git commit -m "feat(workbench-ui): Open/Import button, Recent (localStorage), jobs indicator + panel, wizard markup"
```

---

### Task 16: The wizard: file browser, area picker, and the step flow

**Files:**
- Create: `static/js/filebrowser.js`, `static/js/areapicker.js`, `static/js/wizard.js`
- Modify: `static/js/header.js`, `static/js/main.js`
- Test: `packages/gmnspy/tests/test_workbench_static.py`

- [ ] **Step 1: Append the failing test to `packages/gmnspy/tests/test_workbench_static.py`**

```python
def test_wizard_modules_exist_and_are_wired_from_main():
    names = {p.name for p in JS_DIR.glob("*.js")}
    assert {"wizard.js", "filebrowser.js", "areapicker.js", "jobs.js"} <= names
    main = (JS_DIR / "main.js").read_text()
    assert 'from "./wizard.js"' in main and 'from "./jobs.js"' in main
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: `1 failed, 18 passed`. `test_wizard_modules_exist_and_are_wired_from_main` fails its subset `AssertionError`.

- [ ] **Step 3: Create `static/js/filebrowser.js`**

The browser only lists what `/api/fs/list` returns, which is limited to `io.allowed_roots`.
- One click picks an entry of a selectable kind, or opens a plain folder.
- A double click opens any folder.
- `configure({kinds})` lets the area step reuse one instance for both sources.

```javascript
// Server-side file browser over GET /api/fs/list (only io.allowed_roots). Files are opened in place, never uploaded.
import { getJSON } from "./api.js";
import { esc, toast } from "./dom.js";

const KIND_LABEL = { gmns: "GMNS", zip: "zip", duckdb: "DuckDB", datapackage: "datapackage", osm: "OSM XML",
  json: "JSON", overture: "Overture" };

// el: container element. opts.kinds: entry kinds that can be picked. opts.pickFolder: offer "Use this folder".
// opts.onPick(entry): called with the picked entry ({path, target, kind, is_dir}).
export function createFileBrowser(el, opts) {
  let listing = null, picked = null;

  function render() {
    const up = listing.path ? '<button class="mini ghost" data-up>&#8593; Up</button>' : "";
    const here = listing.path ? `<code class="fb-path">${esc(listing.path)}</code>` : '<span class="fb-path">Allowed folders</span>';
    const use = opts.pickFolder && listing.path ? '<button class="mini" data-here>Use this folder</button>' : "";
    const rows = listing.entries.map((e, i) => {
      const ok = opts.kinds.includes(e.kind), on = picked && picked.path === e.path;
      return `<div class="fb-row${ok ? " ok" : ""}${on ? " on" : ""}" data-i="${i}">` +
        `<span class="fb-ico">${e.is_dir ? "&#128193;" : "&#128196;"}</span><span class="fb-name">${esc(e.name)}</span>` +
        (e.kind ? `<span class="fb-kind">${esc(KIND_LABEL[e.kind] || e.kind)}</span>` : "") + "</div>";
    });
    const more = listing.truncated ? '<div class="empty">Showing the first 2000 entries.</div>' : "";
    el.innerHTML = `<div class="fb-bar">${up}${here}${use}</div><div class="fb-list">${rows.join("") || '<span class="empty">Empty folder.</span>'}${more}</div>`;
  }

  async function show(path) {
    try {
      listing = await getJSON(`/api/fs/list${path ? `?path=${encodeURIComponent(path)}` : ""}`);
      render();
    } catch (e) { toast(e.message); }
  }

  function pick(entry) { picked = entry; render(); opts.onPick(entry); }

  el.addEventListener("click", ev => {
    const t = ev.target.closest("[data-up],[data-here],[data-i]");
    if (!t || !listing) return;
    if (t.hasAttribute("data-up")) { show(listing.parent); return; }
    if (t.hasAttribute("data-here")) { pick({ path: listing.path, target: listing.path, kind: null, is_dir: true }); return; }
    const e = listing.entries[Number(t.dataset.i)];
    if (opts.kinds.includes(e.kind)) pick(e);
    else if (e.is_dir) show(e.path);
  });
  el.addEventListener("dblclick", ev => {
    const t = ev.target.closest("[data-i]");
    const e = t && listing && listing.entries[Number(t.dataset.i)];
    if (e && e.is_dir) show(e.path);
  });

  return {
    show,
    reset(path = null) { picked = null; return show(path); },
    configure(changes) { Object.assign(opts, changes); }, // e.g. {kinds} when the wizard's source changes
  };
}
```

- [ ] **Step 4: Create `static/js/areapicker.js`**

The area picker has its own small MapLibre map, created the first time the Area step is shown, because a hidden
container has no size.
- **Draw:** toggle the button, then drag a rectangle. Its four corners are draggable markers, and dragging one
  keeps the opposite corner fixed.
- **Coordinates:** `W,S,E,N`, or `lat,lon` plus a buffer.
- **Place:** an explicit search. All candidate outlines are drawn dashed, and clicking a candidate selects and
  fits it.
- **Local file:** the file browser, limited to `.osm`/`.json` for OSM and snapshot folders for Overture.

```javascript
// Area step: Draw / Coordinates / Place / Local file. Every map tab ends in one bbox, previewed on its own small map.
import { getJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { createFileBrowser } from "./filebrowser.js";

const M_PER_DEG_LAT = 111320; // same spherical approximation as gmnspy.osm.query.point_buffer_bbox
const OPPOSITE = [2, 3, 0, 1]; // corner order SW, SE, NE, NW; dragging one keeps its opposite fixed
const FILE_KINDS = { osm: ["osm", "json"], overture: ["overture"] };
const EMPTY = { type: "FeatureCollection", features: [] };

let map = null, markers = [], drawStart = null, drawing = false;
let tab = "draw", area = null, inputFile = null, candidates = [], fileBrowser = null, onChange = () => {};

const round6 = v => Math.round(v * 1e6) / 1e6;
const ring = b => [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]];
const corners = b => [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]];
const polygonFeature = coords => ({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coords] } });
const lonLat = poly => poly.map(([lat, lon]) => [lon, lat]); // place polygons are (lat, lon), like the server's
const bboxOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(round6);

export function pointBbox(lat, lon, m) {
  const dlat = m / M_PER_DEG_LAT, cos = Math.cos((lat * Math.PI) / 180);
  const dlon = cos ? m / (M_PER_DEG_LAT * cos) : dlat;
  return [lon - dlon, lat - dlat, lon + dlon, lat + dlat];
}

export function areaBbox(a) { return a.kind === "point" ? pointBbox(a.lat, a.lon, a.buffer_m) : a.bbox; }

// What the build action needs from this step: {area} or {input_file}, or null when nothing is chosen yet.
export function areaChoice() {
  if (tab === "file") return inputFile ? { input_file: inputFile } : null;
  return area ? { area } : null;
}

function setArea(next, { fit = false, quiet = false } = {}) {
  area = next;
  render();
  if (fit && area) { const b = areaBbox(area); map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 30, duration: 300 }); }
  if (!quiet) onChange();
}

function render() {
  if (!map || !map.getSource("ap-area")) return;
  const shape = !area ? null : area.kind === "place" && area.polygon ? lonLat(area.polygon) : ring(areaBbox(area));
  map.getSource("ap-area").setData(shape ? polygonFeature(shape) : EMPTY);
  const editable = area && area.kind === "bbox";
  markers.forEach((m, i) => {
    if (editable) m.setLngLat(corners(area.bbox)[i]).addTo(map); else m.remove();
  });
  const b = area && areaBbox(area);
  $("ap-summary").textContent = b ? `W,S,E,N = ${b.map(v => v.toFixed(5)).join(", ")}` : "No area yet.";
}

function makeMarkers() {
  markers = [0, 1, 2, 3].map(i => {
    const m = new maplibregl.Marker({ draggable: true, color: "#2dd2e6", scale: 0.6 });
    m.on("drag", () => {
      const p = m.getLngLat(), fixed = corners(area.bbox)[OPPOSITE[i]];
      area = { kind: "bbox", bbox: bboxOf([p.lng, p.lat], fixed) };
      map.getSource("ap-area").setData(polygonFeature(ring(area.bbox)));
    });
    m.on("dragend", () => setArea(area));
    return m;
  });
}

function wireDraw() {
  map.on("mousedown", e => {
    if (!drawing) return;
    e.preventDefault();
    drawStart = [e.lngLat.lng, e.lngLat.lat];
  });
  map.on("mousemove", e => {
    if (drawStart) setArea({ kind: "bbox", bbox: bboxOf(drawStart, [e.lngLat.lng, e.lngLat.lat]) }, { quiet: true });
  });
  map.on("mouseup", () => {
    if (!drawStart) return;
    drawStart = null; drawing = false;
    map.dragPan.enable(); map.getCanvas().style.cursor = ""; $("ap-draw").classList.remove("on");
    onChange();
  });
}

// Create the preview map the first time the Area step is shown (a hidden container has no size).
export function showAreaMap(style) {
  if (map) { map.resize(); return; }
  map = new maplibregl.Map({ container: "ap-map", style, center: [-98.5, 39.8], zoom: 3 });
  map.on("load", () => {
    map.addSource("ap-area", { type: "geojson", data: EMPTY });
    map.addSource("ap-cands", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "ap-cands-line", type: "line", source: "ap-cands",
      paint: { "line-color": "#9aa3b2", "line-width": 1, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "ap-area-fill", type: "fill", source: "ap-area", paint: { "fill-color": "#2dd2e6", "fill-opacity": 0.12 } });
    map.addLayer({ id: "ap-area-line", type: "line", source: "ap-area", paint: { "line-color": "#2dd2e6", "line-width": 2 } });
    render();
  });
  makeMarkers();
  wireDraw();
}

function setTab(name) {
  tab = name;
  for (const b of document.querySelectorAll("#ap-tabs button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".ap-pane")) p.hidden = p.dataset.pane !== name;
  $("ap-map").hidden = name === "file";
  $("ap-summary").hidden = name === "file";
  if (name !== "file" && map) map.resize();
  onChange();
}

function applyCoordinates() {
  const nums = s => s.split(",").map(v => Number(v.trim())).filter(v => Number.isFinite(v));
  const bbox = nums($("ap-bbox").value), point = nums($("ap-point").value), buffer = Number($("ap-buffer").value);
  if (bbox.length === 4) {
    if (!(bbox[0] < bbox[2] && bbox[1] < bbox[3])) { toast("bbox must be W,S,E,N with W<E and S<N"); return; }
    setArea({ kind: "bbox", bbox: bbox.map(round6) }, { fit: true });
  } else if (point.length === 2 && buffer > 0) {
    setArea({ kind: "point", lat: point[0], lon: point[1], buffer_m: buffer }, { fit: true });
  } else {
    toast("Enter W,S,E,N, or lat,lon plus a buffer in metres");
  }
}

async function searchPlace() {
  const q = $("ap-q").value.trim();
  if (!q) return;
  $("ap-cands").innerHTML = '<span class="empty">Searching…</span>';
  try {
    candidates = (await getJSON(`/api/geocode?q=${encodeURIComponent(q)}`)).candidates;
  } catch (e) { candidates = []; toast(e.message); }
  $("ap-cands").innerHTML = candidates.length
    ? candidates.map((c, i) => `<div class="cand" data-i="${i}">${esc(c.display_name)} <span class="fb-kind">${esc(c.type)}</span></div>`).join("")
    : '<span class="empty">No matches.</span>';
  const outlines = candidates.map(c => polygonFeature(c.polygon ? lonLat(c.polygon) : ring(c.bbox)));
  if (map && map.getSource("ap-cands")) map.getSource("ap-cands").setData({ type: "FeatureCollection", features: outlines });
}

function pickCandidate(i) {
  const c = candidates[i];
  for (const el of document.querySelectorAll("#ap-cands .cand")) el.classList.toggle("on", Number(el.dataset.i) === i);
  setArea({ kind: "place", name: c.display_name, bbox: c.bbox, polygon: c.polygon }, { fit: true });
}

// Reset for a new build of `source` ("osm" | "overture").
export function resetAreaPicker(source) {
  area = null; inputFile = null; candidates = []; drawing = false; drawStart = null;
  $("ap-cands").innerHTML = "";
  $("ap-file-note").textContent = source === "osm" ? "A .osm XML file or an Overpass JSON export." : "A folder holding segment.parquet + connector.parquet.";
  fileBrowser.configure({ kinds: FILE_KINDS[source] });
  fileBrowser.reset();
  if (map && map.getSource("ap-cands")) map.getSource("ap-cands").setData(EMPTY);
  render();
  setTab("draw");
}

export function wireAreaPicker(handler) {
  onChange = handler;
  fileBrowser = createFileBrowser($("ap-file-fb"), { kinds: [], onPick: e => { inputFile = e.target; onChange(); } });
  for (const b of document.querySelectorAll("#ap-tabs button")) b.onclick = () => setTab(b.dataset.tab);
  $("ap-draw").onclick = () => {
    if (!map) return;
    drawing = !drawing;
    $("ap-draw").classList.toggle("on", drawing);
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) map.dragPan.disable(); else map.dragPan.enable();
  };
  $("ap-apply").onclick = applyCoordinates;
  $("ap-search").onclick = searchPlace;
  $("ap-q").onkeydown = e => { if (e.key === "Enter") searchPlace(); };
  $("ap-cands").onclick = e => { const c = e.target.closest(".cand"); if (c) pickCandidate(Number(c.dataset.i)); };
}
```

- [ ] **Step 5: Create `static/js/wizard.js`**

```javascript
// Open / Import wizard: source → (browse | URL | area → options → estimate) → exactly one dispatched action.
// Browse, URL check, place search, and estimate are read-only queries; only Open / Build are recorded actions.
import { dispatch, getJSON, postJSON } from "./api.js";
import { areaChoice, resetAreaPicker, showAreaMap, wireAreaPicker } from "./areapicker.js";
import { $, esc, toast } from "./dom.js";
import { createFileBrowser } from "./filebrowser.js";
import { openJobsPanel } from "./jobs.js";
import { store } from "./store.js";

const FLOWS = { local: ["source", "local"], url: ["source", "url"],
  osm: ["source", "area", "options", "run"], overture: ["source", "area", "options", "run"] };
const GMNS_KINDS = ["gmns", "zip", "duckdb", "datapackage"];
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/; // BuildNetwork.name
const NEXT_LABEL = { local: "Open", url: "Open", area: "Next", options: "Estimate" };

const wz = { src: null, step: "source", local: null, urlOk: false, outDir: null, estimate: null, prefilled: false };
let localFb = null, outFb = null;

const fmtSeconds = s => (s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);
const fmtBytes = b => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB`
  : `${Math.max(1, Math.round(b / 1e3))} kB`);

function canAdvance() {
  switch (wz.step) {
    case "local": return Boolean(wz.local);
    case "url": return wz.urlOk;
    case "area": return Boolean(areaChoice());
    case "options": return Boolean(wz.outDir) && NAME_RE.test($("opt-name").value.trim());
    case "run": return Boolean(wz.estimate);
    default: return false;
  }
}

function runLabel() {
  const r = wz.estimate;
  if (!r) return "Build";
  if (r.estimate.seconds == null) return "Run anyway";
  return r.needs_approval ? `Run (~${fmtSeconds(r.estimate.seconds)})` : "Build";
}

function updateFoot() {
  $("wz-back").disabled = wz.step === "source";
  $("wz-next").hidden = wz.step === "source";
  $("wz-next").textContent = wz.step === "run" ? runLabel() : NEXT_LABEL[wz.step] || "Next";
  $("wz-next").disabled = !canAdvance();
}

function go(step) {
  wz.step = step;
  for (const s of document.querySelectorAll(".wz-step")) s.hidden = s.dataset.step !== step;
  for (const el of document.querySelectorAll(".ovt-only")) el.hidden = wz.src !== "overture";
  if (step === "area") showAreaMap(store.get().basemap);
  if (step === "options") prefillOptions();
  if (step === "run") runEstimate();
  updateFoot();
}

function buildAction() {
  const tags = $("opt-extra-tags").value.split(",").map(t => t.trim()).filter(Boolean);
  const action = {
    type: "build_network", source: wz.src, ...areaChoice(),
    output_dir: wz.outDir, output_format: $("opt-format").value, name: $("opt-name").value.trim(),
    network_type: $("opt-network-type").value, spec_version: $("opt-spec").value.trim() || null,
  };
  if (tags.length) action.extra_tags = tags;
  if (wz.src === "overture" && $("opt-release").value.trim()) action.overture_release = $("opt-release").value.trim();
  return action;
}

async function prefillOptions() {
  outFb.reset(wz.outDir);
  if (wz.prefilled) return;
  try {
    const v = (await getJSON("/api/settings")).values;
    $("opt-network-type").value = v.build.network_type;
    $("opt-extra-tags").value = v.build.extra_tags.join(", ");
    $("opt-spec").value = v.io.spec_version;
    $("opt-format").value = v.io.default_format === "zip" ? "parquet" : v.io.default_format;
    $("opt-release").placeholder = v.overture.release || "pinned default";
    $("ap-buffer").value = v.build.buffer_m;
    wz.prefilled = true;
  } catch (e) { toast(e.message); }
  const choice = areaChoice();
  const base = choice && choice.area && choice.area.kind === "place" ? choice.area.name.split(",")[0] : "network";
  if (!$("opt-name").value) $("opt-name").value = `${base}-${wz.src}`.toLowerCase().replace(/[^a-z0-9_.-]+/g, "-");
  updateFoot();
}

function renderEstimate(r) {
  const e = r.estimate;
  $("wz-estimate").innerHTML = e.seconds == null
    ? `<b>No estimate.</b> <span class="muted">${esc(e.basis)}</span><br>You can still run it, but it may take a long time.`
    : `<b>About ${fmtSeconds(e.seconds)}</b>, ~${fmtBytes(e.out_bytes)} on disk.<br><span class="muted">${esc(e.basis)}</span>` +
      (r.needs_approval ? `<br>That is over the ${fmtSeconds(r.threshold_s)} approval threshold (<code>app.approve_above_s</code>).` : "");
}

async function runEstimate() {
  wz.estimate = null;
  $("wz-estimate").textContent = "Estimating…";
  updateFoot();
  try {
    wz.estimate = await postJSON("/api/estimate", buildAction());
    renderEstimate(wz.estimate);
  } catch (e) {
    $("wz-estimate").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
  updateFoot();
}

async function checkUrl() {
  wz.urlOk = false;
  updateFoot();
  const url = $("wz-url").value.trim();
  if (!url) return;
  $("wz-url-result").textContent = "Checking…";
  try {
    const r = await postJSON("/api/check-url", { url });
    wz.urlOk = r.reachable;
    const creds = ` Credentials from: <b>${esc(r.credential_source)}</b>.`;
    $("wz-url-result").innerHTML = r.reachable
      ? `Reachable (${esc(r.kind)}).${creds}${r.tables.length ? ` Tables: ${r.tables.map(esc).join(", ")}.` : ""}`
      : `<span class="err">Not reachable: ${esc(r.error || "unknown error")}</span>${creds}`;
  } catch (e) {
    $("wz-url-result").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
  updateFoot();
}

async function submit(action) {
  $("wz-next").disabled = true;
  try {
    await dispatch(action);
    closeWizard();
    openJobsPanel();
  } catch (e) {
    toast(e.message);
    updateFoot();
  }
}

function next() {
  if (wz.step === "local") submit({ type: "open_network", source: wz.local.target });
  else if (wz.step === "url") submit({ type: "open_network", source: $("wz-url").value.trim() });
  else if (wz.step === "run") submit({ ...buildAction(), approved: Boolean(wz.estimate.needs_approval) });
  else go(FLOWS[wz.src][FLOWS[wz.src].indexOf(wz.step) + 1]);
}

function back() {
  const flow = FLOWS[wz.src] || ["source"];
  go(flow[Math.max(flow.indexOf(wz.step) - 1, 0)]);
}

function choose(src) {
  wz.src = src;
  if (src === "local") { wz.local = null; localFb.reset(); }
  if (src === "url") { wz.urlOk = false; $("wz-url-result").textContent = ""; }
  if (src === "osm" || src === "overture") resetAreaPicker(src);
  go(FLOWS[src][1]);
}

export function openWizard() {
  Object.assign(wz, { src: null, local: null, urlOk: false, estimate: null });
  $("opt-name").value = "";
  $("wizard").hidden = false;
  go("source");
}

export function closeWizard() { $("wizard").hidden = true; }

export function wireWizard() {
  localFb = createFileBrowser($("wz-local-fb"), { kinds: GMNS_KINDS, onPick: e => { wz.local = e; updateFoot(); } });
  outFb = createFileBrowser($("opt-out-fb"), {
    kinds: [], pickFolder: true, onPick: e => { wz.outDir = e.path; $("opt-outdir").textContent = e.path; updateFoot(); },
  });
  wireAreaPicker(updateFoot);
  for (const b of document.querySelectorAll(".wz-choice")) b.onclick = () => choose(b.dataset.src);
  $("wz-next").onclick = next;
  $("wz-back").onclick = back;
  $("wz-close").onclick = closeWizard;
  $("wz-check").onclick = checkUrl;
  $("wz-url").oninput = () => { wz.urlOk = false; updateFoot(); };
  $("wz-url").onkeydown = e => { if (e.key === "Enter") checkUrl(); };
  $("opt-name").oninput = updateFoot;
  $("wizard").onkeydown = e => { if (e.key === "Escape") closeWizard(); };
}
```

- [ ] **Step 6: Wire the button and boot the wizard**

In `static/js/header.js`, add `import { openWizard } from "./wizard.js";` after the `map.js` import. In
`wireHeader`, after the `net-select` line, add:

```javascript
  $("open-wizard").onclick = () => openWizard();
```

In `static/js/main.js`, add `import { wireWizard } from "./wizard.js";` after the `table.js` import, and change
`wireJobs();` in `boot()` to `wireJobs(); wireWizard();`.

- [ ] **Step 7: Run the static checks**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_workbench_static.py -q`
Expected: `22 passed`.

- [ ] **Step 8: Commit**

```bash
git add packages/gmnspy/gmnspy/workbench/static packages/gmnspy/tests/test_workbench_static.py
git commit -m "feat(workbench-ui): Open/Import wizard (file browser, area picker with editable bbox, estimate + approve)"
```

---

### Task 17: Docs, the full suite and lint, then an end-to-end browser check

**Files:**
- Modify: `packages/gmnspy/docs/cookbook/workbench.md`

- [ ] **Step 1: Update the cookbook page**

In `packages/gmnspy/docs/cookbook/workbench.md`, replace:

```markdown
Open <http://127.0.0.1:8850>. You can open more networks from the header (a path or URL) and switch between
them with the network picker. `gmnspy viz` and `gmnspy select-serve` are aliases of `gmnspy app`.
```

with:

```markdown
Open <http://127.0.0.1:8850>. Open more networks with **Open / Import…** in the header (see below) or
the **Recent** list, and switch between them with the network picker. `gmnspy viz` and `gmnspy select-serve`
are aliases of `gmnspy app`.
```

Insert this section directly above `## Settings`. The Python block carries `<!-- doctest: skip -->` because it
would call Overpass. Every symbol it names (`gmnspy.workbench.ApprovalRequired`, `gmnspy.overture.layout`) exists
and is exported, so the doc-contract tests pass.

````markdown
## Open or import a network

**Open / Import…** opens a wizard with four sources:

- **GMNS on this machine**: a server-side file browser. Entries are tagged (GMNS folder, `.zip`, `.duckdb`,
  `datapackage.json`); pick one and it opens in place. Nothing is uploaded.
- **GMNS at a URL** (`s3://`, `gs://`, `az://`, `https://`): **Check** says whether the URL is reachable, which
  credential source would be used (`env`, `keyring`, `netrc`, or `none`; never the secret), and which tables it found.
- **Build from OpenStreetMap** or **Build from Overture**: choose an area by drawing a rectangle (drag its corners
  to adjust), typing `W,S,E,N` or a point plus a buffer, or searching for a place and picking one of the
  outlines. You can instead pick a local file: a `.osm` XML file or an Overpass JSON export for OSM, or an
  Overture snapshot folder holding `segment.parquet` + `connector.parquet` (see `gmnspy.overture.layout`).

A build always writes to the output folder and format you choose (Parquet, CSV, or DuckDB) and then opens the
result from disk, so what you see is what was saved. It never overwrites an existing output. Zip output is not
available yet.

Before a build runs, the wizard shows an estimate of its time and size, from a quick count (Overpass
`out count`, or a DuckDB `COUNT(*)` over Overture) and a simple cost model. When the estimate is over
`app.approve_above_s` (90 s by default), or when the count fails, the button changes to **Run (~N min)** or
**Run anyway**, and the build only starts when you click it. The cost model's numbers are in
`gmnspy/workbench/data/build_cost.toml`; they are rough, so treat the estimate as a guide.

Opens and builds run as background jobs. The **Jobs** button in the header shows their stage and progress and
lets you cancel one; a cancel takes effect when the job reaches its next stage.

### Which folders the app can read and write

The file browser, opening a local path, and build input and output folders are all limited to
`io.allowed_roots`. When that list is empty (the default) it means your home folder. Paths given to
`gmnspy app` on the command line are always allowed for that session.

```toml
# ./gmnspy.toml
[io]
allowed_roots = ["~/networks", "/data/gmns"]

[app]
approve_above_s = 120
```

### The same thing from Python

A build is an ordinary action, so the history strip shows it as Python you can replay. The replayed call always
passes `approved=True`, because re-running a build you already approved counts as approval.

<!-- doctest: skip -->
```python
from gmnspy.workbench import BuildNetwork, Session

app = Session()
app.do(
    BuildNetwork(
        source="osm",
        area={"kind": "bbox", "bbox": (-78.91, 35.98, -78.88, 36.01)},
        output_dir="/home/me/networks",
        output_format="parquet",
        name="durham-core",
        approved=True,
    )
)
```

Without `approved=True`, a build over the threshold raises `gmnspy.workbench.ApprovalRequired`, and its
`.estimate` holds the estimate.
````

- [ ] **Step 2: Run the doc-contract tests**

Run: `uv run --all-extras pytest packages/gmnspy/tests/test_documented_api_contract.py packages/gmnspy/tests/test_documented_cli_contract.py packages/gmnspy/tests/test_documented_python_contract.py -q`
Expected: all pass.

- [ ] **Step 3: Run everything CI runs**

Run: `uv run --all-extras pytest packages/gmnspy packages/datagrove -q && uv run ruff check packages && uv run ruff format --check packages && uv run lint-imports && uv run python scripts/lint_no_sql.py`
Expected:
- pytest: all pass; the only new skip is the opt-in calibration test;
- ruff: `All checks passed!` and every file already formatted;
- import-linter: `2 kept, 0 broken`;
- `lint_no_sql.py`: exits 0.

If import-linter reports `gmnspy.cli is not allowed to import gmnspy.osm`, a static `from gmnspy.osm ...` or
`from gmnspy.overture import ...` has crept into a workbench module. Route it through `optional_module`
(Decision 18).

- [ ] **Step 4: Commit the docs**

```bash
git add packages/gmnspy/docs/cookbook/workbench.md
git commit -m "docs(gmnspy): Workbench Open / Import wizard, allowed roots, estimate + approval"
```

- [ ] **Step 5: Browser verification checklist**

Prepare a scratch area outside the repo, so nothing is written into tracked fixtures:

```bash
D=$(mktemp -d) && mkdir -p $D/out && cp -R packages/gmnspy/tests/fixtures/osm packages/gmnspy/tests/fixtures/overture $D/ \
  && cp -R packages/gmnspy/gmnspy/fixtures/rdu_i40/parquet $D/rdu && echo $D
```

Create `.claude/launch.json` (do not commit it). Use the printed `$D` as the value of `GMNSPY_IO__ALLOWED_ROOTS`
and in the source path:

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "workbench",
      "runtimeExecutable": "env",
      "runtimeArgs": ["GMNSPY_IO__ALLOWED_ROOTS=[\"<D>\"]", "uv", "run", "--all-extras", "gmnspy", "app", "<D>/rdu", "--port", "8850"],
      "port": 8850
    }
  ]
}
```

Start it with `preview_start` (`name: "workbench"`), set the viewport to 1400×900, and check each item. Use
`read_console_messages` for errors and screenshots for visuals.

1. **Header.** There is no path box. **Open / Import…**, **Recent…** (disabled when empty) and **Jobs 0** are
   visible. `job-1 open rdu` is listed as done. The console has no errors.
2. **Local GMNS.** Choose Open / Import… → GMNS on this machine → `<D>`. The listing tags `rdu` as **GMNS** and
   `overture` as **Overture**; `osm` is a plain folder. Pick `rdu` → **Open**. The wizard closes, a job runs, a
   second network `rdu-2` appears and becomes active, and **Recent** lists it.
3. **Roots are enforced.** In the browser console, run
   `await (await fetch('/api/fs/list?path=/')).json()`. The result is a `403` detail, `... outside the allowed folders`.
4. **URL check.** Choose GMNS at a URL → `ftp://example.org/x` → **Check**. It reports
   `Not reachable: unsupported URL scheme 'ftp'... Credentials from: none.`, and **Open** stays disabled. No
   secret is ever shown.
5. **Draw an area.** Choose Build from OpenStreetMap. On the Draw tab, click **Draw** and drag a rectangle on the
   small map. A cyan rectangle with four corner markers appears, `W,S,E,N = ...` updates, and **Next** enables.
   Drag a corner: the opposite corner stays fixed and the summary updates. Do **not** run this build: a real
   Overpass call is out of scope for the check.
6. **Coordinates tab.** Enter `-78.95,35.95,-78.85,36.05` → **Preview**: the map fits the box. Clear it, then
   enter `35.99,-78.90` with a buffer of `500` → **Preview**: a square appears.
7. **Place tab** (optional; it makes one real Nominatim request). Search `Durham, North Carolina`: candidates
   are listed and their outlines drawn dashed. Click one: it is selected and fitted.
8. **Local-file build.** On the Local file tab, open `<D>/osm` and pick `tiny.osm` (tagged **OSM XML**) → **Next**.
   The Options step is pre-filled from settings (drive, spec `0.97`, Parquet). Pick `<D>/out` → **Use this folder**;
   Name `tiny-osm` → **Estimate**. It shows `About 1 s ... osm_file: ... bytes of file`, and the button reads
   **Build** → click it. In the Jobs panel, `build tiny-osm` runs through estimate, query, convert, write, open
   and register, then shows done. The map shows the two-link network, the header reads `2 links · 2 nodes`, and
   the history strip shows `app.do(BuildNetwork(source='osm', input_file=..., ..., approved=True))`.
   `<D>/out/tiny-osm/link.parquet` exists.
9. **Never overwrite.** Repeat item 8 with the same name. The estimate step shows
   `... tiny-osm already exists; choose another name ...`.
10. **Approval gate.** Run `curl -s -XPOST localhost:8850/api/actions -H 'content-type: application/json' -d '{"type":"set_setting","key":"app.approve_above_s","value":0}'`.
    Then repeat item 8 with the name `tiny-2`. The estimate says it is over the 0 s threshold, and the button
    reads **Run (~1 s)**. Click it; the build succeeds. Run the same build again with a new name, and this time
    send it from the console with `approved` left out:
    `await fetch('/api/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'build_network',source:'osm',input_file:'<D>/osm/tiny.osm',output_dir:'<D>/out',output_format:'csv',name:'tiny-3'})})`.
    The Jobs panel shows `failed: approval required: ...`, a red toast appears, and the history strip shows the
    failed `BuildNetwork`.
11. **Overture snapshot.** Use Build from Overture → Local file → `<D>/overture` (tagged **Overture**), with the
    DuckDB format and the name `ovt`. It builds `<D>/out/ovt.duckdb` and opens it. The Overture release field is
    visible only for this source.
12. **Cancel.** In the console, start a build and cancel it at once:
    `const r = await (await fetch('/api/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'build_network',source:'overture',input_file:'<D>/overture',output_dir:'<D>/out',output_format:'parquet',name:'cancel-me',approved:true})})).json(); await fetch('/api/jobs/'+r.result.job_id+'/cancel',{method:'POST'})`.
    The job ends as `cancelled` (or `done`, if it finished first) and the console shows no error. When it was
    cancelled, `<D>/out/cancel-me` does not exist.
13. **Zip is off.** In the Options step the format list shows **Zip (not yet)**, disabled.
14. **SSE from Python.** In a terminal, run
    `curl -s -XPOST localhost:8850/api/actions -H 'content-type: application/json' -d '{"type":"open_network","source":"<D>/rdu"}'`.
    It answers `202` with a job, and the open browser shows the job and the new network without a reload.

Stop the preview with `preview_stop`. Reset the viewport (`resize_window` preset `desktop`). Record any defect as
a failing test, or fix it, before you open the PR.

---

## Self-review notes (completed while writing)

- **Spec coverage, against the "Open / Import wizard (P1a)" section of the design doc:**

| Spec item | Where |
|---|---|
| Entry point: path box removed; Open / Import… button and Recent | Task 15 (markup, Recent via `localStorage`, Decision 14); Task 16 (wiring) |
| Step 1, local source: file browser | Task 4 (`list_dir`, kinds); Task 16 (`filebrowser.js`) |
| Step 1, URL source: Check with reachability, credential source (never the secret) and tables | Task 8 (`credential_source`, `check_url`); Task 14 (`POST /api/check-url`) |
| Step 1, OSM and Overture builds, by area or by local file | Tasks 5, 6, 9, 13, 16 |
| File browser limited to `io.allowed_roots` (default home), enforced in `OpenNetwork` | Task 2 (`paths`); Task 4 (listing); Task 12 (open); Task 13 (build input/output); Task 3 (CLI trust) |
| Recognised kinds tagged; only valid targets selectable; opened in place, no upload | Task 4 (`detect_kind`, `open_target`); Task 16 (`kinds` filter) |
| Area step: draw with editable corners, coordinates, point + buffer, place with candidate outlines; OSM keeps the polygon | Task 9 (`Area`); Task 7 (`geocode_candidates`); Task 16 (`areapicker.js`); Task 13 (Overpass `poly:`) |
| Options prefilled from Settings | Task 1 (`build.*`); Task 16 (`prefillOptions`) |
| Output folder and format required; write first, then open from disk | Task 13 (`plan_build`, `write_output`, `_job_build_network`); zip deferred (Decision 11) |
| Estimate → approve → run: cheap pre-query, calibrated model, threshold `app.approve_above_s` (90 s) | Tasks 6, 7, 10, 13; Task 14 (`/api/estimate`); Task 16 (Run (~N min) / Run anyway) |
| A failed pre-query asks the user before running | Task 10 (`needs_approval(None) is True`); Task 13 test `test_unavailable_estimate_needs_approval`; Task 16 "Run anyway" |
| Jobs: stages, progress over SSE, cancel, header indicator, opens don't hold the lock | Task 11 (`JobRunner`); Task 12 (`submit`, `_load` off the lock, test `test_load_runs_without_holding_the_session_lock`); Task 15 (`jobs.js`) |
| Audit: `OpenNetwork` and `BuildNetwork` recorded, estimate and approval stored, Python replay counts as approval | Task 12 (`_finish`/`_record`); Task 13 (`result.estimate`, `ApprovalRequired.payload`, `replay_overrides`) |
| Audit: browse, check, search and estimate not recorded | Task 14 (`test_estimate_is_not_recorded`; routes outside `/api/actions`) |
| Later: `.pbf`, upload, Overture polygon clipping, divisions lookup | Scope notes (deferred) |
| Two audit logs: a build is not a `NetworkChange` | Decision 26 |
| Transit: roadway component only, no retrofit needed | Decision 27 |
| Read-only routes behind the loopback guard | Task 14 (`test_check_url_respects_the_origin_guard`, `test_reads_respect_the_host_guard`) |
| CLI keeps working; minimal sharing with `gmnspy build` | Task 3; Task 12 (dispatch waits); Decision 24 |
| Doc-contract tests | Task 17, Steps 1–2 |

- **Placeholder scan:**
  - No "TBD", "similar to Task N", or elided code.
  - Every new file appears in full.
  - Every edit to an existing file gives the exact text to replace and its replacement, or the exact line to add
    and where it goes.
  - The only `<D>` placeholders are in the manual browser checklist, and Step 5 says how to fill them.
- **Type and name consistency** (checked by running the plan's code against a copy of `feat/workbench-p0`):
  - `Session.submit/dispatch/dispatch_recorded/_finish/_record/_load/_register/_job_*` are used the same way in
    Tasks 12–14.
  - `Job.history_seq` is set by `_finish` through `JobRunner.update`.
  - `BuildPlan.kind` uses the `SourceKind` literals that the TOML keys and `estimate_build` expect.
  - `Area.to_bbox()/to_polygon()` are used by `count_osm`, `build._osm_records` and `build._overture_read`.
  - `ApprovalRequired(estimate, threshold_s)` matches both its raise site and its re-raise in `dispatch`.
  - The JS imports resolve to real exports (enforced by `test_relative_imports_resolve_to_real_exports`), and
    every `$("id")` exists in `index.html`.
  - In the scratch run: the full suite gave `1967 passed, 6 skipped`; ruff was clean; import-linter gave
    `2 kept`; `lint_no_sql` was clean.
  - The browser walk-through of items 1, 2, 4, 5 and 8 passed against that build.
- **Fixed during the review:**
  - The first draft imported `gmnspy.osm` / `gmnspy.overture` statically from the workbench, which broke the
    import-linter contract. The fix is `optional_module` plus the dependency-free `gmnspy.overture.layout`.
  - The first draft bound `JobRunner` to `events.publish` eagerly, so tests that replace `publish` missed the job
    events. It is now late-bound.
  - Job labels had embedded full paths. They now use `default_label`.
  - `Session.dispatch` now re-raises `PathNotAllowed`/`JobCancelled`/`ApprovalRequired` as their own types.
  - The CLI only resolved paths that existed. It now resolves (and trusts) every local source, so a typo still
    reports `could not open`.
  - `to_python` dropped the area's `kind` discriminator through `exclude_defaults`. It now omits only top-level
    defaults.

## Risks and open questions

- **Zip cannot round-trip (pre-existing bug).** `Network.from_source("…/leavenworth.csv.zip")` fails today: DuckDB
  reports "No files found" for the `::link.csv` member path. `Network.write(..., format="zip")` is not a
  registered format either. Consequences:
  - P1a rejects zip output with `NotSupportedYet`;
  - the file browser still tags `.zip` as openable, but opening one fails with `could not open …`.

  **Question:** should a separate fix to the zip read path come before P1a, or should `.zip` be untagged in the
  browser until then?

  > **SUPERSEDED (2026-10-02):** zip read/write was fixed in 4b743fb; zip is a normal output format.
- **Shared DuckDB connection (pre-existing, widened).** HTTP threads already query networks concurrently on
  datagrove's single default ibis/DuckDB connection. P1a adds job threads that open networks on that same
  connection; builds use a private engine (Decision 16). If concurrent use proves unsafe, the fix belongs in
  datagrove: per-thread cursors or an engine lock.

  > **Outcome (2026-10-02):** it was unsafe: two simultaneous `OpenNetwork` jobs failed in 20 of 20 rounds
  > ("Attempting to execute an unsuccessful or closed pending query result"). Fixed in datagrove with an engine
  > lock: `IbisEngine` serializes its ibis backend (`serialize_backend`), wrapping every backend method in one
  > re-entrant lock stored on the backend, so direct `expr.execute()` calls are covered too; memtable GC
  > finalizers and the raw-connection spatial install take the same lock. Per-thread cursors were rejected
  > because ibis `read_*` temp views and the engine's temp tables are private to the connection that created
  > them. Remaining gaps: batch readers (`to_pyarrow_batches`) are consumed after the lock is released, and
  > expressions bound to ibis's process-wide default backend are not serialized. Separately, a job now
  > registers its network and records its history entry in one critical section, so history order matches
  > registry order.
- **Cancel is cooperative.** A cancel lands at the next stage boundary, so an in-flight Overpass download can run
  for up to `osm.timeout` (180 s) after you click Cancel.
- **The cost model is a seed.** One measured run, many guesses, and output sizes taken from a 178-link fixture.
  The calibration test (`GMNSPY_CALIBRATE=1`) prints a fitted `s_per_link`. **Question:** who runs it, and
  against which bboxes, to replace the seed before release?
- **Pre-query cost:**
  - A remote Overture `COUNT(*)` over S3 can take tens of seconds, and `/api/estimate` blocks one request
    thread while it runs.
  - An Overpass `out count` over a huge area can time out (25 s), which makes the estimate "unavailable" and
    asks for approval.
- **History order** follows job completion, not submission (Decision 2). Undo in P2 should key on `seq`, not on
  submission time.
- **Non-loopback bind.** With `--host 0.0.0.0`, anyone on the network can list `io.allowed_roots`, which is the
  home folder by default. The CLI already warns. **Question:** should P1a refuse to start with empty roots on a
  public bind?
- **Nominatim policy.** Place search sends `osm.user_agent` and runs only on an explicit Search. Heavy use should
  point the setting at a self-hosted instance (`base_url` is not yet a setting).
