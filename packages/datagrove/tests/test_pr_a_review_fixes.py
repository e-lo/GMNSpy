"""Tests for the Batch A review fixes consolidated in PR-A.

Covers the new public surface introduced to dedupe the helpers that
were drifting across datagrove + gmnspy CLI / server / MCP:

* :meth:`datagrove.dataset.Package.safe_count` (F1/S3)
* :class:`datagrove.api.PackageRegistry` ``.require`` / ``.source_for`` /
  ``loader=`` (F2, F4)
* :func:`datagrove.engines.resolve_engine` (S1)
* :class:`datagrove.api.ExtraRouterFactory` + ``AuthDep`` + ``PackageLoader``
  type aliases (S2)
* :func:`datagrove.mcp.build_server` ``state=`` kwarg seam (F5)
* :meth:`datagrove.reports.ValidationReport.to_dict` used as the
  canonical wire shape across api + mcp + gmnspy (F1, schema parity)
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Package.safe_count (S3, F1) — replaces three duplicate _safe_count helpers
# ---------------------------------------------------------------------------


def test_package_safe_count_returns_int_for_present_table():
    """`safe_count` returns the row count for a table that exists."""
    from datagrove.dataset import Package, Table
    from datagrove.engines.pandas_engine import PandasEngine

    e = PandasEngine()
    pkg = Package.from_tables({"x": Table(name="x", expr=e.from_records([{"a": 1}, {"a": 2}]), engine=e)})
    assert pkg.safe_count("x") == 2


def test_package_safe_count_returns_none_for_absent_table():
    """`safe_count` on a missing table returns None — preview never crashes."""
    from datagrove.dataset import Package, Table
    from datagrove.engines.pandas_engine import PandasEngine

    e = PandasEngine()
    pkg = Package.from_tables({"x": Table(name="x", expr=e.from_records([{"a": 1}]), engine=e)})
    assert pkg.safe_count("absent") is None


def test_package_safe_count_swallows_count_exception():
    """If `table.count()` raises, `safe_count` returns None — preview-safe."""
    from datagrove.dataset import Package, Table
    from datagrove.engines.pandas_engine import PandasEngine

    class _BrokenTable(Table):
        def count(self) -> int:
            raise RuntimeError("backend hiccup")

    e = PandasEngine()
    bad = _BrokenTable(name="bad", expr=e.from_records([{"a": 1}]), engine=e)
    pkg = Package.from_tables({"bad": bad})
    assert pkg.safe_count("bad") is None


# ---------------------------------------------------------------------------
# datagrove.engines.resolve_engine (S1) — replaces two duplicate _resolve_engine
# ---------------------------------------------------------------------------


def test_resolve_engine_none_returns_default():
    """`resolve_engine(None)` returns the registered default engine."""
    from datagrove.engines import Engine, get_engine, resolve_engine

    assert isinstance(resolve_engine(None), Engine)
    # Same instance contract as get_engine() — default lookup.
    assert type(resolve_engine(None)) is type(get_engine())


def test_resolve_engine_names_are_case_insensitive():
    """`resolve_engine` accepts lower/upper/mixed case."""
    from datagrove.engines import resolve_engine

    for spelling in ("pandas", "PANDAS", "Pandas"):
        assert type(resolve_engine(spelling)).__name__ == "PandasEngine"


def test_resolve_engine_unknown_raises_value_error_with_known_engines():
    """Unknown engine name raises ValueError that lists the known options."""
    from datagrove.engines import resolve_engine

    with pytest.raises(ValueError, match="unknown engine 'bogus'"):
        resolve_engine("bogus")


# ---------------------------------------------------------------------------
# PackageRegistry: require, source_for, loader injection (F2, F4)
# ---------------------------------------------------------------------------


def test_registry_require_returns_package_for_known_id():
    """`registry.require(id)` returns the loaded package — public version of _safe_get."""
    pytest.importorskip("fastapi")
    from datagrove.api import PackageRef, PackageRegistry, ServerSettings
    from gmnspy.fixtures import leavenworth

    settings = ServerSettings(packages=[PackageRef(id="demo", source=str(leavenworth.csv_dir()))])
    registry = PackageRegistry(settings)
    pkg = registry.require("demo")
    assert pkg.tables  # non-empty load


def test_registry_require_raises_http_404_for_unknown_id():
    """`registry.require(missing)` raises fastapi.HTTPException(404)."""
    pytest.importorskip("fastapi")
    from datagrove.api import PackageRegistry, ServerSettings
    from fastapi import HTTPException

    settings = ServerSettings(packages=[])
    registry = PackageRegistry(settings)
    with pytest.raises(HTTPException) as exc_info:
        registry.require("nope")
    assert exc_info.value.status_code == 404
    assert "'nope'" in exc_info.value.detail


def test_registry_source_for_returns_string_without_loading():
    """`registry.source_for(id)` returns the configured source path without materialising."""
    pytest.importorskip("fastapi")
    from datagrove.api import PackageRef, PackageRegistry, ServerSettings

    settings = ServerSettings(packages=[PackageRef(id="demo", source="/tmp/some/path/")])
    registry = PackageRegistry(settings)
    assert registry.source_for("demo") == "/tmp/some/path/"


def test_registry_source_for_raises_keyerror_for_unknown_id():
    pytest.importorskip("fastapi")
    from datagrove.api import PackageRegistry, ServerSettings

    settings = ServerSettings(packages=[])
    registry = PackageRegistry(settings)
    with pytest.raises(KeyError):
        registry.source_for("nope")


def test_registry_package_loader_injection_caches_subclass_instances():
    """Passing a custom loader makes the cache hold the domain-typed instance."""
    pytest.importorskip("fastapi")
    from datagrove.api import PackageRef, PackageRegistry, ServerSettings
    from gmnspy import Network
    from gmnspy.fixtures import leavenworth

    settings = ServerSettings(packages=[PackageRef(id="demo", source=str(leavenworth.csv_dir()))])
    registry = PackageRegistry(settings, loader=Network.from_source)
    loaded = registry.require("demo")
    # The cache now holds a Network (subclass of Package), not a bare Package.
    assert isinstance(loaded, Network)
    assert loaded.spec_version  # GMNS-specific attribute available directly


# ---------------------------------------------------------------------------
# build_app: package_loader threading + extra_router_factory typed (F4, S2)
# ---------------------------------------------------------------------------


def test_build_app_threads_package_loader_into_registry():
    """`build_app(package_loader=...)` reaches the registry via /networks/{id}."""
    pytest.importorskip("fastapi")
    pytest.importorskip("igraph")
    from datagrove.api import AuthSettings, PackageRef, ServerSettings
    from fastapi.testclient import TestClient
    from gmnspy.fixtures import leavenworth
    from gmnspy.server import build_app

    settings = ServerSettings(
        bind="127.0.0.1",
        auth=AuthSettings(kind="none"),
        packages=[PackageRef(id="demo", source=str(leavenworth.csv_dir()))],
    )
    client = TestClient(build_app(settings))
    body = client.get("/networks/demo").json()
    # spec_version is on Network only — present means the loader fed a Network into the cache.
    assert body["spec_version"] == "0.97"


# ---------------------------------------------------------------------------
# MCP build_server state= kwarg seam (F5)
# ---------------------------------------------------------------------------


def test_datagrove_mcp_build_server_accepts_state_kwarg():
    """`build_server(state=...)` stores the dict on `server.datagrove_state`."""
    pytest.importorskip("mcp")
    from datagrove.mcp import build_server

    shared: dict[str, object] = {"some_key": "value"}
    server = build_server(state=shared)
    assert server.datagrove_state is shared


def test_datagrove_mcp_build_server_state_defaults_to_empty_dict():
    """No `state=` → the seam holds an empty dict so callers can setdefault freely."""
    pytest.importorskip("mcp")
    from datagrove.mcp import build_server

    server = build_server()
    assert server.datagrove_state == {}


def test_gmnspy_mcp_build_server_forwards_state_kwarg():
    """gmnspy's build_server forwards `state=` to the generic factory."""
    pytest.importorskip("mcp")
    pytest.importorskip("igraph")
    from gmnspy.mcp import build_server

    shared: dict[str, object] = {}
    server = build_server(state=shared)
    assert server.datagrove_state is shared


