r"""Session — atomic batch of :class:`Edit`\ s with a chronological rollback log.

Architecture §6.4: ``Session`` brackets a chain of edits applied to one
:class:`~datagrove.dataset.Package`, atomic on exception, persisting
its rollback log to a parquet sidecar on clean commit.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

from .apply import apply_edit, reverse_edit
from .errors import EditingError
from .types import Edit, EditResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from types import TracebackType

    from datagrove.dataset.package import Package


logger = logging.getLogger(__name__)


__all__ = ["Session"]


class Session:
    r"""Atomic batch of :class:`Edit`\ s with chronological rollback log.

    Inside the ``with`` block, :meth:`add_edit` applies each
    :class:`Edit` immediately and appends its :class:`EditResult` to
    the in-memory log; the package's :class:`DirtyTracker` (when
    attached) is notified on every apply. On exception, every applied
    edit is reversed in LIFO order before the exception propagates
    (atomicity); on clean exit, the log is persisted to ``log_path``
    (when set) so :func:`datagrove.editing.rollback` can replay later.

    Args:
        package: The :class:`~datagrove.dataset.Package` to mutate.
        log_path: Optional sidecar parquet path. ``None`` keeps the
            log in memory only.
        session_id: Optional explicit session id; default is a uuid4.

    Examples:
        >>> import tempfile, pathlib
        >>> from datagrove.dataset import Package, Table
        >>> from datagrove.editing import Edit, Session
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> e = PandasEngine()
        >>> pkg = Package.from_tables({"x": Table(name="x", expr=e.from_records([{"a": 1}]), engine=e)})
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     log = pathlib.Path(tmp) / "history.parquet"
        ...     with Session(pkg, log_path=log) as s:
        ...         _ = s.add_edit(Edit(op="add_rows", table="x",
        ...                             payload={"rows": [{"a": 2}, {"a": 3}]}))
        ...     pkg["x"].count(), log.exists()
        (3, True)
    """

    def __init__(
        self,
        package: Package,
        *,
        log_path: Path | str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Construct an unopened session — call :meth:`__enter__` (or use ``with``) before edits."""
        self.package = package
        self.log_path: Path | None = Path(log_path) if log_path is not None else None
        self.session_id = session_id or f"sess-{uuid.uuid4().hex[:12]}"
        self.results: list[EditResult] = []
        self._open = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Session:
        """Open the session for :meth:`add_edit` calls."""
        self._open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Commit (persist log) on clean exit; reverse every applied edit on exception."""
        self._open = False
        if exc_type is not None:
            for result in reversed(self.results):
                try:
                    reverse_edit(self.package, result)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("session rollback failed on %s/%s", result.edit.table, result.edit.op)
            return False
        if self.log_path is not None and self.results:
            self._persist_log(self.log_path)
        return False

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def add_edit(self, edit: Edit) -> EditResult:
        """Apply ``edit`` immediately, stamp with ``session_id``, append to the log.

        Raises :class:`EditingError` if called outside the ``with`` block.

        Examples:
            >>> from datagrove.dataset import Package, Table
            >>> from datagrove.editing import Edit, Session
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> pkg = Package.from_tables({"x": Table(name="x", expr=e.from_records([{"a": 1}]), engine=e)})
            >>> with Session(pkg) as s:
            ...     r = s.add_edit(Edit(op="add_rows", table="x", payload={"rows": [{"a": 9}]}))
            >>> r.diff.rows_added
            1
        """
        if not self._open:
            raise EditingError("Session.add_edit called outside the `with` block — open the session first.")
        result = apply_edit(self.package, edit, session_id=self.session_id)
        self.results.append(result)
        return result

    def rollback(self) -> None:
        """Reverse every edit applied in this session in LIFO order (without raising)."""
        for result in reversed(self.results):
            reverse_edit(self.package, result)
        self.results.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_log(self, log_path: Path) -> None:
        """Write the rollback log to ``log_path`` as a single parquet file."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        records = [_serialize_result(idx, r) for idx, r in enumerate(self.results)]
        pq.write_table(pa.Table.from_pylist(records), log_path)
        logger.debug("session %s wrote %d edits to %s", self.session_id, len(self.results), log_path)


# ---------------------------------------------------------------------------
# Log serialisation helpers — internal per §9
# ---------------------------------------------------------------------------


def _serialize_result(index: int, result: EditResult) -> dict[str, Any]:
    """Flatten an :class:`EditResult` into a parquet-safe row dict (JSON-encoded blobs)."""
    return {
        "session_id": result.session_id or "",
        "edit_index": index,
        "op": result.edit.op,
        "table": result.edit.table,
        "payload_json": _safe_json(result.edit.payload),
        "metadata_json": _safe_json(result.edit.metadata),
        "rollback_json": _safe_json(result.rollback_data),
        "rows_added": result.diff.rows_added,
        "rows_removed": result.diff.rows_removed,
        "rows_changed": result.diff.rows_changed,
        "applied_at": result.applied_at.isoformat(),
    }


def _safe_json(obj: Any) -> str:
    """JSON-encode ``obj``, falling back to ``str()`` placeholders for non-serialisable parts."""

    def _default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if callable(value):
            return f"<callable {getattr(value, '__name__', 'anon')}>"
        return f"<unserialisable {type(value).__name__}>"

    try:
        return json.dumps(obj, default=_default)
    except Exception:  # pragma: no cover - defensive
        return json.dumps({"_error": "serialisation failed", "_type": type(obj).__name__})
