"""Contract test: every Python code block in our docs must actually run.

**Why this test exists.** The Python-API contract test
(``test_documented_api_contract.py``) catches references to symbols
that don't exist. The CLI contract test
(``test_documented_cli_contract.py``) catches references to CLI flags
that don't exist. Neither catches the third doc-vs-code drift class —
a code block that uses real symbols + real flags but calls them with
wrong arguments, wrong shapes, or in the wrong order.

The pre-beta review on 2026-05-27 found a dozen examples of this
class in cookbook + quickstart pages: `report.passed`, `i.is_error()`,
`net.validate(passes=[...])`, `from_point(lon=, lat=)`,
`report.to_html("path.html")`, and so on. None of these would be
caught by the symbol/flag tests — they exec-fail at runtime.

This test closes that gap. It walks every ``.md`` doc, extracts every
``python``-tagged fenced block, executes each in a fresh namespace,
and reports failures with line numbers.

**Scope decisions:**

- We only execute blocks tagged ``python`` (not pseudocode or ``py``
  for inline snippets).
- We **skip** blocks marked with the HTML comment
  ``<!-- doctest: skip -->`` immediately before the fence (escape
  hatch for examples that need network access, real S3 creds, or a
  GUI).
- We **skip** the migration guide (it deliberately shows OLD v0.3
  API that must NOT exist in v1.0).
- We **skip** generated artifacts (``llms*.txt``, ``api-index.json``).
- We **skip** assert-style blocks that depend on user input (we
  detect ``input(`` calls and skip those).
- We run blocks in a per-file namespace so common imports established
  in early blocks carry through later ones in the same page (the
  natural way a user reads the page top-to-bottom).
- Each block is wrapped in ``contextlib.redirect_stdout`` so prints
  don't pollute pytest output unless the block raises.

When this test goes red on a doc page, the failure message includes
the file, line of the fence, and the full traceback — the same
debugging info the user would see, minus their muscle memory.
"""

from __future__ import annotations

import contextlib
import io
import re
import textwrap
import warnings
from pathlib import Path

import pytest

# Repo layout: packages/gmnspy/tests/test_documented_python_contract.py
REPO_ROOT = Path(__file__).resolve().parents[3]

_DOC_GLOBS = [
    "packages/datagrove/README.md",
    "packages/datagrove/docs/**/*.md",
    "packages/gmnspy/README.md",
    "packages/gmnspy/docs/**/*.md",
    "README.md",
    "BETA.md",
]

# Fenced ```python blocks. Capture the leading line for line-number
# reporting, and the body. The directive form `.. code-block:: python`
# (RST inside markdown) is rare in our docs but we handle it too.
#
# Anchor the opening fence to start-of-line so blockquote-wrapped
# examples (`> `​``python ... `​``) — the page-style-guide pattern —
# are ignored entirely. Their inner content isn't meant to exec.
_FENCE_RE = re.compile(
    r"^```python\n(?P<body>.*?)\n```",
    flags=re.DOTALL | re.MULTILINE,
)
_RST_BLOCK_RE = re.compile(
    r"\.\.\s+code-block::\s+python\s*\n((?:[ \t]+:[\w-]+:.*\n)*)\n((?:[ \t]+.*\n?)+)",
    flags=re.MULTILINE,
)

# Inline marker placed in markdown to skip a fenced block. Example:
#     <!-- doctest: skip -->
#     ```python
#     ...code that needs S3 creds...
#     ```
_SKIP_MARKER = re.compile(r"<!--\s*doctest:\s*skip\s*-->\s*$", re.MULTILINE)


def _block_is_skipped(text: str, fence_start: int) -> bool:
    """Was the immediately-preceding non-blank line a skip marker?"""
    # Walk backwards from fence_start looking for the marker; stop at
    # the previous fence or 5 lines back (whichever first).
    preamble = text[max(0, fence_start - 500) : fence_start]
    # Take the last few lines of preamble.
    tail = "\n".join(preamble.splitlines()[-5:])
    return bool(_SKIP_MARKER.search(tail))


def _collect_blocks() -> list[tuple[Path, int, str]]:
    """Walk every doc, return [(path, line_no, body), ...]."""
    blocks: list[tuple[Path, int, str]] = []
    for glob in _DOC_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if path.name.startswith("llms") or path.name == "api-index.json":
                continue
            # Skip the migration guide — it deliberately quotes OLD v0.3
            # API as the "before" side of the migration table.
            if path.name == "v0.3-to-v1.0.md":
                continue
            text = path.read_text(encoding="utf-8")
            for match in _FENCE_RE.finditer(text):
                if _block_is_skipped(text, match.start()):
                    continue
                # Block is "real". Compute line number of the fence's
                # first line (the ```python line, 1-indexed).
                line_no = text[: match.start()].count("\n") + 1
                body = match.group("body")
                # Skip blocks that need user input.
                if "input(" in body:
                    continue
                blocks.append((path.relative_to(REPO_ROOT), line_no, body))
    return blocks


