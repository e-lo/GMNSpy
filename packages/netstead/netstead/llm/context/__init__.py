"""System context for the natural-language features: the shipped guide and a project's notes.

Two layers, each with its own toggle and size cap in ``llm.quality``:

* :func:`assistant_context` — ``gmns_assistant.md``, maintained and shipped with netstead: the GMNS
  data model, how to fill the selection tool, and worked examples. Identical for every provider.
* :func:`find_project_context` + :func:`read_capped` — optional project notes, read from next to
  the active network or from the project directory. It is user content, so it is only read when
  ``llm.quality.project_context`` says so for the provider in use.

Project-note discovery (coordinator override; departs from the original plan, which read the
whole of an ``AGENTS.md``/``CLAUDE.md``):

1. A dedicated ``NETSTEAD.md`` is preferred and, when found, sent whole. It is searched for next to
   the active network first, then in the project directory.
2. Otherwise, ``AGENTS.md`` — and failing that, ``CLAUDE.md`` — is searched in the same order, but
   only its ``## netstead`` section (any heading level from ``##`` to ``####``, matched
   case-insensitively, running until the next heading of the same or a shallower level) is ever
   read. A file without that section is skipped as if it were absent.
3. If none of the above has notes, there are none. ``project_dir=None`` is never papered over with
   the process's current working directory — only the network-folder candidate is searched.

``AGENTS.md``/``CLAUDE.md`` are coding-assistant files that live in code repositories and carry
instructions for a coding agent, not for the network's language-model features; only a section a
maintainer explicitly addressed to netstead is ever sent, and the rest of either file is never read.

Every candidate this module reads is resolved (symlinks followed) and checked against a caller
-supplied set of allowed roots before it is opened, so a symlink planted inside an allowed folder
cannot be used to exfiltrate an arbitrary file on disk to a remote LLM. Callers in the Workbench
pass ``workbench.paths.allowed_roots(settings)``; this module does not import ``workbench`` itself
(that would create an import cycle, since ``workbench`` already imports from ``netstead.llm``).
"""

from __future__ import annotations

import logging
import re
import stat
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

__all__ = [
    "ASSISTANT_CONTEXT_FILE",
    "NETSTEAD_CONTEXT_FILE",
    "PROJECT_CONTEXT_NAMES",
    "assistant_context",
    "find_project_context",
    "read_capped",
]

_LOG = logging.getLogger(__name__)

