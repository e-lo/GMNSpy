"""AI-consumable docgen — llms.txt + llms-full.txt + api-index.json.

These three generators emit static artifacts that sit at the docs site
root and are consumed by AI agents (architecture §6.9).

- ``llms.txt`` is the `llms-txt convention <https://llmstxt.org/>`_:
  a short, human + LLM-readable summary that points at canonical pages.
- ``llms-full.txt`` is the same nav, but every page body concatenated
  in order — suitable for one-shot context priming.
- ``api-index.json`` is a machine-readable enumeration of every public
  symbol (re-exported via ``__all__``) across a list of packages, so
  an agent can discover the supported API surface without scraping
  the rendered docs.

The api-index ``schema_version`` is pinned from day one ("1") because
downstream agents will key on it; any breaking shape change must bump
this string and ship a migration note.

Pure stdlib (``importlib``, ``inspect``) + string emission. No SQL, no
pandas, no network.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

# Public schema version for the api-index.json contract. Bump only on
# breaking shape changes; downstream AI agents key on this.
API_INDEX_SCHEMA_VERSION = "1"


def _absolute_url(site_url: str, href: str) -> str:
    """Join a base site URL and a page href without producing ``//``."""
    return f"{site_url.rstrip('/')}/{href.lstrip('/')}"


def generate_llms_txt(*, site_url: str, nav: list[dict]) -> str:
    """Generate the ``llms.txt`` file content per the llms-txt convention.

    https://llmstxt.org/ — top-level summary + links to canonical pages.
    Each nav section becomes an ``## H2`` block listing
    ``- [Title](abs-url): description`` bullets.

    Args:
        site_url: Docs site root URL (trailing slash tolerated).
        nav: ``[{"section": str, "pages": [{"title", "href",
            "description"}]}]``.

    Returns:
        Rendered llms.txt string, newline-terminated.
    """
    lines: list[str] = ["# datagrove + gmnspy documentation", ""]
    lines.append(
        "Generated from the mkdocs nav for AI-agent consumption. Each link below points at the canonical rendered page."
    )
    lines.append("")
    for section in nav:
        lines.append(f"## {section['section']}")
        lines.append("")
        for page in section["pages"]:
            url = _absolute_url(site_url, page["href"])
            desc = page.get("description", "").strip()
            suffix = f": {desc}" if desc else ""
            lines.append(f"- [{page['title']}]({url}){suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_llms_full_txt(
    *,
    site_url: str,
    nav: list[dict],
    page_loader: Callable[[str], str],
) -> str:
    """Generate ``llms-full.txt``: every doc page concatenated in nav order.

    Each page is preceded by a ``<!-- source: href url: ... -->``
    delimiter so AI consumers can attribute extracted spans.

    Args:
        site_url: Docs site root URL.
        nav: Same shape as :func:`generate_llms_txt`.
        page_loader: ``href -> rendered text``; caller wires this to
            mkdocs' ``build_files`` registry, a filesystem walk, or
            a test stub.
    """
    parts: list[str] = [
        "# datagrove + gmnspy full documentation",
        "",
        "Every doc page concatenated in nav order. Each section starts "
        "with a `<!-- source: ... -->` delimiter pointing at the "
        "canonical URL.",
        "",
    ]
    for section in nav:
        for page in section["pages"]:
            href = page["href"]
            url = _absolute_url(site_url, href)
            parts.append(f"<!-- source: {href} url: {url} -->")
            parts.append("")
            parts.append(page_loader(href))
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# api-index.json
# ---------------------------------------------------------------------------


def _classify(obj: Any) -> str:
    """Best-effort symbol kind classification for the api-index."""
    if inspect.isclass(obj):
        return "class"
    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
        return "function"
    if inspect.ismethod(obj):
        return "method"
    if inspect.ismodule(obj):
        return "module"
    return "value"


def _safe_signature(obj: Any) -> str:
    """Return a printable signature, or ``""`` if introspection fails."""
    try:
        return f"{obj.__name__}{inspect.signature(obj)}"
    except (TypeError, ValueError):
        return getattr(obj, "__name__", repr(obj))


def _stability_for(module_name: str) -> str:
    """Stability marker derived from package version string.

    Anything with ``dev``, ``a``, or ``b`` in the version (PEP 440
    pre-release segments) is alpha; otherwise stable. Cheap heuristic
    pending a per-symbol ``@stability`` decorator in a later phase.
    """
    try:
        root = module_name.split(".")[0]
        mod = importlib.import_module(root)
        version = getattr(mod, "__version__", "")
    except ImportError:
        return "alpha"
    v = str(version).lower()
    if not v or "dev" in v or "a" in v or "b" in v or "rc" in v:
        return "alpha"
    return "stable"


def _package_version(package_name: str) -> str:
    """Return ``__version__`` from the package root, or empty string."""
    try:
        root = importlib.import_module(package_name.split(".")[0])
    except ImportError:
        return ""
    return str(getattr(root, "__version__", ""))


def _collect_symbols(package_name: str) -> list[dict]:
    """Introspect every name in ``package.__all__``, emit symbol records."""
    mod = importlib.import_module(package_name)
    names = list(getattr(mod, "__all__", []))
    stability = _stability_for(package_name)
    out: list[dict] = []
    for name in names:
        try:
            obj = getattr(mod, name)
        except AttributeError:
            continue
        out.append(
            {
                "name": name,
                "kind": _classify(obj),
                "module": getattr(obj, "__module__", package_name),
                "signature": _safe_signature(obj),
                "docstring": inspect.getdoc(obj) or "",
                "stability": stability,
            }
        )
    return out


def generate_api_index_json(packages: list[str]) -> str:
    """Generate a machine-readable public-API index for AI agents.

    Walks every name in each package's ``__all__`` via stdlib
    ``inspect`` + ``importlib`` and emits JSON with ``schema_version``
    pinned to ``"1"``. Shape::

        {"schema_version": "1", "generated_at": "<iso>",
         "packages": {"<pkg>": {"version": str, "symbols": [
            {"name", "kind", "module", "signature", "docstring",
             "stability"}, ...]}}}

    Args:
        packages: Importable dotted package names.

    Raises:
        ImportError: if any package cannot be imported.
    """
    doc: dict[str, Any] = {
        "schema_version": API_INDEX_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "packages": {},
    }
    for pkg in packages:
        doc["packages"][pkg] = {
            "version": _package_version(pkg),
            "symbols": _collect_symbols(pkg),
        }
    return json.dumps(doc, indent=2, sort_keys=False)