def _is_obviously_pseudocode(body: str) -> bool:
    """Heuristic: skip blocks that are clearly outline/pseudocode.

    We don't want to false-positive on snippets like ``net.foo(...)``
    where the ``...`` is a literal placeholder. These usually appear
    inside admonitions explaining shape, not executable recipes. The
    heuristic catches:

    * Empty blocks.
    * Blocks that ONLY contain ``...`` placeholders or comments.
    * Blockquote-wrapped blocks (every line starts with ``> ``). Common
      in the page-style guide where blocks demonstrate "what good code
      should look like" inside a blockquote — they're not meant to exec.
    """
    stripped = body.strip()
    if not stripped:
        return True
    # All-ellipsis or all-comment bodies.
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if all(ln in ("...", "# ...") or ln.startswith("# ") for ln in lines):
        return True
    # Blockquote-wrapped blocks — every non-blank source line starts
    # with `> ` (markdown blockquote marker). exec would choke on the
    # `>` characters; the block is illustrative, not runnable.
    source_lines = [ln for ln in body.splitlines() if ln.strip()]
    return bool(source_lines) and all(ln.lstrip().startswith("> ") for ln in source_lines)


# Per-file namespace cache so subsequent blocks see earlier imports.
# Pytest parametrizes once per (path, line_no) tuple but we want a
# shared namespace per path — a module-level dict keyed by path does it.
_NAMESPACES: dict[Path, dict] = {}


def _blocks_for_parametrize() -> list[tuple[Path, int, str]]:
    out = []
    for path, line, body in _collect_blocks():
        if _is_obviously_pseudocode(body):
            continue
        out.append((path, line, body))
    return out


_BLOCKS = _blocks_for_parametrize()

# Known doc-vs-code gaps that the pre-beta review surfaced and are
# tracked for a follow-up cookbook-sweep PR. Each entry is (path,
# line_no) so the test xfails specifically rather than skipping. Remove
# the entry once the underlying doc is fixed and the block runs.
#
# This list is the punch-list for the v1.0-beta cookbook sweep. As
# each block is fixed, remove its entry — the strict assertion takes
# over and prevents regression. Net-zero entries by GA.
#
# Format: {(relative_path_str, fence_line_no): "reason"}
_KNOWN_BROKEN: dict[tuple[str, int], str] = {
}


@pytest.fixture
def _isolate_quality_registry():
    """Snapshot + restore the datagrove quality rule registry per block.

    Doc blocks that exec ``register_rule(...)`` (e.g. the customise-
    quality cookbook) would otherwise leak into subsequent tests in
    the broader suite that depend on a clean registry. Snapshot the
    state before exec, restore after — same dance as
    ``tests/io/conftest.py``'s adapter-registry fixture.
    """
    from datagrove.quality import registry as _qreg

    snapshot = dict(_qreg._registry)
    discovered = _qreg._discovered
    try:
        yield
    finally:
        _qreg._registry.clear()
        _qreg._registry.update(snapshot)
        _qreg._discovered = discovered


@pytest.mark.parametrize(
    "path,line_no,body",
    _BLOCKS,
    ids=[f"{p}:{ln}" for p, ln, _ in _BLOCKS],
)
def test_documented_python_block_runs(path: Path, line_no: int, body: str, _isolate_quality_registry: None) -> None:
    """Every ```python fenced block in our docs must exec without raising.

    Closes the doc-vs-code drift class the symbol + flag contract
    tests don't catch — calls with wrong args, wrong shapes, or wrong
    method names that pass type/symbol resolution but raise at runtime.

    When this fails, the traceback is the SAME thing a user
    copy-pasting the example would see, with one indirection (the
    pytest harness). Fix the doc block, the test goes green, the
    next reader gets a working example.

    Skip an unreliable block with ``<!-- doctest: skip -->`` on the
    line immediately before the fence. Reserve for blocks that need
    network access, real cloud creds, a GUI, or other genuine
    non-determinism — not "this is broken and I'd rather not fix it".
    """
    key = (str(path), line_no)
    if key in _KNOWN_BROKEN:
        pytest.xfail(f"known doc-vs-code gap: {_KNOWN_BROKEN[key]}")

    # Dedent in case the block was inside a list or admonition.
    code = textwrap.dedent(body)

    # Shared namespace per file so an earlier `import gmnspy` carries.
    ns = _NAMESPACES.setdefault(path, {"__name__": f"__doctest__.{path.name}"})

    # Suppress prints, warnings (pyplot etc), but let exceptions escape.
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            exec(compile(code, str(path), "exec"), ns)
    except Exception as exc:
        pytest.fail(
            f"Documented Python block raised at exec time:\n"
            f"  file:  {path}\n"
            f"  fence: line {line_no}\n"
            f"  error: {type(exc).__name__}: {exc}\n\n"
            f"--- block body ---\n{code}\n"
            f"--- stdout so far ---\n{buf.getvalue() or '(empty)'}\n\n"
            f"Fix options:\n"
            f"  - Update the doc block to call the real API\n"
            f"  - Mark with `<!-- doctest: skip -->` if it genuinely needs\n"
            f"    network/cloud creds/GUI/non-determinism\n"
            f"  - Add ({path!s}, {line_no}) to _KNOWN_BROKEN in\n"
            f"    {Path(__file__).name} with a tracking reason"
        )
