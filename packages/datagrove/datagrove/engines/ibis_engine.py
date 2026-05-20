"""Ibis (duckdb-backed) execution engine — the default engine for datagrove.

This is the **only** module in the codebase permitted to embed raw SQL
strings; ``scripts/lint_no_sql.py`` allowlists this file. All other
modules must use ibis expressions (or call into this engine) to talk to
data. In practice the implementation below sticks to ibis-level
expressions and the backend's structured APIs (``create_table``,
``read_csv``, ``to_parquet``); the allowlist exists so that a deliberate
escape hatch is available if one is ever needed.

Default backend
---------------

``IbisEngine()`` constructs a fresh in-memory duckdb connection. Pass a
pre-opened backend (``IbisEngine(con=ibis.duckdb.connect("net.duckdb"))``)
to point at a file or share a connection. The engine owns one duckdb
connection for its lifetime; call ``close()`` to release it.

Dispatch model (post-issue-#134 inversion)
------------------------------------------

The engine exposes **per-format primitives** (``read_csv``,
``read_parquet``, ``read_duckdb_table``, ``from_records`` + the
matching ``write_*``). Adapters in :mod:`datagrove.io` call these
primitives directly. :meth:`scan` and :meth:`write` are thin
convenience methods that route format dispatch through
``datagrove.io.dispatch`` / ``datagrove.io.get_adapter`` — no per-format
if/elif lives in this module anymore.

The single carve-out in :meth:`scan` is dict sources: the dispatcher
can't sniff a ``{"data": ...}`` or ``{"format": "duckdb", ...}`` dict,
so :meth:`scan` short-circuits those two shapes and calls
:meth:`from_records` / :meth:`read_duckdb_table` directly before
handing the rest off to ``dispatch``.
"""

from __future__ import annotations

import contextlib
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ibis
from ibis.backends import BaseBackend
from ibis.expr import types as ir

from datagrove.types import SourceRef

