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
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

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


class FakeKeyring:
    """In-memory stand-in for the ``keyring`` module: tests never touch the real OS keychain."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.store.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.store[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        del self.store[(service_name, username)]


@pytest.fixture
def fake_keyring() -> FakeKeyring:
    """A fresh in-memory keyring."""
    return FakeKeyring()


class FakeAPI:
    """Canned JSON per ``(METHOD, path)`` behind an ``httpx.MockTransport``; every request is kept.

    ``add`` queues responses for a route; once one is left it repeats. ``raises`` makes the
    transport raise that exception instead (e.g. ``httpx.ConnectError("refused")``). A ``bytes``
    body is sent as-is (e.g. Ollama's newline-delimited JSON pull progress).
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[tuple[int, Any, dict[str, str], Exception | None]]] = {}
        self.requests: list[Any] = []

    def add(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raises: Exception | None = None,
    ) -> FakeAPI:
        self.routes.setdefault((method.upper(), path), []).append((status, body, headers or {}, raises))
        return self

    def transport(self) -> Any:
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            queue = self.routes.get((request.method, request.url.path))
            if not queue:
                return httpx.Response(599, json={"error": f"no fake route for {request.method} {request.url.path}"})
            status, body, headers, raises = queue.pop(0) if len(queue) > 1 else queue[0]
            if raises is not None:
                raise raises
            if isinstance(body, bytes):
                return httpx.Response(status, content=body, headers=headers)
            return httpx.Response(status, json=body, headers=headers)

        return httpx.MockTransport(handler)

    def body(self, index: int = -1) -> dict[str, Any]:
        """The JSON body of a recorded request (default: the last one)."""
        return json.loads(self.requests[index].content)


@pytest.fixture
def fake_api() -> FakeAPI:
    """A fresh fake provider API."""
    return FakeAPI()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if code under test opens a real HTTP connection (LLM tests use ``fake_api``)."""
    httpx = pytest.importorskip("httpx")

    def refuse(self: Any, request: Any) -> Any:
        raise AssertionError(f"real network call in a test: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(autouse=True)
def _no_system_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a test reach the developer's real keychain: ``keyring="auto"`` resolves to "none".

    Tests that need a keyring pass ``fake_keyring`` explicitly.
    """
    monkeypatch.setattr("gmnspy.llm.secrets.system_keyring", lambda: None)


@pytest.fixture
def run_node():
    """Run ``node`` with captured text output, launched via ``posix_spawn`` rather than fork.

    A pytest-xdist worker is heavily multithreaded (DuckDB, etc.). On macOS, forking such a
    process occasionally crashes the child before it execs (exit -11, no output), which showed
    up as ~1-in-4 flaky full parallel runs. An absolute executable path with
    ``close_fds=False`` lets :mod:`subprocess` use ``posix_spawn``, which never forks the
    worker.
    """

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        node = shutil.which("node")
        assert node, "node not installed"
        return subprocess.run([node, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, close_fds=False)

    return run