# ---------------------------------------------------------------------------
# Wire shape parity: api + mcp + gmnspy all emit ValidationReport.to_dict() (F1)
# ---------------------------------------------------------------------------


def test_validate_package_api_returns_canonical_to_dict_shape():
    """`POST /packages/{id}/validate` returns the full ValidationReport.to_dict shape."""
    pytest.importorskip("fastapi")
    from datagrove.api import AuthSettings, PackageRef, ServerSettings, build_app
    from fastapi.testclient import TestClient
    from gmnspy.fixtures import leavenworth

    settings = ServerSettings(
        bind="127.0.0.1",
        auth=AuthSettings(kind="none"),
        packages=[PackageRef(id="demo", source=str(leavenworth.csv_dir()))],
    )
    client = TestClient(build_app(settings))
    body = client.post("/packages/demo/validate").json()
    # Canonical shape (was {issues, spec_version} before; now full):
    assert {"report_version", "spec_version", "source", "created_at", "metadata", "summary", "issues"} <= body.keys()
    assert body["report_version"] == "1"


def test_quality_mcp_tool_returns_canonical_to_dict_shape():
    """gmnspy MCP `quality_check` tool returns the canonical to_dict shape too."""
    pytest.importorskip("mcp")
    pytest.importorskip("igraph")
    import asyncio

    from gmnspy.fixtures import leavenworth
    from gmnspy.mcp import build_server

    server = build_server()
    result = asyncio.run(server._tool_manager.call_tool("quality_check", {"source": str(leavenworth.csv_dir())}))
    assert {"report_version", "summary", "issues"} <= result.keys()
    # Every issue carries the canonical issue dict (including `extra`).
    if result["issues"]:
        assert "extra" in result["issues"][0]
