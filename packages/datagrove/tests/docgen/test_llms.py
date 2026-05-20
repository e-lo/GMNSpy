"""Tests for AI-consumable docgen (architecture §6.9).

Covers three generators in :mod:`datagrove.docgen.llms`:

- :func:`generate_llms_txt` — llms-txt convention summary file.
- :func:`generate_llms_full_txt` — concatenation of every doc page.
- :func:`generate_api_index_json` — machine-readable public API index.

The api-index schema is a contract for downstream AI agents — see
``schema_version`` pinning in the architecture doc — so we lock both
its shape and a representative excerpt from :mod:`datagrove.reports`.
"""

from __future__ import annotations

import json

import pytest
from datagrove.docgen import (
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
)

# A minimal synthetic mkdocs-style nav. Each entry maps a section title
# to an ordered list of {title, href, description} page descriptors.
SYNTHETIC_NAV: list[dict] = [
    {
        "section": "Getting started",
        "pages": [
            {
                "title": "Install",
                "href": "install.md",
                "description": "Pip + uv install instructions.",
            },
            {
                "title": "Quickstart",
                "href": "quickstart.md",
                "description": "Load + validate a tiny network in 5 lines.",
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
        ],
    },
]


class TestGenerateLlmsTxt:
    def test_emits_title_summary_and_section_links(self):
        """llms.txt must include site title, every page title, and absolute URLs."""
        out = generate_llms_txt(
            site_url="https://example.org/docs",
            nav=SYNTHETIC_NAV,
        )

        # llms-txt convention: leading "# Title" line.
        assert out.startswith("#")
        # Sections become H2 headings.
        assert "## Getting started" in out
        assert "## Reference" in out
        # Every page becomes a bullet with title + absolute URL + description.
        assert "[Install](https://example.org/docs/install.md)" in out
        assert "[Quickstart](https://example.org/docs/quickstart.md)" in out
        assert "[API](https://example.org/docs/api.md)" in out
        assert "Pip + uv install instructions." in out

    def test_strips_trailing_slash_from_site_url(self):
        """Trailing slash on site_url must not produce double slashes in links."""
        out = generate_llms_txt(
            site_url="https://example.org/docs/",
            nav=SYNTHETIC_NAV,
        )
        assert "https://example.org/docs//install.md" not in out
        assert "https://example.org/docs/install.md" in out


class TestGenerateLlmsFullTxt:
    def test_concatenates_pages_with_headers_and_loader(self):
        """llms-full.txt is a single text blob: per-page header + body via loader."""
        bodies = {
            "install.md": "# Install\n\nRun `pip install datagrove`.",
            "quickstart.md": "# Quickstart\n\nLoad a network.",
            "api.md": "# API\n\nSee mkdocstrings.",
        }
        out = generate_llms_full_txt(
            site_url="https://example.org/docs",
            nav=SYNTHETIC_NAV,
            page_loader=lambda href: bodies[href],
        )

        # Every page body appears.
        for body in bodies.values():
            assert body in out

        # A delimiter / source comment must reference each href so an
        # AI consumer can attribute sections back to canonical URLs.
        assert "install.md" in out
        assert "quickstart.md" in out
        assert "api.md" in out
        # Page bodies appear in nav order.
        assert out.index("Run `pip install datagrove`.") < out.index("Load a network.") < out.index("See mkdocstrings.")


class TestGenerateApiIndexJson:
    def test_returns_valid_json_with_pinned_schema_version(self):
        """The schema_version must be pinned to '1' so downstream agents can lock."""
        raw = generate_api_index_json(packages=["datagrove.reports"])
        doc = json.loads(raw)

        assert doc["schema_version"] == "1"
        assert "generated_at" in doc
        assert "packages" in doc
        assert "datagrove.reports" in doc["packages"]

    def test_introspects_reports_public_symbols(self):
        """Every name in datagrove.reports.__all__ must appear in the index."""
        raw = generate_api_index_json(packages=["datagrove.reports"])
        doc = json.loads(raw)

        pkg = doc["packages"]["datagrove.reports"]
        names = {sym["name"] for sym in pkg["symbols"]}

        # From datagrove.reports.__all__:
        expected = {
            "Category",
            "Issue",
            "Severity",
            "ValidationReport",
            "render_html",
            "render_json",
            "render_rich",
            "severity_rank",
        }
        assert expected <= names

    def test_symbol_records_have_required_fields(self):
        """Each symbol record must have name, kind, module, signature, docstring, stability."""
        raw = generate_api_index_json(packages=["datagrove.reports"])
        doc = json.loads(raw)
        symbols = doc["packages"]["datagrove.reports"]["symbols"]

        required = {"name", "kind", "module", "signature", "docstring", "stability"}
        for sym in symbols:
            assert required <= set(sym.keys()), f"missing fields in {sym}"

        # Stability is one of the documented values.
        for sym in symbols:
            assert sym["stability"] in {"stable", "alpha"}

        # ValidationReport should be classified as a class with a class signature.
        vr = next(s for s in symbols if s["name"] == "ValidationReport")
        assert vr["kind"] == "class"
        # The signature should include spec_version since dataclass __init__ has it.
        assert "spec_version" in vr["signature"]

        # render_json is a function — kind should reflect that.
        rj = next(s for s in symbols if s["name"] == "render_json")
        assert rj["kind"] == "function"

    def test_unknown_package_raises_module_not_found(self):
        """Unknown packages bubble up ImportError so misconfig is loud."""
        with pytest.raises((ImportError, ModuleNotFoundError)):
            generate_api_index_json(packages=["datagrove.does_not_exist"])
