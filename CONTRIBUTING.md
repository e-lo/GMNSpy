# Development

## Basic Setup

This is a **uv workspace** with two packages — `corral` (generic Frictionless engine) and `netstead` (GMNS toolkit on top). Install both packages with **all extras**, editable, in a single command from the repo root:

```bash
uv sync --all-packages --all-extras
```

That's what CI runs. It creates `.venv/` at the workspace root with both packages installed editable, plus every optional extra (`polars`, `pandas`, `s3`, `gcs`, `azure`, `keyring`, `mcp`, `clean`, `server`, `notebook`) so the full test suite + `--doctest-modules` sweep can collect every file.

Run things via `uv run`:

```bash
uv run netstead --help
uv run corral --help
uv run pytest packages
```

> **zsh users:** `[` and `]` are glob characters on zsh (the default shell on macOS). If you want to install **just one** extra ad-hoc, quote the brackets: `uv add 'netstead[clean]'` (not `uv add netstead[clean]`, which gives `zsh: no matches found`). The workspace-level `uv sync --all-packages --all-extras` doesn't hit this — no brackets in the command.

### One package at a time (rare)

If you want to install only one of the two packages (e.g. to mimic what a downstream user sees):

```bash
uv pip install -e 'packages/corral[polars,s3]'    # quoted for zsh
uv pip install -e 'packages/netstead[clean,server]'    # transitively gets corral
```

### Older / non-uv setup (not recommended)

```bash
pip install -r dev-requirements.txt
pip install -e packages/corral
pip install -e packages/netstead
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

- Support Python 3.11+.
- DuckDB (via ibis) is the only compute engine; pandas / polars / Arrow are I/O formats at the edges. No raw SQL outside `corral.engines.ibis_engine` (`scripts/lint_no_sql.py`).
- Lint and format with `ruff` (`uv run ruff check`, `uv run ruff format`); `pre-commit` runs both.
- Use Google-style docstrings for public classes and functions
- Use logging
- All code should have an associated test
- [Documentation](#documentation) lives in each package's `docs/` folder (`packages/*/docs`) and is built with `mkdocs`
- Public API is documented from docstrings in each package's `docs/reference/api.md`
- Architecture lives in [`packages/corral/docs/architecture.md`](https://github.com/e-lo/netstead/blob/main/packages/corral/docs/architecture.md). Decisions, PRDs, designs and implementation plans go in [`docs/design/`](https://github.com/e-lo/netstead/blob/main/docs/design/README.md) — see its README for the conventions and the index of every record.
- Right now, this repo prioritizes Legibility/Simplicity >> Efficiency. That might change later.

*Contributions which do not meet these requirements may not be approved*

## Testing and CI

Tests are located in the `tests` folder and leverage `pytest`

Running tests:

```bash
pytest
```

Tests are automatically run when commits are pushed to Github using the `.github/workflows/tests.yml` workflow.

## Documentation

Documentation uses `mkdocs`: one small umbrella site at the repo root plus a site per package.

1. Install the documentation dependency group

```bash
uv sync --all-packages --all-extras --group docs
```

2. Serve a site locally (umbrella, or a package's own site)

```bash
uv run mkdocs serve                                  # umbrella landing page
uv run mkdocs serve -f packages/netstead/mkdocs.yml  # netstead docs
uv run mkdocs serve -f packages/corral/mkdocs.yml    # corral docs
```

General settings for documentation can be found in `mkdocs.yml`

Each package site's mkdocs-macros hooks (spec tables, live nav) are in `packages/<pkg>/main.py`

`.github/workflows/documentation.yml` builds the umbrella and both package sites and deploys them to GitHub Pages.

## Pull Requests

Use the following guidance in creating and responding to pull requests

- Submit PRs to `main` (the trunk). Branch as `<type>/<slug>`, e.g. `feat/scope-zones`.
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
