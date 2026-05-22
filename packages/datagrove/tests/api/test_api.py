"""Tests for the generic datagrove FastAPI app (task 4.10 / issue #91).

End-to-end via :class:`fastapi.testclient.TestClient` so the auth +
endpoint contracts are exercised together. Auth tested in both modes
(``none`` and ``bearer``); endpoints tested against the Leavenworth
fixture mounted under a synthetic public id.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from datagrove.api import (
    AuthSettings,
    PackageRef,
    ServerSettings,
    build_app,
    generate_dev_token,
    load_settings,
)
from fastapi.testclient import TestClient
from gmnspy.fixtures import leavenworth


def _settings(*, auth_kind: str = "none", token: str | None = None) -> ServerSettings:
    """Build a test ServerSettings with the Leavenworth fixture mounted as ``demo``."""
    return ServerSettings(
        bind="127.0.0.1",
        port=8000,
        auth=AuthSettings(kind=auth_kind, token=token),
        packages=[PackageRef(id="demo", source=str(leavenworth.csv_dir()), description="Leavenworth fixture")],
    )


# ---------------------------------------------------------------------------
# Health (always open)
# ---------------------------------------------------------------------------


def test_health_always_open_with_bearer_auth():
    """`/health` does not require auth (load-balancer probe)."""
    settings = _settings(auth_kind="bearer", token="t0p-s3cret")
    client = TestClient(build_app(settings))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth — none
# ---------------------------------------------------------------------------


def test_endpoints_open_when_auth_none():
    """auth.kind='none' lets unauthenticated requests through."""
    client = TestClient(build_app(_settings(auth_kind="none")))
    assert client.get("/packages").status_code == 200
    assert client.get("/packages/demo").status_code == 200


# ---------------------------------------------------------------------------
# Auth — bearer
# ---------------------------------------------------------------------------


def test_endpoints_require_token_when_bearer():
    """No Bearer header -> 401 with WWW-Authenticate."""
    client = TestClient(build_app(_settings(auth_kind="bearer", token="abc")))
    r = client.get("/packages")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_endpoints_accept_correct_token():
    """Correct Bearer token -> 200."""
    client = TestClient(build_app(_settings(auth_kind="bearer", token="abc")))
    r = client.get("/packages", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200


def test_endpoints_reject_wrong_token():
    """Wrong Bearer token -> 401."""
    client = TestClient(build_app(_settings(auth_kind="bearer", token="abc")))
    r = client.get("/packages", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_bearer_without_token_in_settings_fails_fast():
    """AuthSettings(kind='bearer', token=None) is a misconfiguration."""
    settings = ServerSettings(auth=AuthSettings(kind="bearer", token=None))
    with pytest.raises(ValueError, match="requires `token`"):
        build_app(settings)


# ---------------------------------------------------------------------------
# Endpoint shapes
# ---------------------------------------------------------------------------


def test_list_packages_returns_configured_ids():
    """`/packages` returns the configured ids."""
    client = TestClient(build_app(_settings()))
    r = client.get("/packages")
    body = r.json()
    assert len(body) == 1
    assert body[0]["id"] == "demo"
    assert "source" in body[0]


def test_get_package_returns_metadata():
    """`/packages/{id}` returns table list + row counts."""
    client = TestClient(build_app(_settings()))
    r = client.get("/packages/demo")
    body = r.json()
    assert body["id"] == "demo"
    assert body["table_count"] >= 1
    assert all({"name", "rows", "columns"} <= t.keys() for t in body["tables"])


def test_get_package_404_on_unknown_id():
    """Unknown package id -> 404."""
    client = TestClient(build_app(_settings()))
    r = client.get("/packages/nope")
    assert r.status_code == 404


def test_get_spec_returns_resolved_datapackage():
    """`/packages/{id}/spec` returns the Frictionless DataPackage as JSON."""
    client = TestClient(build_app(_settings()))
    r = client.get("/packages/demo/spec")
    body = r.json()
    assert "name" in body
    assert "resources" in body


def test_validate_returns_issues_document():
    """`/packages/{id}/validate` returns ``{issues: [...], spec_version}``."""
    client = TestClient(build_app(_settings()))
    r = client.post("/packages/demo/validate")
    body = r.json()
    assert "issues" in body and isinstance(body["issues"], list)


# ---------------------------------------------------------------------------
# Security warnings
# ---------------------------------------------------------------------------


def test_warn_on_unsafe_combination_emits_log(caplog):
    """auth=none + public bind logs a WARNING."""
    settings = ServerSettings(bind="0.0.0.0", auth=AuthSettings(kind="none"))
    with caplog.at_level("WARNING"):
        settings.warn_on_unsafe_combinations()
    assert any("NO authentication" in r.message for r in caplog.records)


def test_localhost_with_no_auth_does_not_warn(caplog):
    """auth=none + localhost is fine — no warning."""
    settings = ServerSettings(bind="127.0.0.1", auth=AuthSettings(kind="none"))
    with caplog.at_level("WARNING"):
        settings.warn_on_unsafe_combinations()
    assert not any("NO authentication" in r.message for r in caplog.records)


def test_is_public_bind_detects_known_loopback_aliases():
    """127.0.0.1 / localhost / ::1 are NOT public; everything else is."""
    for loopback in ("127.0.0.1", "localhost", "::1"):
        assert ServerSettings(bind=loopback).is_public_bind() is False
    assert ServerSettings(bind="0.0.0.0").is_public_bind() is True


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_settings_json(tmp_path):
    """JSON config round-trips to ServerSettings."""
    cfg = tmp_path / "server.json"
    cfg.write_text(
        '{"bind": "127.0.0.1", "port": 9000, "auth": {"kind": "bearer", "token": "abc"}, '
        '"packages": [{"id": "demo", "source": "/tmp/foo"}]}'
    )
    settings = load_settings(cfg)
    assert settings.port == 9000
    assert settings.auth.token == "abc"
    assert settings.packages[0].id == "demo"


def test_generate_dev_token_returns_url_safe_string():
    """Dev token helper returns a 40+ char URL-safe string."""
    t = generate_dev_token()
    assert isinstance(t, str) and len(t) >= 40
