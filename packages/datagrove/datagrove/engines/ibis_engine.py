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

Source resolution (today)
-------------------------

``scan()`` does not yet delegate to ``datagrove.io.dispatch`` because the
FormatAdapter registry is empty until tasks 1.7-1.11 ship. Instead the
engine inspects the source itself:

1. Explicit ``format=`` kwarg wins (``"csv"`` / ``"parquet"`` /
   ``"duckdb"``).
2. ``dict`` sources are treated as duckdb table handles
   (``{"path": "net.duckdb", "table": "link"}``).
3. Filename extension: ``.csv`` / ``.parquet`` / ``.duckdb``.
4. URL scheme: ``http(s)://`` and ``s3://`` are passed through to
   duckdb's httpfs/s3 extensions via the relevant reader.
5. Anything else raises ``NotImplementedError`` naming the task that
   will add the missing adapter.

Migration path (when adapters land, task 1.7+)
----------------------------------------------

When ``datagrove.io`` has registered adapters, ``scan()`` should:

1. ``adapter = datagrove.io.dispatch(source, format=format)``
2. ``return adapter.read(source, engine=self, schema=schema, **kwargs)``

Each adapter's ``read`` will call back into the engine via its native
``read_csv`` / ``read_parquet`` / ``read_*`` shortcuts (or via
``con.register`` for in-memory frames). The dict / table-name handling
for the duckdb adapter stays here because it is engine-specific. The
``__resolve_kind`` helper below maps to roughly the same set of names
the adapters will register under, so the swap is local.
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
    # scan
    # ------------------------------------------------------------------

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> ir.Table:
        """Open ``source`` as a lazy ibis ``Table``.

        See the module docstring for the resolution order and the
        migration path for when the FormatAdapter registry is populated.

        Args:
            source: A filesystem path, URL, ``Path``, or duckdb-table
                handle dict (``{"path": "net.duckdb", "table": "link"}``).
            format: Explicit format hint (``"csv"`` / ``"parquet"`` /
                ``"duckdb"``). Overrides extension sniffing.
            schema: Optional Frictionless :class:`Schema`. When given,
                columns are cast to the declared types using ibis
                expressions (no raw SQL).
            **kwargs: Forwarded to the backend reader. For
                ``"duckdb"`` source kind, ``table=...`` selects which
                table to read.

        Returns:
            A lazy ``ibis.expr.types.Table``.

        Raises:
            NotImplementedError: If the source kind has no in-engine
                reader yet (the relevant FormatAdapter ships in a later
                task; the message names which).
            InvalidEngineCallError: If ``format="duckdb"`` is used
                without a ``table=`` kwarg.
            UnsupportedSourceError: If ``source`` is a dict whose shape
                matches neither ``{"data": ...}`` nor the duckdb handle.

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
        kind = _resolve_kind(source, format)

        if kind == "data":
            # _resolve_kind only returns "data" when source is a dict
            # carrying a "data" key — narrow for the type checker.
            assert isinstance(source, dict)
            table = self._scan_inline_data(source)
        elif kind == "csv":
            path = _as_path_str(source)
            table = self.con.read_csv(path, **kwargs)
        elif kind == "parquet":
            path = _as_path_str(source)
            table = self.con.read_parquet(path, **kwargs)
        elif kind == "duckdb":
            table = self._scan_duckdb(source, **kwargs)
        else:
            # _resolve_kind already raises with a helpful message for
            # the no-adapter-yet case; this branch is defence in depth.
            raise NotImplementedError(  # pragma: no cover - unreachable today
                f"ibis engine: source kind {kind!r} not supported yet"
            )

        if schema is not None:
            table = _apply_schema_casts(table, schema)
        return table

    def _scan_inline_data(self, source: dict) -> ir.Table:
        """Register an in-memory ``{"data": ...}`` dict as a duckdb temp table.

        Accepts either a list of row dicts or a columnar dict — the same
        two shapes :class:`pandas.DataFrame` accepts — so callers can use
        the same handle across all three engines. We round-trip through
        pyarrow rather than ibis ``memtable`` so the table is materialized
        eagerly inside our duckdb connection (matters because the source
        dict is mutable in the caller's scope).
        """
        import pyarrow as pa

        data = source["data"]
        # pyarrow has two distinct constructors for the two inline shapes
        # the cross-engine contract accepts: ``pa.table(columnar_dict)`` and
        # ``pa.Table.from_pylist(list_of_row_dicts)``.
        arrow = pa.table(data) if isinstance(data, dict) else pa.Table.from_pylist(list(data))
        name = _temp_table_name("inline")
        self.con.create_table(name, obj=arrow, temp=True)
        return self.con.table(name)

    def _scan_duckdb(self, source: SourceRef, **kwargs: Any) -> ir.Table:
        """Read one table out of a duckdb file or handle dict."""
        if isinstance(source, dict):
            path = source.get("path")
            table_name = source.get("table") or kwargs.pop("table", None)
            if path is None or table_name is None:
                raise InvalidEngineCallError(
                    "duckdb dict source must include 'path' and 'table' (e.g. {'path': 'net.duckdb', 'table': 'link'})"
                )
            backend = ibis.duckdb.connect(str(path))
            return backend.table(table_name)

        table_name = kwargs.pop("table", None)
        if table_name is None:
            raise InvalidEngineCallError(
                "ibis engine: scan(<duckdb file>) requires table=<name>; "
                "pass e.g. engine.scan(path, table='link'). Multi-table "
                "enumeration ships with the duckdb FormatAdapter in task 1.9."
            )
        backend = ibis.duckdb.connect(_as_path_str(source))
        return backend.table(table_name)

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
    # write
    # ------------------------------------------------------------------

    def write(self, expr: ir.Table, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Persist ``expr`` to ``dest`` in ``fmt``.

        Args:
            expr: A lazy ibis ``Table``.
            dest: Path or URL.
            fmt: One of ``"csv"`` / ``"parquet"`` / ``"duckdb"``.
            **kwargs: Forwarded to the backend writer. For
                ``fmt="duckdb"``, ``table=<name>`` selects the
                destination table name (defaults to the expression's
                relation name when ibis exposes one, else ``"data"``).

        Raises:
            NotImplementedError: If ``fmt`` has no in-engine writer
                yet — message names the task that will add the
                adapter.

        Examples:
            >>> import tempfile, pathlib
            >>> from datagrove.engines.ibis_engine import IbisEngine
            >>> tmpdir = pathlib.Path(tempfile.mkdtemp())
            >>> src = tmpdir / "t.csv"
            >>> _ = src.write_text(chr(10).join(["a,b", "1,2", "3,4", ""]))
            >>> engine = IbisEngine()
            >>> dst = tmpdir / "out.parquet"
            >>> engine.write(engine.scan(src), dst, "parquet")
            >>> engine.scan(dst).count().to_pyarrow().as_py()
            2
            >>> engine.close()
        """
        dest_str = _as_path_str(dest)
        fmt_lower = fmt.lower()

        if fmt_lower == "parquet":
            self.con.to_parquet(expr, dest_str, **kwargs)
        elif fmt_lower == "csv":
            self.con.to_csv(expr, dest_str, **kwargs)
        elif fmt_lower == "duckdb":
            self._write_duckdb(expr, dest_str, **kwargs)
        else:
            raise NotImplementedError(
                f"ibis engine: write(fmt={fmt!r}) is not supported yet — "
                "the relevant FormatAdapter lands in tasks 1.7-1.11"
            )

    def _write_duckdb(self, expr: ir.Table, dest_path: str, **kwargs: Any) -> None:
        """Persist ``expr`` into a duckdb file at ``dest_path``.

        We can't ``create_table`` on a different backend directly with
        an ibis expression rooted in ``self.con``, so we hop through
        Arrow. For Leavenworth-sized fixtures this is free; for very
        large writes a future task (1.9) will teach the duckdb adapter
        to ATTACH instead.
        """
        table_name = kwargs.pop("table", None) or _expr_relation_name(expr) or "data"
        arrow = expr.to_pyarrow()
        dst = ibis.duckdb.connect(dest_path)
        try:
            # Overwrite semantics: drop if it exists so write() is
            # idempotent for tests. This mirrors how ``to_parquet``
            # behaves (file is replaced).
            if table_name in dst.list_tables():
                dst.drop_table(table_name)
            dst.create_table(table_name, obj=arrow)
        finally:
            dst.disconnect()

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


def _resolve_kind(source: SourceRef, format: str | None) -> str:
    """Decide which in-engine reader to use for ``source``.

    Returns one of ``"data"`` / ``"csv"`` / ``"parquet"`` / ``"duckdb"``.
    Raises :class:`NotImplementedError` for unsupported formats (naming
    the task that will add the adapter), or
    :class:`UnsupportedSourceError` for unrecognised dict shapes.
    """
    if format is not None:
        f = format.lower()
        if f in {"csv", "parquet", "duckdb", "data"}:
            return f
        raise NotImplementedError(
            f"ibis engine: format={format!r} not supported yet — the relevant FormatAdapter lands in tasks 1.7-1.11"
        )

    if isinstance(source, dict):
        # Cross-engine dict-source contract (see Engine.scan docstring):
        #   {"data": ...}                                  → inline data
        #   {"format": "duckdb", "path": ..., "table": ...} → duckdb handle
        #   {"path": "x.duckdb", "table": ...}             → duckdb handle
        #     (path-suffix shorthand)
        if "data" in source:
            return "data"
        fmt = str(source.get("format", "")).lower()
        if fmt == "duckdb":
            return "duckdb"
        path = source.get("path")
        if isinstance(path, (str, Path)) and str(path).lower().endswith(".duckdb"):
            return "duckdb"
        raise UnsupportedSourceError(
            f"ibis engine: dict source shape not recognised (keys={sorted(source)!r}). "
            "Supported shapes: {'data': [...]} for inline data, or "
            "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
        )

    path_str = _as_path_str(source).lower()
    # URL-scheme paths still typically have a recognizable extension
    # at the tail. duckdb's httpfs/s3 extensions read https:// and
    # s3:// directly via the matching reader.
    if path_str.endswith(".csv") or path_str.endswith(".csv.gz"):
        return "csv"
    if path_str.endswith(".parquet"):
        return "parquet"
    if path_str.endswith(".duckdb"):
        return "duckdb"

    # Anything else — surface a clear "no adapter for this yet" error
    # rather than a cryptic backend traceback. The task IDs let a
    # reader trace the deferred work to the issue tree.
    raise NotImplementedError(
        f"ibis engine: source {str(source)!r} has no in-engine reader yet. "
        "Adapters for csv.zip / xlsx / partitioned-parquet / remote-fsspec "
        "ship in tasks 1.7-1.11; for now pass an explicit format= or a "
        ".csv/.parquet/.duckdb path."
    )


def _apply_schema_casts(table: ir.Table, schema: Schema) -> ir.Table:
    """Cast ``table`` columns to match Frictionless ``schema`` types.

    Only fields whose type maps cleanly to an ibis dtype (per
    :data:`_FRICTIONLESS_TO_IBIS`) are cast. Fields not present in the
    table are skipped — that's a validation concern, not a scan
    concern.

    Implementation note: we collect casts into a single ``.cast()``
    call rather than chaining per-field ``.mutate``s. ibis builds a
    single projection either way, but the dict-form ``cast`` reads
    closer to the Frictionless schema for someone debugging types.
    """
    casts: dict[str, str] = {}
    columns = set(table.columns)
    for field in schema.fields:
        if field.name not in columns or field.type is None:
            continue
        ibis_type = _FRICTIONLESS_TO_IBIS.get(field.type)
        if ibis_type is not None:
            casts[field.name] = ibis_type
    if not casts:
        return table
    return table.cast(casts)


def _expr_relation_name(expr: ir.Table) -> str | None:
    """Return the underlying relation name of ``expr``, if it has one."""
    op = expr.op()
    name = getattr(op, "name", None)
    return name if isinstance(name, str) else None


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
