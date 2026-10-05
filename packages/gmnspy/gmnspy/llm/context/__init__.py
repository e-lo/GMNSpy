"""System context for the natural-language features: the shipped guide and a project's notes.

Two layers, each with its own toggle and size cap in ``llm.quality``:

* :func:`assistant_context` — ``gmns_assistant.md``, maintained and shipped with gmnspy: the GMNS
  data model, how to fill the selection tool, and worked examples. Identical for every provider.
* :func:`find_project_context` + :func:`read_capped` — optional project notes, read from next to
  the active network or from the project directory. It is user content, so it is only read when
  ``llm.quality.project_context`` says so for the provider in use.

Project-note discovery (coordinator override; departs from the original plan, which read the
whole of an ``AGENTS.md``/``CLAUDE.md``):

1. A dedicated ``GMNSPY.md`` is preferred and, when found, sent whole. It is searched for next to
   the active network first, then in the project directory.
2. Otherwise, ``AGENTS.md`` — and failing that, ``CLAUDE.md`` — is searched in the same order, but
   only its ``## gmnspy`` section (any heading level from ``##`` to ``####``, matched
   case-insensitively, running until the next heading of the same or a shallower level) is ever
   read. A file without that section is skipped as if it were absent.
3. If none of the above has notes, there are none.

``AGENTS.md``/``CLAUDE.md`` are coding-assistant files that live in code repositories and carry
instructions for a coding agent, not for the network's language-model features; only a section a
maintainer explicitly addressed to gmnspy is ever sent, and the rest of either file is never read.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

__all__ = [
    "ASSISTANT_CONTEXT_FILE",
    "GMNSPY_CONTEXT_FILE",
    "PROJECT_CONTEXT_NAMES",
    "assistant_context",
    "find_project_context",
    "read_capped",
]

#: The shipped guide, in this package.
ASSISTANT_CONTEXT_FILE = "gmns_assistant.md"
#: A dedicated gmnspy project-notes file, sent whole when present.
GMNSPY_CONTEXT_FILE = "GMNSPY.md"
#: Coding-assistant files to fall back to, in the order they are searched. Only their
#: ``## gmnspy`` section (see :func:`_gmnspy_section`) is ever read.
PROJECT_CONTEXT_NAMES = ("AGENTS.md", "CLAUDE.md")
_TRUNCATED = "\n\n[… truncated at {n} characters …]"
_SECTION_NAME = "gmnspy"
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$", re.MULTILINE)


def _cap(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0:
        return ""
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + _TRUNCATED.format(n=max_chars)


def _gmnspy_section(text: str) -> str | None:
    """The body of the first ``##``-``####`` heading named ``gmnspy`` (case-insensitive), or ``None``.

    The section runs until the next heading whose level is the same or shallower (fewer ``#``),
    or to the end of the text.
    """
    headings = list(_HEADING_RE.finditer(text))
    for i, heading in enumerate(headings):
        level = len(heading.group(1))
        if not (2 <= level <= 4) or heading.group(2).strip().casefold() != _SECTION_NAME:
            continue
        end = len(text)
        for later in headings[i + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        return text[heading.end() : end].strip()
    return None


def _places(source: str | None, project_dir: str | Path | None) -> list[Path]:
    """Folders to search, nearest first: the local network's folder, then the project dir."""
    places: list[Path] = []
    if source and "://" not in source:
        path = Path(source)
        places.append(path if path.is_dir() else path.parent)
    places.append(Path(project_dir) if project_dir is not None else Path.cwd())
    return places


def assistant_context(max_chars: int) -> str:
    """The shipped GMNS assistant guide, capped at ``max_chars`` (0 means none).

    Examples:
        >>> assistant_context(0)
        ''
        >>> assistant_context(100_000).startswith("# GMNS assistant guide")
        True
    """
    text = resources.files("gmnspy.llm.context").joinpath(ASSISTANT_CONTEXT_FILE).read_text(encoding="utf-8")
    return _cap(text, max_chars)


def find_project_context(source: str | None, project_dir: str | Path | None) -> Path | None:
    """The project-notes file to use, or ``None``.

    Prefers a ``GMNSPY.md`` (sent whole), next to a local network ``source`` first and then in
    ``project_dir``. Failing that, falls back to ``AGENTS.md`` and then ``CLAUDE.md`` in the same
    search order, but only a file that has a ``## gmnspy`` section counts — one without is treated
    as absent. URL sources are skipped: notes are only read from this machine.
    """
    places = _places(source, project_dir)
    for place in places:
        candidate = place / GMNSPY_CONTEXT_FILE
        if candidate.is_file():
            return candidate
    for name in PROJECT_CONTEXT_NAMES:
        for place in places:
            candidate = place / name
            if not candidate.is_file():
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if _gmnspy_section(text) is not None:
                return candidate
    return None


def read_capped(path: Path, max_chars: int) -> str:
    """``path``'s notes, capped at ``max_chars``, prefixed with where they came from.

    A ``GMNSPY.md`` is sent whole. An ``AGENTS.md``/``CLAUDE.md`` contributes only its
    ``## gmnspy`` section (see :func:`find_project_context`); the rest of that file is never read.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    body = text if path.name == GMNSPY_CONTEXT_FILE else (_gmnspy_section(text) or "")
    return _cap(f"Project notes from {path.name}:\n\n{body}", max_chars)
