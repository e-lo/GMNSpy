"""One-shot rename: gmnspy -> netstead, datagrove -> corral, repo GMNSpy -> netstead.

Idempotent and mechanical. To move a pre-rename branch onto main, use
scripts/migrate_branch_to_netstead.sh (it runs this script for you). Direct use:

    uv run python scripts/rename_to_netstead.py
    uv lock && uv run ruff format . && uv run ruff check --fix .
    git add -A && git commit -m "chore: apply netstead/corral rename"

The PyPI distribution for corral is ``dbcorral`` (``corral`` is blocked as too similar to
an existing project); the import name stays ``corral``. That and other one-off doc fixes
live in a separate hand-written commit on the trunk, not in this script.

Historical text (changelogs, release drafts, the v0.3 migration guide) is left as-is.
Delete this script once no pre-rename branches remain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATH_MOVES = [
    ("packages/datagrove/datagrove", "packages/datagrove/corral"),
    ("packages/datagrove", "packages/corral"),
    ("packages/gmnspy/gmnspy", "packages/gmnspy/netstead"),
    ("packages/gmnspy", "packages/netstead"),
    (".github/workflows/publish-datagrove.yml", ".github/workflows/publish-corral.yml"),
    # Replaces the legacy v0.3 publish.yml; PyPI's trusted publisher for netstead expects this filename.
    (".github/workflows/publish-gmnspy.yml", ".github/workflows/publish.yml"),
    ("skills/datagrove-validate", "skills/corral-validate"),
    (".claude/skills/gmnspy-review", ".claude/skills/netstead-review"),
]

# Order matters: URLs before the bare brand, so the repo path comes out lowercase.
REPLACEMENTS = [
    ("e-lo/GMNSpy", "e-lo/netstead"),
    ("github.io/GMNSpy", "github.io/netstead"),
    ("GMNSpy", "Netstead"),
    ("GMNSPY", "NETSTEAD"),
    ("Gmnspy", "Netstead"),
    ("GmnSpy", "NetStead"),
    ("gmnspy", "netstead"),
    ("DATAGROVE", "CORRAL"),
    ("Datagrove", "Corral"),
    ("datagrove", "corral"),
]

SKIP_NAMES = {"CHANGELOG.md", "uv.lock", "rename_to_netstead.py"}
SKIP_PREFIXES = ("docs/_release-drafts/",)
SKIP_FILES = {"packages/netstead/docs/migration/v0.3-to-v1.0.md"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def move_paths() -> None:
    for src, dst in PATH_MOVES:
        if (ROOT / src).exists():
            git("mv", "-f", src, dst)


def rewrite(path: str) -> bool:
    file = ROOT / path
    try:
        text = file.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return False
    new = text
    for old, repl in REPLACEMENTS:
        new = new.replace(old, repl)
    if new == text:
        return False
    file.write_text(new, encoding="utf-8")
    return True


def skipped(path: str) -> bool:
    return Path(path).name in SKIP_NAMES or path.startswith(SKIP_PREFIXES) or path in SKIP_FILES


def main() -> None:
    move_paths()
    changed = [p for p in git("ls-files").splitlines() if not skipped(p) and rewrite(p)]
    print(f"rewrote {len(changed)} files")


if __name__ == "__main__":
    main()
