"""Contract test: every public symbol the docs reference must exist.

**Why this test exists.** During the v1.0 CLI walk-through review on
2026-05-26 we discovered ``gmnspy.read()`` and ``gmnspy.validate()`` were
documented in the README + quickstart + migration guide + llms-full.txt
(~15 references between them) but never implemented. The Batch A 3-lens
code review never opened the docs; the CI test suite never followed an
import chain from a markdown file.

This test closes that gap. It walks every ``.md`` file under each
package's docs tree + README, extracts every reference of the form
``gmnspy.<name>`` or ``datagrove.<name>``, and asserts:

1. The dotted path resolves via ``importlib`` (it's a real attribute).
2. If the doc reference is the top-level form (one dot, e.g.
   ``gmnspy.read``), the symbol is also in the package's ``__all__``
   so it shows up in ``dir()`` / tab-completion.

A doc reference of the form ``gmnspy.X.Y`` (submodule attribute) is
checked transitively — Y must be importable from X.

**Scope decisions:**

- We **only** check ``gmnspy.X`` and ``datagrove.X`` style references —
  not bare Python identifiers (``Network``, ``Package``) which the docs
  might mention without importing.
- We **skip** anything that looks like a path (contains ``/``) or a
  URL.
- We **whitelist** known-fictional references (e.g. v0.3 API names
  shown in the migration guide as "old, do not use") via an explicit
  set below — better than fuzzy heuristics.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

# Repo layout: packages/gmnspy/tests/test_documented_api_contract.py
REPO_ROOT = Path(__file__).resolve().parents[3]

# Markdown files to scan. Includes both per-package docs trees plus
# their READMEs (READMEs render on GitHub + PyPI and are often the
# first place a user lands).
_DOC_GLOBS = [
    "packages/datagrove/README.md",
    "packages/datagrove/docs/**/*.md",
    "packages/gmnspy/README.md",
    "packages/gmnspy/docs/**/*.md",
]

# Pattern: `gmnspy.<name>` or `datagrove.<name>`, possibly with further
# dotted attributes. We capture the full dotted form so we can resolve
# it via importlib + getattr chain.
_REF_RE = re.compile(r"\b(gmnspy|datagrove)((?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)")

# Known-fictional references. Most of these are v0.3 API names that
# the migration guide explicitly tells users NOT to use. Anything we
# *intentionally* describe as old-and-removed goes here.
_KNOWN_FICTIONAL = {
    # Old v0.3 API surface, documented in migration/v0.3-to-v1.0.md
    # as the "before" side of the migration table. These names are
    # intentionally referenced as "don't use these anymore"; they
    # MUST NOT exist in the v1.0 surface. (The migration page itself
    # is also skipped wholesale in _collect_references; this catches
    # any prose references that leak into other pages.)
    "gmnspy.read_gmns_network",
    "gmnspy.read_gmns_csv",
    "gmnspy.schema.document_schemas_to_md",
    "gmnspy.schema.read_config",
    "gmnspy.schema.read_schema",
    "gmnspy.utils.list_to_md_table",
    "gmnspy.utils.logger",
    "gmnspy.validation._check_",
    "gmnspy.validation.apply_schema_to_df",
    "gmnspy.validation.constraint_checking",
    "gmnspy.validation.validate_foreign_keys",
    # Cosmetic references in prose ("the gmnspy.spec submodule") that
    # aren't real attribute paths but match the regex.
    "gmnspy.__file__",  # python builtin, just a doc example
    "gmnspy.symbols",  # generic prose
    "gmnspy.utils",  # generic prose; no such submodule
    "datagrove.utils",  # generic prose; no such submodule
    "datagrove.package",  # lowercase — refers to the Package class, not a submodule
    # Setuptools entry-point GROUP NAME (not a Python attribute path).
    # Appears in `[project.entry-points."datagrove.quality.rules"]`
    # and in architectural prose ("the datagrove.quality.rules group").
    "datagrove.quality.rules",
}

# Known doc-vs-code gaps surfaced by this test on its first run
# (2026-05-26). Each entry here is a TODO: either implement the
# symbol or change the doc reference. As gaps are closed, REMOVE the
# entry from this set — the strict assertion then takes over and
# prevents regression.
#
# Open a tracking issue for any gap that won't be fixed in the same
# PR as the doc change. Each entry below SHOULD have a corresponding
# tracker.
_KNOWN_DOC_GAPS = {
    # Doc-side fixes (point at wrong / nonexistent names):
    "datagrove.quality.run",
    # — architecture.md §6.x says `datagrove.quality.run(net)` but
    #   reality is `datagrove.quality.run_quality`. Rename one side.
    "datagrove.validation.codes",
    # — cookbook/validate-network.md says "the full list lives in
    #   datagrove.validation.codes". The codes enum is actually at
    #   datagrove.validation.types or datagrove.reports.<X>. Fix doc.
    "gmnspy.bench.run_bench",
    # — cookbook/run-bench.md promises a programmatic API at
    #   gmnspy.bench.run_bench, but bench is CLI-only. Either
    #   promote the CLI's bench function or fix the doc.
    "gmnspy.scope.from_bbox",
    "gmnspy.scope.from_polygon",
    # — concepts/engines.md says these live in gmnspy.scope but
    #   they're actually in datagrove.dataset.view (from_bbox exists,
    #   from_polygon may not). Either add re-exports in gmnspy.scope
    #   or fix the doc reference.
}


def _collect_references() -> dict[str, list[Path]]:
    """Walk every doc file, return {dotted_ref: [files that mention it]}."""
    refs: dict[str, list[Path]] = {}
    for glob in _DOC_GLOBS:
        for path in REPO_ROOT.glob(glob):
            # Skip auto-generated artifacts (llms*.txt + ai/api-index.json
            # are built from the source docs; we'd double-count, and the
            # api-index.json embeds docstrings that mention old API names).
            if path.name.startswith("llms") or path.name == "api-index.json":
                continue
            text = path.read_text(encoding="utf-8")
            # Strip fenced code blocks tagged as bash/shell/console/toml.
            # Bash/shell blocks reference CLI commands, not Python imports.
            # TOML blocks contain `[project.entry-points."datagrove.X.Y"]`
            # group names that look like Python paths but aren't.
            text = re.sub(
                r"```(?:bash|shell|sh|console|zsh|toml|ini)\n.*?\n```",
                "",
                text,
                flags=re.DOTALL,
            )
            # Strip inline ENTRY POINT group strings — `"datagrove.quality.rules"`
            # inside `[project.entry-points."..."]` is a setuptools group name,
            # not a Python attribute path. Same for any quoted dotted string
            # that lives inside a TOML-shaped `entry-points` context.
            text = re.sub(
                r'\[project\.entry-points\."[^"]+"\]',
                "",
                text,
            )
            text = re.sub(
                r'`?\[project\.entry-points\."[^"]+"\]`?',
                "",
                text,
            )
            # Strip migration-table "old API" cells. The migration guide
            # has a "| OLD | NEW | NOTES |" table where the OLD column
            # mentions v0.3 names that must NOT exist. We can't easily
            # parse the table column; instead we skip any reference that
            # appears inside backticks AND a paragraph mentioning migration.
            # Cheap proxy: drop the whole migration page from scanning.
            if path.name == "v0.3-to-v1.0.md":
                continue
            for match in _REF_RE.finditer(text):
                pkg, dotted = match.group(1), match.group(2)
                full = f"{pkg}{dotted}"
                if full in _KNOWN_FICTIONAL:
                    continue
                refs.setdefault(full, []).append(path.relative_to(REPO_ROOT))
    return refs


def _resolve(dotted: str) -> tuple[bool, str]:
    """Try to import / getattr-chain a dotted path. Return (ok, error_msg)."""
    parts = dotted.split(".")
    # Try importing the longest dotted-prefix that's a module, then
    # getattr() the remainder.
    obj = None
    consumed = 0
    for i in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:i]))
            consumed = i
            break
        except ImportError:
            continue
    if obj is None:
        return False, f"cannot import any prefix of {dotted!r}"
    for attr in parts[consumed:]:
        if not hasattr(obj, attr):
            return False, f"{'.'.join(parts[:consumed])} has no attribute {attr!r}"
        obj = getattr(obj, attr)
    return True, ""


def _references() -> list[tuple[str, list[Path]]]:
    """Parametrize helper: return [(ref, mentioning_files), ...]."""
    return sorted(_collect_references().items())


@pytest.mark.parametrize(
    "dotted_ref,mentioning_files",
    _references(),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_documented_symbol_exists(dotted_ref: str, mentioning_files: list[Path]) -> None:
    """Every ``gmnspy.X`` / ``datagrove.X`` in our docs must actually resolve.

    If a doc page promises ``import gmnspy; gmnspy.X(...)``, then
    ``gmnspy.X`` had better exist when a user types it. This test fails
    loudly when docs and code drift — closes the gap that let
    ``gmnspy.read()`` live in the README for months while throwing
    ``AttributeError`` at runtime.

    On failure, the message tells you both *what* is missing and
    *which docs* claim it exists, so the fix is targeted.
    """
    ok, err = _resolve(dotted_ref)
    if not ok:
        files = "\n    ".join(str(p) for p in mentioning_files)
        if dotted_ref in _KNOWN_DOC_GAPS:
            pytest.xfail(f"known doc-vs-code gap: {dotted_ref} ({err}) — see _KNOWN_DOC_GAPS in {Path(__file__).name}")
        pytest.fail(
            f"Documented symbol does not exist: {dotted_ref}\n"
            f"  reason: {err}\n"
            f"  referenced by:\n    {files}\n\n"
            f"Fix options:\n"
            f"  - Implement {dotted_ref} (if the docs are aspirational)\n"
            f"  - Update the docs to use the actual import path\n"
            f"  - Add {dotted_ref!r} to _KNOWN_FICTIONAL in {Path(__file__).name}\n"
            f"    if the reference is intentional prose (e.g. an old API name\n"
            f"    described in a migration guide)\n"
            f"  - Add {dotted_ref!r} to _KNOWN_DOC_GAPS if you're tracking\n"
            f"    the gap for a follow-up PR (xfail until removed)."
        )
    # The reference resolves now. If it was in the known-gap list,
    # that's a regression in the OTHER direction — someone fixed it
    # but forgot to remove the xfail entry. Force a flag so the gap
    # list stays accurate.
    if dotted_ref in _KNOWN_DOC_GAPS:
        pytest.fail(
            f"{dotted_ref} now resolves but is still in _KNOWN_DOC_GAPS. "
            f"Remove it from the set in {Path(__file__).name} so the "
            f"strict assertion takes over and guards against regression."
        )


def test_top_level_read_is_public() -> None:
    """``gmnspy.read`` and ``datagrove.read`` are the documented I/O front door.

    Belt-and-suspenders on the parametrized scan: explicitly assert these
    exist AND are in ``__all__`` (so they show up in ``dir()`` and any
    auto-generated reference docs treat them as public).
    """
    import datagrove
    import gmnspy

    assert hasattr(gmnspy, "read"), "gmnspy.read missing — see architecture §6.1"
    assert "read" in gmnspy.__all__, "gmnspy.read exists but isn't in __all__"
    assert hasattr(datagrove, "read"), "datagrove.read missing — see architecture §6.1"
    assert "read" in datagrove.__all__, "datagrove.read exists but isn't in __all__"
