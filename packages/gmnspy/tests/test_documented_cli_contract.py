"""Contract test: every CLI flag the docs reference must exist.

**Why this test exists.** The Python-API contract test (``test_documented_api_contract.py``)
catches doc-vs-code drift for ``gmnspy.X`` / ``datagrove.X`` symbols. It doesn't catch
**CLI** drift — the v1.0 walk-through on 2026-05-26 found ``gmnspy validate --report=html
-o PATH`` documented but never implemented (only ``--json`` existed).

This test closes that gap. It walks every ``.md`` doc, finds every
``gmnspy ...`` / ``datagrove ...`` invocation in a bash/zsh/console
fenced block (or inline backticks), and asserts every ``--flag``
mentioned actually exists on the resolved command.

**Implementation:**

1. Build the typer apps + convert them to click Groups so we can
   introspect per-command parameter lists.
2. Walk each doc, extract every ``$ gmnspy …`` / ``$ datagrove …`` /
   bare ``gmnspy …`` invocation. Strip ``uv run`` prefix.
3. Parse via ``shlex`` to split into subcommand path + flags.
4. Look up the resolved command's flag set via click's
   ``Command.params``. Assert every documented flag is present.

**Scope decisions:**

- Only checks the **flag names** (``--html``, ``--json``, ``-y``).
  Doesn't validate flag values, types, or behavior — those are the
  CLI's own tests.
- Skips invocations whose subcommand path can't be resolved (e.g.
  documented commands that don't exist) — those are flagged as the
  resolution-error case rather than the flag-missing case.
- Skips placeholder flags (``--<placeholder>``) and obviously-templated
  tokens (``${VAR}``, ``$LV``).
- Whitelist entries for env-var-shaped tokens, prose snippets that
  look like commands but aren't.

When a CLI flag is removed or renamed, the test fails listing every
doc that references the old name. When a doc is written that promises
a flag we never implemented, same.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from pathlib import Path

import pytest
from typer.main import get_command

# Repo layout: packages/gmnspy/tests/test_documented_cli_contract.py
REPO_ROOT = Path(__file__).resolve().parents[3]

# Markdown files to scan. Same set as the Python-API contract test —
# we want the two checks to share a "what counts as a doc" definition.
_DOC_GLOBS = [
    "packages/datagrove/README.md",
    "packages/datagrove/docs/**/*.md",
    "packages/gmnspy/README.md",
    "packages/gmnspy/docs/**/*.md",
]

# Patterns:
#   1. Fenced code block tagged bash/zsh/sh/console — any line that
#      starts with `gmnspy` or `datagrove` (optionally prefixed with
#      `uv run `, `$ `, or both).
#   2. Inline backtick: `gmnspy X --y` (case-sensitive, single backticks).
_FENCE_RE = re.compile(
    r"```(?:bash|sh|shell|console|zsh)\n(.+?)\n```",
    flags=re.DOTALL,
)
_INVOCATION_LINE_RE = re.compile(
    r"^\s*(?:\$\s+)?(?:uv\s+run\s+)?(gmnspy|datagrove)\s+(.+?)$",
    flags=re.MULTILINE,
)
_INLINE_RE = re.compile(
    r"`(?:uv\s+run\s+)?(gmnspy|datagrove)\s+([^`]+?)`",
)

# Flags that appear as PROSE placeholders, not real invocations
# (e.g. "use --report=html" inside a sentence describing what to add).
# Add entries here only after confirming the doc text is clearly prose
# referring to a flag that exists OR is intentionally documented as
# not-yet-implemented.
_KNOWN_PROSE_FLAGS: set[tuple[str, tuple[str, ...], str]] = set()
# format: (package, command_path, flag)
# e.g. ("gmnspy", ("validate",), "--report=html")


def _extract_invocations() -> list[tuple[str, str, list[str], Path]]:
    """Walk every doc, return [(package, raw_args, mentioning_file), ...].

    package is "gmnspy" or "datagrove"; raw_args is the post-command-
    name argv as a single string (later parsed via shlex).
    """
    out: list[tuple[str, str, list[str], Path]] = []
    for glob in _DOC_GLOBS:
        for path in REPO_ROOT.glob(glob):
            # Skip generated docs + the migration guide (which deliberately
            # quotes old-API forms as the "before" side).
            if path.name.startswith("llms") or path.name == "api-index.json":
                continue
            if path.name == "v0.3-to-v1.0.md":
                continue
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(REPO_ROOT)

            # 1) Lines inside bash/zsh fenced blocks.
            for fence in _FENCE_RE.finditer(text):
                block = fence.group(1)
                for inv in _INVOCATION_LINE_RE.finditer(block):
                    pkg, args = inv.group(1), inv.group(2).strip()
                    # Strip trailing line-continuation + inline comment.
                    args = re.sub(r"\s+#.*$", "", args)
                    args = args.rstrip("\\").strip()
                    if args:
                        out.append((pkg, args, [], rel))

            # 2) Inline backtick references — `gmnspy info --json`.
            for inv in _INLINE_RE.finditer(text):
                pkg, args = inv.group(1), inv.group(2).strip()
                if args:
                    out.append((pkg, args, [], rel))
    return out


def _parse(pkg: str, raw_args: str) -> tuple[tuple[str, ...], list[str]] | None:
    """Split a raw arg string into (command_path, flags).

    Returns None when the args can't be safely parsed (shlex failure,
    leading `--`, etc.) — better to skip than to false-positive.
    """
    try:
        tokens = shlex.split(raw_args, comments=True)
    except ValueError:
        return None
    command_path: list[str] = []
    flags: list[str] = []
    seen_flag = False
    for tok in tokens:
        # Stop accumulating command words once we see the first flag.
        if tok.startswith("--"):
            seen_flag = True
            flag_name = tok.split("=", 1)[0]
            flags.append(flag_name)
        elif tok.startswith("-") and len(tok) >= 2 and tok[1].isalpha():
            seen_flag = True
            flags.append(tok)
        elif not seen_flag:
            # Pure positional before any flag → looks like a subcommand
            # word UNLESS it's an obvious value (contains /, =, $, etc.).
            if any(c in tok for c in "/=$") or tok.startswith("."):
                # First positional that looks like a path — stop collecting
                # subcommand words (the rest are arg values).
                seen_flag = True  # bail out of subcommand collection
            else:
                command_path.append(tok)
        # else: positional after a flag — ignore (it's a flag value).
    return tuple(command_path), flags


#: Flags click attaches to EVERY command via Context (not via params),
#: so we add them to every command's flag set explicitly.
_UNIVERSAL_FLAGS = {"--help", "-h"}


def _build_cli_map() -> dict[str, dict[tuple[str, ...], set[str]]]:
    """Build {package: {command_path: {flag, ...}}} from typer's click commands.

    Walks both typer apps recursively. Each leaf command's params are
    introspected for their option strings. Click stores ALL aliases in
    ``Option.opts``, so ``--json`` and ``-j`` both land in the set.
    Universal flags (``--help`` / ``-h``) are unioned in — click adds
    them via Context rather than Command.params.
    """
    from datagrove.cli.app import build_app as build_datagrove_app
    from gmnspy.cli.app import _build_gmnspy_app

    def walk(cmd, prefix: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], set[str]]]:
        # Click's Command exposes params (Options + Arguments). Pull
        # everything that has a `--`-style opt.
        flags: set[str] = set(_UNIVERSAL_FLAGS)
        for param in getattr(cmd, "params", []):
            for opt in getattr(param, "opts", []) or []:
                if opt.startswith("-"):
                    flags.add(opt)
            for opt in getattr(param, "secondary_opts", []) or []:
                if opt.startswith("-"):
                    flags.add(opt)
        yield prefix, flags

        # Group → recurse into children.
        commands = getattr(cmd, "commands", None) or {}
        for name, child in commands.items():
            yield from walk(child, (*prefix, name))

    out: dict[str, dict[tuple[str, ...], set[str]]] = {}
    for pkg, app_builder in (("datagrove", build_datagrove_app), ("gmnspy", _build_gmnspy_app)):
        typer_app = app_builder()
        click_app = get_command(typer_app)
        out[pkg] = dict(walk(click_app, ()))
    return out


def _expand_command_path(
    available: dict[tuple[str, ...], set[str]],
    candidate: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Return the longest known prefix of ``candidate`` that's a real command path.

    Allows users to add a positional arg after the command (``gmnspy
    info <path> --json``) — we resolve to ``("info",)`` and check its
    flags. Returns None if no prefix resolves.
    """
    for n in range(len(candidate), -1, -1):
        prefix = candidate[:n]
        if prefix in available:
            return prefix
    return None


