"""Tests for the wizard's URL check (in-memory filesystem; never touches the network).

One test runs a real ``http.server.ThreadingHTTPServer`` to exercise the actual fsspec HTTP
backend's timeout plumbing (the thing a fake ``url_to_fs`` can't catch); it binds to
``127.0.0.1`` on an ephemeral port only and talks to nothing else.
"""

import functools
import http.server
import threading
import uuid

import pytest
from corral.io import credentials as creds_mod
from fsspec.implementations.memory import MemoryFileSystem
from netstead.workbench import urlcheck as urlcheck_mod
from netstead.workbench.urlcheck import check_url


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


def test_chained_url_is_rejected():
    report = check_url("simplecache::s3://bucket/net")
    assert report["reachable"] is False and "chained" in report["error"]


def test_file_scheme_is_rejected():
    report = check_url("file:///etc/passwd")
    assert report["reachable"] is False
    assert "local file browser" in report["error"]


def test_backend_error_is_reported_not_raised():
    def boom(url, **_):
        raise PermissionError("access denied")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False and report["error"] == "PermissionError: access denied"


def test_backend_error_scrubs_url_secrets():
    def boom(url, **_):
        raise OSError("https://bucket.s3.amazonaws.com/x?X-Amz-Signature=SECRET&token=abc")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False
    assert "SECRET" not in report["error"]
    assert "token=abc" not in report["error"]
    assert report["error"] == "OSError: https://bucket.s3.amazonaws.com/x"


def test_slow_backend_times_out_quickly():
    import time

    def hangs(url, **_):
        class _Fs:
            def exists(self, path):
                time.sleep(5)
                return True

        return _Fs(), "/net"

    start = time.perf_counter()
    report = check_url("s3://bucket/net", url_to_fs=hangs, timeout_s=0.2)
    elapsed = time.perf_counter() - start
    assert report["reachable"] is False
    assert report["error"] == "timed out after 0.2s"
    assert elapsed < 2.0


def test_az_url_scrubs_secrets():
    def boom(url, **_):
        raise OSError("fetch failed for az://acct/c/x?sv=1&sig=SECRET")

    report = check_url("az://acct/c/x", url_to_fs=boom)
    assert report["reachable"] is False
    assert "SECRET" not in report["error"]
    assert report["error"] == "OSError: fetch failed for az://acct/c/x"


def test_s3_url_with_userinfo_is_rejected_like_open_without_echoing_it():
    def boom(url, **_):  # pragma: no cover - never reached: the URL is refused before probing
        raise AssertionError("probed a URL with credentials in it")

    report = check_url("s3://AKIA:key@b/k", url_to_fs=boom)
    assert report["reachable"] is False and "credential cascade" in report["error"]
    assert "AKIA" not in repr(report) and "key@" not in repr(report)


@pytest.mark.parametrize(
    ("url", "match"),
    [
        ("s3:../x", "scheme://host"),
        ("https://h.example/a/../x", "'..' path segments"),
        ("https://h.example/a\\..\\x", "backslashes"),
        ("s3://b/a\\net.csv.zip", "backslashes"),
        ("duckdb:///data/x.duckdb", "local file browser"),
        ("/data/net", "local file browser"),
    ],
)
def test_check_applies_the_same_source_rules_as_open(url, match):
    report = check_url(url)
    assert report["reachable"] is False and match in report["error"]


def test_url_field_is_scrubbed_too():
    def boom(url, **_):
        raise OSError("boom")

    report = check_url("s3://AKIA:key@b/k?X-Amz-Signature=SECRET", url_to_fs=boom)
    assert "SECRET" not in report["url"]
    assert "AKIA" not in report["url"]
    assert report["url"] == "s3://b/k"


def test_scrub_handles_malformed_ipv6_url_without_raising():
    def boom(url, **_):
        raise OSError("bad url https://[x in here")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False
    assert "https://<redacted>" in report["error"]


def test_check_url_never_raises_even_if_scrub_breaks(monkeypatch):
    def exploding_scrub(_text):
        raise RuntimeError("scrub itself is broken")

    monkeypatch.setattr(urlcheck_mod, "_scrub", exploding_scrub)

    def boom(url, **_):
        raise OSError("whatever")

    report = check_url("s3://bucket/net", url_to_fs=boom)
    assert report["reachable"] is False
    assert report["error"] is not None


def test_real_http_server_is_reachable(tmp_path):
    (tmp_path / "node.csv").write_text("a,b\n1,2\n")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        report = check_url(f"http://127.0.0.1:{port}/node.csv", timeout_s=10.0)
        assert report["reachable"] is True
        assert report["kind"] == "file"
        assert report["error"] is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
