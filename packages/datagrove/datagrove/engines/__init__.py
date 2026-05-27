"""Engine abstraction (ibis/duckdb default; polars; pandas) for lazy + eager dataframe ops.

The public surface is small:

- ``Engine`` — the structural protocol every backend implements.
- ``EngineNotAvailableError`` — raised when a backend is missing or
  its optional deps are not installed.
- ``register_engine`` / ``get_engine`` / ``set_default_engine`` /
  ``list_engines`` — the in-process registry.

The default engine is **ibis** (duckdb backend). It is auto-registered
at import time. Optional engines (``polars``, ``pandas``) are
auto-registered only if their dependency is importable, so this
module's import never hard-requires the optional extras.

Concrete engine implementations live in sibling modules
(``ibis_engine.py``, ``polars_engine.py``, ``pandas_engine.py``). Real
implementations land in tasks 1.3 / 1.4 / 1.5; for task 1.2 they are
stubs that raise ``NotImplementedError``.
"""

from __future__ import annotations

from .base import (
    Engine,
    EngineNotAvailableError,
    InvalidEngineCallError,
    NativeFrame,
    SourceRef,
    TableExpr,
    UnsupportedSourceError,
)

# ---------------------------------------------------------------------------
# Registry state (module-level singleton, in-process)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Engine] = {}
_DEFAULT: str | None = None


def register_engine(engine: Engine, *, default: bool = False) -> None:
    """Register an engine instance under its ``name`` attribute.

    Re-registering an existing name overwrites the previous registration
    (no warning). This is intentional — it lets tests and notebooks swap
    in fakes without ceremony, and lets a downstream package replace
    the stock implementation.

    Args:
        engine: An instance satisfying the ``Engine`` protocol. Must
            expose a non-empty ``name`` string and the engine methods
            (``scan`` / ``materialize`` / ``to_pandas`` / ``to_polars``
            / ``write``).
        default: If ``True``, also make this the default engine
            returned by ``get_engine()`` with no argument.

    Raises:
        TypeError: If ``engine`` does not satisfy the ``Engine``
            protocol (missing one or more required methods).
        ValueError: If ``engine.name`` is empty.

    Examples:
        Register a minimal fake engine and look it up. The fake uses a
        unique name to avoid colliding with auto-registered engines:

        >>> from datagrove.engines import (
        ...     register_engine, get_engine, list_engines
        ... )
        >>> class _DoctestEngine:
        ...     name = "doctest-register"
        ...     def read_csv(self, source, schema=None, **kw): return None
        ...     def read_parquet(self, source, schema=None, **kw): return None
        ...     def read_duckdb_table(self, source, table, schema=None, **kw): return None
        ...     def from_records(self, records, schema=None): return None
        ...     def from_arrow(self, arrow_table): return None
        ...     def write_csv(self, expr, dest, **kw): return None
        ...     def write_parquet(self, expr, dest, **kw): return None
        ...     def write_duckdb_table(self, expr, dest, table, **kw): return None
        ...     def cast_schema(self, expr, schema): return expr
        ...     def scan(self, source, schema=None, **kw): return None
        ...     def write(self, expr, dest, fmt, **kw): return None
        ...     def materialize(self, expr): return None
        ...     def to_pandas(self, expr): return None
        ...     def to_polars(self, expr): return None
        ...     def columns(self, expr): return []
        ...     def count(self, expr): return 0
        ...     def head(self, expr, n): return expr
        ...     def select(self, expr, columns): return expr
        >>> fake = _DoctestEngine()
        >>> try:
        ...     register_engine(fake)
        ...     get_engine("doctest-register") is fake
        ... finally:
        ...     from datagrove import engines as _eng
        ...     _ = _eng._REGISTRY.pop("doctest-register", None)
        True
    """
    global _DEFAULT
    if not isinstance(engine, Engine):
        raise TypeError(
            f"{engine!r} does not satisfy the Engine protocol "
            "(needs a 'name' attribute plus per-format primitives "
            "read_csv/read_parquet/read_duckdb_table/from_records/from_arrow and "
            "write_csv/write_parquet/write_duckdb_table, plus cast_schema, "
            "scan, write, materialize, to_pandas, to_polars, "
            "and the lazy-introspection methods columns/count/head/select)"
        )
    if not getattr(engine, "name", None):
        raise ValueError("Engine.name must be a non-empty string")
    _REGISTRY[engine.name] = engine
    if default or _DEFAULT is None:
        _DEFAULT = engine.name


def get_engine(name: str | None = None) -> Engine:
    """Return the registered engine for ``name``, or the default if ``None``.

    Args:
        name: The engine name (``"ibis"`` / ``"polars"`` / ``"pandas"``
            / a custom registration). ``None`` returns the default.

    Returns:
        The registered engine instance.

    Raises:
        EngineNotAvailableError: If the registry is empty, or the
            requested name is not registered. The message lists the
            currently-registered engine names so the caller can correct
            the typo or install the missing extra.

    Examples:
        Look up the auto-registered default (typically ``ibis``):

        >>> from datagrove.engines import get_engine
        >>> default = get_engine()
        >>> default.name in {"ibis", "polars", "pandas"}
        True

        Looking up a name that is not registered raises a clear error:

        >>> from datagrove.engines import EngineNotAvailableError
        >>> try:
        ...     get_engine("not-a-real-engine")
        ... except EngineNotAvailableError as exc:
        ...     "not-a-real-engine" in str(exc)
        True
    """
    if not _REGISTRY:
        raise EngineNotAvailableError(
            "no engines registered — install datagrove with at least one engine "
            "(default install includes ibis-framework[duckdb])"
        )
    key = name if name is not None else _DEFAULT
    if key is None:  # pragma: no cover - guarded by the empty-registry check above
        raise EngineNotAvailableError("no default engine set and no name provided")
    if key not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise EngineNotAvailableError(
            f"engine {key!r} is not registered (available: {available}). "
            f"For optional engines, install the relevant extra: "
            f"`pip install datagrove[polars]` or `pip install datagrove[pandas]`."
        )
    return _REGISTRY[key]


