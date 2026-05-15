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
    NativeFrame,
    SourceRef,
    TableExpr,
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
        engine: An instance satisfying the ``Engine`` protocol.
        default: If ``True``, also make this the default engine
            returned by ``get_engine()`` with no argument.
    """
    global _DEFAULT
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
    """
    global _DEFAULT
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise EngineNotAvailableError(f"cannot set default to {name!r}: not registered (available: {available})")
    _DEFAULT = name


def list_engines() -> list[str]:
    """Return the sorted list of currently-registered engine names."""
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


__all__ = [
    "Engine",
    "EngineNotAvailableError",
    "NativeFrame",
    "SourceRef",
    "TableExpr",
    "get_engine",
    "list_engines",
    "register_engine",
    "set_default_engine",
]
