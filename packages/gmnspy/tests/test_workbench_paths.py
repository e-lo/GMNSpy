"""Tests for the workbench allowed-roots path policy."""

import os
from pathlib import Path

import pytest
from gmnspy.config import Settings
from gmnspy.workbench.errors import PathNotAllowed
from gmnspy.workbench.paths import allowed_roots, classify_source, is_allowed, is_url, open_locator, resolve_allowed


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


# ------------------------------------------------------------------ classify_source: only remote schemes skip the roots


def test_classify_remote_url_passes_through(tmp_path):
    assert classify_source("s3://b/k", _settings(tmp_path)) == ("remote", "s3://b/k")


def test_classify_duckdb_url_inside_root_is_local(tmp_path):
    db = tmp_path / "net.duckdb"
    assert classify_source(f"duckdb://{db}", _settings(tmp_path)) == ("local", db.resolve())


def test_classify_duckdb_url_outside_root_rejected(tmp_path):
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        classify_source("duckdb:///etc/secret.duckdb", _settings(tmp_path))


def test_classify_file_url_is_checked_as_a_local_path(tmp_path):
    inside = tmp_path / "net"
    assert classify_source(inside.as_uri(), _settings(tmp_path)) == ("local", inside.resolve())
    with pytest.raises(PathNotAllowed, match="outside the allowed folders"):
        classify_source("file:///etc/net", _settings(tmp_path))


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ("local:///x", "unsupported URL scheme 'local'"),
        ("simplecache::file:///x", "chained"),
        ("file://otherhost/x", "must name a local path"),
    ],
)
def test_classify_rejects_other_schemes(tmp_path, source, match):
    with pytest.raises(PathNotAllowed, match=match):
        classify_source(source, _settings(tmp_path))


@pytest.mark.parametrize("bad", ["~nosuchuser-gmnspy/x", "net\x00work"])
def test_unusable_local_path_is_path_not_allowed(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match="not a usable local path"):
        resolve_allowed(bad, _settings(tmp_path))
    assert not is_allowed(bad, _settings(tmp_path))


@pytest.mark.parametrize("bad", [" s3://b/../../secret/link.parquet", "\x01s3://b/k", "s\t3://b/k", "s3://b/k\n"])
def test_whitespace_and_control_characters_are_rejected(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match="whitespace or control characters"):
        classify_source(bad, _settings(tmp_path))
    assert not is_url(bad)


def test_open_locator_keeps_the_duckdb_hint(tmp_path):
    db = tmp_path / "net.db"
    assert open_locator(f"duckdb://{db}", _settings(tmp_path)) == f"duckdb://{db.resolve()}"
    assert open_locator(str(db), _settings(tmp_path)) == str(db.resolve())
    assert open_locator("s3://b/k", _settings(tmp_path)) == "s3://b/k"


@pytest.mark.parametrize("bad", ["s3:../x", "https:x", "http:/abs", "S3:..//x", "s3:///no-host"])
def test_remote_scheme_without_scheme_slash_slash_host_is_rejected(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match="must look like scheme://host"):
        classify_source(bad, _settings(tmp_path))
    assert not is_url(bad)


@pytest.mark.parametrize("prefix", ["duckdb://", "duckdb:", "DUCKDB://"])
def test_duckdb_prefix_is_stripped_robustly(tmp_path, prefix):
    db = tmp_path / "net.db"
    assert classify_source(f"{prefix}{db}", _settings(tmp_path)) == ("local", db.resolve())


@pytest.mark.parametrize("bad", ["https://@/x", "https://:80/x", "s3://user@/k"])
def test_remote_url_without_a_hostname_is_rejected(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match="must look like scheme://host"):
        classify_source(bad, _settings(tmp_path))


@pytest.mark.parametrize("bad", ["s3://b/../../secret/link.parquet", "https://h/a/../x.parquet", "s3://b/.."])
def test_remote_url_with_dotdot_segment_is_rejected(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match=r"'\.\.' path segments"):
        classify_source(bad, _settings(tmp_path))


def test_remote_url_with_dots_inside_a_name_is_fine(tmp_path):
    assert classify_source("s3://b/v1..2/x.parquet", _settings(tmp_path)) == ("remote", "s3://b/v1..2/x.parquet")


@pytest.mark.parametrize(
    "bad", ["https://alice:hunter2@h.example/net", "s3://AKIAXX:s3cr3t@bucket/net", "https://token@h.example/x"]
)
def test_remote_url_with_userinfo_is_rejected_without_echoing_it(tmp_path, bad):
    with pytest.raises(PathNotAllowed, match="credential cascade") as exc:
        classify_source(bad, _settings(tmp_path))
    message = str(exc.value)
    assert "env" in message and "keyring" in message and "netrc" in message
    assert not any(secret in message for secret in ("alice", "hunter2", "AKIAXX", "s3cr3t", "token"))
