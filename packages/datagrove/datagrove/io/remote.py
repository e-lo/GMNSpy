"""Remote (URL) format adapter -- two-layer dispatch over fsspec.

RemoteAdapter is the front for any URL-based source: ``http(s)://``,
``s3://``, ``gs://`` / ``gcs://``, ``az://`` / ``abfs(s)://``. It does
**not** parse the underlying bytes itself. Instead it:

    1. Parses the URL and extracts the host.
    2. Resolves storage credentials via :func:`datagrove.io.credentials.resolve_credentials`.
    3. Determines the **inner** format from the URL's extension (or an
       explicit ``format=`` kwarg).
    4. Looks up the matching inner :class:`FormatAdapter` and delegates
       to its ``read`` / ``write`` / ``scan``, passing
       ``storage_options=...`` through so the inner adapter can hand it
       to fsspec / ibis / polars natively.

This means the credentials cascade is enforced in exactly one place even
though every format (csv, parquet, duckdb, zipcsv) can live behind a URL.

Self-registers at module import via :func:`datagrove.io.register_adapter`.

Examples:
    Direct use is rare; the front-door is :func:`datagrove.io.dispatch`,
    which routes any URL through RemoteAdapter automatically:

    >>> from datagrove.io import dispatch
    >>> adapter = dispatch("s3://bucket/data.csv")  # doctest: +SKIP
    >>> adapter.name  # doctest: +SKIP
    'remote'
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

import fsspec

from datagrove.io import dispatch, register_adapter
from datagrove.io.base import (
    FormatAdapter,
    FormatNotDetected,
    ResourceListing,
    ResourceRef,
    SourceRef,
)
from datagrove.io.credentials import resolve_credentials

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import Schema

__all__ = ["RemoteAdapter"]

_logger: Final = logging.getLogger(__name__)

# Schemes RemoteAdapter claims. Order matches the architecture spec.
_REMOTE_SCHEMES: Final[tuple[str, ...]] = (
    "http",
    "https",
    "s3",
    "gs",
    "gcs",
    "az",
    "abfs",
    "abfss",
)

# Schemes that are read-only over HTTP semantics. ``s3``/``gs``/``az`` etc.
# do support writes through fsspec when credentials and the matching extra
# (``s3fs``/``gcsfs``/``adlfs``) are installed.
_READONLY_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class RemoteAdapter:
    """URL-based source adapter with credentials cascade + inner-format dispatch.

    The adapter itself owns no parsing logic -- it resolves a URL, attaches
    storage_options, then delegates to whichever sibling adapter owns the
    URL's extension. This keeps the URL and credential machinery in exactly
    one place across all formats.
    """

    name: str = "remote"
    extensions: tuple[str, ...] = ()
    schemes: tuple[str, ...] = _REMOTE_SCHEMES

    # ----- probe -----------------------------------------------------------

    def probe(self, source: SourceRef) -> bool:
        """Return True if ``source`` looks like a URL with a known scheme.

        Total -- never raises on malformed input. Non-string sources
        return False.
        """
        if not isinstance(source, str):
            return False
        try:
            scheme = urlparse(source).scheme.lower()
        except (ValueError, AttributeError):
            return False
        return bool(scheme) and scheme in _REMOTE_SCHEMES

    # ----- read ------------------------------------------------------------

    def read(
        self,
        source: SourceRef,
        engine: Engine,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> TableExpr:
        """Open ``source`` via fsspec and delegate to the inner-format adapter.

        Args:
            source: A URL string.
            engine: The execution engine, forwarded to the inner adapter.
            schema: Optional Frictionless schema, forwarded.
            **kwargs: Adapter options. Two special keys are consumed here
                and not forwarded:

                - ``credentials``: explicit dict for the credentials
                  cascade. Overrides env / keyring / netrc.
                - ``format``: explicit inner-format override. Used when
                  the URL extension is ambiguous (e.g. an
                  extensionless API endpoint that returns parquet).

                All other kwargs are forwarded verbatim, **plus** a
                ``storage_options=...`` entry built from the resolved
                credentials.

        Returns:
            Whatever the inner adapter's ``read`` returns -- a lazy table
            expression.

        Raises:
            FormatNotDetected: If the URL has no extension and no
                ``format=`` override was given.
        """
        explicit_creds = kwargs.pop("credentials", None)
        inner_format_override = kwargs.pop("format", None)

        url_str = str(source)
        storage_options = self._storage_options_for(url_str, explicit_creds)
        inner = self._inner_adapter(url_str, format=inner_format_override)

        # Don't double-log the credential values -- log identity only.
        _logger.debug("remote.read host=%s inner=%s", _host_of(url_str), inner.name)

        return inner.read(
            url_str,
            engine,
            schema=schema,
            storage_options=storage_options,
            **kwargs,
        )

    # ----- write -----------------------------------------------------------

    def write(
        self,
        expr: TableExpr,
        dest: SourceRef,
        engine: Engine,
        **kwargs: Any,
    ) -> None:
        """Delegate write to the inner-format adapter, or refuse for HTTP.

        Raises:
            NotImplementedError: If ``dest`` is an ``http(s)://`` URL.
                HTTP is read-only in our default cloud-backend matrix.
                Object stores (s3/gs/az) do route through to the inner
                adapter with credentials attached.
        """
        explicit_creds = kwargs.pop("credentials", None)
        inner_format_override = kwargs.pop("format", None)

        url_str = str(dest)
        scheme = (urlparse(url_str).scheme or "").lower()
        if scheme in _READONLY_SCHEMES:
            raise NotImplementedError(
                f"Writing to {scheme}:// URLs is not supported "
                "(HTTP is read-only). For cloud writes use s3://, gs://, or az:// "
                "with the matching datagrove extra installed."
            )

        storage_options = self._storage_options_for(url_str, explicit_creds)
        inner = self._inner_adapter(url_str, format=inner_format_override)

        _logger.debug("remote.write host=%s inner=%s", _host_of(url_str), inner.name)

        inner.write(
            expr,
            url_str,
            engine,
            storage_options=storage_options,
            **kwargs,
        )

    # ----- scan ------------------------------------------------------------

    def scan(self, source: SourceRef, engine: Engine) -> ResourceListing:
        """List one-or-more resources at ``source``.

        For a URL pointing at a single file the listing has one entry.
        For a URL pointing at a directory-like prefix (``s3://b/p/``),
        ``fsspec.filesystem(scheme).ls(...)`` is consulted. Each child
        that has a recognised extension contributes one
        :class:`ResourceRef`.
        """
        url_str = str(source)
        scheme = (urlparse(url_str).scheme or "").lower()

        # Trailing-slash heuristic: an explicit directory-shaped URL.
        looks_like_dir = url_str.endswith("/")

        if looks_like_dir or _path_has_no_extension(url_str):
            try:
                storage_options = self._storage_options_for(url_str, None)
                fs = fsspec.filesystem(scheme, **storage_options)
            except (ValueError, ImportError):
                # fsspec couldn't build a filesystem for this scheme
                # (missing optional dep, etc.). Fall back to single-resource.
                fs = None

            if fs is not None:
                # Only consult ls when fsspec confirms a directory.
                is_dir = False
                try:
                    is_dir = bool(fs.isdir(_strip_scheme(url_str)))
                except Exception:
                    is_dir = looks_like_dir
                if is_dir:
                    entries = fs.ls(_strip_scheme(url_str))
                    return [_resource_ref_for(entry) for entry in entries if _has_known_extension(str(entry))]

        # Single-resource fallback (also the path for non-dir URLs).
        return [_resource_ref_for(url_str)]

    # ----- internals -------------------------------------------------------

    def _storage_options_for(self, url_str: str, explicit: dict | None) -> dict:
        """Resolve credentials for ``url_str``'s host."""
        host = _host_of(url_str)
        return resolve_credentials(host, explicit=explicit)

    def _inner_adapter(self, url_str: str, format: str | None = None) -> FormatAdapter:
        """Resolve the inner-format adapter for ``url_str``.

        Loop guard: never returns RemoteAdapter itself. If the dispatcher
        somehow resolves back to ``remote`` (e.g. because a URL scheme
        match wins over the extension), strip the URL scheme and retry
        on the plain path. This keeps ``remote.read`` from recursing
        into itself.
        """
        try:
            adapter = dispatch(url_str, format=format)
        except FormatNotDetected:
            # Retry with the scheme stripped -- the extension is the only
            # way to recover an inner format for an HTTP URL.
            stripped = _strip_scheme(url_str)
            if stripped != url_str:
                adapter = dispatch(stripped, format=format)
            else:
                raise

        if adapter is self or getattr(adapter, "name", None) == self.name:
            # URL-scheme dispatch picked us. Strip the scheme and retry
            # on the bare path so extension dispatch can reach the real
            # inner adapter.
            stripped = _strip_scheme(url_str)
            adapter = dispatch(stripped, format=format)

        return adapter


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _host_of(url_str: str) -> str:
    """Return the host portion of a URL, or the empty string."""
    parsed = urlparse(url_str)
    return parsed.netloc or ""


def _strip_scheme(url_str: str) -> str:
    """Return ``url_str`` with the ``scheme://netloc`` prefix removed.

    Used by inner-format dispatch so that ``https://x.com/foo.parquet``
    resolves through the ``.parquet`` extension lookup rather than the
    ``https`` scheme lookup.
    """
    parsed = urlparse(url_str)
    if not parsed.scheme:
        return url_str
    return parsed.path.lstrip("/") or url_str


def _path_has_no_extension(url_str: str) -> bool:
    """True if the URL's tail has no ``.ext`` suffix."""
    parsed = urlparse(url_str)
    name = PurePosixPath(parsed.path).name
    return "." not in name


def _has_known_extension(path: str) -> bool:
    """Return True if ``path`` ends with at least one ``.suffix``.

    Used to filter directory listings down to plausible data files.
    Adapter resolution still happens via the registry -- this just
    skips obvious junk (``_SUCCESS`` markers, directories, etc.).
    """
    return "." in PurePosixPath(path).name


def _resource_ref_for(path: str) -> ResourceRef:
    """Build a ResourceRef from a single file path / URL.

    The ``format`` field is best-effort: the file's extension when
    present, else ``"remote"``.
    """
    name = PurePosixPath(urlparse(path).path or path).stem or path
    suffixes = PurePosixPath(urlparse(path).path or path).suffixes
    fmt = suffixes[-1].lstrip(".").lower() if suffixes else "remote"
    return ResourceRef(name=name, path=path, format=fmt)


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------

register_adapter(RemoteAdapter())
