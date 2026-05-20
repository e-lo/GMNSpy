"""Value types for the editing framework — Edit, Diff, EditResult.

Generic — no domain semantics (no ``links``/``simplify_geometry``;
those live in ``gmnspy.clean`` in Phase 3). The four supported ops
(``add_rows`` / ``update_rows`` / ``delete_rows`` / ``replace_table``)
are interpreted by :mod:`datagrove.editing.apply`; the value types
here just carry the request + the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = ["Diff", "Edit", "EditResult"]


#: Per-Diff sample cap. Bounded so a full-table replace doesn't pull
#: a million rows into Python just to show what changed.
SAMPLE_CAP = 50


@dataclass(frozen=True)
class Edit:
    """One atomic mutation against one table — domain-free.

    Supported ops + their ``payload`` shapes:

    * ``"add_rows"`` — ``{"rows": [{...}, {...}]}``
    * ``"update_rows"`` — ``{"predicate": <ibis predicate>, "set": {col: value}}``
    * ``"delete_rows"`` — ``{"predicate": <ibis predicate>}``
    * ``"replace_table"`` — ``{"expr": <engine TableExpr>}``

    Attributes:
        op: One of the four op names above. Unknown ops raise
            :class:`~datagrove.editing.errors.UnsupportedEditOp` at
            apply time.
        table: Logical table name (matches
            :attr:`datagrove.dataset.Table.name`).
        payload: Op-specific arguments — see above.
        metadata: Free-form bag carried into the rollback log.

    Examples:
        >>> from datagrove.editing import Edit
        >>> e = Edit(op="add_rows", table="link", payload={"rows": [{"link_id": 99}]})
        >>> e.op, e.table
        ('add_rows', 'link')
    """

    op: str
    table: str
    payload: dict = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Diff:
    """Before/after delta produced by applying one :class:`Edit`.

    The sample lists are bounded at :data:`SAMPLE_CAP` rows (the apply
    pipeline enforces the cap). Row counts are net.

    Attributes:
        edit: The :class:`Edit` that produced this Diff.
        rows_added / rows_removed / rows_changed: Net counts.
        before_sample / after_sample: Up to :data:`SAMPLE_CAP` rows;
            ``None`` when no sample was captured.

    Examples:
        >>> from datagrove.editing import Diff, Edit
        >>> d = Diff(edit=Edit(op="add_rows", table="x", payload={"rows": [{}]}),
        ...          rows_added=1, rows_removed=0, rows_changed=0)
        >>> d.rows_added
        1
    """

    edit: Edit
    rows_added: int
    rows_removed: int
    rows_changed: int
    before_sample: list[dict] | None = None
    after_sample: list[dict] | None = None


@dataclass
class EditResult:
    """The outcome of one :class:`Edit` + how to roll it back.

    Mutable so the owning :class:`~datagrove.editing.session.Session`
    can stamp ``session_id`` after construction. ``rollback_data`` is
    opaque per-op (callers pass it to :func:`datagrove.editing.rollback`
    rather than interpreting it directly).

    Attributes:
        edit / diff: Inputs and outputs of the apply.
        rollback_data: Op-specific blob the reverse handler consumes.
        applied_at: Wall-clock time the edit landed.
        session_id: Owning :class:`Session`'s id (``None`` for
            standalone applies).

    Examples:
        >>> from datetime import datetime
        >>> from datagrove.editing import Diff, Edit, EditResult
        >>> e = Edit(op="add_rows", table="x", payload={"rows": [{}]})
        >>> r = EditResult(
        ...     edit=e,
        ...     diff=Diff(edit=e, rows_added=1, rows_removed=0, rows_changed=0),
        ...     rollback_data=None,
        ...     applied_at=datetime(2026, 1, 1),
        ... )
        >>> r.diff.rows_added
        1
    """

    edit: Edit
    diff: Diff
    rollback_data: Any
    applied_at: datetime
    session_id: str | None = None
