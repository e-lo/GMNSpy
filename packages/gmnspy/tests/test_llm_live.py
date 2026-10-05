"""Opt-in live smoke test: one real selection per provider, with your own keys / local Ollama.

    GMNSPY_LIVE_LLM=anthropic,ollama uv run --all-extras pytest packages/gmnspy/tests/test_llm_live.py -m live_llm

Keys come from the env or the OS keyring (this test deliberately uses the real keyring, via
:func:`~datagrove.io.credentials.system_keyring`, not the ``fake_keyring`` the rest of the suite
uses). Override a model with ``GMNSPY_LIVE_<PROVIDER>_MODEL``; otherwise each provider's default
model is used (see ``gmnspy/llm/models.toml``; for Ollama, an installed stand-in when the default
isn't installed). CI never sets ``GMNSPY_LIVE_LLM``, so
every case here is always skipped there, and nobody should run this file without deliberately
opting in -- it spends real tokens and quota.
"""

import os

import pytest
from datagrove.io.credentials import system_keyring
from gmnspy.config import load_settings
from gmnspy.llm import build_registry
from gmnspy.select.parse import LLMParser

pytestmark = pytest.mark.live_llm

LIVE = {name.strip() for name in os.environ.get("GMNSPY_LIVE_LLM", "").split(",") if name.strip()}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini", "ollama"])
def test_live_selection_round_trip(provider: str) -> None:
    """Parse one real utterance through ``provider``'s tiny default model."""
    if provider not in LIVE:
        pytest.skip(f"set GMNSPY_LIVE_LLM={provider} to run")
    registry = build_registry(load_settings().settings, keyring=system_keyring())
    model = registry.resolve_model(provider, os.environ.get(f"GMNSPY_LIVE_{provider.upper()}_MODEL"))
    parser = LLMParser(registry.provider(provider), model)
    intent, mode = parser.parse_detailed("I-40 EB between South Miami Boulevard and Airport Boulevard")
    assert intent.facility is not None and intent.facility.direction == "EB"
    assert intent.from_anchor and intent.to_anchor
    assert mode in ("tools", "json")