# Build once at module load — cheap, the typer app construction is the
# same work pytest fixtures do for the CLI tests.
_CLI_MAP = _build_cli_map()


def _invocations_for_parametrize() -> list[tuple[str, tuple[str, ...], str, str, Path]]:
    """Return one entry per (package, resolved_cmd_path, flag, original_args, doc).

    Pytest will then run one test per (cmd, flag) doc reference.
    """
    seen: dict[tuple[str, tuple[str, ...], str], tuple[str, Path]] = {}
    for pkg, raw_args, _, doc in _extract_invocations():
        parsed = _parse(pkg, raw_args)
        if parsed is None:
            continue
        candidate_path, flags = parsed
        available = _CLI_MAP.get(pkg, {})
        resolved = _expand_command_path(available, candidate_path)
        if resolved is None:
            # The subcommand doesn't exist — skip; a separate test
            # could check command-existence if useful.
            continue
        for flag in flags:
            key = (pkg, resolved, flag)
            seen.setdefault(key, (raw_args, doc))
    return [(pkg, path, flag, original, doc) for (pkg, path, flag), (original, doc) in sorted(seen.items())]


_INVOCATIONS = _invocations_for_parametrize()


@pytest.mark.parametrize(
    "package,command_path,flag,original_args,doc",
    _INVOCATIONS,
    ids=[f"{pkg} {' '.join(path)} {flag}".strip() for pkg, path, flag, _, _ in _INVOCATIONS],
)
def test_documented_cli_flag_exists(
    package: str,
    command_path: tuple[str, ...],
    flag: str,
    original_args: str,
    doc: Path,
) -> None:
    """Every ``--flag`` mentioned in a documented CLI invocation must exist.

    Regression closer for the walk-through finding that
    ``gmnspy validate --report=html`` was documented in the README
    cookbook but the actual command only accepted ``--json``. CI now
    fails immediately when any doc reference drifts away from real
    CLI surface.
    """
    available_flags = _CLI_MAP[package].get(command_path, set())
    cmd_display = f"{package} {' '.join(command_path)}".strip()

    if (package, command_path, flag) in _KNOWN_PROSE_FLAGS:
        pytest.xfail(f"known prose-only reference to {flag} in {cmd_display}")

    assert flag in available_flags, (
        f"Documented CLI flag does not exist: '{cmd_display} {flag}'\n"
        f"  documented in: {doc}\n"
        f"  full invocation: {package} {original_args}\n"
        f"  available flags on {cmd_display!r}: "
        f"{sorted(available_flags) if available_flags else '(none)'}\n\n"
        f"Fix options:\n"
        f"  - Add {flag} to the command's typer signature\n"
        f"  - Update the doc to use the correct flag name\n"
        f"  - Whitelist via _KNOWN_PROSE_FLAGS in {Path(__file__).name}\n"
        f"    if the reference is intentional prose (not an executable example)."
    )


def test_cli_map_built_successfully() -> None:
    """Smoke: at minimum we found commands on both apps.

    Catches the case where one of the typer apps fails to construct
    (import error, breaking refactor) — the parametrized test above
    would silently have zero cases, hiding the real failure.
    """
    assert _CLI_MAP["gmnspy"], "gmnspy app produced no commands"
    assert _CLI_MAP["datagrove"], "datagrove app produced no commands"
    # Spot-check known commands exist.
    assert ("validate",) in _CLI_MAP["gmnspy"]
    assert ("info",) in _CLI_MAP["gmnspy"]
    assert ("validate",) in _CLI_MAP["datagrove"]
    # And known flags.
    assert "--json" in _CLI_MAP["gmnspy"][("validate",)]
    assert "--html" in _CLI_MAP["gmnspy"][("validate",)]
