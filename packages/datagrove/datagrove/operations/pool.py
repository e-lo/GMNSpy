r"""Batch / pool context manager — defer + coalesce :class:`Edit`\ s on a :class:`Package`.

Architecture §6.5: ``with package.batch(): ...`` queues edits, coalesces
compatible ones, applies them through a single
:class:`~datagrove.editing.Session`, and validates once on clean
commit. Atomic on exception: when the ``with`` body raises, the queue
is discarded without ever opening a Session (state is therefore
unchanged).

Coalescing rules (per task spec):

* Consecutive ``add_rows`` on the same table merge into one with
  concatenated ``rows``. A non-``add_rows`` edit in between BREAKS the
  streak so predicates see the right row count.
* ``replace_table`` on table X discards every pending edit on X queued
  earlier — those writes would just be overwritten.
* ``update_rows`` / ``delete_rows`` are left untouched (their
  predicates depend on the live table state at apply time).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from datagrove.editing import Edit, Session
from datagrove.reports import Severity

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path
    from types import TracebackType

    from datagrove.dataset.package import Package

logger = logging.getLogger(__name__)


__all__ = ["Batch", "BatchValidationError", "coalesce"]


def coalesce(edits: list[Edit]) -> list[Edit]:
    """Merge compatible same-table edits, preserving original order otherwise.

    See module docstring for the full rule list.

    Args:
        edits: The pending queue, in insertion order.

    Returns:
        A new list with coalesced edits in the original relative order.

    Examples:
        >>> from datagrove.editing import Edit
        >>> from datagrove.operations import coalesce
        >>> a = Edit(op="add_rows", table="t", payload={"rows": [{"id": 1}]})
        >>> b = Edit(op="add_rows", table="t", payload={"rows": [{"id": 2}]})
        >>> out = coalesce([a, b])
        >>> len(out), out[0].payload["rows"]
        (1, [{'id': 1}, {'id': 2}])
    """
    # Pass 1: replace_table cancels prior pending edits on the same table.
    pruned: list[Edit] = []
    for edit in edits:
        if edit.op == "replace_table":
            pruned = [prior for prior in pruned if prior.table != edit.table]
        pruned.append(edit)

    # Pass 2: collapse consecutive same-table add_rows into the most
    # recent entry. Anything else breaks the streak.
    out: list[Edit] = []
    for edit in pruned:
        if edit.op == "add_rows" and out and out[-1].op == "add_rows" and out[-1].table == edit.table:
            prev = out[-1]
            merged_rows = list(prev.payload.get("rows", [])) + list(edit.payload.get("rows", []))
            out[-1] = Edit(
                op="add_rows",
                table=prev.table,
                payload={**prev.payload, "rows": merged_rows},
                metadata=prev.metadata,
            )
        else:
            out.append(edit)
    return out


class _BatchCommit:
    """Snapshot of one commit: the Session + applied results + validation report."""

    __slots__ = ("results", "session", "validation")

    def __init__(self, session: Session, results: list[Any], validation: Any) -> None:
        self.session = session
        self.results = results
        self.validation = validation


class BatchValidationError(Exception):
    """Raised on commit when ``strict=True`` and validation surfaced ERROR issues.

    By the time this raises the batch's Session has been rolled back, so
    package state is restored to its pre-batch snapshot.
    """


class Batch:
    r"""Defer + coalesce :class:`Edit`\ s on a :class:`Package` (architecture §6.5).

    :meth:`add_edit` only **queues** edits — nothing is applied until
    ``__exit__`` (or an explicit :meth:`flush`). On clean exit the queue
    is coalesced via :func:`coalesce`, applied atomically through a
    single :class:`~datagrove.editing.Session`, then validated once. On
    exception, the queue is discarded **without ever opening a
    Session**, so package state is guaranteed unchanged.

    Args:
        package: The :class:`~datagrove.dataset.Package` to mutate.
        log_path: Optional sidecar path forwarded to the underlying
            :class:`Session` (rollback-log file).
        strict: When ``True``, an ERROR-severity issue in the post-commit
            validation report triggers a Session rollback and re-raises
            as :class:`BatchValidationError`.

    Examples:
        >>> from datagrove.dataset import Package, Table
        >>> from datagrove.editing import Edit
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> from datagrove.operations import Batch
        >>> e = PandasEngine()
        >>> pkg = Package.from_tables(
        ...     {"t": Table(name="t", expr=e.from_records([{"id": 1}]), engine=e)}
        ... )
        >>> with Batch(pkg) as b:
        ...     b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 2}]}))
        ...     b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 3}]}))
        >>> pkg["t"].count()
        3
    """

    def __init__(
        self,
        package: Package,
        *,
        log_path: Path | str | None = None,
        strict: bool = False,
    ) -> None:
        """Construct an unopened batch — open via ``with`` before queueing."""
        self.package = package
        self.log_path = log_path
        self.strict = strict
        #: Pending edits, in insertion order.
        self.pending: list[Edit] = []
        #: Snapshot of the most-recent commit; ``None`` until first flush/commit.
        self.last_result: _BatchCommit | None = None
        self._open = False

    def __enter__(self) -> Batch:
        """Open the batch for :meth:`add_edit` calls."""
        self._open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Commit on clean exit; discard the queue on exception (no Session opened)."""
        self._open = False
        if exc_type is not None:
            self.pending.clear()
            return False
        if self.pending:
            self._commit()
        return False

    def add_edit(self, edit: Edit) -> None:
        """Queue ``edit`` for application at commit time.

        Raises:
            RuntimeError: When called outside the ``with`` block.

        Examples:
            >>> from datagrove.dataset import Package, Table
            >>> from datagrove.editing import Edit
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.operations import Batch
            >>> e = PandasEngine()
            >>> pkg = Package.from_tables(
            ...     {"t": Table(name="t", expr=e.from_records([{"id": 1}]), engine=e)}
            ... )
            >>> with Batch(pkg) as b:
            ...     b.add_edit(Edit(op="add_rows", table="t", payload={"rows": [{"id": 9}]}))
            >>> pkg["t"].count()
            2
        """
        if not self._open:
            raise RuntimeError("Batch.add_edit called outside the `with` block — open the batch first.")
        self.pending.append(edit)

    def flush(self) -> _BatchCommit | None:
        """Apply the pending queue immediately (mid-block manual commit).

        Returns ``None`` when the queue is empty. Otherwise opens a
        Session, applies the coalesced edits, validates once, clears
        the queue, and stashes the result on :attr:`last_result`.
        """
        if not self.pending:
            return None
        return self._commit()

    def _commit(self) -> _BatchCommit:
        """Open Session, apply coalesced queue, validate, optionally rollback."""
        coalesced = coalesce(self.pending)
        self.pending.clear()
        session = Session(self.package, log_path=self.log_path)
        with session:
            for edit in coalesced:
                session.add_edit(edit)
        report = self.package.validate()
        commit = _BatchCommit(session=session, results=list(session.results), validation=report)
        self.last_result = commit
        if self.strict and any(issue.severity == Severity.ERROR for issue in report.issues):
            # Reverse the just-applied session so package state matches
            # the pre-commit snapshot, then raise.
            session.rollback()
            n_err = sum(1 for i in report.issues if i.severity == Severity.ERROR)
            raise BatchValidationError(
                f"Batch commit failed validation: {n_err} error(s) "
                f"in {len(report.issues)} issue(s) — batch rolled back."
            )
        return commit
