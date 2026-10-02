"""The wizard's URL **Check**: is a remote GMNS source reachable, which credential layer applies, what's in it.

Read-only and never records an action. It reports the *name* of the credential source
(``env``/``keyring``/``netrc``/``none``, from :func:`datagrove.io.credentials.credential_source`),
never a credential value, and lists table names only (no data is read).
"""

from __future__ import annotations

import logging
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


def _tables(fs: Any, path: str) -> list[str]:
    names = (PurePosixPath(str(p)).name for p in fs.ls(path, detail=False))
    return sorted({n.split(".", 1)[0] for n in names if n.lower().endswith(_TABLE_SUFFIXES)})


def check_url(url: str, *, url_to_fs: Callable[..., tuple[Any, str]] = fsspec.core.url_to_fs) -> dict[str, Any]:
    """Probe ``url`` and describe it for the wizard.

    Args:
        url: An ``http(s)``/``s3``/``gs``/``az``/... URL to a GMNS folder or file.
        url_to_fs: ``fsspec.core.url_to_fs``-compatible factory (injectable for tests).

    Returns:
        ``{"url", "reachable", "credential_source", "kind", "tables", "error"}`` where ``kind`` is
        ``"folder"``, ``"file"``, or ``None`` when unreachable, and ``tables`` lists the table names
        found directly inside a folder (``link``, ``node``, ...).
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
    try:
        fs, path = url_to_fs(url, **resolve_credentials(parts.netloc))
        if not fs.exists(path):
            report["error"] = "not found"
            return report
        report["reachable"] = True
        if fs.isdir(path):
            report["kind"], report["tables"] = "folder", _tables(fs, path)
        else:
            report["kind"] = "file"
    except ImportError as exc:
        report["error"] = f"missing filesystem support for {parts.scheme}:// ({exc})"
    except Exception as exc:  # boundary: any remote failure is reported to the user, not raised
        logger.info("check_url %s failed: %s", parts.netloc, type(exc).__name__)
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report
