"""Tests for gmnspy.llm.secrets — write-only API-key storage (env vars, then the OS keyring)."""

import pytest
from gmnspy.llm.errors import MissingKey
from gmnspy.llm.secrets import (
    KEYRING_SERVICE,
    KeySlot,
    SecretStore,
    SecretStoreError,
    looks_like_secret,
    origin_of,
    redact,
)

ENV_NAMES = {"openai": ("GMNSPY_OPENAI_API_KEY", "OPENAI_API_KEY")}
OPENAI = KeySlot("openai")


def _store(keyring=None, environ=None):
    return SecretStore(environ=environ or {}, env_names=ENV_NAMES, keyring=keyring)


def test_env_beats_keyring_and_gmnspy_name_comes_first(fake_keyring):
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "from-ring")
    env = {"OPENAI_API_KEY": "standard", "GMNSPY_OPENAI_API_KEY": "ours"}
    assert _store(fake_keyring, env).lookup(OPENAI) == ("ours", "env")
    assert _store(fake_keyring, {"OPENAI_API_KEY": "standard"}).lookup(OPENAI) == ("standard", "env")
    assert _store(fake_keyring).lookup(OPENAI) == ("from-ring", "keyring")


def test_origin_slot_never_uses_env(fake_keyring):
    custom = KeySlot("openai", "https://llm.example.org")
    store = _store(fake_keyring, {"OPENAI_API_KEY": "standard"})
    assert custom.name == "openai@https://llm.example.org"
    assert store.lookup(custom) is None
    with pytest.raises(MissingKey, match=r"for https://llm\.example\.org"):
        store.get(custom, "OpenAI")


def test_missing_key_message_offers_the_keyring_and_the_env_vars(fake_keyring):
    with pytest.raises(MissingKey) as info:
        _store(fake_keyring).get(OPENAI, "OpenAI")
    assert str(info.value) == (
        "OpenAI: no API key is configured. Add one in Settings → Language models, "
        "or set GMNSPY_OPENAI_API_KEY or OPENAI_API_KEY."
    )


def test_without_a_keyring_the_only_way_is_an_env_var():
    store = _store(keyring=None)
    with pytest.raises(MissingKey, match="no OS keyring, so set GMNSPY_OPENAI_API_KEY or OPENAI_API_KEY"):
        store.get(OPENAI, "OpenAI")
    with pytest.raises(SecretStoreError, match=r"no OS keyring.*then restart it"):
        store.set(OPENAI, "sk-test-key")
    assert store.remove(OPENAI) == [] and not store.keyring_available


def test_set_in_keyring_status_and_remove(fake_keyring):
    store = _store(fake_keyring)
    assert store.set(OPENAI, "  sk-test-key  ") == "keyring"
    assert fake_keyring.store[(KEYRING_SERVICE, "openai")] == "sk-test-key"
    assert store.status(OPENAI) == {"configured": True, "source": "keyring"}
    assert store.remove(OPENAI) == ["keyring"]
    assert store.status(OPENAI) == {"configured": False, "source": None}
    assert store.remove(OPENAI) == []


def test_blank_or_spaced_keys_rejected(fake_keyring):
    store = _store(fake_keyring)
    for bad in ("", "   ", "two words"):
        with pytest.raises(SecretStoreError, match="cannot be empty"):
            store.set(OPENAI, bad)


def test_broken_keyring_read_is_no_key_and_write_error_hides_detail():
    class Broken:
        def get_password(self, *a):
            raise RuntimeError("locked")

        def set_password(self, *a):
            raise RuntimeError("secret sk-ant-api03-SHOULDNOTAPPEARabcdefghij")

        def delete_password(self, *a):
            raise RuntimeError("locked")

    store = _store(Broken())
    assert store.lookup(OPENAI) is None
    with pytest.raises(SecretStoreError) as info:
        store.set(OPENAI, "k1")
    assert "SHOULDNOTAPPEAR" not in str(info.value) and "RuntimeError" in str(info.value)


def test_redact_and_looks_like_secret():
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz0123"
    assert redact(f"bad key {key}", key) == "bad key [redacted]"
    assert (
        redact("Incorrect API key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX given") == "Incorrect API key [redacted] given"
    )
    assert looks_like_secret({"a": ["x", "AIzaSyA-abcdefghijklmnopqrstuvwxyz012"]})
    assert not looks_like_secret("task-abcdefghijklmnopqrstuvwxyz")  # 'sk-' inside a word is not a key
    assert not looks_like_secret("claude-sonnet-5") and not looks_like_secret(42)
    assert origin_of("HTTPS://API.Example.org:8443/v1/x") == "https://api.example.org:8443"


def test_repr_never_shows_keys(fake_keyring):
    store = _store(fake_keyring)
    store.set(OPENAI, "sk-test-repr-check")
    assert "sk-test" not in repr(store)


def test_origin_of_drops_default_ports_and_keeps_ipv6_brackets():
    assert origin_of("https://api.example.org:443/v1") == "https://api.example.org"
    assert origin_of("http://api.example.org:80/v1") == "http://api.example.org"
    assert origin_of("https://api.example.org:8443/v1") == "https://api.example.org:8443"
    assert origin_of("http://[::1]:11434/") == "http://[::1]:11434"
    assert origin_of("https://[2001:db8::1]/v1") == "https://[2001:db8::1]"


def test_origin_of_rejects_userinfo_and_empty_scheme_or_host():
    with pytest.raises(ValueError, match="username or password"):
        origin_of("https://evil:sneaky@api.example.org/v1")
    with pytest.raises(ValueError, match="username or password"):
        origin_of("https://token@api.example.org/v1")
    with pytest.raises(ValueError, match="scheme and a host"):
        origin_of("api.example.org/v1")
    with pytest.raises(ValueError, match="scheme and a host"):
        origin_of("https:///v1")


def test_set_and_remove_errors_have_no_exception_context(fake_keyring):
    class Broken:
        def get_password(self, *a):
            return "something"

        def set_password(self, *a):
            raise RuntimeError("locked")

        def delete_password(self, *a):
            raise RuntimeError("locked")

    store = _store(Broken())
    with pytest.raises(SecretStoreError) as set_info:
        store.set(OPENAI, "sk-test-key")
    assert set_info.value.__context__ is None and set_info.value.__cause__ is None

    with pytest.raises(SecretStoreError) as remove_info:
        store.remove(OPENAI)
    assert remove_info.value.__context__ is None and remove_info.value.__cause__ is None


def test_keyring_read_failure_reports_locked_not_missing():
    class Broken:
        def get_password(self, *a):
            raise RuntimeError("locked")

        def set_password(self, *a):
            raise RuntimeError("locked")

        def delete_password(self, *a):
            raise RuntimeError("locked")

    store = _store(Broken())
    with pytest.raises(MissingKey, match=r"could not be read \(locked\?\)"):
        store.get(OPENAI, "OpenAI")


def test_looks_like_secret_scans_dict_keys_and_sets():
    key = "sk-proj-abcdefghijklmnopqrstuvwxyz0123"
    assert looks_like_secret({key: "harmless"})
    assert looks_like_secret({"abcdefghijklmnopqrstuvwxyz0123", key})  # a set
    assert looks_like_secret(f"FOO_{key}")  # 'sk-' right after '_' still counts
    assert looks_like_secret(f"bar-{key}")  # ... and right after '-'
    assert looks_like_secret(f"SK-ANT-{'A' * 25}")  # case-insensitive prefix
