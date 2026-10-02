"""Tests for the wizard's URL check (in-memory filesystem; never touches the network)."""

import uuid

import pytest
from datagrove.io import credentials as creds_mod
from fsspec.implementations.memory import MemoryFileSystem
from gmnspy.workbench.urlcheck import check_url


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_keyring", lambda host: {})
    monkeypatch.setattr(creds_mod, "_lookup_netrc", lambda host: {})


@pytest.fixture
def memfs():
    fs, root = MemoryFileSystem(), f"/wbcheck-{uuid.uuid4().hex}"
    fs.pipe({f"{root}/net/link.parquet": b"x", f"{root}/net/node.parquet": b"x", f"{root}/net/notes.txt": b"x"})
    fs.pipe({f"{root}/net.zip": b"x"})
    yield fs, root
    fs.rm(root, recursive=True)


def _factory(fs, path, seen=None):
    def url_to_fs(url, **storage_options):
        if seen is not None:
            seen.append(storage_options)
        return fs, path

    return url_to_fs


def test_folder_lists_tables(memfs):
    fs, root = memfs
    report = check_url("s3://bucket/net", url_to_fs=_factory(fs, f"{root}/net"))
    assert report["reachable"] and report["kind"] == "folder" and report["tables"] == ["link", "node"]
    assert report["credential_source"] == "none" and report["error"] is None


def test_file_has_no_tables(memfs):
    fs, root = memfs
    report = check_url("https://example.org/net.zip", url_to_fs=_factory(fs, f"{root}/net.zip"))
    assert report["reachable"] and report["kind"] == "file" and report["tables"] == []


def test_missing_is_unreachable(memfs):
    fs, root = memfs
    report = check_url("s3://bucket/gone", url_to_fs=_factory(fs, f"{root}/gone"))
    assert report["reachable"] is False and report["error"] == "not found"


def test_reports_source_name_never_the_secret(memfs, monkeypatch):
    fs, root = memfs
    monkeypatch.setattr(creds_mod, "_lookup_env", lambda host: {"token": "s3cr3t"})
    seen: list[dict] = []
    report = check_url("s3://bucket/net", url_to_fs=_factory(fs, f"{root}/net", seen))
    assert report["credential_source"] == "env"
    assert seen == [{"token": "s3cr3t"}]  # the secret goes to the filesystem...
    assert "s3cr3t" not in repr(report)  # ...and never into the report


def test_unsupported_scheme():
    report = check_url("ftp://example.org/net")
    assert report["reachable"] is False and "unsupported URL scheme" in report["error"]


def test_file_scheme_is_rejected():
    report = check_url("file:///etc/passwd")
    assert report["reachable"] is False
    assert "local file browser" in report["error"]


def test_backend_error_is_reported_not_raised():
    def boom(url, **_):
        raise PermissionError("access denied")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False and report["error"] == "PermissionError: access denied"
