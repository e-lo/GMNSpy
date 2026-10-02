"""Tests for the workbench allowed-roots path policy."""

import os
from pathlib import Path

import pytest
from gmnspy.config import Settings
from gmnspy.workbench.errors import PathNotAllowed
from gmnspy.workbench.paths import allowed_roots, is_allowed, is_url, resolve_allowed


def _settings(*roots: Path) -> Settings:
    return Settings.model_validate({"io": {"allowed_roots": [str(r) for r in roots]}})


@pytest.mark.parametrize(
    ("source", "expected"),
    [("s3://b/k", True), ("https://x.org/n.zip", True), ("/data/net", False), ("C:\\data\\net", False), ("net", False)],
)
def test_is_url(source, expected):
    assert is_url(source) is expected


def test_empty_roots_means_home():
    assert allowed_roots(Settings()) == [Path.home().resolve()]


def test_inside_root_resolves(tmp_path):
    (tmp_path / "net").mkdir()
    assert resolve_allowed(tmp_path / "net", _settings(tmp_path)) == (tmp_path / "net").resolve()
    assert resolve_allowed(tmp_path, _settings(tmp_path)) == tmp_path.resolve()


def test_missing_path_inside_root_is_allowed(tmp_path):
    assert is_allowed(tmp_path / "not-yet" / "out", _settings(tmp_path))


def test_dotdot_escape_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        resolve_allowed(root / ".." / "elsewhere", _settings(root))


def test_sibling_with_shared_prefix_rejected(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data-private").mkdir()
    assert not is_allowed(tmp_path / "data-private", _settings(tmp_path / "data"))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathNotAllowed):
        resolve_allowed(root / "link", _settings(root))
