"""Format adapter registry (csv, parquet, duckdb, zipcsv, remote URL + credentials).

This package owns the :class:`FormatAdapter` protocol and the registry +
dispatcher that route a :data:`SourceRef` (path or URL) to the correct
concrete adapter. Concrete adapters (csv/parquet/duckdb/zipcsv/remote)
are implemented in sibling modules and self-register at import time via
:func:`register_adapter`.

Resolution order in :func:`dispatch`:

    1. Explicit ``format=`` keyword --exact name lookup.
    2. URL scheme match (``duckdb://...`` → adapter declaring ``duckdb``
       in ``schemes``).
    3. Filename extension match. Compound extensions (e.g. ``.csv.zip``)
       are tried before the simple tail (``.zip``) so a zip-of-csv adapter
       wins over a generic zip handler.
    4. ``probe`` chain --every registered adapter is asked, in
       registration order, whether it can read the source. The first
       ``True`` wins.
    5. :class:`FormatNotDetected` raised, listing registered adapters.

The registry intentionally does **not** auto-register any adapters —
those land in tasks 1.7-1.11. Importing this package gives you a working
dispatcher with an empty registry, suitable for testing with mock
adapters.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .base import (
    AdapterNotAvailableError,
    FormatAdapter,
    FormatError,
    FormatNotDetected,
    ResourceListing,
    ResourceRef,
    SourceRef,
)

# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------
# Three indexed dicts kept in sync by ``register_adapter``:
#   _REGISTRY:   name           → adapter
#   _BY_EXT:     extension key  → adapter name  (compound extensions allowed)
#   _BY_SCHEME:  url scheme     → adapter name
# Insertion order in _REGISTRY is preserved (Python 3.7+) and is the order
# in which probe() is consulted in the fallback chain.

_REGISTRY: dict[str, FormatAdapter] = {}
_BY_EXT: dict[str, str] = {}
_BY_SCHEME: dict[str, str] = {}


def register_adapter(adapter: FormatAdapter) -> None:
    """Register ``adapter`` into the global registry.

    Re-registering an adapter with an existing ``name`` overwrites the
    previous entry (and rebinds its extensions/schemes). This makes
    test setup and adapter swapping straightforward.

    Args:
        adapter: A :class:`FormatAdapter` instance with non-empty ``name``.

    Raises:
        TypeError: If ``adapter`` does not satisfy the
            :class:`FormatAdapter` protocol.
        ValueError: If ``adapter.name`` is empty.

    Examples:
        Register a minimal fake adapter and confirm it appears in the
        registry. The fake uses a unique name to avoid colliding with
        the stock adapters registered in later tasks:

        >>> from datagrove.io import register_adapter, get_adapter
        >>> from datagrove.io.base import ResourceRef
        >>> class _DoctestAdapter:
        ...     name = "doctest-register"
        ...     extensions = ("doctestfmt",)
        ...     schemes = ()
        ...     def probe(self, source): return False
        ...     def read(self, source, engine, schema=None, **kw): return None
        ...     def write(self, expr, dest, engine, **kw): return None
        ...     def scan(self, source, engine):
        ...         return [ResourceRef(
        ...             name=self.name, path=str(source), format=self.name
        ...         )]
        >>> fake = _DoctestAdapter()
        >>> from datagrove import io as _io
        >>> try:
        ...     register_adapter(fake)
        ...     get_adapter("doctest-register") is fake
        ... finally:
        ...     _ = _io._REGISTRY.pop("doctest-register", None)
        ...     _io._purge_bindings_for("doctest-register")
        True
    """
    if not isinstance(adapter, FormatAdapter):
        raise TypeError(f"{adapter!r} does not satisfy the FormatAdapter protocol")
    if not adapter.name:
        raise ValueError("FormatAdapter.name must be non-empty")

    name = adapter.name

    # If overwriting, scrub the previous adapter's ext/scheme bindings so we
    # don't leave dangling pointers to a deregistered name.
    if name in _REGISTRY:
        _purge_bindings_for(name)

    _REGISTRY[name] = adapter
    for ext in adapter.extensions:
        _BY_EXT[ext.lower().lstrip(".")] = name
    for scheme in adapter.schemes:
        _BY_SCHEME[scheme.lower()] = name


def _purge_bindings_for(name: str) -> None:
    """Remove ext/scheme bindings that point at ``name``."""
    for ext, owner in list(_BY_EXT.items()):
        if owner == name:
            del _BY_EXT[ext]
    for scheme, owner in list(_BY_SCHEME.items()):
        if owner == name:
            del _BY_SCHEME[scheme]


def get_adapter(name: str) -> FormatAdapter:
    """Look up an adapter by name.

    Args:
        name: The adapter's short identifier.

    Returns:
        The registered adapter.

    Raises:
        AdapterNotAvailableError: If no adapter with ``name`` is registered.

    Examples:
        Asking for an unknown adapter raises a clear error that lists
        what *is* registered:

        >>> from datagrove.io import get_adapter, AdapterNotAvailableError
        >>> try:
        ...     get_adapter("not-a-real-adapter")
        ... except AdapterNotAvailableError as exc:
        ...     "not-a-real-adapter" in str(exc)
        True

        Round-trip via :func:`register_adapter`:

        >>> from datagrove.io import register_adapter
        >>> from datagrove.io.base import ResourceRef
        >>> from datagrove import io as _io
        >>> class _DoctestAdapter:
        ...     name = "doctest-get"
        ...     extensions = ()
        ...     schemes = ()
        ...     def probe(self, source): return False
        ...     def read(self, source, engine, schema=None, **kw): return None
        ...     def write(self, expr, dest, engine, **kw): return None
        ...     def scan(self, source, engine):
        ...         return [ResourceRef(
        ...             name=self.name, path=str(source), format=self.name
        ...         )]
        >>> fake = _DoctestAdapter()
        >>> try:
        ...     register_adapter(fake)
        ...     get_adapter("doctest-get") is fake
        ... finally:
        ...     _ = _io._REGISTRY.pop("doctest-get", None)
        ...     _io._purge_bindings_for("doctest-get")
        True
    """
    try:
        return _REGISTRY[name]
    except KeyError as err:
        raise AdapterNotAvailableError(
            f"No adapter registered under name {name!r}. Registered adapters: {list(_REGISTRY)!r}"
        ) from err


def list_adapters() -> list[str]:
    """Return the names of all registered adapters in registration order.

    Examples:
        With no adapters auto-registered at import time, ``list_adapters``
        reflects exactly what callers have registered themselves:

        >>> from datagrove.io import register_adapter, list_adapters
        >>> from datagrove.io.base import ResourceRef
        >>> from datagrove import io as _io
        >>> class _DoctestAdapter:
        ...     name = "doctest-list"
        ...     extensions = ()
        ...     schemes = ()
        ...     def probe(self, source): return False
        ...     def read(self, source, engine, schema=None, **kw): return None
        ...     def write(self, expr, dest, engine, **kw): return None
        ...     def scan(self, source, engine):
        ...         return [ResourceRef(
        ...             name=self.name, path=str(source), format=self.name
        ...         )]
        >>> try:
        ...     register_adapter(_DoctestAdapter())
        ...     "doctest-list" in list_adapters()
        ... finally:
        ...     _ = _io._REGISTRY.pop("doctest-list", None)
        ...     _io._purge_bindings_for("doctest-list")
        True
    """
    return list(_REGISTRY)


def _clear_registry() -> None:
    """Drop all registered adapters (test helper).

    Not part of the public API --intended for test fixtures that need a
    clean slate. Not exported from ``__all__``.
    """
    _REGISTRY.clear()
    _BY_EXT.clear()
    _BY_SCHEME.clear()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _normalize_path_str(source: SourceRef) -> str:
    """Coerce ``source`` to a string for URL/extension parsing.

    Accepts the ``str`` and ``Path`` arms of :data:`SourceRef`. The
    ``dict`` arm of :data:`SourceRef` is a structured engine handle
    (e.g. ``{"format": "duckdb", "path": "...", "table": "link"}``);
    the dispatcher cannot meaningfully sniff a scheme or extension from
    it and requires an explicit ``format=`` kwarg.

    Raises:
        TypeError: If ``source`` is a ``dict`` (caller must pass an
            explicit ``format=`` so :func:`dispatch` skips sniffing) or
            an otherwise-unsupported type.
    """
    if isinstance(source, Path):
        return str(source)
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        raise TypeError(
            "dispatch cannot sniff a dict source handle; pass an explicit format=, "
            "e.g. dispatch(handle, format='duckdb'). dict handles are intended for "
            "engine-side use after dispatch has resolved an adapter."
        )
    raise TypeError(f"unsupported SourceRef type: {type(source).__name__!r} (expected str, Path, or dict)")


def _scheme_of(source_str: str) -> str | None:
    """Extract a URL scheme from ``source_str``, if any.

    Returns the scheme lowercase (without ``://``), or ``None`` if the
    source has no scheme or only a single-letter scheme (which is most
    likely a Windows drive letter like ``C:\\path``).
    """
    parsed = urlparse(source_str)
    scheme = parsed.scheme.lower()
    if not scheme or len(scheme) == 1:
        return None
    return scheme


def _extension_keys(source_str: str) -> list[str]:
    """Return candidate extension keys for ``source_str``, longest first.

    For ``"foo.csv.zip"`` returns ``["csv.zip", "zip"]`` so a compound
    adapter (zipcsv) gets first crack before a generic single-extension
    adapter.
    """
    # Strip any URL fragments/queries before looking at the path tail.
    parsed = urlparse(source_str)
    path = parsed.path if parsed.scheme and len(parsed.scheme) > 1 else source_str
    name = Path(path).name.lower()

    parts = name.split(".")
    if len(parts) <= 1:
        return []
    # Build progressively shorter compound suffixes.
    # e.g. parts = ["foo", "csv", "zip"] → suffixes = ["csv.zip", "zip"]
    suffixes: list[str] = []
    for i in range(1, len(parts)):
        suffixes.append(".".join(parts[i:]))
    return suffixes


def dispatch(source: SourceRef, *, format: str | None = None) -> FormatAdapter:
    """Resolve ``source`` to a registered :class:`FormatAdapter`.

    Args:
        source: The source reference.
        format: Optional explicit adapter name. When given, takes
            precedence over all sniffing.

    Returns:
        The resolved adapter.

    Raises:
        AdapterNotAvailableError: If ``format`` is given but unregistered.
        FormatNotDetected: If no resolution stage matched.

    Examples:
        Extension-based routing — register a fake that owns a unique
        extension, then dispatch a matching path:

        >>> from datagrove.io import register_adapter, dispatch
        >>> from datagrove.io.base import ResourceRef
        >>> from datagrove import io as _io
        >>> class _DoctestAdapter:
        ...     name = "doctest-dispatch"
        ...     extensions = ("doctestfmt",)
        ...     schemes = ()
        ...     def probe(self, source): return False
        ...     def read(self, source, engine, schema=None, **kw): return None
        ...     def write(self, expr, dest, engine, **kw): return None
        ...     def scan(self, source, engine):
        ...         return [ResourceRef(
        ...             name=self.name, path=str(source), format=self.name
        ...         )]
        >>> fake = _DoctestAdapter()
        >>> try:
        ...     register_adapter(fake)
        ...     dispatch("data/example.doctestfmt") is fake
        ... finally:
        ...     _ = _io._REGISTRY.pop("doctest-dispatch", None)
        ...     _io._purge_bindings_for("doctest-dispatch")
        True

        An explicit ``format=`` short-circuits all sniffing. The
        extension on the source is ignored when ``format`` is given:

        >>> other = _DoctestAdapter()
        >>> try:
        ...     register_adapter(other)
        ...     dispatch("anything-at-all", format="doctest-dispatch").name
        ... finally:
        ...     _ = _io._REGISTRY.pop("doctest-dispatch", None)
        ...     _io._purge_bindings_for("doctest-dispatch")
        'doctest-dispatch'
    """
    # 1. Explicit format wins.
    if format is not None:
        return get_adapter(format)

    source_str = _normalize_path_str(source)

    # 2. URL scheme match.
    scheme = _scheme_of(source_str)
    if scheme is not None and scheme in _BY_SCHEME:
        return _REGISTRY[_BY_SCHEME[scheme]]

    # 3. Extension match --longest compound first.
    for ext_key in _extension_keys(source_str):
        if ext_key in _BY_EXT:
            return _REGISTRY[_BY_EXT[ext_key]]

    # 4. Probe chain --registration order.
    for adapter in _REGISTRY.values():
        try:
            if adapter.probe(source):
                return adapter
        except Exception:
            # An adapter's probe must be cheap and total; if it raises,
            # treat it as a non-match rather than letting it crash the
            # dispatch pipeline.
            continue

    # 5. Give up with a useful error message.
    raise FormatNotDetected(
        f"Could not determine format for source {source_str!r}. Registered adapters: {list(_REGISTRY)!r}"
    )


__all__ = [
    "AdapterNotAvailableError",
    "FormatAdapter",
    "FormatError",
    "FormatNotDetected",
    "ResourceListing",
    "ResourceRef",
    "SourceRef",
    "dispatch",
    "get_adapter",
    "list_adapters",
    "register_adapter",
]
