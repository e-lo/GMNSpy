"""Polars engine — lazy-frame execution adapter (Phase 1 task 1.4, issue #51).

Polars is the lighter-weight alternative to the default ibis engine: the same
``Engine`` protocol, but every read primitive returns a
:class:`polars.LazyFrame` that defers work until ``.collect()`` (the
per-method ``materialize`` / ``to_polars`` / ``to_pandas`` / ``write_*``
paths). Lazy by default is the key Lens-A contract — pushdown happens inside
polars's optimizer, not here.

Dispatch model (post-issue-#134 inversion)
------------------------------------------

The engine exposes **per-format primitives** (``read_csv``,
``read_parquet``, ``read_duckdb_table``, ``from_records`` + the
matching ``write_*``). Adapters in :mod:`datagrove.io` call these
primitives directly. :meth:`scan` and :meth:`write` are thin convenience
methods that route format dispatch through ``datagrove.io.dispatch`` /
``datagrove.io.get_adapter``. No per-format if/elif lives in this module
anymore.

No raw SQL appears in this module. Polars' built-in scanners
(``scan_csv``, ``scan_parquet``) own the file I/O; reading a duckdb
table uses the duckdb Python relation API (``con.table(name).pl()``).
Writing duckdb tables requires a table-creation SQL statement which is
banned outside ibis_engine, so :meth:`write_duckdb_table` raises
``EngineNotAvailableError`` and points callers at
:class:`~datagrove.engines.ibis_engine.IbisEngine`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from datagrove.types import SourceRef

from .errors import EngineNotAvailableError, InvalidEngineCallError, UnsupportedSourceError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from datagrove.spec.model import Schema


# Frictionless type name → polars dtype. Inlined at module scope (rather
# than imported from a shared defaults module) per Lens C — the map is
# small and only used in one place. The cross-engine parity test
# (test_cross_engine_dtype_parity) asserts this keyset matches the
# corresponding maps in ibis_engine + pandas_engine, so adding a new
# Frictionless type later forces all three engines to update together.
_FRICTIONLESS_TO_POLARS: dict[str, type[pl.DataType]] = {
    "integer": pl.Int64,
    "number": pl.Float64,
    "string": pl.Utf8,
    "boolean": pl.Boolean,
}


class PolarsEngine:
    r"""Polars-backed engine. Primitives return lazy frames; ``collect`` is on you.

    Attributes:
        name: Registry key (``"polars"``).

    Examples:
        Scan a CSV lazily, then collect explicitly:

        >>> from datagrove.engines.polars_engine import PolarsEngine
        >>> import polars as pl
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     p = pathlib.Path(tmp) / "t.csv"
        ...     _ = p.write_text("a,b\n1,2\n3,4\n")
        ...     lazy = PolarsEngine().scan(p)
        ...     isinstance(lazy, pl.LazyFrame)
        True
    """

    name: str = "polars"

    # ------------------------------------------------------------------
    # Read primitives — adapters call these directly
    # ------------------------------------------------------------------

    def read_csv(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pl.LazyFrame:
        """Lazy-read a CSV via :func:`polars.scan_csv`.

        Args:
            source: Path / URL. URLs work via polars's fsspec integration
                when ``storage_options=`` is passed in ``kwargs``.
            schema: Optional Frictionless schema; columns are cast after
                scan via :meth:`cast_schema`.
            **kwargs: Forwarded verbatim to :func:`polars.scan_csv`
                (``separator``, ``has_header``, ``n_rows``,
                ``storage_options``, ...).

        Returns:
            A :class:`polars.LazyFrame`.
        """
        lf = pl.scan_csv(str(source), **kwargs)
        return self.cast_schema(lf, schema) if schema is not None else lf

    def read_parquet(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        *,
        hive_partitioning: bool = False,
        **kwargs: Any,
    ) -> pl.LazyFrame:
        """Lazy-read parquet (single file or Hive-partitioned directory).

        Polars wants an explicit glob for multi-file reads; the engine
        auto-builds one for directory sources unless the caller has
        already enabled hive partitioning (I3 — the adapter forwards
        the path verbatim and lets engines own the partitioning detail).

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            schema: Optional Frictionless schema.
            hive_partitioning: Enable Hive-style partition discovery.
                Auto-enabled for directory sources when caller didn't
                set it.
            **kwargs: Forwarded to :func:`polars.scan_parquet`.

        Returns:
            A :class:`polars.LazyFrame`.
        """
        src_str = str(source)
        if not hive_partitioning and Path(src_str).is_dir():
            # Directory + caller didn't explicitly enable — auto-on.
            lf = pl.scan_parquet(f"{src_str}/**/*.parquet", hive_partitioning=True, **kwargs)
        elif hive_partitioning:
            lf = pl.scan_parquet(src_str, hive_partitioning=True, **kwargs)
        else:
            lf = pl.scan_parquet(src_str, **kwargs)
        return self.cast_schema(lf, schema) if schema is not None else lf

    def read_duckdb_table(
        self,
        source: SourceRef,
        *,
        table: str,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pl.LazyFrame:
        """Read one table out of a duckdb file via the duckdb Python relation API.

        No SQL string is constructed — we use ``con.table(name).pl()``
        and then ``.lazy()`` so downstream operators get a LazyFrame
        like other primitives in this engine.

        Args:
            source: Path to a ``.duckdb`` file.
            table: The table name (required).
            schema: Optional Frictionless schema.
            **kwargs: Reserved (currently ignored).

        Raises:
            InvalidEngineCallError: If ``table`` is empty.
            EngineNotAvailableError: If the duckdb dep is missing.
        """
        del kwargs  # reserved for future use
        if not table:
            raise InvalidEngineCallError("polars engine: read_duckdb_table requires a non-empty table= argument")
        # Lazy import: duckdb is a polars-optional dep at this engine's
        # boundary. We do NOT want importing polars_engine to hard-require it.
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - duckdb ships with the default install
            raise EngineNotAvailableError(
                "polars engine: scanning .duckdb files requires the 'duckdb' package "
                "(install with `pip install duckdb`, or use the ibis engine)."
            ) from exc

        con = duckdb.connect(str(source), read_only=True)
        # con.table(name) is the Python relation API — no SQL string.
        lf = con.table(table).pl().lazy()
        return self.cast_schema(lf, schema) if schema is not None else lf

    def from_records(
        self,
        records: list[dict[str, Any]] | dict[str, list[Any]],
        schema: Schema | None = None,
    ) -> pl.LazyFrame:
        """Build a LazyFrame from in-memory records.

        :class:`polars.LazyFrame` accepts both list-of-row-dicts and
        columnar-dict natively.

        Args:
            records: Either ``[{"a": 1}, {"a": 2}]`` or ``{"a": [1, 2]}``.
            schema: Optional Frictionless schema.

        Returns:
            A :class:`polars.LazyFrame`.
        """
        lf = pl.LazyFrame(records)
        return self.cast_schema(lf, schema) if schema is not None else lf

    def from_arrow(self, arrow_table: Any) -> pl.LazyFrame:
        """Wrap a :class:`pyarrow.Table` directly as a :class:`polars.LazyFrame`.

        Type-preserving counterpart to :meth:`from_records`:
        ``pl.from_arrow`` keeps Arrow's column types intact (binary,
        decimal, timestamp, large-string), which the
        ``records → from_records`` round-trip used to lose.
        """
        return pl.from_arrow(arrow_table).lazy()

    # ------------------------------------------------------------------
    # Write primitives — adapters call these directly
    # ------------------------------------------------------------------

    def write_csv(self, expr: pl.LazyFrame, dest: SourceRef, **kwargs: Any) -> None:
        """Collect ``expr`` and write it to ``dest`` as CSV."""
        expr.collect().write_csv(str(dest), **kwargs)

    def write_parquet(
        self,
        expr: pl.LazyFrame,
        dest: SourceRef,
        *,
        partition_by: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Collect ``expr`` and write it to ``dest`` as parquet.

        Partitioned writes are handled by :class:`~datagrove.io.parquet_adapter.ParquetAdapter`
        via pyarrow (so on-disk layout matches across engines); the
        engine primitive rejects ``partition_by`` to surface that
        contract clearly.
        """
        if partition_by:
            raise InvalidEngineCallError(
                "polars engine: partitioned writes go through "
                "ParquetAdapter.write(partition_by=...) which routes "
                "through pyarrow rather than this primitive"
            )
        expr.collect().write_parquet(str(dest), **kwargs)

    def write_duckdb_table(
        self,
        expr: pl.LazyFrame,
        dest: SourceRef,
        *,
        table: str,
        **kwargs: Any,
    ) -> None:
        """Defer duckdb writes to IbisEngine — polars can't write duckdb without SQL.

        Writing a table into a duckdb file requires a table-creation
        SQL statement; the no-raw-SQL rule bans that in this module.
        Callers should use :class:`~datagrove.engines.ibis_engine.IbisEngine`
        for duckdb writes (or round-trip through parquet).
        """
        del expr, dest, table, kwargs
        raise EngineNotAvailableError(
            "polars engine: writing to a duckdb file requires a table-creation "
            "SQL statement which is not available in this module (no-raw-SQL "
            "rule). Use IbisEngine for duckdb writes, or export to parquet "
            "and load separately."
        )

    # ------------------------------------------------------------------
    # Schema cast — promoted from internal helper to public primitive
    # ------------------------------------------------------------------

    def cast_schema(self, expr: pl.LazyFrame, schema: Schema) -> pl.LazyFrame:
        """Cast columns of a LazyFrame per a Frictionless schema.

        Unknown Frictionless types are skipped (no cast) rather than
        erroring — the v0.3 ``apply_schema_to_df`` bug was a reminder
        that silent-but-noisy is the safer default for partial schemas.

        Args:
            expr: A :class:`polars.LazyFrame`.
            schema: A Frictionless :class:`~datagrove.spec.model.Schema`.

        Returns:
            A LazyFrame with the casts applied, or ``expr`` unchanged
            if no field type was castable.
        """
        if schema is None or not getattr(schema, "fields", None):
            return expr
        present = set(expr.collect_schema().names())
        casts: dict[str, type[pl.DataType]] = {
            f.name: _FRICTIONLESS_TO_POLARS[f.type]
            for f in schema.fields
            if f.type in _FRICTIONLESS_TO_POLARS and f.name in present
        }
        if not casts:
            return expr
        # polars' .cast() Mapping type uses an internal ColumnNameOrSelector /
        # PolarsDataType union; the runtime accepts dict[str, type[DataType]]
        # but the stubs don't model that overload. Safe at runtime.
        return expr.cast(casts)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Convenience delegators — route through io.dispatch
    # ------------------------------------------------------------------

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pl.LazyFrame:
        r"""Open ``source`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.dispatch` plus a
        short carve-out for dict sources (the dispatcher rejects dicts;
        they're routed to :meth:`from_records` /
        :meth:`read_duckdb_table` directly).

        Args:
            source: Path / URL / ``Path`` / handle dict — see the
                :class:`~datagrove.engines.base.Engine` protocol for the
                accepted dict shapes.
            format: Optional explicit format hint forwarded to dispatch.
            schema: Optional Frictionless schema.
            **kwargs: Forwarded to the resolved adapter's ``read``.

        Returns:
            A :class:`polars.LazyFrame`.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl, tempfile, pathlib
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     p = pathlib.Path(tmp) / "t.csv"
            ...     _ = p.write_text("a,b\n1,2\n")
            ...     isinstance(PolarsEngine().scan(p), pl.LazyFrame)
            True
        """
        if isinstance(source, dict):
            return _scan_dict(self, source, schema=schema, **kwargs)
        from datagrove.io import dispatch

        adapter = dispatch(source, format=format)
        return adapter.read(source, engine=self, schema=schema, **kwargs)

    def write(
        self,
        expr: pl.LazyFrame,
        dest: SourceRef,
        fmt: str,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` to ``dest`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.get_adapter`.
        """
        from datagrove.io import get_adapter

        adapter = get_adapter(fmt)
        adapter.write(expr, dest, engine=self, **kwargs)

    # ------------------------------------------------------------------
    # materialize + converters
    # ------------------------------------------------------------------

    def materialize(self, expr: pl.LazyFrame) -> pl.DataFrame:
        """Collect ``expr`` into a :class:`polars.DataFrame`.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl
            >>> lazy = pl.LazyFrame({"a": [1, 2, 3]})
            >>> df = PolarsEngine().materialize(lazy)
            >>> isinstance(df, pl.DataFrame), df.height
            (True, 3)
        """
        return expr.collect()

    def to_pandas(self, expr: pl.LazyFrame) -> pd.DataFrame:
        """Materialize ``expr`` and return a ``pandas.DataFrame``.

        Per the :class:`~datagrove.engines.base.Engine` protocol, the
        returned frame uses pandas **numpy-backed nullable dtypes**
        (``Int64`` / ``Float64`` / ``string`` / ``boolean``) — NOT
        the pyarrow-extension dtypes (``int64[pyarrow]`` etc.) that
        ``to_pandas(use_pyarrow_extension_array=True)`` would produce.
        We standardize on numpy-backed nullable because downstream
        libraries (sklearn, geopandas pre-1.0, older matplotlib) do not
        understand ``pd.ArrowDtype`` columns yet, and the parity test
        ``test_cross_engine_dtype_parity`` locks the convention in.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl
            >>> lazy = pl.LazyFrame({"a": [1, 2]})
            >>> pdf = PolarsEngine().to_pandas(lazy)
            >>> list(pdf.columns), len(pdf), str(pdf["a"].dtype)
            (['a'], 2, 'Int64')
        """
        # polars's default to_pandas() returns numpy dtypes (int64,
        # object, float64). .convert_dtypes() upcasts those into the
        # nullable family that matches the cross-engine convention.
        return expr.collect().to_pandas().convert_dtypes()

    def to_polars(self, expr: pl.LazyFrame) -> pl.DataFrame:
        """Collect ``expr`` — trivial, since polars is the native engine.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl
            >>> df = PolarsEngine().to_polars(pl.LazyFrame({"a": [1]}))
            >>> isinstance(df, pl.DataFrame)
            True
        """
        return expr.collect()


# ---------------------------------------------------------------------------
# Helpers (module-level — symmetric with ibis_engine + pandas_engine)
# ---------------------------------------------------------------------------


def _scan_dict(
    engine: PolarsEngine,
    source: dict[str, Any],
    *,
    schema: Schema | None,
    **kwargs: Any,
) -> pl.LazyFrame:
    """Route the two supported dict-source shapes to the right primitive.

    Symmetric with :func:`datagrove.engines.ibis_engine._scan_dict` and
    :func:`datagrove.engines.pandas_engine._scan_dict`. Both shapes
    documented on :meth:`datagrove.engines.base.Engine.scan`.
    """
    if "data" in source:
        return engine.from_records(source["data"], schema=schema)

    fmt = str(source.get("format", "")).lower()
    path = source.get("path")
    is_duckdb_handle = fmt == "duckdb" or (isinstance(path, (str, Path)) and str(path).lower().endswith(".duckdb"))
    if is_duckdb_handle:
        if path is None:
            raise InvalidEngineCallError(
                f"polars engine: duckdb dict source requires 'path' (got keys={sorted(source)!r})"
            )
        table = source.get("table") or kwargs.pop("table", None)
        if not table:
            raise InvalidEngineCallError(
                f"polars engine: duckdb dict source requires 'table' (got keys={sorted(source)!r})"
            )
        return engine.read_duckdb_table(str(path), table=table, schema=schema, **kwargs)

    raise UnsupportedSourceError(
        f"polars engine: dict source shape not recognised (keys={sorted(source)!r}). "
        "Supported shapes: {'data': [...]} for inline data, or "
        "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
    )


__all__ = ["PolarsEngine"]