#: The shipped guide, in this package.
ASSISTANT_CONTEXT_FILE = "gmns_assistant.md"
#: A dedicated netstead project-notes file, sent whole when present.
NETSTEAD_CONTEXT_FILE = "NETSTEAD.md"
#: Coding-assistant files to fall back to, in the order they are searched. Only their
#: ``## netstead`` section (see :func:`_netstead_section`) is ever read.
PROJECT_CONTEXT_NAMES = ("AGENTS.md", "CLAUDE.md")
_TRUNCATED = "\n\n[… truncated at {n} characters …]"
_SECTION_NAME = "netstead"
#: Hard ceiling, in bytes, on how much of a candidate file this module will ever read off disk.
#: Project-note files are small, hand-maintained documents; anything past this is almost certainly
#: not meant to be sent to an LLM, so :func:`find_project_context` skips such a file (logging a
#: note) rather than scanning all of it for a heading, and :func:`read_capped` reads only its first
#: ``_read_limit(max_chars)`` bytes (at least this floor, or 50x the caller's character cap,
#: whichever is larger) rather than loading the whole file before truncating.
_MAX_FILE_BYTES = 1_000_000
_ATX_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*))?$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _cap(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0:
        return ""
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + _TRUNCATED.format(n=max_chars)


def _read_limit(max_chars: int) -> int:
    """Byte ceiling for one :func:`read_capped` read: the larger of :data:`_MAX_FILE_BYTES` and 50x ``max_chars``."""
    return max(_MAX_FILE_BYTES, 50 * max_chars)


def _read_head(path: Path, limit: int) -> str:
    """The first ``limit`` bytes of ``path``, decoded as UTF-8 (a leading BOM is dropped)."""
    with path.open("rb") as handle:
        raw = handle.read(limit)
    return raw.decode("utf-8-sig", errors="replace")


def _iter_headings(text: str) -> list[tuple[int, str, int, int]]:
    """``(level, title, start, end)`` for each ATX heading in ``text`` that is outside a fenced code block.

    ``start``/``end`` are character offsets of the heading's own line (``end`` includes its
    trailing newline, if any). Fenced code blocks (opened by a line of 3+ backticks or 3+ tildes,
    closed by a matching line of at least that many of the same character) are tracked so that a
    ``#`` inside one is never mistaken for a heading.
    """
    headings: list[tuple[int, str, int, int]] = []
    pos = 0
    fence_char: str | None = None
    fence_len = 0
    for line in text.splitlines(keepends=True):
        line_start = pos
        pos += len(line)
        stripped = line.rstrip("\n").rstrip("\r")
        if fence_char is None:
            fence_match = _FENCE_RE.match(stripped)
            if fence_match:
                marker = fence_match.group(1)
                fence_char, fence_len = marker[0], len(marker)
                continue
            heading_match = _ATX_RE.match(stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title = (heading_match.group(2) or "").strip()
                title = title.rstrip("#").rstrip()
                headings.append((level, title, line_start, pos))
        else:
            closing = re.match(rf"^[ \t]{{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$", stripped)
            if closing:
                fence_char, fence_len = None, 0
    return headings


def _netstead_section(text: str) -> str | None:
    """The body of the first ``##``-``####`` heading named ``netstead`` (case-insensitive), or ``None``.

    Headings inside fenced code blocks are ignored, both as a possible match and as a possible end
    of the section. The section runs until the next (non-fenced) heading whose level is the same
    or shallower (fewer ``#``), or to the end of the text.
    """
    headings = _iter_headings(text)
    for i, (level, title, _start, end) in enumerate(headings):
        if not (2 <= level <= 4) or title.casefold() != _SECTION_NAME:
            continue
        section_end = len(text)
        for later_level, _later_title, later_start, _later_end in headings[i + 1 :]:
            if later_level <= level:
                section_end = later_start
                break
        return text[end:section_end].strip()
    return None


def _places(source: str | None, project_dir: str | Path | None) -> list[Path]:
    """Folders to search, nearest first: the local network's folder, then the project dir.

    ``project_dir=None`` contributes no folder — it is never replaced by the current working
    directory, which would let an unrelated folder's notes leak into an unrelated session.
    """
    places: list[Path] = []
    if source and "://" not in source:
        path = Path(source)
        places.append(path if path.is_dir() else path.parent)
    if project_dir is not None:
        places.append(Path(project_dir))
    return places


def _resolved_roots(roots: Sequence[str | Path]) -> list[Path]:
    resolved = []
    for root in roots:
        try:
            resolved.append(Path(root).resolve())
        except (OSError, RuntimeError):  # pragma: no cover - defensive
            continue
    return resolved


def _allowed_candidate(candidate: Path, roots: list[Path]) -> Path | None:
    """``candidate`` resolved and checked, or ``None`` if it should be skipped.

    Resolves symlinks and rejects a target outside ``roots`` — a ``NETSTEAD.md``/``AGENTS.md`` that
    is (or sits behind) a symlink pointing outside the allowed folders is never read, so it can't
    be used to smuggle an arbitrary file on disk into a prompt sent to a remote LLM. Also rejects
    anything that isn't a plain regular file (sockets, devices, FIFOs, directories).
    """
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        return None
    try:
        mode = resolved.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode):
        return None
    return resolved


def assistant_context(max_chars: int) -> str:
    """The shipped GMNS assistant guide, capped at ``max_chars`` (0 means none).

    Examples:
        >>> assistant_context(0)
        ''
        >>> assistant_context(100_000).startswith("# GMNS assistant guide")
        True
    """
    text = resources.files("netstead.llm.context").joinpath(ASSISTANT_CONTEXT_FILE).read_text(encoding="utf-8")
    return _cap(text, max_chars)


def find_project_context(
    source: str | None, project_dir: str | Path | None, roots: Sequence[str | Path]
) -> Path | None:
    """The project-notes file to use, or ``None``.

    Prefers a ``NETSTEAD.md`` (sent whole), next to a local network ``source`` first and then in
    ``project_dir``. Failing that, falls back to ``AGENTS.md`` and then ``CLAUDE.md`` in the same
    search order, but only a file that has a ``## netstead`` section counts — one without is treated
    as absent. URL sources are skipped: notes are only read from this machine. ``project_dir=None``
    is never replaced by the current working directory.

    Every candidate is resolved and must fall inside ``roots`` (e.g.
    ``workbench.paths.allowed_roots(settings)``); one that doesn't — including a symlink that
    resolves outside ``roots`` — is skipped as if absent, falling through to the next candidate. A
    candidate larger than :data:`_MAX_FILE_BYTES` is likewise skipped (and logged), rather than
    read in full to test for a heading.
    """
    resolved_roots = _resolved_roots(roots)
    places = _places(source, project_dir)
    for place in places:
        candidate = _allowed_candidate(place / NETSTEAD_CONTEXT_FILE, resolved_roots)
        if candidate is None:
            continue
        if candidate.stat().st_size > _MAX_FILE_BYTES:
            _LOG.warning("skipping oversized project-notes file %s (> %d bytes)", candidate, _MAX_FILE_BYTES)
            continue
        return candidate
    for name in PROJECT_CONTEXT_NAMES:
        for place in places:
            candidate = _allowed_candidate(place / name, resolved_roots)
            if candidate is None:
                continue
            if candidate.stat().st_size > _MAX_FILE_BYTES:
                _LOG.warning("skipping oversized project-notes file %s (> %d bytes)", candidate, _MAX_FILE_BYTES)
                continue
            text = _read_head(candidate, _MAX_FILE_BYTES)
            if _netstead_section(text) is not None:
                return candidate
    return None


def read_capped(path: str | Path, max_chars: int, roots: Sequence[str | Path]) -> str:
    """``path``'s notes, capped at ``max_chars``, prefixed with where they came from.

    A ``NETSTEAD.md`` is sent whole. An ``AGENTS.md``/``CLAUDE.md`` contributes only its
    ``## netstead`` section (see :func:`find_project_context`); the rest of that file is never read.

    ``path`` is re-resolved and re-checked against ``roots`` (see :func:`find_project_context`);
    a ``path`` that fails that check — including one normally obtained from
    :func:`find_project_context` but that changed (or was replaced by a symlink) since — yields
    ``""``. At most ``_read_limit(max_chars)`` bytes are ever read off disk, so a file that grew
    very large after discovery is truncated rather than read in full.
    """
    resolved_roots = _resolved_roots(roots)
    resolved = _allowed_candidate(Path(path), resolved_roots)
    if resolved is None:
        return ""
    limit = _read_limit(max_chars)
    size = resolved.stat().st_size
    if size > limit:
        _LOG.warning(
            "truncating oversized project-notes file %s (%d bytes > %d byte read limit)", resolved, size, limit
        )
    text = _read_head(resolved, limit)
    body = text if resolved.name == NETSTEAD_CONTEXT_FILE else (_netstead_section(text) or "")
    return _cap(f"Project notes from {resolved.name}:\n\n{body}", max_chars)
