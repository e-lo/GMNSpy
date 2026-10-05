"""Tests for gmnspy.llm.registry — adapters from settings + keys, status, models, connection tests."""

import threading

import pytest
from gmnspy.config import load_settings
from gmnspy.llm import registry as registry_module
from gmnspy.llm.errors import MissingKey, ProviderUnavailable
from gmnspy.llm.registry import build_registry, is_local_url
from gmnspy.llm.secrets import KEYRING_SERVICE

pytestmark = pytest.mark.usefixtures("no_network")


class _CountingProvider:
    """Fake adapter standing in for Ollama: counts ``list_models()`` calls; can be made to fail."""

    def __init__(self, calls: list[int], *, fail: bool = False, **_ignored) -> None:
        self._calls = calls
        self._fail = fail

    def list_models(self) -> list[str]:
        self._calls.append(1)
        if self._fail:
            raise ProviderUnavailable("ollama", "Ollama (local): could not be reached.")
        return ["qwen3:4b"]


@pytest.fixture
def make(tmp_path, isolated_env, fake_keyring, fake_api):
    def _make(overrides=None, environ=None):
        env = {**isolated_env, **(environ or {})}
        settings = load_settings(project_dir=tmp_path, environ=env, overrides=overrides).settings
        return build_registry(settings, environ=env, keyring=fake_keyring, transport=fake_api.transport())

    return _make


def test_status_rows_report_configuration_never_keys(make, fake_keyring, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}]})
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "sk-ant-secret-value")
    rows = {r["provider"]: r for r in make().status()}
    assert list(rows) == ["anthropic", "openai", "gemini", "ollama"]
    assert (rows["anthropic"]["configured"], rows["anthropic"]["source"], rows["anthropic"]["usable"]) == (
        True,
        "keyring",
        True,
    )
    assert (rows["openai"]["configured"], rows["openai"]["usable"], rows["openai"]["local"]) == (False, False, False)
    assert (rows["ollama"]["usable"], rows["ollama"]["models"], rows["ollama"]["local"]) == (True, 1, True)
    assert rows["gemini"]["default_model"] == "gemini-2.5-flash-lite"
    assert "sk-ant-secret-value" not in repr(rows)


def test_env_key_status(make):
    reg = make(environ={"GEMINI_API_KEY": "AIza-from-env"})
    assert reg.secrets.status(reg.slot("gemini")) == {"configured": True, "source": "env"}


