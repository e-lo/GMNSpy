"""Operation cost model, gating, batch/pool, progress reporting.

This package implements the operation-level primitives described in
``docs/architecture.md`` §6.5:

* :class:`OperationCost` — heuristic wall-time estimate for one op.
* :func:`gate` — threshold check + optional approval block.
* :class:`ApprovalRequired` — raised when an op needs explicit approval.

Batch / pool and progress reporting land in later tasks (3.x). The
CLI prompt that catches :class:`ApprovalRequired` lives in
:mod:`datagrove.cli` (Phase 4 task 4.7).
"""

from .cost_model import COEFFICIENTS, OperationCost
from .gating import ApprovalRequired, gate

__all__ = ["COEFFICIENTS", "ApprovalRequired", "OperationCost", "gate"]
