"""Operation cost model, gating, batch/pool, progress reporting.

This package implements the operation-level primitives described in
``docs/architecture.md`` §6.5:

* :class:`OperationCost` / :data:`COEFFICIENTS` / :func:`gate` /
  :class:`ApprovalRequired` — heuristic cost estimate + threshold gating
  with CLI-friendly approval semantics (task 3.1).
* :func:`progress` / :class:`Spinner` / :func:`is_notebook` — notebook-aware
  progress reporting (task 3.3).
* :class:`Batch` / :func:`coalesce` will land in task 3.2 and be added
  to ``__all__`` then.

The CLI prompt that catches :class:`ApprovalRequired` lives in
:mod:`datagrove.cli` (Phase 4 task 4.7).
"""

from .cost_model import COEFFICIENTS, OperationCost
from .gating import ApprovalRequired, gate
from .progress import Spinner, is_notebook, progress

__all__ = [
    "ApprovalRequired",
    "COEFFICIENTS",
    "OperationCost",
    "Spinner",
    "gate",
    "is_notebook",
    "progress",
]
