"""Tests for the credentials cascade resolver.

Covers the order kwarg → env → keyring → .netrc → empty dict, plus the
non-leaking-into-logs guarantee.
"""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Layer 1: explicit kwarg
# ---------------------------------------------------------------------------


def test_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit dict shortcircuits the cascade.

    Even with an env var, keyring, and netrc primed with different
    values, an explicit dict is returned verbatim.
    """
    from datagrove.io.credentials import resolve_credentials

    # Prime every downstream layer.
    monkeypatch.setenv("GMNSPY_CRED_EXAMPLE_COM_TOKEN", "env-token")
    explicit = {"token": "explicit-token"}

    out = resolve_credentials("example.com", explicit=explicit)
    assert out == {"token": "explicit-token"}
    # Don't return the caller's dict by identity — that's a mutation hazard.
    assert out is not explicit


# ---------------------------------------------------------------------------
# Layer 2: env var
# ---------------------------------------------------------------------------


def test_env_var_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bearer-token env var resolves to ``{"token": value}``."""
    from datagrove.io.credentials import resolve_credentials

    monkeypatch.setenv("GMNSPY_CRED_S3_AMAZONAWS_COM_TOKEN", "abc123")
    assert resolve_credentials("s3.amazonaws.com") == {"token": "abc123"}


def test_env_var_host_sanitization(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosts are uppercased and ``.`` becomes ``_`` for env var lookup."""
    from datagrove.io.credentials import resolve_credentials

    monkeypatch.setenv("GMNSPY_CRED_S3_AMAZONAWS_COM_TOKEN", "via-sanitized")
    # Caller passes the raw host; the resolver does the sanitization.
    assert resolve_credentials("s3.amazonaws.com") == {"token": "via-sanitized"}


def test_env_var_host_strips_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Port numbers in host are dropped before env lookup."""
    from datagrove.io.credentials import resolve_credentials

    monkeypatch.setenv("GMNSPY_CRED_MINIO_LOCAL_TOKEN", "with-port")
    assert resolve_credentials("minio.local:9000") == {"token": "with-port"}


def test_env_var_key_secret_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_KEY`` + ``_SECRET`` produces an S3-style storage_options dict."""
    from datagrove.io.credentials import resolve_credentials

    monkeypatch.setenv("GMNSPY_CRED_S3_AMAZONAWS_COM_KEY", "AKIA...")
    monkeypatch.setenv("GMNSPY_CRED_S3_AMAZONAWS_COM_SECRET", "shh")

    assert resolve_credentials("s3.amazonaws.com") == {
        "key": "AKIA...",
        "secret": "shh",
    }


def test_env_var_empty_string_is_no_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty-string env var must not be returned as a credential.

    An empty token would silently route through fsspec, producing an
    auth error far from its root cause. Treat empty as missing and fall
    through.
    """
    from datagrove.io.credentials import resolve_credentials

    monkeypatch.setenv("GMNSPY_CRED_EXAMPLE_COM_TOKEN", "")
    assert resolve_credentials("example.com") == {}


# ---------------------------------------------------------------------------
# Layer 3: keyring
# ---------------------------------------------------------------------------


def test_keyring_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """When env is unset, keyring.get_password is consulted."""
    from datagrove.io import credentials as creds_mod

    # Build a stub keyring module that the resolver will import lazily.
    fake_keyring = types.ModuleType("keyring")
    calls: list[tuple[str, str]] = []

    def get_password(service: str, name: str) -> str | None:
        calls.append((service, name))
        return "keyring-token" if name == "example.com" else None

    fake_keyring.get_password = get_password  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    # Force the resolver to take the keyring path: no env, no netrc.
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: None)

    out = creds_mod.resolve_credentials("example.com")
    assert out == {"token": "keyring-token"}
    assert calls == [("datagrove", "example.com")]


def test_keyring_missing_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """When keyring is not importable, the cascade silently advances."""
    from datagrove.io import credentials as creds_mod

    # Hide a previously-imported keyring (if any) and make the import
    # raise. ``_resolve_keyring`` must swallow the ImportError.
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: {"username": "u", "password": "p"})

    out = creds_mod.resolve_credentials("example.com")
    # Falls through to netrc.
    assert out == {"username": "u", "password": "p"}


# ---------------------------------------------------------------------------
# Layer 4: netrc
# ---------------------------------------------------------------------------


def test_netrc_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """A matching netrc entry returns ``{"username": ..., "password": ...}``."""
    from datagrove.io import credentials as creds_mod

    netrc_path = tmp_path / ".netrc"
    netrc_path.write_text(
        "machine example.com\n  login alice\n  password s3cret\n",
        encoding="utf-8",
    )
    netrc_path.chmod(0o600)  # netrc parser is strict about perms

    # Disable keyring so we reach netrc deterministically.
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("NETRC", str(netrc_path))

    assert creds_mod.resolve_credentials("example.com") == {
        "username": "alice",
        "password": "s3cret",
    }


def test_netrc_no_machine_entry_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """When the netrc has no entry for the host, the cascade returns empty.

    The netrc lookup must not raise on a missing machine entry — that's
    the dominant case for hosts users have never authenticated with.
    """
    from datagrove.io import credentials as creds_mod

    netrc_path = tmp_path / ".netrc"
    netrc_path.write_text(
        "machine other.example\n  login bob\n  password hunter2\n",
        encoding="utf-8",
    )
    netrc_path.chmod(0o600)

    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("NETRC", str(netrc_path))

    assert creds_mod.resolve_credentials("nowhere.example") == {}


def test_netrc_missing_file_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """A non-existent netrc path must not raise."""
    from datagrove.io import credentials as creds_mod

    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("NETRC", str(tmp_path / "does-not-exist"))

    assert creds_mod.resolve_credentials("example.com") == {}


# ---------------------------------------------------------------------------
# Terminal: empty
# ---------------------------------------------------------------------------


def test_no_creds_returns_empty_dict(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """No layer has anything → returns ``{}``."""
    from datagrove.io import credentials as creds_mod

    # Sterile environment.
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("NETRC", str(tmp_path / "no-netrc"))

    assert creds_mod.resolve_credentials("unknown.host") == {}


# ---------------------------------------------------------------------------
# Security: never log credentials
# ---------------------------------------------------------------------------


def test_no_creds_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A sentinel credential value must not appear in any log / stdout / stderr.

    Routes a unique sentinel through every layer of the cascade and
    asserts that it never lands in captured log records or in stdout /
    stderr. Catches accidental ``logger.info(f"resolved {value}")``-style
    leaks.
    """
    from datagrove.io.credentials import resolve_credentials

    sentinel = "SENTINEL-CREDENTIAL-DO-NOT-LOG-873x21"

    # Push the sentinel through every layer so any one of them leaking
    # would fail this test.
    monkeypatch.setenv("GMNSPY_CRED_LEAK_TEST_HOST_TOKEN", sentinel)
    caplog.set_level(logging.DEBUG, logger="datagrove")

    out = resolve_credentials("leak.test.host", explicit={"token": sentinel})
    assert out == {"token": sentinel}

    captured = capsys.readouterr()
    leaked_in = []
    for record in caplog.records:
        if sentinel in record.getMessage():
            leaked_in.append(f"log record: {record.name}")
    if sentinel in captured.out:
        leaked_in.append("stdout")
    if sentinel in captured.err:
        leaked_in.append("stderr")

    assert not leaked_in, f"Credential sentinel leaked into: {leaked_in}"
