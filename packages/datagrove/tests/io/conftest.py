"""Snapshot + restore the adapter registry around every io/ test.

Several io/ tests mutate the module-level
:data:`datagrove.io._REGISTRY` (clear, register fake adapters, etc.).
Without restoration, downstream tests in later directories find an
empty registry and can't load directory-of-csv sources.

This autouse fixture snapshots the registry at test entry and
restores it at test exit — individual tests are still free to clear /
register inside their body; the snapshot covers the cleanup.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _snapshot_adapter_registry():
    """Snapshot + restore ``datagrove.io._REGISTRY`` / ``_BY_EXT`` / ``_BY_SCHEME``."""
    from datagrove.io import _BY_EXT, _BY_SCHEME, _REGISTRY, _clear_registry

    saved_reg = dict(_REGISTRY)
    saved_ext = dict(_BY_EXT)
    saved_scheme = dict(_BY_SCHEME)
    try:
        yield
    finally:
        _clear_registry()
        _REGISTRY.update(saved_reg)
        _BY_EXT.update(saved_ext)
        _BY_SCHEME.update(saved_scheme)
