"""The wizard's URL **Check**: is a remote GMNS source reachable, which credential layer applies, what's in it.

Read-only and never records an action. It reports the *name* of the credential source
(``env``/``keyring``/``netrc``/``none``, from :func:`datagrove.io.credentials.credential_source`),
never a credential value, and lists table names only (no data is read).

This probes an arbitrary ``http(s)``/``s3``/``gs``/``az``/... host supplied by the caller; it is meant
for the workbench's local, single-user server, not for exposure to untrusted callers.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import fsspec
from datagrove.io.credentials import credential_source, resolve_credentials

__all__ = ["REMOTE_SCHEMES", "check_url"]

logger = logging.getLogger(__name__)

#: URL schemes the wizard accepts for "GMNS at a URL" (the datagrove remote adapter's schemes).
REMOTE_SCHEMES = ("http", "https", "s3", "gs", "gcs", "az", "abfs", "abfss")

_TABLE_SUFFIXES = (".csv", ".parquet")
#: Cap on how many directory entries we inspect when listing tables (a huge bucket shouldn't hang this).
_MAX_LS_ENTRIES = 1000
#: Cap on the scrubbed error message length shown to the user.
_MAX_ERROR_LEN = 200
_URL_RE = re.compile(r"https?://\S+")


def _scrub(text: str) -> str:
    """Strip query strings and userinfo from any URL in ``text``, and cap its length.

    Backend exceptions (S3, Azure, GCS, HTTP clients) routinely embed the failing URL, including
    presigned-URL signatures or ``user:pass@host`` credentials, in their messages. Only the
    scheme/host/path survives; everything after ``?`` and any userinfo before ``@`` is dropped.
    """

    def _strip_url(match: re.Match[str]) -> str:
        parts = urlsplit(match.group(0))
        netloc = parts.netloc.rsplit("@", 1)[-1]
        return f"{parts.scheme}://{netloc}{parts.path}"

    return _URL_RE.sub(_strip_url, text)[:_MAX_ERROR_LEN]


def _tables(fs: Any, path: str) -> list[str]:
    entries = fs.ls(path, detail=False)[:_MAX_LS_ENTRIES]
    names = (PurePosixPath(str(p)).name for p in entries)
    return sorted({n.split(".", 1)[0] for n in names if n.lower().endswith(_TABLE_SUFFIXES)})


def check_url(
    url: str,
    *,
    url_to_fs: Callable[..., tuple[Any, str]] = fsspec.core.url_to_fs,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """Probe ``url`` and describe it for the wizard.

    The probe (``url_to_fs`` plus ``exists``/``isdir``/``ls``) runs in a worker thread so a slow or
    unresponsive host cannot hang the caller: we wait at most ``timeout_s`` for it. On a timeout the
    worker thread is not cancelled (threads cannot be killed from outside) and may keep running in
    the background until the underlying call itself returns or errors; only its result is discarded.

    Args:
        url: An ``http(s)``/``s3``/``gs``/``az``/... URL to a GMNS folder or file.
        url_to_fs: ``fsspec.core.url_to_fs``-compatible factory (injectable for tests).
        timeout_s: Maximum time to wait for the probe before reporting it as unreachable.

    Returns:
        ``{"url", "reachable", "credential_source", "kind", "tables", "error"}`` where ``kind`` is
        ``"folder"``, ``"file"``, or ``None`` when unreachable, and ``tables`` lists the table names
        found directly inside a folder (``link``, ``node``, ...). ``error`` is a short, scrubbed
        message safe to show in the UI: it never contains credential values, and any URL inside it
        has had its query string and userinfo stripped.
    """
    parts = urlsplit(url)
    report: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "credential_source": "none",
        "kind": None,
        "tables": [],
        "error": None,
    }
    scheme = parts.scheme.lower()
    if scheme == "file":
        report["error"] = "file:// is not accepted here; use the local file browser for local paths"
        return report
    if scheme not in REMOTE_SCHEMES:
        report["error"] = f"unsupported URL scheme {parts.scheme!r}; use one of {', '.join(REMOTE_SCHEMES)}"
        return report
    report["credential_source"] = credential_source(parts.netloc)
    storage_options = resolve_credentials(parts.netloc)
    if scheme in ("http", "https"):
        # Cheap best-effort: ask the HTTP backend to give up around the same deadline. The thread
        # join below is the actual guarantee, since not every fsspec backend honours this.
        storage_options = {**storage_options, "client_kwargs": {"timeout": timeout_s}}

    def _probe() -> dict[str, Any]:
        result: dict[str, Any] = {"reachable": False, "kind": None, "tables": [], "error": None}
        try:
            fs, path = url_to_fs(url, **storage_options)
            if not fs.exists(path):
                result["error"] = "not found"
                return result
            result["reachable"] = True
            if fs.isdir(path):
                result["kind"], result["tables"] = "folder", _tables(fs, path)
            else:
                result["kind"] = "file"
        except ImportError as exc:
            result["error"] = _scrub(f"missing filesystem support for {parts.scheme}:// ({exc})")
        except Exception as exc:  # boundary: any remote failure is reported to the user, not raised
            logger.debug("check_url %s failed: %s", parts.netloc, exc)
            result["error"] = _scrub(f"{type(exc).__name__}: {exc}")
        return result

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        probed = executor.submit(_probe).result(timeout=timeout_s)
        report.update(probed)
    except concurrent.futures.TimeoutError:
        report["error"] = f"timed out after {timeout_s:g}s"
    finally:
        executor.shutdown(wait=False)
    return report
