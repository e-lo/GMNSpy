"""mkdocs-macros entry point — wires datagrove.docgen into the docs site.

This file is consumed by ``mkdocs-macros-plugin`` (declared under
``plugins:`` in :file:`mkdocs.yml`) and exposes a ``define_env(env)``
function that registers per-page macros.

Macros (matching the names used in :file:`docs/spec.md` and
:file:`docs/spec-versions/*.md`):

- ``include_file(filename, downshift_h1=True, start_line=0, end_line=None)``
  — verbatim file inclusion with optional H1 downshift and a built-in
  link-rewrite table for files moved/renamed in the v1.0 docs layout.
- ``local_frictionless_spec(version="0.97")`` — render the package
  overview of a vendored ``packages/gmnspy/gmnspy/spec/<version>/``.
- ``local_frictionless_schemas(version="0.97")`` — render the per-
  schema markdown tables of the same vendored spec.
- ``official_frictionless_spec(branch)`` /
  ``official_frictionless_schemas(branch)`` — convenience aliases that
  load the official upstream Frictionless package from GitHub for a
  given branch (``master`` or ``development``); falls back to the
  vendored ``0.97`` if the upstream load fails (so the docs build in
  offline / sandboxed environments and on PRs without network egress).

The renderers themselves live in :mod:`datagrove.docgen.markdown` —
this file is intentionally thin (no business logic) so the macros stay
trivial to test and the docgen module stays usable from other surfaces
(notebook, CLI, the AI api-index).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

# The mkdocs-macros plugin imports this module from the repo root; the
# packages are on ``sys.path`` because uv installs them in dev mode.
from datagrove.docgen import package_to_md, schemas_to_md
from datagrove.spec import SpecLoadError, load_package

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent
VENDORED_SPEC_ROOT = REPO_ROOT / "packages" / "gmnspy" / "gmnspy" / "spec"
DEFAULT_LOCAL_VERSION = "0.97"
OFFICIAL_BASE = "https://raw.githubusercontent.com/zephyr-data-specs/GMNS"

# Find/replace table for file inclusions whose link targets need
# rewriting in the new docs layout (carried over from v0.3 main.py).
FIND_REPLACE: dict[str, str] = {
    "<CONTRIBUTING.md>": "[Contributing Section](development/#CONTRIBUTING)",
    "(CODE_OF_CONDUCT.md)": "(development/#CODE_OF_CONDUCT)",
    "CONTRIBUTING.md)": "development/#CONTRIBUTING)",
    "<LICENSE>": "[LICENSE](https://github.com/e-lo/GMNSpy/blob/main/LICENSE)",
    "contributors.md)": "development/#contributors)",
    "architecture.md)": "architecture)",
}

_md_heading_re = {n: re.compile(rf"(#{{{n}}}\s)(.*)") for n in range(1, 6)}


def _downshift_md(md: str) -> str:
    """Shift every markdown heading down by one level (H1→H2, H2→H3, …)."""
    # Process deepest first so we don't double-shift an already-shifted line.
    for n in (5, 4, 3, 2, 1):
        md = re.sub(_md_heading_re[n], r"#\1\2", md)
    return md


def _load_local_package(version: str):
    """Load a vendored ``packages/gmnspy/gmnspy/spec/<version>/datapackage.json``."""
    pkg_path = VENDORED_SPEC_ROOT / version / "datapackage.json"
    return load_package(pkg_path)


def _load_official_package(branch: str):
    """Load the upstream Frictionless package for a GMNS branch.

    Falls back to the vendored ``0.97`` (with a logger.warning) when the
    network load fails — keeps docs builds green in offline environments.
    """
    url = f"{OFFICIAL_BASE}/{branch}/Specification_md/datapackage.json"
    try:
        return load_package(url)
    except SpecLoadError as e:
        logger.warning("Falling back to vendored 0.97 for branch=%r: %s", branch, e)
        return _load_local_package(DEFAULT_LOCAL_VERSION)


def define_env(env: Any) -> None:
    """Register mkdocs-macros macros against the build environment.

    ``env`` is the ``MacrosPlugin`` instance; ``env.macro`` is the
    decorator that registers a callable as a Jinja macro.
    """

    @env.macro
    def include_file(
        filename: str,
        downshift_h1: bool = True,
        start_line: int = 0,
        end_line: int | None = None,
    ) -> str:
        """Verbatim file inclusion macro (replaces v0.3 include_file)."""
        full_filename = os.path.join(env.project_dir, filename)
        with open(full_filename, encoding="utf-8") as f:
            lines = f.readlines()
        line_range = lines[start_line:end_line]
        content = "".join(line_range)

        if _md_heading_re[1].search(content) and downshift_h1:
            content = _downshift_md(content)

        page_base = getattr(getattr(env, "page", None), "file", None)
        page_url = getattr(page_base, "url", "") if page_base else ""
        for find, replace in FIND_REPLACE.items():
            if page_url and page_url in replace:
                replace = replace.replace(page_url, "")
            content = content.replace(find, replace)
        return content

    @env.macro
    def local_frictionless_spec(version: str = DEFAULT_LOCAL_VERSION) -> str:
        """Package overview markdown for the vendored GMNS ``version``."""
        logger.info("local_frictionless_spec(version=%r)", version)
        return package_to_md(_load_local_package(version))

    @env.macro
    def local_frictionless_schemas(version: str = DEFAULT_LOCAL_VERSION) -> str:
        """Per-schema markdown tables for the vendored GMNS ``version``."""
        logger.info("local_frictionless_schemas(version=%r)", version)
        return schemas_to_md(_load_local_package(version))

    @env.macro
    def official_frictionless_spec(branch: str = "master") -> str:
        """Package overview for the upstream GMNS Frictionless package."""
        logger.info("official_frictionless_spec(branch=%r)", branch)
        return package_to_md(_load_official_package(branch))

    @env.macro
    def official_frictionless_schemas(branch: str = "master") -> str:
        """Per-schema tables for the upstream GMNS Frictionless package."""
        logger.info("official_frictionless_schemas(branch=%r)", branch)
        return schemas_to_md(_load_official_package(branch))
