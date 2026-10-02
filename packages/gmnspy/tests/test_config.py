"""Tests for gmnspy.config — layered settings."""

import sys
from pathlib import Path

import pytest
from gmnspy.config import Settings, SettingsError, get_value, load_settings, user_config_path
from gmnspy.spec import DEFAULT_SPEC


def _write_user(env: dict[str, str], text: str) -> Path:
    path = Path(env["GMNSPY_CONFIG_DIR"]) / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_defaults_when_no_files(tmp_path, isolated_env):
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.select.provider == "stub"
    assert loaded.settings.io.spec_version == DEFAULT_SPEC
    assert loaded.settings.app.port == 8850
    assert loaded.sources["select.provider"] == "default"


def test_precedence_user_project_env_session(tmp_path, isolated_env):
    _write_user(isolated_env, '[app]\nport = 9001\nhost = "0.0.0.0"\n[viz]\nbasemap = "esri"\n')
    (tmp_path / "gmnspy.toml").write_text("[app]\nport = 9002\n")
    env = {**isolated_env, "GMNSPY_SELECT__PROVIDER": "claude", "GMNSPY_APP__PORT": "9003"}
    loaded = load_settings(project_dir=tmp_path, environ=env, overrides={"app.port": 9004})
    s = loaded.settings
    assert (s.viz.basemap, s.app.host, s.select.provider, s.app.port) == ("esri", "0.0.0.0", "claude", 9004)
    assert loaded.sources["viz.basemap"] == "user"
    assert loaded.sources["select.provider"] == "env"
    assert loaded.sources["app.port"] == "session"


def test_project_beats_user(tmp_path, isolated_env):
    _write_user(isolated_env, "[app]\nport = 9001\n")
    (tmp_path / "gmnspy.toml").write_text("[app]\nport = 9002\n")
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.app.port == 9002
    assert loaded.sources["app.port"] == "project"


def test_env_json_list_and_unrelated_vars_ignored(tmp_path, isolated_env):
    env = {**isolated_env, "GMNSPY_IO__ALLOWED_ROOTS": '["/data", "/tmp"]', "GMNSPY_AUTO_INDEX_THRESHOLD": "5"}
    loaded = load_settings(project_dir=tmp_path, environ=env)
    assert loaded.settings.io.allowed_roots == ["/data", "/tmp"]


def test_rule_settings_nest_under_validation(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text(
        '[validation.rules.dangling-node]\nenabled = false\nseverity_override = "warning"\n'
    )
    rules = load_settings(project_dir=tmp_path, environ=isolated_env).settings.validation.rules
    assert rules["dangling-node"].enabled is False
    assert rules["dangling-node"].severity_override == "warning"


def test_unknown_key_in_file_rejected(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[select]\nbogus = 1\n")
    with pytest.raises(SettingsError, match="project"):
        load_settings(project_dir=tmp_path, environ=isolated_env)


def test_invalid_toml_names_the_file(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[app\n")
    with pytest.raises(SettingsError, match=r"gmnspy\.toml"):
        load_settings(project_dir=tmp_path, environ=isolated_env)


def test_bad_env_json_rejected(tmp_path, isolated_env):
    with pytest.raises(SettingsError, match="GMNSPY_IO__ALLOWED_ROOTS"):
        load_settings(project_dir=tmp_path, environ={**isolated_env, "GMNSPY_IO__ALLOWED_ROOTS": "[oops"})


def test_user_config_path_override():
    assert user_config_path({"GMNSPY_CONFIG_DIR": "/cfg"}) == Path("/cfg/config.toml")


@pytest.mark.skipif(sys.platform == "win32", reason="XDG applies off Windows only")
def test_user_config_path_xdg():
    assert user_config_path({"XDG_CONFIG_HOME": "/x"}) == Path("/x/gmnspy/config.toml")


def test_get_value():
    assert get_value(Settings(), "app.port") == 8850
    with pytest.raises(SettingsError, match="unknown setting"):
        get_value(Settings(), "app.nope")
