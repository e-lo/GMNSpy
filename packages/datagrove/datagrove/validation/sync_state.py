"""Sync-state model — DirtyTracker for out-of-sync awareness (task 2.6 / issue #65).

This module is the "did anything change since I last validated?" layer
of the datagrove validation framework. Other validators (schema, FK,
structural) answer "is the data valid *right now*?"; this one answers
"is the validation result I'm holding still *trustworthy*?".

The motivating bug class is v0.3's silent FK staleness: a user would
``validate(net)`` (clean), then edit a node row, then ``write(net)``,
and the on-disk file would carry the now-broken FK with no warning at
all. The :class:`DirtyTracker` closes that loop — every clean FK
validation stamps content hashes for both sides of the FK; any later
read walks the FK graph and flags every stamp whose hashes don't match
the current tables.

Public surface
--------------

- :class:`DirtyTracker` — the stateful tracker. Mutable, not
  thread-safe (matches the rest of the engine / dataset layer in v1.0).
- :class:`TableHash` — frozen value type: ``(table, content_hash,
  computed_at)``. Stored in :class:`DirtyTracker` and re-emitted on
  ``stamp_table``.
- :class:`FKStamp` — frozen value type: hashes for the source FK
  column + target FK column at validation time. Stored in
  :class:`DirtyTracker` and re-emitted on ``stamp_fk``.
- :func:`hash_table` — sha256 of a whole table's content. Used for
  table-level "did anything change?" checks.
- :func:`hash_column` — sha256 of a single column's content. Used by
  ``stamp_fk`` callers (the FK validator) so the hash represents JUST
  the FK columns — a change to an unrelated column doesn't invalidate
  the FK stamp.

Hash algorithm
--------------

Both helpers use ``pandas.util.hash_pandas_object(series, index=False)``
to obtain a row-wise hash and then sha256 the underlying bytes:

.. code-block:: python

    hashlib.sha256(
        pd.util.hash_pandas_object(series, index=False).values.tobytes()
    ).hexdigest()

Properties of this choice:

- **Values matter** — encoded via pandas' canonical dtype representation.
  Because the engine layer normalises to the same nullable dtypes
  (``Int64`` / ``Float64`` / ``string`` / ``boolean``) on
  :meth:`Engine.to_pandas`, the hash is **stable across engines**: the
  same data scanned through ibis, polars, or pandas yields the same
  hex digest.
- **Row order matters** — ``hash_pandas_object`` is order-preserving.
  A reordered table is treated as a different table; that matches the
  sync-state contract (if the row layout on disk changed, the user did
  *something* and we shouldn't pretend nothing happened). Callers that
  want order-independent comparison should sort first.
- **Column scope** — :func:`hash_column` hashes one Series; unrelated
  columns can change without invalidating the FK stamp.
- **Algorithm** — sha256 from the stdlib. Cryptographic strength is
  overkill for the use case, but the stdlib dependency keeps wheels
  small and the cost is microseconds-per-column on the Leavenworth-
  scale fixtures (sha256 of N rows runs at GB/s on modern CPUs).
  xxhash would be faster but is a third-party dep we don't otherwise
  need.

Codes emitted
-------------

============================  =====================================================
Code                          When emitted
============================  =====================================================
``sync.fk_stale``             A previously validated FK has source OR target
                              content hash that no longer matches. Severity:
                              WARNING by default, ERROR under ``strict=True``.
``sync.unverifiable``         An FK was stamped but the table is no longer in
                              ``current_tables``. Severity: WARNING by default,
                              ERROR under ``strict=True``.
============================  =====================================================

Sync state contract for downstream consumers
--------------------------------------------

The FK validator (:mod:`datagrove.validation.foreign_keys`, task 2.4)
should — after a clean per-FK pass — write a record into
``ValidationReport.metadata["_sync_state"]`` keyed on the tuple
``(source_table, source_field, target_table, target_field)`` (composite
fields joined by ``","``) with the value being a dict
``{"source_hash": ..., "target_hash": ..., "validated_at": ISO-8601}``.
:class:`DirtyTracker` consumes that convention via
:meth:`DirtyTracker.load_from_report` so the producer (FK validator)
and consumer (DirtyTracker) are decoupled. The Package layer (task 2.7)
then ties the report's FK stamps back into a long-lived DirtyTracker on
the package.

v0.3 regression
---------------

The v0.3 behaviour we're locking out: a stale FK silently passing
because there was no hash record to compare against. The
:func:`test_v03_silent_failure_regression` test pins the inverse — a
stale FK MUST surface an Issue, not silently pass.

Examples:
    >>> from datagrove.engines.pandas_engine import PandasEngine
    >>> from datagrove.validation.sync_state import DirtyTracker
    >>> e = PandasEngine()
    >>> link = e.scan({"data": [{"link_id": 1, "from_node_id": 1}]})
    >>> tracker = DirtyTracker()
    >>> stamp = tracker.stamp_table("link", link, e)
    >>> tracker.is_table_dirty("link", link, e)
    False
    >>> # Unknown tables are NOT dirty — we have no baseline to compare.
    >>> tracker.is_table_dirty("never_stamped", link, e)
    False
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

import pandas as pd

from datagrove.reports import Category, Severity, ValidationReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine, TableExpr

__all__ = [
    "DirtyTracker",
    "FKStamp",
    "TableHash",
    "hash_column",
    "hash_table",
]


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableHash:
    """Content fingerprint for one table at one point in time.

    Frozen + hashable so it can be stored in sets / dicts and carried
    alongside :class:`Issue` records without risk of mutation.

    Attributes:
        table: Logical table name (matches the Frictionless resource
            name; e.g. ``"link"``, ``"node"``).
        content_hash: Hex-encoded sha256 of the
            ``pd.util.hash_pandas_object`` output for the table. See the
            module docstring for the algorithm details.
        computed_at: Wall-clock time when the hash was computed
            (timezone-naive local time, matching ``datetime.now()``).

    Examples:
        >>> from datetime import datetime
        >>> h = TableHash(table="link", content_hash="abc123",
        ...               computed_at=datetime(2025, 1, 1))
        >>> h.table
        'link'
        >>> hash(h) == hash(h)  # frozen + hashable
        True
    """

    table: str
    content_hash: str
    computed_at: datetime


@dataclass(frozen=True)
class FKStamp:
    """Validation-time fingerprint of one FK relationship.

    Captures the content hashes of BOTH sides of a single foreign-key
    relationship at the moment the FK validator stamped them. A later
    read of the same FK is "stale" if EITHER side's current hash has
    changed.

    Composite FKs store their fields as a comma-joined string so the
    type stays trivially hashable (tuples would also work but make the
    JSON serialisation noisier).

    Attributes:
        source_table: Source table name (``"link"``).
        source_field: Source field name(s); composite FKs are joined
            with ``","`` (e.g. ``"a,b"``).
        target_table: Target table name (``"node"``).
        target_field: Target field name(s); composite-joined like
            ``source_field``.
        source_hash: Hex sha256 of the source column at validation time.
        target_hash: Hex sha256 of the target column at validation time.
        validated_at: When the stamp was recorded.

    Examples:
        >>> from datetime import datetime
        >>> stamp = FKStamp(
        ...     source_table="link", source_field="from_node_id",
        ...     target_table="node", target_field="node_id",
        ...     source_hash="aaa", target_hash="bbb",
        ...     validated_at=datetime(2025, 1, 1),
        ... )
        >>> stamp.source_table
        'link'
        >>> stamp.source_field
        'from_node_id'
    """

    source_table: str
    source_field: str
    target_table: str
    target_field: str
    source_hash: str
    target_hash: str
    validated_at: datetime


# ---------------------------------------------------------------------------
# Hash helpers — content-addressed fingerprints
# ---------------------------------------------------------------------------


def _hash_series(series: pd.Series) -> str:
    """Internal helper — sha256 hex digest of a single pandas Series.

    Routes through ``pd.util.hash_pandas_object`` to get a row-wise
    uint64 hash, then sha256 the underlying bytes for a stable hex
    digest. ``index=False`` so a reset / re-indexed Series with the
    same values produces the same hash.
    """
    # ``pd.util.hash_pandas_object`` exists at runtime but isn't typed as
    # part of the public ``pandas`` module — pin the attribute access
    # through ``getattr`` so pyright doesn't flag the call. The runtime
    # path is unchanged.
    util_mod = getattr(pd, "util")  # noqa: B009
    hash_pandas_object = util_mod.hash_pandas_object
    row_hashes = hash_pandas_object(series, index=False)
    # ``.values`` returns a numpy array; ``.tobytes()`` gives us the
    # raw uint64 bytes in canonical little-endian (numpy guarantees
    # byte order via the dtype). sha256 over those bytes is the hex
    # digest we record.
    return hashlib.sha256(row_hashes.values.tobytes()).hexdigest()


def hash_table(expr: TableExpr, engine: Engine) -> str:
    """Compute the content hash of an entire table.

    Materialises ``expr`` via :meth:`Engine.to_pandas`, then hashes the
    rows column-by-column and combines the per-column digests into a
    single stable hex digest. Column order does affect the hash (we
    hash the columns in their materialised order); this is a
    deliberate choice — a reordered schema IS a different table for
    sync-state purposes.

    Args:
        expr: An engine-native table expression (or a pre-materialised
            ``pandas.DataFrame``).
        engine: The engine that produced ``expr``. Used for the
            :meth:`Engine.to_pandas` round-trip.

    Returns:
        Hex-encoded sha256 digest of the table's content.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> e = PandasEngine()
        >>> t1 = e.scan({"data": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]})
        >>> t2 = e.scan({"data": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]})
        >>> hash_table(t1, e) == hash_table(t2, e)
        True
        >>> t3 = e.scan({"data": [{"a": 9, "b": 2}, {"a": 3, "b": 4}]})
        >>> hash_table(t1, e) == hash_table(t3, e)
        False
    """
    df = _materialise(engine, expr)
    # Hash each column independently and combine. Hashing the
    # concatenation of per-column digests gives a stable
    # column-order-aware aggregate without re-hashing the whole frame
    # (which would also work but be slightly slower on wide tables).
    parts = [f"{col}:{_hash_series(cast(pd.Series, df[col]))}" for col in df.columns]
    combined = "|".join(parts).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def hash_column(expr: TableExpr, column: str, engine: Engine) -> str:
    """Compute the content hash of a single column.

    Same algorithm as :func:`hash_table` but scoped to one Series. Used
    by FK-validator callers so each ``FKStamp`` captures JUST the FK
    columns. A change to an unrelated column doesn't invalidate the
    stamp — exactly what we want for sync-state semantics.

    For composite FKs the caller is expected to combine per-column
    hashes themselves (e.g. concatenation of two ``hash_column`` calls)
    or hash the synthetic tuple column.

    Args:
        expr: Engine-native table expression.
        column: The column to hash. Must exist in the materialised
            DataFrame; missing columns raise :class:`KeyError`.
        engine: The engine that produced ``expr``.

    Returns:
        Hex-encoded sha256 digest of the column's content.

    Raises:
        KeyError: If ``column`` is not in the materialised DataFrame.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> e = PandasEngine()
        >>> t = e.scan({"data": [{"a": 1, "b": 2}, {"a": 1, "b": 9}]})
        >>> h_a = hash_column(t, "a", e)
        >>> h_b = hash_column(t, "b", e)
        >>> h_a == h_b
        False
    """
    df = _materialise(engine, expr)
    if column not in df.columns:
        raise KeyError(f"hash_column: column {column!r} not in materialised frame; available: {list(df.columns)}")
    return _hash_series(cast(pd.Series, df[column]))


def _materialise(engine: Engine, expr: TableExpr) -> pd.DataFrame:
    """Internal — pass through DataFrames; otherwise round-trip via the engine.

    Mirrors :func:`datagrove.validation.foreign_keys._materialise` so
    callers can hand us either a pre-materialised DataFrame (the common
    case after the orchestrator pre-materialises) or an engine-native
    expression.
    """
    if isinstance(expr, pd.DataFrame):
        return expr
    return engine.to_pandas(expr)


# ---------------------------------------------------------------------------
# DirtyTracker
# ---------------------------------------------------------------------------


class DirtyTracker:
    """Records content-hash stamps for tables + FK validations.

    The answer to "has anything changed since I validated this?". Used
    by writes (warn on stale FK), interactive editing (gmnspy.clean /
    .edit surfaces), and the long-lived ``Package`` (task 2.7) so a
    ``net.write()`` call can re-check sync state before flushing.

    Lifecycle:

    1. :meth:`stamp_table` records the current content hash of a
       table. Idempotent — calling it again replaces the stamp.
    2. :meth:`stamp_fk` records a validated FK relationship; called by
       the FK validator after a clean pass. The caller provides the
       precomputed source + target column hashes so we don't
       re-materialise.
    3. :meth:`is_table_dirty` returns ``True`` iff the current table's
       content hash differs from the recorded one. Returns ``False``
       for unstamped tables (unknown != dirty).
    4. :meth:`stale_fks` returns the list of stamps whose source or
       target hash no longer matches. Consumers emit
       ``sync.fk_stale`` Issues per stale stamp.
    5. :meth:`mark_dirty` explicitly removes a stamp (use after a
       direct DataFrame mutation that bypassed the engine).
    6. :meth:`check` is the convenience method: walks the FK stamps,
       compares against ``current_tables``, returns a populated
       :class:`ValidationReport`.

    Thread safety: NOT thread-safe. Consistent with the rest of the
    engine / dataset layer in v1.0. Concurrent edit + validate flows
    should fence with an external lock.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> e = PandasEngine()
        >>> link = e.scan({"data": [{"link_id": 1, "from_node_id": 1}]})
        >>> node = e.scan({"data": [{"node_id": 1}]})
        >>> tracker = DirtyTracker()
        >>> _ = tracker.stamp_table("link", link, e)
        >>> _ = tracker.stamp_table("node", node, e)
        >>> tracker.stamp_fk_from_exprs(
        ...     "link", "from_node_id", link,
        ...     "node", "node_id", node,
        ...     engine=e,
        ... ).source_table
        'link'
        >>> # Nothing has changed — no stale FKs.
        >>> tracker.stale_fks({"link": link, "node": node}, e)
        []
    """

    def __init__(self) -> None:
        """Construct an empty tracker — no table stamps, no FK stamps."""
        self._tables: dict[str, TableHash] = {}
        self._fks: list[FKStamp] = []

    # ------------------------------------------------------------------
    # Table stamps
    # ------------------------------------------------------------------

    def stamp_table(self, name: str, expr: TableExpr, engine: Engine) -> TableHash:
        """Record (or replace) the current content hash for a table.

        Idempotent — calling twice on the same name replaces the prior
        stamp. The previous stamp is dropped; only the most recent
        survives.

        Args:
            name: Logical table name (matches the Resource name).
            expr: Current engine-native expression for that table.
            engine: The engine that produced ``expr``.

        Returns:
            The newly recorded :class:`TableHash`.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> t = e.scan({"data": [{"a": 1}]})
            >>> tracker = DirtyTracker()
            >>> stamp = tracker.stamp_table("t", t, e)
            >>> stamp.table
            't'
        """
        content_hash = hash_table(expr, engine)
        stamp = TableHash(table=name, content_hash=content_hash, computed_at=datetime.now())
        self._tables[name] = stamp
        return stamp

    def get_table_stamp(self, name: str) -> TableHash | None:
        """Return the most recent stamp for ``name``, or ``None`` if unstamped.

        Args:
            name: Logical table name.

        Examples:
            >>> tracker = DirtyTracker()
            >>> tracker.get_table_stamp("never_stamped") is None
            True
        """
        return self._tables.get(name)

    def is_table_dirty(self, name: str, expr: TableExpr, engine: Engine) -> bool:
        """Return ``True`` iff the current content hash differs from the stamp.

        Returns ``False`` for unstamped tables — "unknown" is not the
        same as "dirty", because we have no baseline to compare
        against. Callers that want to treat unknown as dirty should
        check :meth:`get_table_stamp` first.

        Args:
            name: Logical table name.
            expr: Current expression to check.
            engine: The engine that produced ``expr``.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> t = e.scan({"data": [{"a": 1}]})
            >>> tracker = DirtyTracker()
            >>> tracker.is_table_dirty("t", t, e)  # never stamped
            False
            >>> _ = tracker.stamp_table("t", t, e)
            >>> tracker.is_table_dirty("t", t, e)
            False
        """
        stamp = self._tables.get(name)
        if stamp is None:
            return False
        return hash_table(expr, engine) != stamp.content_hash

    def mark_dirty(self, name: str) -> None:
        """Explicitly drop the stamp for ``name``.

        Use this after a direct DataFrame mutation that bypassed the
        engine — the recorded hash no longer represents the live data,
        and dropping it is safer than leaving a stale stamp in place
        (a future :meth:`is_table_dirty` would return ``False`` because
        the stale hash happens to still match the no-longer-current
        expression you stamped earlier).

        After ``mark_dirty``, ``is_table_dirty`` returns ``False`` for
        the same reason it does for any unstamped table — there's no
        baseline. The intent is "force the user to re-validate", and
        the next validation pass will re-stamp the table fresh.

        Args:
            name: Logical table name. Silent no-op if unstamped.

        Examples:
            >>> tracker = DirtyTracker()
            >>> tracker.mark_dirty("never_stamped")  # no-op
            >>> tracker.get_table_stamp("never_stamped") is None
            True
        """
        self._tables.pop(name, None)

    def known_tables(self) -> list[str]:
        """Return the names of all currently stamped tables.

        Useful for introspection — what does the tracker know about?

        Examples:
            >>> tracker = DirtyTracker()
            >>> tracker.known_tables()
            []
        """
        return list(self._tables.keys())

    # ------------------------------------------------------------------
    # FK stamps
    # ------------------------------------------------------------------

    def stamp_fk(
        self,
        source_table: str,
        source_field: str,
        target_table: str,
        target_field: str,
        *,
        source_hash: str,
        target_hash: str,
    ) -> FKStamp:
        """Record an FK validation, given precomputed column hashes.

        The hashes are supplied by the caller — typically the FK
        validator, which has already materialised both sides at
        validation time and computed the per-column digest as part of
        that pass. This avoids a second materialisation round-trip and
        keeps the FK validator's dependency on this module one-way
        (it imports ``hash_column``; we don't import the validator).

        Composite FKs join their field names with ``","`` (e.g.
        ``"a,b"``) so :class:`FKStamp` stays trivially hashable.

        Args:
            source_table: Source table name (``"link"``).
            source_field: Source field name, or comma-joined for
                composite FKs.
            target_table: Target table name (``"node"``).
            target_field: Target field name, or comma-joined.
            source_hash: Hex sha256 of the source column at validation
                time. Compute via :func:`hash_column` (or your own
                equivalent — we just store the string).
            target_hash: Hex sha256 of the target column at validation
                time.

        Returns:
            The newly recorded :class:`FKStamp`.

        Examples:
            >>> tracker = DirtyTracker()
            >>> stamp = tracker.stamp_fk(
            ...     "link", "from_node_id", "node", "node_id",
            ...     source_hash="abc", target_hash="def",
            ... )
            >>> stamp.source_hash
            'abc'
        """
        stamp = FKStamp(
            source_table=source_table,
            source_field=source_field,
            target_table=target_table,
            target_field=target_field,
            source_hash=source_hash,
            target_hash=target_hash,
            validated_at=datetime.now(),
        )
        self._fks.append(stamp)
        return stamp

    def stamp_fk_from_exprs(
        self,
        source_table: str,
        source_field: str,
        source_expr: TableExpr,
        target_table: str,
        target_field: str,
        target_expr: TableExpr,
        *,
        engine: Engine,
    ) -> FKStamp:
        """Convenience — stamp an FK by computing hashes from expressions.

        Equivalent to calling :func:`hash_column` on each side and
        forwarding the results to :meth:`stamp_fk`, but in one call so
        callers that don't have the hashes already don't need to repeat
        the boilerplate. Less efficient when the validator has already
        materialised — prefer :meth:`stamp_fk` in that case.

        Only handles single-field FKs (the column-scoped hash is one
        Series). Composite FKs should call :meth:`stamp_fk` directly
        with a precomputed combined hash.

        Args:
            source_table: Source table name.
            source_field: Source field name (single field only).
            source_expr: Source expression.
            target_table: Target table name.
            target_field: Target field name (single field only).
            target_expr: Target expression.
            engine: The engine that produced both expressions.

        Returns:
            The newly recorded :class:`FKStamp`.
        """
        src_hash = hash_column(source_expr, source_field, engine)
        tgt_hash = hash_column(target_expr, target_field, engine)
        return self.stamp_fk(
            source_table,
            source_field,
            target_table,
            target_field,
            source_hash=src_hash,
            target_hash=tgt_hash,
        )

    def stale_fks(
        self,
        current_tables: dict[str, TableExpr],
        engine: Engine,
    ) -> list[FKStamp]:
        """Return every FK stamp whose source or target hash no longer matches.

        Walks the recorded :class:`FKStamp` list, materialises each
        referenced column from ``current_tables``, recomputes the hash,
        and returns the stamps where either side has drifted. Stamps
        for tables that are no longer in ``current_tables`` are also
        returned (they're "unverifiable" — see :meth:`check` for
        Issue emission).

        Composite FKs (with comma-joined field names) are handled by
        hashing the joint column set as a single concatenated digest;
        this matches the column-set-aware semantics described in the
        module docstring.

        Args:
            current_tables: Current mapping of ``{name: TableExpr}``.
            engine: The engine that produced the expressions.

        Returns:
            List of :class:`FKStamp` records whose state has drifted.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> link = e.scan({"data": [{"link_id": 1, "from_node_id": 1}]})
            >>> node = e.scan({"data": [{"node_id": 1}]})
            >>> tracker = DirtyTracker()
            >>> _ = tracker.stamp_fk_from_exprs(
            ...     "link", "from_node_id", link,
            ...     "node", "node_id", node,
            ...     engine=e,
            ... )
            >>> tracker.stale_fks({"link": link, "node": node}, e)
            []
        """
        stale: list[FKStamp] = []
        # Cache materialised frames so a package with many FKs against
        # the same table only pays the conversion cost once.
        cache: dict[str, pd.DataFrame] = {}

        def _frame(name: str) -> pd.DataFrame | None:
            if name in cache:
                return cache[name]
            expr = current_tables.get(name)
            if expr is None:
                return None
            cache[name] = _materialise(engine, expr)
            return cache[name]

        for stamp in self._fks:
            src_df = _frame(stamp.source_table)
            tgt_df = _frame(stamp.target_table)
            if src_df is None or tgt_df is None:
                # Unverifiable — table dropped. Surface as stale; the
                # downstream Issue emitter (:meth:`check`) differentiates
                # via the missing-table check.
                stale.append(stamp)
                continue
            try:
                current_src = _column_hash_from_df(src_df, stamp.source_field)
                current_tgt = _column_hash_from_df(tgt_df, stamp.target_field)
            except KeyError:
                # A column the stamp references no longer exists — that's
                # functionally the same as the table being gone.
                stale.append(stamp)
                continue
            if current_src != stamp.source_hash or current_tgt != stamp.target_hash:
                stale.append(stamp)
        return stale

    def clear_fk_stamps(self) -> None:
        """Drop every recorded FK stamp.

        Useful when a caller wants to re-run FK validation from
        scratch (the next clean pass re-stamps).

        Examples:
            >>> tracker = DirtyTracker()
            >>> _ = tracker.stamp_fk("a", "x", "b", "y",
            ...                       source_hash="s", target_hash="t")
            >>> tracker.clear_fk_stamps()
            >>> tracker.stale_fks({}, engine=None)  # doctest: +SKIP
            []
        """
        self._fks.clear()

    # ------------------------------------------------------------------
    # Report emission
    # ------------------------------------------------------------------

    def check(
        self,
        current_tables: dict[str, TableExpr],
        *,
        engine: Engine,
        report: ValidationReport | None = None,
        strict: bool = False,
    ) -> ValidationReport:
        """Run staleness checks; populate a :class:`ValidationReport`.

        For every recorded :class:`FKStamp` whose source or target hash
        no longer matches the current data, emits either
        ``sync.fk_stale`` (data drifted) or ``sync.unverifiable``
        (table dropped from ``current_tables``). Severity is
        ``WARNING`` by default and ``ERROR`` under ``strict=True``.

        The report is mutated in place (or created if ``None``) and
        returned. Existing issues are preserved — this method only
        appends.

        Args:
            current_tables: Current mapping of ``{name: TableExpr}``.
            engine: The engine that produced the expressions.
            report: Existing report to append into. Created when
                ``None``; returned in either case.
            strict: When ``True``, sync-state issues are ``ERROR``
                instead of ``WARNING``.

        Returns:
            The :class:`ValidationReport` — the same instance as
            ``report`` if one was passed.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> link = e.scan({"data": [{"link_id": 1, "from_node_id": 1}]})
            >>> node = e.scan({"data": [{"node_id": 1}]})
            >>> tracker = DirtyTracker()
            >>> _ = tracker.stamp_fk_from_exprs(
            ...     "link", "from_node_id", link,
            ...     "node", "node_id", node,
            ...     engine=e,
            ... )
            >>> r = tracker.check({"link": link, "node": node}, engine=e)
            >>> r.is_clean
            True
        """
        if report is None:
            report = ValidationReport()
        severity = Severity.ERROR if strict else Severity.WARNING
        fix_hint = "Run validate() to refresh, or pass strict=False to skip this check."

        for stamp in self._fks:
            src_label = f"{stamp.source_table}.{stamp.source_field}"
            tgt_label = f"{stamp.target_table}.{stamp.target_field}"
            fk_label = f"FK {src_label} -> {tgt_label}"

            # Unverifiable — source or target table missing entirely.
            if stamp.source_table not in current_tables:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.unverifiable",
                    message=(
                        f"{fk_label}: source table {stamp.source_table!r} is no longer present; cannot verify staleness"
                    ),
                    table=stamp.source_table,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                    },
                )
                continue
            if stamp.target_table not in current_tables:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.unverifiable",
                    message=(
                        f"{fk_label}: target table {stamp.target_table!r} is no longer present; cannot verify staleness"
                    ),
                    table=stamp.source_table,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                    },
                )
                continue

            # Both tables present — recompute hashes.
            src_df = _materialise(engine, current_tables[stamp.source_table])
            tgt_df = _materialise(engine, current_tables[stamp.target_table])

            try:
                current_src = _column_hash_from_df(src_df, stamp.source_field)
            except KeyError:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.unverifiable",
                    message=(
                        f"{fk_label}: source column {stamp.source_field!r} is no longer present "
                        f"in {stamp.source_table!r}; cannot verify staleness"
                    ),
                    table=stamp.source_table,
                    column=stamp.source_field,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                    },
                )
                continue
            try:
                current_tgt = _column_hash_from_df(tgt_df, stamp.target_field)
            except KeyError:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.unverifiable",
                    message=(
                        f"{fk_label}: target column {stamp.target_field!r} is no longer present "
                        f"in {stamp.target_table!r}; cannot verify staleness"
                    ),
                    table=stamp.source_table,
                    column=stamp.source_field,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                    },
                )
                continue

            src_changed = current_src != stamp.source_hash
            tgt_changed = current_tgt != stamp.target_hash
            if not (src_changed or tgt_changed):
                continue

            if src_changed:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.fk_stale",
                    message=(
                        f"{fk_label}: source table {stamp.source_table!r} has changed since "
                        f"validation; re-run validate() to confirm"
                    ),
                    table=stamp.source_table,
                    column=stamp.source_field,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                        "side": "source",
                    },
                )
            if tgt_changed:
                report.add(
                    severity=severity,
                    category=Category.SYNC_STATE,
                    code="sync.fk_stale",
                    message=(
                        f"{fk_label}: target table {stamp.target_table!r} has changed since "
                        f"validation; re-run validate() to confirm"
                    ),
                    table=stamp.source_table,
                    column=stamp.source_field,
                    fix_hint=fix_hint,
                    extra={
                        "target_table": stamp.target_table,
                        "target_field": stamp.target_field,
                        "source_field": stamp.source_field,
                        "side": "target",
                    },
                )
        return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _column_hash_from_df(df: pd.DataFrame, field_spec: str) -> str:
    """Hash a (possibly composite) column spec against an already-materialised frame.

    ``field_spec`` is either a single column name or a comma-joined
    list (the same convention :class:`FKStamp` stores). For the
    composite case we hash each column independently and combine —
    matching :func:`hash_table`'s combine step — so the result is
    column-order aware and any single-column drift invalidates the
    stamp.
    """
    fields = [f.strip() for f in field_spec.split(",")] if "," in field_spec else [field_spec]
    if len(fields) == 1:
        column = fields[0]
        if column not in df.columns:
            raise KeyError(column)
        return _hash_series(cast(pd.Series, df[column]))
    # Composite — hash each field and combine.
    parts: list[str] = []
    for column in fields:
        if column not in df.columns:
            raise KeyError(column)
        parts.append(f"{column}:{_hash_series(cast(pd.Series, df[column]))}")
    combined = "|".join(parts).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()
