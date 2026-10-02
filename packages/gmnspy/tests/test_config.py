"""Tests for gmnspy.config — layered settings."""

import sys
import tomllib
from pathlib import Path

import pytest
from gmnspy.config import Settings, SettingsError, dumps_toml, get_value, load_settings, save_setting, user_config_path
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


def test_save_setting_round_trips_and_coerces(tmp_path, isolated_env):
    path = save_setting("app.port", "9100", scope="user", environ=isolated_env)
    assert path == Path(isolated_env["GMNSPY_CONFIG_DIR"]) / "config.toml"
    assert "port = 9100" in path.read_text()
    assert load_settings(project_dir=tmp_path, environ=isolated_env).settings.app.port == 9100


def test_save_setting_project_scope_keeps_other_keys(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text('[viz]\nbasemap = "esri"\n')
    save_setting("select.provider", "claude", scope="project", project_dir=tmp_path, environ=isolated_env)
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert (s.viz.basemap, s.select.provider) == ("esri", "claude")


def test_save_setting_none_resets_to_default(tmp_path, isolated_env):
    save_setting("app.port", 9100, scope="user", environ=isolated_env)
    save_setting("app.port", None, scope="user", environ=isolated_env)
    loaded = load_settings(project_dir=tmp_path, environ=isolated_env)
    assert loaded.settings.app.port == 8850 and loaded.sources["app.port"] == "default"


def test_save_setting_rejects_unknown_key_without_writing(tmp_path, isolated_env):
    with pytest.raises(SettingsError):
        save_setting("select.bogus", 1, scope="user", environ=isolated_env)
    assert not (Path(isolated_env["GMNSPY_CONFIG_DIR"]) / "config.toml").exists()


def test_dumps_toml_round_trips_nested_tables_and_quoting():
    data = {
        "io": {"allowed_roots": ["/a", 'b "q"'], "spec_version": "0.97"},
        "validation": {"rules": {"dangling-node": {"enabled": False, "thresholds": {"max": 2.5}}, "my rule": {}}},
    }
    assert tomllib.loads(dumps_toml(data)) == data


def test_approval_threshold_and_build_defaults(tmp_path, isolated_env):
    s = load_settings(project_dir=tmp_path, environ=isolated_env).settings
    assert s.app.approve_above_s == 90.0
    assert (s.build.network_type, s.build.buffer_m, s.build.extra_tags) == ("drive", 1000.0, [])


def test_negative_approval_threshold_rejected(tmp_path, isolated_env):
    (tmp_path / "gmnspy.toml").write_text("[app]\napprove_above_s = -1\n")
    with pytest.raises(SettingsError, match="approve_above_s"):
        load_settings(project_dir=tmp_path, environ=isolated_env)