def test_ollama_running_without_models_is_not_usable(make, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": []})
    row = next(r for r in make().status() if r["provider"] == "ollama")
    assert row["usable"] is False and "ollama pull qwen3:4b" in row["error"]


def test_base_url_override_gets_its_own_key_slot(make, fake_keyring):
    reg = make(
        overrides={"llm.openai.base_url": "https://llm.example.org/v1"}, environ={"OPENAI_API_KEY": "sk-official"}
    )
    fake_keyring.set_password(KEYRING_SERVICE, "openai", "sk-official-in-ring")
    assert reg.slot("openai").name == "openai@https://llm.example.org"
    with pytest.raises(MissingKey, match=r"for https://llm\.example\.org"):
        reg.provider("openai")  # neither the env key nor the official keyring key may go to a new host
    fake_keyring.set_password(KEYRING_SERVICE, "openai@https://llm.example.org", "custom-key")
    provider = reg.provider("openai")
    assert provider.base_url == "https://llm.example.org/v1" and "custom-key" not in repr(provider)


def test_official_url_spelled_out_is_still_the_official_slot(make):
    assert make(overrides={"llm.openai.base_url": "https://API.openai.com/v1/"}).slot("openai").name == "openai"


def test_provider_uses_endpoint_settings(make, fake_keyring):
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    reg = make(overrides={"llm.anthropic.timeout_s": 7})
    assert reg.provider("anthropic").timeout_s == 7
    assert reg.provider("ollama").base_url == "http://localhost:11434"


def test_ollama_provider_gets_the_catalog_thinking_models(make):
    """The registry resolves the catalog's thinking-capable model ids and threads them into the
    Ollama adapter, so it knows which models to send "think": false for."""
    provider = make().provider("ollama")
    assert provider._thinking_models == frozenset({"qwen3:4b", "qwen3:8b"})


def test_models_catalog_and_discovered(make, fake_api):
    fake_api.add("GET", "/api/tags", body={"models": [{"name": "qwen3:8b"}, {"name": "phi4:14b"}]})
    reg = make()
    assert [m["id"] for m in reg.models("anthropic")] == [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-5",
        "claude-opus-5-5",
    ]
    assert reg.models("ollama") == [
        {"id": "qwen3:8b", "label": "Qwen 3 8B", "tier": "balanced", "tools": True, "installed": True},
        {"id": "phi4:14b", "label": "phi4:14b", "tier": None, "tools": None, "installed": True},
    ]


def test_connection_test_reports_catalog_drift_and_missing_model(make, fake_keyring, fake_api):
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("GET", "/v1/models", body={"data": [{"id": "claude-sonnet-5"}]})
    reg = make()
    ok = reg.test("anthropic")
    assert ok["ok"] and ok["models_served"] == 1
    assert ok["catalog_missing"] == ["claude-haiku-4-5-20251001", "claude-opus-5-5"]
    bad_model = reg.test("anthropic", "claude-nope")
    assert (bad_model["ok"], bad_model["error_type"]) == (False, "ModelNotFound")


def test_connection_test_failures_are_reported_not_raised(make, fake_keyring, fake_api):
    reg = make()
    assert reg.test("openai") == {
        "provider": "openai",
        "ok": False,
        "error_type": "MissingKey",
        "message": "OpenAI: no API key is configured. Add one in Settings → Language models, "
        "or set GMNSPY_OPENAI_API_KEY or OPENAI_API_KEY.",
    }
    fake_keyring.set_password(KEYRING_SERVICE, "anthropic", "k")
    fake_api.add("GET", "/v1/models", status=401, body={"error": {"message": "invalid x-api-key"}})
    result = reg.test("anthropic")
    assert (result["ok"], result["error_type"]) == (False, "InvalidKey")


def test_is_local_url():
    assert is_local_url("http://localhost:11434") and is_local_url("http://[::1]:8000/v1")
    assert is_local_url("http://127.0.0.2")  # the whole 127.0.0.0/8 range, not just 127.0.0.1
    assert not is_local_url("http://0.0.0.0")  # bind-all, not loopback: stays remote
    assert not is_local_url("http://gpu-box:11434") and not is_local_url("https://api.openai.com/v1")


def test_auto_quality_settings_follow_the_endpoint_and_the_privacy_note_follows_them(make):
    reg = make()
    assert reg.is_local("ollama") and not reg.is_local("anthropic")
    assert (reg.grounding_on("ollama"), reg.grounding_on("anthropic")) == (True, False)
    assert (reg.project_context_on("ollama"), reg.project_context_on("anthropic")) == (True, False)
    assert reg.disclosure("anthropic") == [
        "your utterance",
        "the selection tool's schema (GMNS field names such as lanes)",
        "the GMNS assistant guide that ships with gmnspy",
    ]
    opted_in = make(
        overrides={"llm.quality.grounding": "on", "llm.quality.project_context": "on", "llm.quality.few_shot": True}
    )
    assert opted_in.disclosure("anthropic")[3:] == [
        "up to 200 street names and route numbers from the active network",
        "your project notes (GMNSPY.md, or the ## gmnspy section of AGENTS.md/CLAUDE.md, up to 4000 characters)",
        "up to 3 earlier selections on this network from this session "
        "(utterance and result, which may include street names from the network)",
    ]
    local_url = make(overrides={"llm.openai.base_url": "http://localhost:1234/v1"})
    assert local_url.grounding_on("openai")  # an OpenAI-compatible server on this machine counts as local


def test_local_probe_is_cached_across_status_and_models(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls))
    reg.status()
    reg.models("ollama")
    reg.status()
    assert len(calls) == 1  # one live probe serves status() and models() alike, within the TTL


def test_local_probe_failure_is_also_cached(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls, fail=True))
    first = next(r for r in reg.status() if r["provider"] == "ollama")
    second = next(r for r in reg.status() if r["provider"] == "ollama")
    assert len(calls) == 1  # a down Ollama isn't re-probed (at PROBE_TIMEOUT_S) on every call
    assert first["usable"] is False and second["usable"] is False


def test_local_probe_cache_expires_after_the_ttl(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls))
    clock = [1000.0]
    monkeypatch.setattr(registry_module.time, "monotonic", lambda: clock[0])
    reg.status()
    assert len(calls) == 1
    clock[0] += registry_module.PROBE_CACHE_TTL_S - 0.01
    reg.status()
    assert len(calls) == 1  # still fresh
    clock[0] += 0.02
    reg.status()
    assert len(calls) == 2  # TTL elapsed: re-probed


def test_test_connection_bypasses_and_clears_the_cache(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls))
    reg.status()
    assert len(calls) == 1
    reg.test("ollama")
    assert len(calls) == 2  # "Test connection" always re-probes, cache hit or not
    reg.status()
    assert len(calls) == 3  # test() also clears the cache, so the very next status() re-probes too


def test_invalidate_probe_cache_is_per_provider_or_everything(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls))
    reg.status()
    reg.invalidate_probe_cache("anthropic")  # a different provider's cache: no effect on ollama's
    reg.status()
    assert len(calls) == 1
    reg.invalidate_probe_cache()
    reg.status()
    assert len(calls) == 2


def test_concurrent_probes_are_serialized_to_one_live_call(make, monkeypatch):
    reg = make()
    calls: list[int] = []
    monkeypatch.setitem(registry_module.ADAPTERS, "ollama", lambda **kw: _CountingProvider(calls))
    threads = [threading.Thread(target=reg.status) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
