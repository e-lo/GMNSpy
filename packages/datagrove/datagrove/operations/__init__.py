"""Operation cost model, gating, batch/pool, progress reporting.

This package implements the operation-level primitives described in
``docs/architecture.md`` §6.5:

* :class:`OperationCost` / :data:`COEFFICIENTS` / :func:`gate` /
  :class:`ApprovalRequired` — heuristic cost estimate + threshold gating
  with CLI-friendly approval semantics (task 3.1).
* :class:`Batch` / :class:`BatchValidationError` / :func:`coalesce` —
  context manager that defers + coalesces edits on a
  :class:`~datagrove.dataset.Package`, applies them atomically through a
  single :class:`~datagrove.editing.Session`, and validates once on
  clean commit (task 3.2).
* :func:`progress` / :class:`Spinner` / :func:`is_notebook` — notebook-aware
  progress reporting (task 3.3).

The CLI prompt that catches :class:`ApprovalRequired` lives in
:mod:`datagrove.cli` (Phase 4 task 4.7).
"""

from .cost_model import COEFFICIENTS, OperationCost
from .gating import ApprovalRequired, gate
from .pool import Batch, BatchValidationError, coalesce
from .progress import Spinner, is_notebook, progress

__all__ = [
    "COEFFICIENTS",
    "ApprovalRequired",
    "Batch",
    "BatchValidationError",
    "OperationCost",
    "Spinner",
    "coalesce",
    "gate",
    "is_notebook",
    "progress",
]
