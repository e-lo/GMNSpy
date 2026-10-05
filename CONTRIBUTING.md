# Development

## Basic Setup

This is a **uv workspace** with two packages — `datagrove` (generic Frictionless engine) and `gmnspy` (GMNS toolkit on top). Install both packages with **all extras**, editable, in a single command from the repo root:

```bash
uv sync --all-packages --all-extras
```

That's what CI runs. It creates `.venv/` at the workspace root with both packages installed editable, plus every optional extra (`polars`, `pandas`, `s3`, `gcs`, `azure`, `keyring`, `mcp`, `clean`, `server`, `notebook`) so the full test suite + `--doctest-modules` sweep can collect every file.

Run things via `uv run`:

```bash
uv run gmnspy --help
uv run datagrove --help
uv run pytest packages -n auto    # fast tier; see "Running tests" below
```

> **zsh users:** `[` and `]` are glob characters on zsh (the default shell on macOS). If you want to install **just one** extra ad-hoc, quote the brackets: `uv add 'gmnspy[clean]'` (not `uv add gmnspy[clean]`, which gives `zsh: no matches found`). The workspace-level `uv sync --all-packages --all-extras` doesn't hit this — no brackets in the command.

### One package at a time (rare)

If you want to install only one of the two packages (e.g. to mimic what a downstream user sees):

```bash
uv pip install -e 'packages/datagrove[polars,s3]'    # quoted for zsh
uv pip install -e 'packages/gmnspy[clean,server]'    # transitively gets datagrove
```

### Older / non-uv setup (not recommended)

```bash
pip install -r dev-requirements.txt
pip install -e packages/datagrove
pip install -e packages/gmnspy
```

## General Process