from .errors import (
    EngineNotAvailableError,
    InvalidEngineCallError,
    UnsupportedSourceError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import polars as pl
    import pyarrow as pa

    from datagrove.spec.model import Schema


# ---------------------------------------------------------------------------
# Frictionless → ibis dtype map
# ---------------------------------------------------------------------------
# Inlined here rather than imported from a defaults module: the map is
# short, only used in one place, and reading it inline is the fastest
# way for a future reviewer to understand what the cast does. (See
# `gmnspy-review` SKILL §Lens C — "inline literals".)
#
# Anything not in this map is left at whatever type the CSV/parquet
# reader inferred. We deliberately do not cast to ibis ``date``/
# ``time``/``timestamp`` from Frictionless ``date``/``time``/``datetime``
# at scan time — those need format strings to be safe, which Frictionless
# carries on the field's ``format`` attribute; honouring them is a
# validation-layer concern (task 1.12+) not a scan-time concern.
#
# Note: Frictionless ``any`` is intentionally absent. GMNS schemas use
# ``any`` for fields like ``link_id`` that could be ints or strings;
# overriding the reader's inferred type with ``string`` would force
# numeric IDs into strings, which is the opposite of helpful. Leaving
# ``any`` columns untouched preserves the file's natural typing.
_FRICTIONLESS_TO_IBIS: dict[str, str] = {
    "integer": "int64",
    "number": "float64",
    "boolean": "boolean",
    "string": "string",
}


# ---------------------------------------------------------------------------
# IbisEngine
# ---------------------------------------------------------------------------


class IbisEngine:
    """Ibis engine adapter, backed by duckdb.

    Default-engine, lazy-by-default, no-raw-SQL implementation of the
    :class:`~datagrove.engines.Engine` protocol.

    Args:
        con: An existing ``ibis`` backend (typically a duckdb one) to
            adopt. When ``None`` the engine creates a fresh in-memory
            duckdb connection. The engine owns the connection's
            lifetime when it created it; if you pass one in, you own
            it.

    Attributes:
        name: Always ``"ibis"`` — used as the registry key.
        con: The underlying ibis backend. Most code should not touch
            this directly; it is exposed for tests and the rare power
            user who needs duckdb-specific extensions.

    Examples:
        Default in-memory connection:

        >>> from datagrove.engines.ibis_engine import IbisEngine
        >>> engine = IbisEngine()
        >>> engine.name
        'ibis'
        >>> engine.con is not None
        True
        >>> engine.close()
    """

    name: str = "ibis"

    def __init__(self, *, con: BaseBackend | None = None) -> None:
        """Construct an engine; create an in-memory duckdb backend if needed.

        See class docstring for the ``con`` argument's semantics and
        examples.
        """
        # We track whether we created the backend ourselves so close()
        # only disconnects what we own. A caller who passed in their own
        # con keeps responsibility for it.
        if con is None:
            self.con: BaseBackend = ibis.duckdb.connect(":memory:")
            self._owns_con = True
        else:
            self.con = con
            self._owns_con = False

    # ------------------------------------------------------------------
    # Read primitives — adapters call these directly
    # ------------------------------------------------------------------

    def read_csv(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> ir.Table:
        """Read a CSV file via duckdb's ``read_csv`` (no SQL).

        Args:
            source: Path / URL / ``Path``. ``http(s)://`` and ``s3://``
                are passed through to duckdb's httpfs/s3 extensions.
            schema: Optional Frictionless schema; columns are cast after
                read via :meth:`cast_schema`.
            **kwargs: Forwarded verbatim to
                :meth:`ibis.backends.duckdb.Backend.read_csv` (``delim``,
                ``header``, ``columns``, ...).

        Returns:
            A lazy ``ibis.expr.types.Table`` over the file.

        Examples:
            >>> import tempfile, pathlib
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.csv"
            >>> _ = p.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> e = IbisEngine()
            >>> e.read_csv(p).count().to_pyarrow().as_py()
            2
            >>> e.close()
        """
        path = _as_path_str(source)
        table = self.con.read_csv(path, **kwargs)
        return self.cast_schema(table, schema) if schema is not None else table

    def read_parquet(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        *,
        hive_partitioning: bool = False,
        **kwargs: Any,
    ) -> ir.Table:
        """Read parquet (single file or Hive-partitioned directory).

        Hive-partitioning is auto-detected for directory sources when
        the adapter doesn't say otherwise: a directory + no caller
        override turns ``hive_partitioning=True`` on so duckdb reinjects
        the partition columns into the result. The caller's explicit
        flag wins either way.

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            schema: Optional Frictionless schema.
            hive_partitioning: Enable Hive-style partition discovery.
                Auto-enabled for directory sources unless explicitly set.
            **kwargs: Forwarded to duckdb's ``read_parquet``.

        Returns:
            A lazy ``ibis.expr.types.Table``.
        """
        path = _as_path_str(source)
        # Auto-enable hive partitioning for directory sources (the
        # adapter forwards the path verbatim and asks engines to handle
        # partitioning natively — I3).
        if not hive_partitioning and Path(path).is_dir():
            hive_partitioning = True
        if hive_partitioning:
            kwargs = {"hive_partitioning": True, **kwargs}
        table = self.con.read_parquet(path, **kwargs)
        return self.cast_schema(table, schema) if schema is not None else table

    def read_duckdb_table(
        self,
        source: SourceRef,
        *,
        table: str,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> ir.Table:
        """Read one named table out of a duckdb file.

        Opens a fresh ibis duckdb backend pointed at the file and
        returns the named table as an ibis expression. ``kwargs`` are
        accepted for protocol symmetry but currently unused — duckdb's
        relation API takes no per-read options for catalogue reads.

        Args:
            source: Path / URL to a ``.duckdb`` file. ``str`` / ``Path``
                are both accepted.
            table: The table name (required).
            schema: Optional Frictionless schema.
            **kwargs: Reserved for future use.

        Returns:
            A lazy ``ibis.expr.types.Table``.

        Raises:
            InvalidEngineCallError: If ``table`` is empty.
        """
        del kwargs  # reserved for future backend-specific options
        if not table:
            raise InvalidEngineCallError("ibis engine: read_duckdb_table requires a non-empty table= argument")
        backend = ibis.duckdb.connect(_as_path_str(source))
        expr = backend.table(table)
        return self.cast_schema(expr, schema) if schema is not None else expr

    def from_records(
        self,
        records: list[dict[str, Any]] | dict[str, list[Any]],
        schema: Schema | None = None,
    ) -> ir.Table:
        """Materialize in-memory records as a duckdb temp table.

        Accepts the two shapes :class:`pandas.DataFrame` accepts (list
        of row dicts OR columnar dict) so callers can use the same
        handle across all three engines. We round-trip through pyarrow
        rather than ibis ``memtable`` so the table is materialized
        eagerly inside our duckdb connection (matters because the
        caller's source dict is mutable in its own scope).

        Args:
            records: Either ``[{"a": 1}, {"a": 2}]`` or ``{"a": [1, 2]}``.
            schema: Optional Frictionless schema.

        Returns:
            A lazy ``ibis.expr.types.Table`` backed by a duckdb temp
            table.
        """
        import pyarrow as pa

        # pyarrow has two distinct constructors for the two inline shapes
        # the cross-engine contract accepts.
        arrow = pa.table(records) if isinstance(records, dict) else pa.Table.from_pylist(list(records))
        name = _temp_table_name("inline")
        self.con.create_table(name, obj=arrow, temp=True)
        expr = self.con.table(name)
        return self.cast_schema(expr, schema) if schema is not None else expr

    def from_arrow(self, arrow_table: pa.Table) -> ir.Table:
        """Register ``arrow_table`` as a duckdb temp table without round-tripping records.

        Type-preserving counterpart to :meth:`from_records` — the Arrow
        buffer is handed straight to duckdb, so binary / decimal /
        timestamp columns survive (the ``to_pylist`` round-trip used to
        coerce them).
        """
        name = _temp_table_name("inline_arrow")
        self.con.create_table(name, obj=arrow_table, temp=True)
        return self.con.table(name)

    # ------------------------------------------------------------------
    # Write primitives — adapters call these directly
    # ------------------------------------------------------------------

    def write_csv(self, expr: ir.Table, dest: SourceRef, **kwargs: Any) -> None:
        """Write ``expr`` to ``dest`` as CSV via duckdb's ``to_csv``.

        Args:
            expr: An ibis expression.
            dest: Target path.
            **kwargs: Forwarded to duckdb's ``to_csv``.
        """
        self.con.to_csv(expr, _as_path_str(dest), **kwargs)

    def write_parquet(
        self,
        expr: ir.Table,
        dest: SourceRef,
        *,
        partition_by: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` to ``dest`` as parquet.

        For partitioned writes the ParquetAdapter handles the
        hive-layout itself (via pyarrow) and never reaches this engine
        primitive — so we reject ``partition_by`` here with a pointer
        at the adapter. Engines could grow native partitioned-write
        support later without changing the adapter.

        Args:
            expr: An ibis expression.
            dest: Target file path.
            partition_by: Must be ``None`` — see note above.
            **kwargs: Forwarded to duckdb's ``to_parquet``.
        """
        if partition_by:
            raise InvalidEngineCallError(
                "ibis engine: partitioned writes go through "
                "ParquetAdapter.write(partition_by=...), which routes "
                "through pyarrow rather than this primitive"
            )
        self.con.to_parquet(expr, _as_path_str(dest), **kwargs)

    def write_duckdb_table(
        self,
        expr: ir.Table,
        dest: SourceRef,
        *,
        table: str,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` into a duckdb file as a named table.

        We can't ``create_table`` on a different backend directly with
        an ibis expression rooted in ``self.con``, so we hop through
        Arrow. For Leavenworth-sized fixtures this is free; for very
        large writes the duckdb adapter could later ATTACH instead.

        Overwrite semantics: the destination table is dropped if it
        exists, so ``write_duckdb_table`` is idempotent (same as
        ``to_parquet``'s file-replacement behaviour).

        Args:
            expr: An ibis expression.
            dest: Target duckdb file path.
            table: Destination table name.
            **kwargs: Reserved for future options (currently ignored).
        """
        del kwargs  # reserved for future use
        if not table:
            raise InvalidEngineCallError("ibis engine: write_duckdb_table requires a non-empty table= argument")
        arrow = expr.to_pyarrow()
        dst = ibis.duckdb.connect(_as_path_str(dest))
        try:
            if table in dst.list_tables():
                dst.drop_table(table)
            dst.create_table(table, obj=arrow)
        finally:
            dst.disconnect()

    # ------------------------------------------------------------------
    # Schema cast — promoted from internal helper to public primitive
    # ------------------------------------------------------------------

    def cast_schema(self, expr: ir.Table, schema: Schema) -> ir.Table:
        """Cast columns of ``expr`` per a Frictionless schema.

        Only fields whose Frictionless type maps cleanly to an ibis
        dtype (per :data:`_FRICTIONLESS_TO_IBIS`) are cast. Fields not
        present in the table are skipped — that's a validation concern,
        not a scan concern.

        Implementation note: we collect casts into a single ``.cast()``
        call rather than chaining per-field ``.mutate``s. ibis builds a
        single projection either way, but the dict-form ``cast`` reads
        closer to the Frictionless schema for someone debugging types.

        Args:
            expr: An ibis expression.
            schema: A Frictionless :class:`~datagrove.spec.model.Schema`.

        Returns:
            A new expression with the casts applied, or ``expr``
            unchanged if no field's type was castable.
        """
        if schema is None or not getattr(schema, "fields", None):
            return expr
        casts: dict[str, str] = {}
        columns = set(expr.columns)
        for field in schema.fields:
            if field.name not in columns or field.type is None:
                continue
            ibis_type = _FRICTIONLESS_TO_IBIS.get(field.type)
            if ibis_type is not None:
                casts[field.name] = ibis_type
        if not casts:
            return expr
        return expr.cast(casts)

    # ------------------------------------------------------------------
    # Convenience delegators — route through io.dispatch
    # ------------------------------------------------------------------

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> ir.Table:
        """Open ``source`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.dispatch` plus a
        short carve-out for dict sources (the dispatcher rejects dicts;
        they're routed to :meth:`from_records` /
        :meth:`read_duckdb_table` directly).

        Args:
            source: Path / URL / ``Path`` / handle dict — see the
                :class:`~datagrove.engines.base.Engine` protocol's
                :meth:`~datagrove.engines.base.Engine.scan` for the
                accepted dict shapes.
            format: Optional explicit format hint forwarded to dispatch.
            schema: Optional Frictionless schema.
            **kwargs: Forwarded to the resolved adapter's ``read``.

        Returns:
            A lazy ``ibis.expr.types.Table``.

        Examples:
            >>> import tempfile, pathlib
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.csv"
            >>> _ = p.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> engine = IbisEngine()
            >>> engine.scan(p).count().to_pyarrow().as_py()
            2
            >>> engine.close()
        """
        # Dict-source carve-out — the dispatcher can't sniff dicts.
        if isinstance(source, dict):
            return _scan_dict(self, source, schema=schema, **kwargs)
        # All other shapes go through the adapter registry.
        from datagrove.io import dispatch

        adapter = dispatch(source, format=format)
        return adapter.read(source, engine=self, schema=schema, **kwargs)

    def write(self, expr: ir.Table, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write ``expr`` to ``dest`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.get_adapter`.
        Adapters skip this and call ``engine.write_<fmt>`` directly.

        Args:
            expr: An ibis expression.
            dest: Target path / URL.
            fmt: Format name (``"csv"``, ``"parquet"``, ``"duckdb"``, ...).
            **kwargs: Forwarded to the adapter's ``write``.
        """
        from datagrove.io import get_adapter

        adapter = get_adapter(fmt)
        adapter.write(expr, dest, engine=self, **kwargs)

    # ------------------------------------------------------------------
    # materialize / converters
    # ------------------------------------------------------------------

    def materialize(self, expr: ir.Table) -> ir.Table:
        """Force execution; return a stable ibis ``Table``.

        Materializes ``expr`` into a duckdb temp table so subsequent
        reads return a fixed row order. This is what callers want when
        they need value-equality semantics (e.g. comparing two scans).

        Args:
            expr: A lazy ibis ``Table``.

        Returns:
            A new ibis ``Table`` pointing at a backend-managed temp
            table. Lifetime is tied to the engine's connection.

        Examples:
            >>> import tempfile, pathlib
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.csv"
            >>> _ = p.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> engine = IbisEngine()
            >>> engine.materialize(engine.scan(p)).count().to_pyarrow().as_py()
            2
            >>> engine.close()
        """
        name = _temp_table_name("mat")
        self.con.create_table(name, obj=expr, temp=True)
        return self.con.table(name)

    def to_pandas(self, expr: ir.Table) -> pd.DataFrame:
        """Materialize ``expr`` and return a ``pandas.DataFrame``.

        Per the :class:`~datagrove.engines.base.Engine` protocol, the
        returned frame uses pandas **numpy-backed nullable dtypes**
        (``Int64`` / ``Float64`` / ``string`` / ``boolean``) so null
        semantics round-trip without silently upcasting integers with
        nulls to ``float64``. We achieve this by post-processing with
        :meth:`pandas.DataFrame.convert_dtypes` — ibis's native
        ``to_pandas`` returns numpy dtypes (``int64``, ``object``,
        ``float64``) which would diverge from polars/pandas engines.

        Examples:
            >>> import tempfile, pathlib
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.csv"
            >>> _ = p.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> engine = IbisEngine()
            >>> df = engine.to_pandas(engine.scan(p))
            >>> len(df), str(df["a"].dtype)
            (2, 'Int64')
            >>> engine.close()
        """
        try:
            df = expr.to_pandas()
        except ImportError as exc:  # pragma: no cover - pandas is an ibis dep
            raise EngineNotAvailableError(
                "pandas is required for IbisEngine.to_pandas; install with `pip install datagrove[pandas]`"
            ) from exc
        return df.convert_dtypes()

    def to_polars(self, expr: ir.Table) -> pl.DataFrame:
        """Materialize ``expr`` and return a ``polars.DataFrame``.

        Uses ibis's native ``to_polars`` (Arrow-backed) when available.
        Polars is an optional extra; missing-dep failures raise
        :class:`~datagrove.engines.errors.EngineNotAvailableError` with
        the right ``pip install`` command.

        Examples:
            >>> import pytest, tempfile, pathlib
            >>> _ = pytest.importorskip("polars")
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> p = pathlib.Path(tempfile.mkdtemp()) / "t.csv"
            >>> _ = p.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> engine = IbisEngine()
            >>> len(engine.to_polars(engine.scan(p)))
            2
            >>> engine.close()
        """
        try:
            return expr.to_polars()
        except ImportError as exc:
            raise EngineNotAvailableError(
                "polars is required for IbisEngine.to_polars; install with `pip install datagrove[polars]`"
            ) from exc

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Disconnect the backend if we created it.

        Idempotent — safe to call multiple times. Connections passed
        in by the caller are left alone.

        Examples:
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> engine = IbisEngine()
            >>> engine.close()
            >>> engine.close()  # idempotent
        """
        if self._owns_con and self.con is not None:
            with contextlib.suppress(Exception):
                # Already-closed connections raise; that's fine — close()
                # is documented as idempotent.
                self.con.disconnect()
            self._owns_con = False

    def __del__(self) -> None:  # pragma: no cover - GC-driven
        """Best-effort connection release on GC; never raise here."""
        with contextlib.suppress(Exception):
            self.close()


# ---------------------------------------------------------------------------
# Helpers (module-level — no state, no polymorphism, easier to read inline)
# ---------------------------------------------------------------------------


def _as_path_str(source: SourceRef) -> str:
    """Coerce ``str`` / ``Path`` / dict-with-path source to a string path."""
    if isinstance(source, Path):
        return str(source)
    if isinstance(source, str):
        return source
    if isinstance(source, dict) and "path" in source:
        return str(source["path"])
    raise UnsupportedSourceError(
        f"ibis engine: cannot coerce source {source!r} to a path (expected str, Path, or dict with 'path' key)"
    )


def _scan_dict(
    engine: IbisEngine,
    source: dict[str, Any],
    *,
    schema: Schema | None,
    **kwargs: Any,
) -> ir.Table:
    """Route the two supported dict-source shapes to the right primitive.

    The dispatcher rejects dict sources (it has no way to sniff them);
    this helper keeps :meth:`IbisEngine.scan` short by handling the two
    accepted shapes here. Both shapes are documented on
    :meth:`datagrove.engines.base.Engine.scan`.
    """
    if "data" in source:
        # Inline data — kwargs are intentionally ignored (records have
        # no reader options).
        return engine.from_records(source["data"], schema=schema)

    fmt = str(source.get("format", "")).lower()
    path = source.get("path")
    is_duckdb_handle = fmt == "duckdb" or (isinstance(path, (str, Path)) and str(path).lower().endswith(".duckdb"))
    if is_duckdb_handle:
        if path is None:
            raise InvalidEngineCallError(
                "duckdb dict source must include 'path' (e.g. {'path': 'net.duckdb', 'table': 'link'})"
            )
        table = source.get("table") or kwargs.pop("table", None)
        if not table:
            raise InvalidEngineCallError(
                "duckdb dict source must include 'table' (e.g. {'path': 'net.duckdb', 'table': 'link'})"
            )
        return engine.read_duckdb_table(str(path), table=table, schema=schema, **kwargs)

    raise UnsupportedSourceError(
        f"ibis engine: dict source shape not recognised (keys={sorted(source)!r}). "
        "Supported shapes: {'data': [...]} for inline data, or "
        "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
    )


_TEMP_COUNTER = count()


def _temp_table_name(prefix: str) -> str:
    """Return a process-unique temp table name for ``create_table``.

    A module-level :class:`itertools.count` iterator avoids the ibis
    backend complaining about a name collision when the same engine
    materializes more than one expression. ``next(counter)`` is more
    legible than the list-mutation trick (``_C[0] += 1``) and removes
    a tiny clever-Python footnote from Lens C.
    """
    return f"_datagrove_{prefix}_{next(_TEMP_COUNTER)}"


__all__ = ["IbisEngine"]
