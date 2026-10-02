"""Local-path policy for the workbench: every local read or write stays under ``io.allowed_roots``.

An empty ``io.allowed_roots`` means "the user's home directory". Paths are
resolved (``~`` expanded, symlinks followed, ``..`` collapsed) *before* the
containment check, so neither a symlink nor a ``..`` segment can escape a root.
URLs are not local paths and are never checked here.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from gmnspy.config import Settings

from .errors import PathNotAllowed

__all__ = ["allowed_roots", "is_allowed", "is_url", "resolve_allowed"]


def is_url(source: str) -> bool:
    """Whether ``source`` is a URL: it has a scheme of two or more letters (a Windows drive letter is not one)."""
    return len(urlsplit(str(source)).scheme) > 1


def allowed_roots(settings: Settings) -> list[Path]:
    """The resolved allowed roots (``io.allowed_roots``, or ``[home]`` when that list is empty)."""
    return [Path(r).expanduser().resolve() for r in settings.io.allowed_roots or [str(Path.home())]]


def _inside(candidate: Path, roots: list[Path]) -> bool:
    return any(candidate.is_relative_to(root) for root in roots)


def is_allowed(path: str | Path, settings: Settings) -> bool:
    """Whether ``path`` resolves inside an allowed root."""
    return _inside(Path(path).expanduser().resolve(), allowed_roots(settings))


def resolve_allowed(path: str | Path, settings: Settings) -> Path:
    """Return ``path`` fully resolved, or raise :class:`PathNotAllowed` if it falls outside every allowed root."""
    candidate = Path(path).expanduser().resolve()
    roots = allowed_roots(settings)
    if not _inside(candidate, roots):
        shown = ", ".join(str(r) for r in roots)
        raise PathNotAllowed(
            f"{path} is outside the allowed folders ({shown}); add a parent folder to io.allowed_roots"
        )
    return candidate