1. [Create an issue](#issues)
2. [Discuss approach](#consensus)
3. [Complete contribution](#coding) in a fork or branch.
4. [Submit a pull-request](#pull-requests)
5. [Respond to reviews](#review-and-approval-process)

Periodically the `develop` branch will be merged with master and a tagged release will be made and distributed to PyPI.

By making any contribution to the projects, contributors self-certify to the [Contributor Agreement](#contributor-agreement).

## Issues

- Search existing issues to see if your issue has already been brought up.
- Create new issues to start discussion on a new topic, feature requests, and bugs; linking to any other relevant issues.
- Fill out issue template to the best of your ability.
- Indiciate urgency and if you are willing to work on it either using tags or in issue text.

*Issues which do not have a clear user story may not be addressed*

### Consensus

If issue is not super obvious/straightforward, please discuss approach with the maintainers/owner and reach a consensus.

*Contributions which do not have consensus with the owner may not be approved*

## Coding

Get assigned. If you are working on issue, please tag yourself as the assignee (or ask to be tagged if you do not have privledges).

Generally:

- Try to be backwards compatible to Python 3.10.
- Be compatible with Numpy 2+, Pandas 2.x and 3.x, OSMNX 1+, PyProj 3.3+
- Use PEP8 and autoformat with `black`
- Use Google-style docstrings for all classes and methods
- Test formatting and autoformat using `pre-commit`
- Use logging
- All code should have an associated test
- [Documentation](#documentation) is in the `docs` folder and is built using `mkdocs`
- Additions to public API should be documented in `docs/api.md`
- Changes to architecture should be documented in `docs/architecture.md`
- Right now, this repo prioritizes Legibility/Simplicity >> Efficiency. That might change later.

*Contributions which do not meet these requirements may not be approved*

## Running tests

Tests live in `packages/datagrove/tests` and `packages/gmnspy/tests` and use `pytest`. Run them through `uv run --all-extras` from the repo root.

**While iterating, run your domain. Before committing a cross-cutting change, run the default. Run the full suite before merge.**

| Tier | Command | Time* |
|---|---|---|
| Domain | `uv run --all-extras pytest <paths below>` | 2–12s |
| Default (fast) | `uv run --all-extras pytest packages -n auto` | ~28s (~50s without `-n auto`) |
| Full | `uv run --all-extras pytest packages -n auto -m ""` | ~31s |

\* Measured on an 8-core Apple-silicon laptop.

- **Default** skips tests marked `slow` (end-to-end runs, like executing every documented Python block or running the bench pipeline) and `perf` (performance-regression bounds). `pyproject.toml` sets this with `-m "not slow and not perf"` in `addopts`.
- **Full** adds `-m ""`, which overrides that filter. Use `-m slow` or `-m perf` to run only one of those groups.
- **`-n auto`** runs tests in parallel with `pytest-xdist` (a dev dependency). It's opt-in. Leave it off when you use `--pdb` or a single test. `addopts` pins `--dist=loadfile` so each test file stays on one worker.
- **Naming a slow file is not enough.** `pytest packages/gmnspy/tests/test_cli_bench.py` deselects everything in it unless you add `-m ""`.
- **`live_llm` tests** call real provider APIs and skip unless you opt in. See the docstring of `packages/gmnspy/tests/test_llm_live.py`.

### Per-domain commands

Paths are relative to the repo root. `T=packages/gmnspy/tests`, `D=packages/datagrove/tests`.

| You touched | Run |
|---|---|
| `datagrove/engines`, `datagrove/io` | `$D/engines $D/io` |
| `datagrove/validation`, `datagrove/quality` | `$D/validation $D/quality` |
| anything else in datagrove | `packages/datagrove` (~15s; ~10s with `-n auto`) |
| `gmnspy/workbench` | `$T/test_workbench_*.py $T/test_cli_workbench.py` |
| `gmnspy/llm` | `$T/test_llm_*.py $T/test_cli_llm.py $T/test_workbench_llm_routes.py $T/test_workbench_ollama_pull.py` |
| `gmnspy/select` | `$T/test_select_*.py` |
| `gmnspy/osm` | `$T/test_osm_*.py` |
| `gmnspy/overture` | `$T/test_overture_*.py` |
| `gmnspy/map`, `gmnspy/viz` | `$T/test_map_*.py $T/test_viz_*.py` |
| `gmnspy/graph`, `scope`, `semantics`, `indexes` | `$T/test_graph*.py $T/test_scope.py $T/test_semantics.py $T/test_indexes.py $T/test_network_scope_accessor.py` |
| `gmnspy/network.py`, `quality`, `spec`, `clean`, geometry | `$T/test_network*.py $T/test_quality.py $T/test_spec.py $T/test_geom*.py $T/test_wkt.py $T/test_clean.py` |
| `gmnspy/cli` | `$T/test_cli*.py` |
| docs (`*.md` with Python blocks) | `$T/test_documented_*.py -m ""` |
| `gmnspy/bench` | `$T/bench $T/test_bench_*.py $T/test_cli_bench*.py -m ""` |

A domain run skips the doctests in the source modules. The default run includes them.

### CI

`.github/workflows/tests.yml` always runs the **full** suite (`-m "" -n auto`), including `slow` and `perf`, on every push and PR across the Python matrix, plus the per-package coverage gates. `bench.yml` also runs the `perf` tests on their own, serially, on PRs that touch performance-critical paths.

## Documentation

Documentation uses `mkdocs` and can be built by:

1. Install documentation requirements

```bash
pip install docs/requirements.txt
```

2. Building and serving a local copy from the `GMNSpy` folder

```bash
mkdocs serve
```

General settings for documentation can be found in `mkdocs.yml`

Code associated with including files and auto-generation of spec-related documentation can be found in `main.py`

PRs and releases will have a documentation version generated using a github workflow `.github/workflows/documentation.yml` using the versioning of `mkdocs` using `mike` package.

## Pull Requests

Use the following guidance in creating and responding to pull requests

- Generally, submit PRs to the `develop` branch.
- Keep pull requests small and focused. One issue is best.
- Link Pull Requests to Issues as appropriate.
- Complete the pull request template as best you can.
- PRs which don't pass the automatic checks should either address issues causing them to fail or comment as to why they aren't.
- Tag an available reviewer to review your PR.

*Pull Requests which do not meet these requirements may not be approved*

### Review and Approval Process

- PRs which don't pass the automatic checks should either address issues causing them to fail or comment as to why they aren't.
- Tag an available reviewer to review your PR.
- Respond to conversation and requests

*Pull Requests which do not respond to reviews may not be approved*

## Contributor Agreement

By making any contribution to the projects, contributors self-certify to the following Contributor Agreement:

By making a contribution to this project, I certify that:
>  
> a. The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
>  
> b. The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
>  
> c. The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
>  
> d. I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.
>  
Attribution: This Contributor Agreement is adapted from the node.js project available here: <https://github.com/nodejs/node/blob/main/CONTRIBUTING.md>.
