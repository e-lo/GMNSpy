"""Unit tests for the re-record script's own key-scrubbing, not for the fixtures it produces.

``scripts/record_llm_fixtures.py`` sits outside every package (it is not installed, and it is not
under ``testpaths``), so it is loaded here straight from its file path rather than imported by
dotted name. These tests exercise :func:`scrub_recorded` directly: the one place the script
touches a decoded response before writing it to disk.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "record_llm_fixtures.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_llm_fixtures", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def record_script() -> ModuleType:
    """The re-record script, loaded once by path (it ships outside every installed package)."""
    return _load_script()


def test_scrub_recorded_removes_the_literal_key(record_script: ModuleType) -> None:
    """A key echoed verbatim in a nested response field is replaced, wherever it sits."""
    secret = "not-a-real-key-but-treated-as-one"
    recording = {
        "choices": [{"message": {"content": f"echo: {secret}"}}],
        "error": {"message": f"bad request, saw header Authorization: Bearer {secret}"},
        "nested": {"list": [secret, "fine"]},
    }
    scrubbed = record_script.scrub_recorded(recording, secret)
    dumped = str(scrubbed)
    assert secret not in dumped
    assert "fine" in dumped  # untouched strings survive


def test_scrub_recorded_removes_key_shaped_text_even_without_the_secret(record_script: ModuleType) -> None:
    """Key-shaped text is scrubbed even when it doesn't match the secret passed in (defence in depth)."""
    leaked = "sk-ant-" + "a" * 32
    scrubbed = record_script.scrub_recorded({"message": f"got {leaked} from somewhere else"}, "unrelated-secret")
    assert leaked not in scrubbed["message"]
    assert "[redacted]" in scrubbed["message"]


def test_scrub_recorded_preserves_shape_and_non_string_values(record_script: ModuleType) -> None:
    """Numbers, bools and ``None`` pass through unchanged; only strings are ever redacted."""
    recording = {"usage": {"input_tokens": 12, "ok": True, "stop_sequence": None}, "items": [1, 2, 3]}
    assert record_script.scrub_recorded(recording, "sk-test") == recording


def test_main_refuses_to_run_without_the_opt_in_env_var(
    record_script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``main()`` raises ``SystemExit`` and never records anything unless the opt-in var is ``"1"``."""
    calls: list[str] = []
    monkeypatch.setattr(record_script, "record", lambda provider: calls.append(provider) or Path("unused"))

    with pytest.raises(SystemExit, match=record_script.OPT_IN_ENV_VAR):
        record_script.main(["anthropic"], environ={})
    assert calls == []

    with pytest.raises(SystemExit):
        record_script.main(["anthropic"], environ={record_script.OPT_IN_ENV_VAR: "0"})
    assert calls == []

    with pytest.raises(SystemExit):
        record_script.main(["anthropic"], environ={record_script.OPT_IN_ENV_VAR: "true"})  # only "1" counts
    assert calls == []


def test_recording_transport_drops_response_headers(record_script: ModuleType) -> None:
    """``_Recording.handle_request`` rebuilds the response with only ``content-type``.

    A provider's real response headers (which could in principle carry request-echoing debug
    data) never reach ``recorder.last``, and so never reach a fixture: :func:`scrub_recorded`
    covers the body, and this is what keeps headers out of the picture entirely.
    """
    import httpx

    recorder = record_script._Recording()
    sensitive = httpx.Response(200, headers={"x-request-id": "abc", "set-cookie": "session=secret"}, json={"ok": True})
    recorder._inner.handle_request = lambda request: sensitive  # stand in for the real network call
    recorder.handle_request(httpx.Request("POST", "https://example.invalid/x"))
    assert recorder.last is not None
    _, response = recorder.last
    kept = {k.lower() for k in response.headers}
    assert "x-request-id" not in kept
    assert "set-cookie" not in kept
    assert kept <= {"content-type", "content-length"}
