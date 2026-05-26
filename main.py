"""mkdocs-macros entry point — markdown macros + AI-docgen build hook.

Wired by ``mkdocs-macros-plugin`` (declared under ``plugins:`` in
:file:`mkdocs.yml`). On every ``mkdocs build`` this module:

1. Registers per-page macros (:func:`include_file`,
   :func:`local_frictionless_spec`, :func:`local_frictionless_schemas`,
   :func:`official_frictionless_spec`, :func:`official_frictionless_schemas`)
   for use inside markdown pages — see :file:`docs/spec.md` and
   :file:`docs/spec-versions/*.md`.
2. Emits AI-docgen artifacts (``llms.txt``, ``llms-full.txt``,
   ``ai/api-index.json``) into ``docs_dir`` per architecture §6.9.

The renderers themselves live in :mod:`datagrove.docgen`; this file is
intentionally thin so the macros stay trivial to test and the docgen
module stays usable from the notebook, CLI, and AI api-index surfaces.

Phase 4 follow-up: swap the static ``_DEFAULT_NAV`` for live mkdocs
nav extraction (``env.conf['nav']`` + ``env.files``). Generator
contracts won't change; only the nav source.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

# The mkdocs-macros plugin imports this module from the repo root; the
# packages are on ``sys.path`` because uv installs them in dev mode.
from datagrove.docgen import (
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
    package_to_md,
    schemas_to_md,
)
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


# Static nav fallback — used when ``env.conf["nav"]`` is missing or
# unparseable. Kept in sync with ``mkdocs.yml`` by hand for now; the
# live-nav extraction below prefers ``env.conf["nav"]`` and only falls
# back to this when the build-time config doesn't expose it.
#
# Updated for docs Wave D-1: split into datagrove/ + gmnspy/ + shared/
# subtrees per audience separation feedback.
_DEFAULT_NAV: list[dict] = [
    {
        "section": "Home",
        "pages": [
            {
                "title": "Home",
                "href": "index.md",
                "description": "Top-level landing — pick datagrove or gmnspy.",
            },
        ],
    },
    {
        "section": "datagrove",
        "pages": [
            {
                "title": "Overview",
                "href": "datagrove/index.md",
                "description": "Generic Frictionless data-package engine — what / use cases / install.",
            },
            {
                "title": "Quickstart",
                "href": "datagrove/quickstart.md",
                "description": "Install, load, validate any Frictionless package in 5 minutes.",
            },
            {
                "title": "Cookbook",
                "href": "datagrove/cookbook/index.md",
                "description": "Generic recipes — S3 reads, format conversion, spatial scope.",
            },
            {
                "title": "API reference",
                "href": "datagrove/reference/api.md",
                "description": "Public datagrove API symbols.",
            },
        ],
    },
    {
        "section": "gmnspy",
        "pages": [
            {
                "title": "Overview",
                "href": "gmnspy/index.md",
                "description": "GMNS Python toolkit — what / use cases / install.",
            },
            {
                "title": "Quickstart",
                "href": "gmnspy/quickstart.md",
                "description": "Load the bundled Leavenworth fixture and run validation in 5 minutes.",
            },
            {
                "title": "What is GMNS?",
                "href": "gmnspy/what-is-gmns.md",
                "description": "Plain-English intro to the spec.",
            },
            {
                "title": "Visual tour",
                "href": "gmnspy/visual-tour.md",
                "description": "Leavenworth rendered as map + validation + edit + scope.",
            },
            {
                "title": "Cookbook",
                "href": "gmnspy/cookbook/index.md",
                "description": "GMNS-specific recipes — validate, scope, edit, host, drive from AI.",
            },
            {
                "title": "API reference",
                "href": "gmnspy/reference/api.md",
                "description": "Public gmnspy API symbols (Network, scope, clean, quality).",
            },
            {
                "title": "Schema reference",
                "href": "gmnspy/reference/spec.md",
                "description": "GMNS field-level reference per table.",
            },
            {
                "title": "Table of tables",
                "href": "gmnspy/reference/table-of-tables.md",
                "description": "Every GMNS table with purpose + FK diagram.",
            },
            {
                "title": "Glossary",
                "href": "gmnspy/reference/glossary.md",
                "description": "GMNS terms + project conventions.",
            },
            {
                "title": "Migration v0.3 → v1.0",
                "href": "gmnspy/migration/v0.3-to-v1.0.md",
                "description": "Side-by-side API mapping for v0.3 users.",
            },
            {
                "title": "MCP tools reference",
                "href": "gmnspy/ai/mcp-tools.md",
                "description": "MCP server tools shipped with gmnspy.",
            },
        ],
    },
    {
        "section": "AI surface",
        "pages": [
            {
                "title": "Overview",
                "href": "shared/ai/index.md",
                "description": "llms.txt + api-index.json + Skills + MCP — how to drive this with an agent.",
            },
            {
                "title": "Drive the CLI from an agent",
                "href": "shared/ai/json-cli.md",
                "description": "--json contract patterns for tool-call loops.",
            },
        ],
    },
    {
        "section": "Concepts",
        "pages": [
            {
                "title": "Frictionless data packages",
                "href": "shared/concepts/frictionless.md",
                "description": "The spec both packages build on, with GMNS mapping.",
            },
        ],
    },
    {
        "section": "Project",
        "pages": [
            {
                "title": "Architecture",
                "href": "shared/architecture.md",
                "description": "Single source of truth for the v1.0 design.",
            },
            {
                "title": "Migration map",
                "href": "shared/migration.md",
                "description": "Where to find migration guidance per package.",
            },
            {
                "title": "Development",
                "href": "shared/development.md",
                "description": "Contributor workflow — monorepo setup, tests, PRs.",
            },
        ],
    },
]

_PACKAGES_FOR_API_INDEX = ["datagrove", "datagrove.reports", "gmnspy"]


def _extract_live_nav(env_conf: dict) -> list[dict] | None:
    """Flatten ``env.conf["nav"]`` into the {section, pages} shape ``_DEFAULT_NAV`` uses.

    mkdocs nav is a recursive list of dict-or-string entries:

    * ``{"Title": "path.md"}`` — a titled leaf page.
    * ``"path.md"`` — a bare leaf (title comes from the page's H1 / frontmatter).
    * ``{"Title": [<more entries>]}`` — a section with children.

    The flattener walks recursively, collecting every leaf under the
    nearest section header. For our purposes a "section" is the
    second-level container (datagrove / gmnspy / AI surface / etc.) so
    the resulting structure is two-level — section → pages — and
    deeper nesting (e.g. gmnspy → Cookbook → recipes) collapses into
    the section's flat page list.

    Returns ``None`` when ``env_conf`` doesn't carry a parseable nav;
    callers fall back to :data:`_DEFAULT_NAV`.
    """
    raw_nav = env_conf.get("nav") if isinstance(env_conf, dict) else None
    if not raw_nav:
        return None

    def _walk(entries: list, default_title: str | None = None) -> list[dict]:
        """Recurse into a nav-entry list, collecting (title, href) leaves."""
        pages: list[dict] = []
        for entry in entries:
            if isinstance(entry, str):
                # Bare path — title falls back to the section name or filename.
                pages.append({"title": default_title or entry, "href": entry, "description": ""})
            elif isinstance(entry, dict) and len(entry) == 1:
                title, body = next(iter(entry.items()))
                if isinstance(body, str):
                    pages.append({"title": title, "href": body, "description": ""})
                elif isinstance(body, list):
                    # Nested section — flatten children under the parent.
                    pages.extend(_walk(body, default_title=title))
        return pages

    sections: list[dict] = []
    for entry in raw_nav:
        if isinstance(entry, str):
            # Top-level bare string (e.g. just "index.md") → its own section.
            sections.append({"section": entry, "pages": [{"title": entry, "href": entry, "description": ""}]})
        elif isinstance(entry, dict) and len(entry) == 1:
            title, body = next(iter(entry.items()))
            if isinstance(body, str):
                # Single-page section.
                sections.append({"section": title, "pages": [{"title": title, "href": body, "description": ""}]})
            elif isinstance(body, list):
                # Multi-page section — recurse and flatten.
                pages = _walk(body, default_title=title)
                if pages:
                    sections.append({"section": title, "pages": pages})
    return sections or None


def _downshift_md(md: str) -> str:
    """Shift every markdown heading down by one level (H1→H2, H2→H3, …)."""
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


def _docs_dir(env: Any) -> Path:
    """Resolve the mkdocs docs_dir from the macros env, with a fallback."""
    try:
        return Path(env.conf["docs_dir"])
    except (AttributeError, KeyError, TypeError):
        return REPO_ROOT / "docs"


def _write_ai_artifacts(docs_dir: Path, nav: list[dict], site_url: str) -> None:
    """Write llms.txt, llms-full.txt, ai/api-index.json into ``docs_dir``."""

    def _page_loader(href: str) -> str:
        page = docs_dir / href
        if page.exists():
            return page.read_text(encoding="utf-8")
        return f"<!-- page {href} not found at build time -->"

    (docs_dir / "llms.txt").write_text(
        generate_llms_txt(site_url=site_url, nav=nav),
        encoding="utf-8",
    )
    (docs_dir / "llms-full.txt").write_text(
        generate_llms_full_txt(site_url=site_url, nav=nav, page_loader=_page_loader),
        encoding="utf-8",
    )
    ai_dir = docs_dir / "ai"
    ai_dir.mkdir(exist_ok=True)
    (ai_dir / "api-index.json").write_text(
        generate_api_index_json(packages=_PACKAGES_FOR_API_INDEX),
        encoding="utf-8",
    )


def define_env(env: Any) -> None:
    """Register mkdocs-macros macros + emit AI-docgen artifacts at build time.

    ``env`` is the ``MacrosPlugin`` instance; ``env.macro`` is the decorator
    that registers a callable as a Jinja macro.
    """
    # --- AI docgen build artifacts (architecture §6.9) ---
    docs_dir = _docs_dir(env)
    env_conf = getattr(env, "conf", {}) if hasattr(env, "conf") else {}
    site_url = (env_conf.get("site_url") if isinstance(env_conf, dict) else None) or "https://e-lo.github.io/GMNSpy"
    # Prefer the live mkdocs nav so llms.txt can't drift from the user-
    # facing site map; fall back to the hand-maintained _DEFAULT_NAV
    # when the macros plugin runs outside a normal build (e.g. tests).
    nav = _extract_live_nav(env_conf) or _DEFAULT_NAV
    try:
        _write_ai_artifacts(docs_dir, nav, site_url)
    except Exception as exc:
        # Docs build shouldn't fail on artifact emission — log & continue.
        logger.warning("AI docgen artifact emission failed: %s", exc)

    # --- Per-page macros ---
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
