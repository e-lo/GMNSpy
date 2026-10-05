"""Ollama model pulls: name validation, streamed progress parsing, typed errors, probe-cache invalidation."""

import json

import httpx
import pytest
from gmnspy.config import Settings
from gmnspy.llm import BadResponse, ModelNotFound, ProviderUnavailable, build_registry
from gmnspy.llm.providers import OllamaProvider
from gmnspy.llm.providers.ollama import PullProgress, PullTracker, valid_model_name

pytestmark = pytest.mark.usefixtures("no_network")


def ndjson(*lines):
    return b"".join(json.dumps(line).encode() + b"\n" for line in lines)


PULL_OK = ndjson(
    {"status": "pulling manifest"},
    {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000},
    {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 250},
    {"status": "pulling bbb", "digest": "sha256:bbb", "total": 100, "completed": 100},
    {"status": "pulling aaa", "digest": "sha256:aaa", "total": 1000, "completed": 1000},
    {"status": "verifying sha256 digest"},
    {"status": "writing manifest"},
    {"status": "success"},
)


@pytest.mark.parametrize(
    "name", ["qwen3:4b", "qwen3", "qwen2.5:7b-instruct-q4_K_M", "library/qwen3:8b", "user/my-model:v1.2"]
)
def test_plain_library_names_are_valid(name):
    assert valid_model_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "evil.example/ns/model:tag",  # a dotted first segment is a registry *host* to Ollama
        "a/b/c",
        "http://evil.example/x",
        "../etc/passwd",
        "qwen3 4b",
        "qwen3:4b;rm",
        ":4b",
        "qwen3:",
        "x" * 129,
        "qwen3:4b\n",
    ],
)
def test_urls_hosts_and_junk_are_not_model_names(name):
    assert not valid_model_name(name)


def test_tracker_sums_layers_and_labels_stages():
    tracker = PullTracker()
    assert tracker.update(PullProgress("pulling manifest")) is None and tracker.stage == "pulling manifest"
    assert tracker.update(PullProgress("pulling aaa", "sha256:aaa", 1000)) == 0.0
    assert tracker.stage == "downloading"
    tracker.update(PullProgress("pulling aaa", "sha256:aaa", 1000, 500))
    assert tracker.update(PullProgress("pulling bbb", "sha256:bbb", 1000, 0)) == pytest.approx(0.25)
    assert (tracker.completed, tracker.total) == (500, 2000)
    tracker.update(PullProgress("verifying sha256 digest"))
    assert tracker.stage == "verifying sha256 digest"
    assert tracker.update(PullProgress("success")) == 1.0


def test_tracker_clamps_completed_to_total():
    tracker = PullTracker()
    assert tracker.update(PullProgress("pulling a", "a", 10, 50)) == 1.0


def test_pull_streams_progress_until_success(fake_api):
    fake_api.add("POST", "/api/pull", body=PULL_OK)
    events = list(OllamaProvider(transport=fake_api.transport()).pull("qwen3:4b"))
    assert events[0].status == "pulling manifest" and events[-1].status == "success"
    assert events[2] == PullProgress("pulling aaa", "sha256:aaa", 1000, 250)
    assert fake_api.body() == {"model": "qwen3:4b", "stream": True}
    assert str(fake_api.requests[-1].url) == "http://localhost:11434/api/pull"


def test_mid_stream_error_line_is_typed(fake_api):
    fake_api.add(
        "POST",
        "/api/pull",
        body=ndjson({"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}),
    )
    with pytest.raises(ModelNotFound, match="no model called 'nope:1b'"):
        list(OllamaProvider(transport=fake_api.transport()).pull("nope:1b"))


def test_http_error_status_is_typed(fake_api):
    fake_api.add("POST", "/api/pull", status=500, body={"error": "disk full"})
    with pytest.raises(ProviderUnavailable, match="disk full"):
        list(OllamaProvider(transport=fake_api.transport()).pull("qwen3:4b"))


def test_unreachable_server_is_provider_unavailable(fake_api):
    fake_api.add("POST", "/api/pull", raises=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable, match="could not reach Ollama"):
        list(OllamaProvider(transport=fake_api.transport()).pull("qwen3:4b"))


def test_stream_that_ends_without_success_is_an_error(fake_api):
    fake_api.add("POST", "/api/pull", body=ndjson({"status": "pulling manifest"}))
    with pytest.raises(BadResponse, match="ended before"):
        list(OllamaProvider(transport=fake_api.transport()).pull("qwen3:4b"))


def test_invalid_name_never_reaches_the_server(fake_api):
    with pytest.raises(ModelNotFound, match="not a valid model name"):
        list(OllamaProvider(transport=fake_api.transport()).pull("evil.example/ns/x"))
    assert fake_api.requests == []


def test_registry_pull_drops_the_probe_cache(fake_api, isolated_env):
    fake_api.add("GET", "/api/tags", body={"models": []}).add(
        "GET", "/api/tags", body={"models": [{"name": "qwen3:4b"}]}
    )
    fake_api.add("POST", "/api/pull", body=PULL_OK)
    reg = build_registry(Settings(), environ=isolated_env, keyring=None, transport=fake_api.transport())
    ollama = lambda: next(r for r in reg.status() if r["provider"] == "ollama")  # noqa: E731
    assert ollama()["models"] == 0
    assert ollama()["models"] == 0  # cached: no second probe yet
    list(reg.pull("qwen3:4b"))
    assert ollama()["models"] == 1  # re-probed after the pull


def test_registry_pull_choices_carry_sizes(isolated_env):
    reg = build_registry(Settings(), environ=isolated_env, keyring=None)
    sizes = {c["id"]: c["size_gb"] for c in reg.pull_choices()}
    assert sizes == {"qwen3:4b": 2.5, "qwen3:8b": 5.2}
