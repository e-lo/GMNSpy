"""mkdocs-macros hook: emit AI docgen artifacts at build time (arch §6.9).

Wired by ``mkdocs.yml`` via the already-installed ``macros`` plugin.
On every ``mkdocs build`` writes ``llms.txt``, ``llms-full.txt``, and
``ai/api-index.json`` into ``docs_dir``.

Phase 4 follow-up: swap the static ``_DEFAULT_NAV`` for live mkdocs
nav extraction (``env.conf['nav']`` + ``env.files``). Generator
contracts won't change; only the nav source.
"""

from __future__ import annotations

from pathlib import Path

from datagrove.docgen import (
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
)

# Static nav stub — replace with live mkdocs nav extraction in Phase 4.
_DEFAULT_NAV: list[dict] = [
    {
        "section": "Overview",
        "pages": [
            {
                "title": "Home",
                "href": "index.md",
                "description": "Project overview + install.",
            },
            {
                "title": "Architecture",
                "href": "architecture.md",
                "description": "Single source of truth for the v1.0 design.",
            },
            {
                "title": "GMNS data model",
                "href": "gmns-data-model.md",
                "description": "ER diagrams for link/node/lane/etc.",
            },
        ],
    },
    {
        "section": "Reference",
        "pages": [
            {
                "title": "API",
                "href": "api.md",
                "description": "Auto-generated symbol reference.",
            },
            {
                "title": "Spec",
                "href": "spec.md",
                "description": "GMNS spec field reference.",
            },
            {
                "title": "Development",
                "href": "development.md",
                "description": "Contributor workflow.",
            },
        ],
    },
]

_PACKAGES_FOR_API_INDEX = ["datagrove", "datagrove.reports"]


def _docs_dir(env) -> Path:
    """Resolve the mkdocs docs_dir from the macros env, with a fallback."""
    try:
        return Path(env.conf["docs_dir"])
    except (AttributeError, KeyError, TypeError):
        return Path(__file__).parent / "docs"


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


def define_env(env) -> None:
    """mkdocs-macros entry point — runs once per ``mkdocs build``."""
    docs_dir = _docs_dir(env)
    site_url = (
        getattr(env, "conf", {}).get("site_url") if hasattr(env, "conf") else None
    ) or "https://e-lo.github.io/GMNSpy"
    _write_ai_artifacts(docs_dir, _DEFAULT_NAV, site_url)
