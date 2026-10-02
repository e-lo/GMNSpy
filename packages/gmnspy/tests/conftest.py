"""Shared pytest fixtures and session-wide guards for the gmnspy suite.

The committed fixture data under ``gmnspy/fixtures`` (the Leavenworth
network in csv / parquet / duckdb / zip form) is read-only reference
data.  Tests must read it and write any derived output to ``tmp_path``.

A test that instead writes a network *into* the fixture directory
mutates version-controlled files and leaves the git tree dirty after a
plain ``pytest`` run.  That has caused accidental fixture commits and
forced ``git checkout`` dances before every rebase.  The autouse guard
below snapshots the fixture files once per session and fails loudly at
teardown if any changed, naming the offending paths so the write can be
redirected to ``tmp_path``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import gmnspy.fixtures

_FIXTURES_ROOT = Path(gmnspy.fixtures.__file__).parent


def _data_files() -> list[Path]:
    """Every committed fixture *data* file (not Python, not caches)."""
    return sorted(
        p
        for p in _FIXTURES_ROOT.rglob("*")
        if p.is_file()
        and p.suffix != ".py"
        and "__pycache__" not in p.parts
    )


def _snapshot() -> dict[Path, str]:
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in _data_files()}


@pytest.fixture(scope="session", autouse=True)
def _fixture_data_is_read_only() -> None:
    """Fail the session if any test mutates committed fixture data.

    A failure means a test wrote into ``gmnspy/fixtures`` instead of
    ``tmp_path``; redirect that write to the ``tmp_path`` the test is
    given (or a copy of the fixture made there).
    """
    before = _snapshot()
    yield
    after = _snapshot()

    changed = sorted(
        str(p.relative_to(_FIXTURES_ROOT))
        for p in set(before) | set(after)
        if before.get(p) != after.get(p)
    )
    assert not changed, (
        "Tests mutated committed fixture data under gmnspy/fixtures; "
        "write derived output to tmp_path, not the fixture dir. "
        f"Changed files: {changed}"
    )