def set_default_engine(name: str) -> None:
    """Set the default engine returned by ``get_engine()`` with no argument.

    Args:
        name: The name of an already-registered engine.

    Raises:
        EngineNotAvailableError: If ``name`` is not registered.

    Examples:
        Swap the default to a freshly-registered fake, then restore:

        >>> from datagrove.engines import (
        ...     register_engine, set_default_engine, get_engine
        ... )
        >>> from datagrove import engines as _eng
        >>> class _DoctestEngine:
        ...     name = "doctest-default"
        ...     def read_csv(self, source, schema=None, **kw): return None
        ...     def read_parquet(self, source, schema=None, **kw): return None
        ...     def read_duckdb_table(self, source, table, schema=None, **kw): return None
        ...     def from_records(self, records, schema=None): return None
        ...     def from_arrow(self, arrow_table): return None
        ...     def write_csv(self, expr, dest, **kw): return None
        ...     def write_parquet(self, expr, dest, **kw): return None
        ...     def write_duckdb_table(self, expr, dest, table, **kw): return None
        ...     def cast_schema(self, expr, schema): return expr
        ...     def scan(self, source, schema=None, **kw): return None
        ...     def write(self, expr, dest, fmt, **kw): return None
        ...     def materialize(self, expr): return None
        ...     def to_pandas(self, expr): return None
        ...     def to_polars(self, expr): return None
        ...     def columns(self, expr): return []
        ...     def count(self, expr): return 0
        ...     def head(self, expr, n): return expr
        ...     def select(self, expr, columns): return expr
        >>> previous = _eng._DEFAULT
        >>> try:
        ...     register_engine(_DoctestEngine())
        ...     set_default_engine("doctest-default")
        ...     get_engine().name
        ... finally:
        ...     _ = _eng._REGISTRY.pop("doctest-default", None)
        ...     _eng._DEFAULT = previous
        'doctest-default'
    """
    global _DEFAULT
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise EngineNotAvailableError(f"cannot set default to {name!r}: not registered (available: {available})")
    _DEFAULT = name


def list_engines() -> list[str]:
    """Return the sorted list of currently-registered engine names.

    Examples:
        The default install auto-registers at least ``ibis``:

        >>> from datagrove.engines import list_engines
        >>> names = list_engines()
        >>> "ibis" in names
        True
        >>> names == sorted(names)
        True
    """
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Auto-registration of stock engines.
#
# Each block is wrapped in try/except ImportError so a missing optional
# dep (polars, pandas) never blocks importing this module. A *broken*
# install of a registered engine surfaces at use-time via
# NotImplementedError (stubs) or the engine's own error path (real
# impls in 1.3 / 1.4 / 1.5).
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised by registry tests
    from .ibis_engine import IbisEngine

    register_engine(IbisEngine(), default=True)
except ImportError:  # pragma: no cover - only fires in a broken install
    pass

try:  # pragma: no cover - exercised conditionally
    import polars as _polars  # noqa: F401

    from .polars_engine import PolarsEngine

    register_engine(PolarsEngine())
except ImportError:  # pragma: no cover - polars is optional
    pass

try:  # pragma: no cover - exercised conditionally
    import pandas as _pandas  # noqa: F401

    from .pandas_engine import PandasEngine

    register_engine(PandasEngine())
except ImportError:  # pragma: no cover - pandas is optional
    pass


# ---------------------------------------------------------------------------
# CLI-facing convenience: resolve a user-typed name to an Engine instance.
# ---------------------------------------------------------------------------


def resolve_engine(name: str | None) -> Engine:
    """Return an :class:`Engine` for ``name`` (or the default when ``name`` is None).

    User-facing helper for CLI / config / MCP flag parsing. Accepts
    one of ``"ibis"`` / ``"pandas"`` / ``"polars"`` (case-insensitive).
    ``None`` returns the registered default (typically ibis).

    This wraps :func:`get_engine` with a single concession: unknown
    names raise :class:`ValueError` with a list of known engines, so
    CLI wrappers can convert that to ``typer.BadParameter`` without
    re-deriving the message.

    Args:
        name: Engine name to resolve. ``None`` returns the default.

    Returns:
        A registered :class:`Engine` instance.

    Raises:
        ValueError: If ``name`` doesn't match a known engine.

    Examples:
        >>> from datagrove.engines import resolve_engine
        >>> eng = resolve_engine(None)  # default (typically IbisEngine)
        >>> isinstance(eng, Engine)
        True
        >>> eng_p = resolve_engine("pandas")
        >>> type(eng_p).__name__
        'PandasEngine'
    """
    if name is None:
        return get_engine()
    key = name.strip().lower()
    if key not in {"ibis", "pandas", "polars"}:
        known = ", ".join(sorted({"ibis", "pandas", "polars"}))
        raise ValueError(f"unknown engine {name!r}; expected one of: {known}")
    return get_engine(key)


__all__ = [
    "Engine",
    "EngineNotAvailableError",
    "InvalidEngineCallError",
    "NativeFrame",
    "SourceRef",
    "TableExpr",
    "UnsupportedSourceError",
    "get_engine",
    "list_engines",
    "register_engine",
    "resolve_engine",
    "set_default_engine",
]
