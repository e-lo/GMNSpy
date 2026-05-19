"""Generic Frictionless-aligned tabular-data-package engine.

Top-level re-exports cover the most common entry points. Submodules
hold the full surface (:mod:`datagrove.engines`, :mod:`datagrove.io`,
:mod:`datagrove.validation`, :mod:`datagrove.dataset`, ...).

Examples:
    >>> from datagrove import Package, Table
    >>> Package is not None and Table is not None
    True
"""

from .dataset import OutOfSyncError, OutOfSyncWarning, Package, Table

__all__ = ["OutOfSyncError", "OutOfSyncWarning", "Package", "Table"]
