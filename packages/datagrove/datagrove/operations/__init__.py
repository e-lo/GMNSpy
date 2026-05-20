"""Operation cost model, gating, batch/pool, progress reporting.

Public surface today (task 3.2):

* :class:`Batch` — context manager that defers + coalesces edits on a
  :class:`~datagrove.dataset.Package`, applies them atomically through a
  single :class:`~datagrove.editing.Session`, and validates once on
  clean commit.
* :func:`coalesce` — pure helper that merges compatible same-table
  edits. Tested in isolation so :mod:`gmnspy.clean` domain ops can reuse
  it when composing higher-level batches.

Cost-model + progress-bar surfaces land in tasks 3.6 / 3.7 / 3.8.
"""

from .pool import Batch, BatchValidationError, coalesce

__all__ = ["Batch", "BatchValidationError", "coalesce"]
