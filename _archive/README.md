# `_archive/` — frozen v0.3.x code

This directory contains the v0.3.5 codebase (Python modules, tests, fixtures, build config) **frozen** as of the start of the v1.0 refactor on `refactor/v1.0`.

## Why it exists

The v1.0 plan calls for a clean break, not a backwards-compatibility shim layer. But during Phase 0 (repo prep), keeping the old code visible — out of the import path — lets us:

- Reference the prior validation logic, schema parsing, and docs macros while building the new `datagrove` + `gmnspy` packages under `packages/`.
- Run `git diff` against the old code when porting bug fixes or behaviors.
- Delete it confidently in a single closeout commit at the end of Phase 0.

## What's here

- `gmnspy/` — the v0.3.5 Python package (modules + spec JSONs).
- `tests/` — the v0.3.5 pytest suite + small CSV fixtures.
- `main.py` — the mkdocs-macros entry point used by the v0.3.5 docs site (will be ported to `datagrove.docgen.markdown` in Phase 3 task 3.4).
- `setup.py` — superseded by the per-package `pyproject.toml`s under `packages/*/`.
- `pytest.ini`, `requirements.txt`, `dev-requirements.txt`, `.flake8` — superseded by the workspace-root `pyproject.toml` (`[tool.pytest.ini_options]`, `[dependency-groups]`, `[tool.ruff]`).

## Lifetime

Removed in the Phase 0 closeout commit (single dedicated commit at the end of Phase 0). After that, this directory will not exist on `refactor/v1.0` or any descendant branch. The history is preserved in the merge of `origin/main` into `refactor/v1.0` and in upstream `main`/`develop`.
