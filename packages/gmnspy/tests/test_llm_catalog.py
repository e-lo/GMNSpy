"""Tests for gmnspy.llm.catalog — the maintained provider/model catalog."""

import pytest
from gmnspy.llm.catalog import CATALOG_OVERLAY, load_catalog


def test_packaged_catalog_has_the_four_providers_in_order():
    cat = load_catalog()
    assert cat.names() == ["anthropic", "openai", "gemini", "ollama"]
    assert cat["ollama"].kind == "local" and cat["anthropic"].kind == "remote"
    assert cat["anthropic"].key_env == ("GMNSPY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")


def test_anthropic_models_are_the_current_ids():
    anthropic = load_catalog()["anthropic"]
    assert [m.id for m in anthropic.models] == ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5-5"]
    assert [m.tier for m in anthropic.models] == ["fast", "balanced", "best"]
    assert anthropic.default_model == "claude-haiku-4-5-20251001"


def test_every_default_model_is_listed_and_every_model_has_a_label():
    for info in load_catalog().providers.values():
        assert info.model(info.default_model) is not None, info.name
        assert all(m.label for m in info.models)


def test_user_overlay_adds_and_relabels_but_cannot_move_keys(tmp_path):
    (tmp_path / CATALOG_OVERLAY).write_text(
        "[openai]\n"
        'default_model = "my-model"\n'
        'base_url = "https://evil.example/v1"\n'
        'key_env = ["EVIL"]\n'
        "[[openai.models]]\n"
        'id = "my-model"\n'
        'label = "Mine"\n'
        'tier = "fast"\n'
        "[mystery]\n"
        'label = "No adapter"\n'
    )
    cat = load_catalog(tmp_path)
    openai = cat["openai"]
    assert openai.default_model == "my-model" and openai.model("my-model").label == "Mine"
    assert openai.base_url == "https://api.openai.com/v1" and openai.key_env == (
        "GMNSPY_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    )
    assert "mystery" not in cat.names()


def test_unknown_provider_and_bad_entries_raise(tmp_path):
    with pytest.raises(KeyError, match="unknown LLM provider 'mistral'"):
        load_catalog()["mistral"]
    (tmp_path / CATALOG_OVERLAY).write_text('[[anthropic.models]]\nlabel = "no id"\n')
    with pytest.raises(ValueError, match="every model needs an id"):
        load_catalog(tmp_path)
