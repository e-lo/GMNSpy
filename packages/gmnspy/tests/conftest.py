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
import json
from importlib import resources
from pathlib import Path

import gmnspy.fixtures
import pytest

_FIXTURES_ROOT = Path(gmnspy.fixtures.__file__).parent


def _data_files() -> list[Path]:
    """Every committed fixture *data* file (not Python, not caches)."""
    return sorted(
        p for p in _FIXTURES_ROOT.rglob("*") if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts
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
        str(p.relative_to(_FIXTURES_ROOT)) for p in set(before) | set(after) if before.get(p) != after.get(p)
    )
    assert not changed, (
        "Tests mutated committed fixture data under gmnspy/fixtures; "
        "write derived output to tmp_path, not the fixture dir. "
        f"Changed files: {changed}"
    )


@pytest.fixture(scope="session")
def rdu_source() -> str:
    """Path to the committed RDU I-40 parquet fixture network (read-only)."""
    return str(resources.files("gmnspy.fixtures.rdu_i40").joinpath("parquet"))


#: Committed test-only fixture files (tests/fixtures), e.g. the local OSM/Overture inputs.
TEST_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """An environ isolated from the real machine.

    The gmnspy user-config dir lives under ``tmp_path`` (never the real ``~/.config``), and
    ``io.allowed_roots`` is pinned to ``tmp_path`` plus the two read-only fixture trees, so the
    workbench's allowed-roots policy behaves the same wherever the repo is checked out.
    """
    roots = [str(tmp_path.resolve()), str(_FIXTURES_ROOT.resolve()), str(TEST_FIXTURES)]
    return {"GMNSPY_CONFIG_DIR": str(tmp_path / "user"), "GMNSPY_IO__ALLOWED_ROOTS": json.dumps(roots)}
