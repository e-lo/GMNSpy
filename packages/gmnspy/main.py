"""mkdocs-macros entry point for the gmnspy documentation site.

Loaded by ``mkdocs-macros-plugin`` from this directory because the
gmnspy ``mkdocs.yml`` lives alongside (`packages/gmnspy/mkdocs.yml`).
Three responsibilities:

1. **Spec macros** — :func:`local_frictionless_spec`,
   :func:`local_frictionless_schemas`, :func:`official_frictionless_spec`,
   :func:`official_frictionless_schemas`. Used inside markdown pages
   to render the vendored or upstream GMNS spec as tables.
2. **AI artifact emission** — emit ``llms.txt``, ``llms-full.txt``,
   ``ai/api-index.json`` per architecture §6.9 (gmnspy package only;
   the datagrove site emits its own from its own ``main.py``).
3. **File inclusion helper** — :func:`include_file` for embedding
   repo-root files (README, CONTRIBUTING, etc.) with link rewriting.

Per the docs v3 split: each package has its own self-contained docs
site with its own macros file. The shared logic was previously in a
repo-root ``main.py``; now lives in two parallel files (this one + the
datagrove one). The duplication is intentional — each site is
independently buildable.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from datagrove.docgen import (
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
    package_to_md,
    schemas_to_md,
)
from datagrove.spec import SpecLoadError, load_package

logger = logging.getLogger(__name__)

# Resolve repo paths from this file's location (packages/gmnspy/).
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
VENDORED_SPEC_ROOT = PACKAGE_ROOT / "gmnspy" / "spec"
DEFAULT_LOCAL_VERSION = "0.97"
OFFICIAL_BASE = "https://raw.githubusercontent.com/zephyr-data-specs/GMNS"

# Link rewrites for include_file: pages that used to reference shared
# docs (CONTRIBUTING, LICENSE, etc.) get pointed at the umbrella or
# GitHub source. The datagrove site holds development.md; gmnspy
# cross-links via absolute URL.
FIND_REPLACE: dict[str, str] = {
    "<CONTRIBUTING.md>": "[Contributing](https://github.com/e-lo/GMNSpy/blob/main/CONTRIBUTING.md)",
    "(CODE_OF_CONDUCT.md)": "(https://github.com/e-lo/GMNSpy/blob/main/CODE_OF_CONDUCT.md)",
    "CONTRIBUTING.md)": "https://github.com/e-lo/GMNSpy/blob/main/CONTRIBUTING.md)",
    "<LICENSE>": "[LICENSE](https://github.com/e-lo/GMNSpy/blob/main/LICENSE)",
    "contributors.md)": "https://github.com/e-lo/GMNSpy/blob/main/CONTRIBUTORS.md)",
    # The architecture lives on the datagrove site; gmnspy pages cross-link.
    "architecture.md)": "https://e-lo.github.io/GMNSpy/datagrove/architecture/)",
}

_md_heading_re = {n: re.compile(rf"(#{{{n}}}\s)(.*)") for n in range(1, 6)}

# Static fallback nav matching packages/gmnspy/mkdocs.yml. The
# live-nav extractor below prefers env.conf["nav"] and only falls
# back to this when the macros plugin runs outside a normal build.
_DEFAULT_NAV: list[dict] = [
    {
        "section": "gmnspy docs",
        "pages": [
            {"title": "Home", "href": "index.md", "description": "gmnspy overview + install."},
            {
                "title": "Quickstart",
                "href": "quickstart.md",
                "description": "Load the bundled Leavenworth fixture and run validation in 5 minutes.",
            },
            {
                "title": "What is GMNS?",
                "href": "what-is-gmns.md",
                "description": "Plain-English intro to the spec.",
            },
            {
                "title": "Visual tour",
                "href": "visual-tour.md",
                "description": "Leavenworth rendered as map + validation + edit + scope.",
            },
        ],
    },
    {
        "section": "Cookbook",
        "pages": [
            {
                "title": "Cookbook",
                "href": "cookbook/index.md",
                "description": "GMNS-specific recipes — validate, scope, edit, host, drive from AI.",
            },
        ],
    },
    {
        "section": "Reference",
        "pages": [
            {
                "title": "API",
                "href": "reference/api.md",
                "description": "Public gmnspy API symbols (Network, scope, clean, quality).",
            },
            {
                "title": "Schema",
                "href": "reference/spec.md",
                "description": "GMNS field-level reference per table.",
            },
            {
                "title": "Table of tables",
                "href": "reference/table-of-tables.md",
                "description": "Every GMNS table with purpose + FK diagram.",
            },
            {
                "title": "Glossary",
                "href": "reference/glossary.md",
                "description": "GMNS terms + project conventions.",
            },
        ],
    },
    {
        "section": "Migration + AI",
        "pages": [
            {
                "title": "Migration v0.3 → v1.0",
                "href": "migration/v0.3-to-v1.0.md",
                "description": "Side-by-side API mapping for v0.3 users.",
            },
            {
                "title": "MCP tools reference",
                "href": "ai/mcp-tools.md",
                "description": "MCP server tools shipped with gmnspy.",
            },
        ],
    },
]

# api-index covers ONLY gmnspy here. The datagrove site emits its own
# api-index covering datagrove + datagrove.reports.
_PACKAGES_FOR_API_INDEX = ["gmnspy"]

SITE_URL = "https://e-lo.github.io/GMNSpy/gmnspy"


def _extract_live_nav(env_conf: dict) -> list[dict] | None:
    """Flatten ``env.conf["nav"]`` into {section, pages} shape.

    Recurses through nested dict/string/list entries. External URLs in
    the nav (used in this site to link to the datagrove site and the
    umbrella) are skipped — they don't belong in the llms.txt artifact
    for this site.
    """
    raw_nav = env_conf.get("nav") if isinstance(env_conf, dict) else None
    if not raw_nav:
        return None

    def _is_external(href: str) -> bool:
        return href.startswith(("http://", "https://"))

    def _walk(entries: list, default_title: str | None = None) -> list[dict]:
        pages: list[dict] = []
        for entry in entries:
            if isinstance(entry, str):
                if not _is_external(entry):
                    pages.append({"title": default_title or entry, "href": entry, "description": ""})
            elif isinstance(entry, dict) and len(entry) == 1:
                title, body = next(iter(entry.items()))
                if isinstance(body, str):
                    if not _is_external(body):
                        pages.append({"title": title, "href": body, "description": ""})
                elif isinstance(body, list):
                    pages.extend(_walk(body, default_title=title))
        return pages

    sections: list[dict] = []
    for entry in raw_nav:
        if isinstance(entry, str):
            if not _is_external(entry):
                sections.append({"section": entry, "pages": [{"title": entry, "href": entry, "description": ""}]})
        elif isinstance(entry, dict) and len(entry) == 1:
            title, body = next(iter(entry.items()))
            if isinstance(body, str):
                if not _is_external(body):
                    sections.append({"section": title, "pages": [{"title": title, "href": body, "description": ""}]})
            elif isinstance(body, list):
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
        return PACKAGE_ROOT / "docs"


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

    Same shape as the repo-root ``main.py`` was, scoped now to the
    gmnspy site only. ``env`` is the ``MacrosPlugin`` instance.
    """
    docs_dir = _docs_dir(env)
    env_conf = getattr(env, "conf", {}) if hasattr(env, "conf") else {}
    site_url = (env_conf.get("site_url") if isinstance(env_conf, dict) else None) or SITE_URL
    nav = _extract_live_nav(env_conf) or _DEFAULT_NAV
    try:
        _write_ai_artifacts(docs_dir, nav, site_url)
    except Exception as exc:
        logger.warning("AI docgen artifact emission failed: %s", exc)

    @env.macro
    def include_file(
        filename: str,
        downshift_h1: bool = True,
        start_line: int = 0,
        end_line: int | None = None,
    ) -> str:
        """Verbatim file inclusion macro with link rewriting.

        ``filename`` is resolved relative to the repo root so that
        README, CONTRIBUTING, LICENSE etc. can be pulled into docs.
        """
        full_filename = os.path.join(REPO_ROOT, filename)
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
