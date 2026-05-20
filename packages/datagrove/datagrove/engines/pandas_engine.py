"""Pandas engine — eager DataFrame execution (Phase 1 task 1.5).

The pandas engine is the **compatibility target** of the engine layer:
small, simple, no lazy expressions, and the convergence point every
other engine round-trips through via ``to_pandas``. It is *eager* —
``read_csv`` / ``read_parquet`` / ``read_duckdb_table`` / ``from_records``
return materialized :class:`pandas.DataFrame`s, not lazy plans.
``materialize()`` and ``to_pandas()`` are identities.

For lazy / regional-scale work use the ibis engine (default) or polars.
This engine exists for:

* notebook users who want a plain pandas object back without a converter
  call;
* cross-engine glue (every other engine implements ``to_pandas``);
* downstream code that depends on pandas-only libraries.

Dispatch model (post-issue-#134 inversion)
------------------------------------------

The engine exposes **per-format primitives** (``read_csv``,
``read_parquet``, ``read_duckdb_table``, ``from_records`` + the
matching ``write_*``). Adapters in :mod:`datagrove.io` call these
primitives directly. :meth:`scan` and :meth:`write` are thin convenience
methods that route format dispatch through ``datagrove.io.dispatch`` /
``datagrove.io.get_adapter``. No per-format if/elif lives in this module
anymore.

Architecture note
-----------------

Per ``docs/architecture.md`` §3 + §8, pandas is **not** allowed inside
datagrove core paths (validation, dataset, operations). It is allowed
here, as the explicit edge-converter / compatibility engine, and at the
``to_pandas()`` boundary of other engines. No raw SQL anywhere —
``lint_no_sql.py`` enforces this; the duckdb integration uses the
duckdb Python API (``con.table(name).df()`` /
``con.register(name, df)``) instead of ``SELECT`` strings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from datagrove.types import SourceRef

from .errors import (
    EngineNotAvailableError,
    InvalidEngineCallError,
    UnsupportedSourceError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import polars as pl

    from datagrove.spec.model import Schema


# Frictionless type name -> pandas nullable dtype. Inlined at point of
# use (per Lens C — small map, single consumer) but defined at module
# scope so the test file can reach it for assertions if needed later.
# Nullable dtypes (``Int64`` capital-I, ``Float64``, ``string``,
# ``boolean``) preserve missing values correctly; numpy ``int64`` would
# silently coerce ``NaN`` to ``0`` for integer columns.
_FRICTIONLESS_TO_PANDAS_NULLABLE: dict[str, str] = {
    "integer": "Int64",
    "number": "Float64",
    "string": "string",
    "boolean": "boolean",
}


class PandasEngine:
    """Eager pandas execution engine.

    The lowest-common-denominator engine. The read primitives return
    materialized :class:`pandas.DataFrame`s; there is no lazy
    expression layer. Cross-engine code that calls
    ``engine.to_pandas(expr)`` on an arbitrary engine and then runs
    pandas ops can switch transparently to this engine and skip the
    converter hop entirely.

    Attributes:
        name: ``"pandas"`` — registry key.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> PandasEngine().name
        'pandas'
    """

    name: str = "pandas"

    # ------------------------------------------------------------------
    # Read primitives — adapters call these directly
    # ------------------------------------------------------------------

    def read_csv(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read a CSV file via :func:`pandas.read_csv`.

        Args:
            source: Path / URL. URLs use pandas' fsspec integration;
                pass ``storage_options=`` for cloud credentials.
            schema: Optional Frictionless schema; columns are cast after
                read via :meth:`cast_schema`.
            **kwargs: Forwarded verbatim to :func:`pandas.read_csv`
                (``sep``, ``encoding``, ``compression``,
                ``storage_options``, ...).

        Returns:
            A materialized :class:`pandas.DataFrame`.
        """
        df = pd.read_csv(str(source), **kwargs)
        return self.cast_schema(df, schema) if schema is not None else df

    def read_parquet(
        self,
        source: SourceRef,
        schema: Schema | None = None,
        *,
        hive_partitioning: bool = False,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read parquet (single file or Hive-partitioned directory).

        Pandas's :func:`~pandas.read_parquet` uses pyarrow underneath,
        which natively handles Hive-partitioned directories and
        reinjects partition columns into the result — no extra kwarg is
        needed. The ``hive_partitioning`` flag is accepted for protocol
        parity but ignored.

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            schema: Optional Frictionless schema.
            hive_partitioning: Ignored — pyarrow auto-detects.
            **kwargs: Forwarded to :func:`pandas.read_parquet`.

        Returns:
            A materialized :class:`pandas.DataFrame`.
        """
        del hive_partitioning  # pyarrow handles it natively
        df = pd.read_parquet(str(source), **kwargs)
        return self.cast_schema(df, schema) if schema is not None else df

    def read_duckdb_table(
        self,
        source: SourceRef,
        *,
        table: str,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read one table out of a duckdb file via the duckdb Python relation API.

        No SQL string is constructed — we use ``con.table(name).df()``.

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
            raise InvalidEngineCallError("pandas engine: read_duckdb_table requires a non-empty table= argument")
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - duckdb ships with default install
            raise EngineNotAvailableError(
                "pandas engine: scanning .duckdb files requires the 'duckdb' package "
                "(install with `pip install duckdb`)."
            ) from exc

        con = duckdb.connect(str(source), read_only=True)
        try:
            df = con.table(table).df()
        finally:
            con.close()
        return self.cast_schema(df, schema) if schema is not None else df

    def from_records(
        self,
        records: list[dict[str, Any]] | dict[str, list[Any]],
        schema: Schema | None = None,
    ) -> pd.DataFrame:
        """Build a DataFrame from in-memory records.

        :class:`pandas.DataFrame` accepts both list-of-row-dicts and
        columnar-dict natively.

        Args:
            records: Either ``[{"a": 1}, {"a": 2}]`` or ``{"a": [1, 2]}``.
            schema: Optional Frictionless schema.

        Returns:
            A :class:`pandas.DataFrame`.
        """
        df = pd.DataFrame(records)
        return self.cast_schema(df, schema) if schema is not None else df

    def from_arrow(self, arrow_table: Any) -> pd.DataFrame:
        """Materialise a :class:`pyarrow.Table` as a :class:`pandas.DataFrame`.

        Type-preserving counterpart to :meth:`from_records`: the Arrow
        buffer is handed to pandas directly, so nullable Int64 / string
        / boolean / timestamp columns survive without going through a
        ``records`` round-trip. The result is normalised through
        ``convert_dtypes()`` so the **numpy-backed nullable** dtype
        contract documented on :meth:`to_pandas` (the cross-engine
        convergence point) is honoured end-to-end.
        """
        return arrow_table.to_pandas().convert_dtypes()

    # ------------------------------------------------------------------
    # Write primitives — adapters call these directly
    # ------------------------------------------------------------------

    def write_csv(self, expr: pd.DataFrame, dest: SourceRef, **kwargs: Any) -> None:
        """Write ``expr`` to ``dest`` as CSV.

        Always ``index=False`` (Frictionless tabular data has no
        row-index concept). Callers passing ``index=True`` get an
        exception from pandas' duplicate-kwarg detection — that's
        intentional, we don't want a silent on-disk surprise.
        """
        expr.to_csv(str(dest), index=False, **kwargs)

    def write_parquet(
        self,
        expr: pd.DataFrame,
        dest: SourceRef,
        *,
        partition_by: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` to ``dest`` as parquet.

        Partitioned writes are handled by :class:`~datagrove.io.parquet_adapter.ParquetAdapter`
        via pyarrow; the engine primitive rejects ``partition_by`` to
        surface that contract clearly.
        """
        if partition_by:
            raise InvalidEngineCallError(
                "pandas engine: partitioned writes go through "
                "ParquetAdapter.write(partition_by=...) which routes "
                "through pyarrow rather than this primitive"
            )
        expr.to_parquet(str(dest), index=False, **kwargs)

    def write_duckdb_table(
        self,
        expr: pd.DataFrame,
        dest: SourceRef,
        *,
        table: str,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` into a duckdb file as a named table (no SQL).

        Uses ``con.register(name, df)`` + ``con.table(name).create(target)``
        — the duckdb Python relational API. No SQL DDL string crosses
        our code boundary, so the no-raw-SQL rule is satisfied for the
        pandas engine.

        Args:
            expr: A pandas DataFrame.
            dest: Target duckdb file path.
            table: Destination table name.
            **kwargs: Reserved (currently ignored).
        """
        del kwargs
        if not table:
            raise InvalidEngineCallError("pandas engine: write_duckdb_table requires a non-empty table= argument")
        import duckdb

        con = duckdb.connect(str(dest))
        try:
            # Register the in-memory DataFrame as a temporary view, then
            # materialize it as a real table via the relational API. No
            # SQL strings cross our code boundary here.
            con.register("__datagrove_pandas_write", expr)
            con.table("__datagrove_pandas_write").create(table)
        finally:
            con.unregister("__datagrove_pandas_write")
            con.close()

    # ------------------------------------------------------------------
    # Schema cast — promoted from internal helper to public primitive
    # ------------------------------------------------------------------

    def cast_schema(self, expr: pd.DataFrame, schema: Schema) -> pd.DataFrame:
        """Cast columns of ``expr`` per a Frictionless schema.

        Columns absent from the schema are left untouched. Columns
        absent from the DataFrame are silently skipped (schema may
        describe more columns than the source actually carries; FK /
        structural validation in datagrove.validation surfaces
        missing-column errors separately).

        Args:
            expr: A pandas DataFrame.
            schema: A Frictionless :class:`~datagrove.spec.model.Schema`.

        Returns:
            A DataFrame with the casts applied, or ``expr`` unchanged
            if no field type was castable.
        """
        if schema is None or not getattr(schema, "fields", None):
            return expr
        cast: dict[str, str] = {}
        for field in schema.fields:
            if field.type is None:
                continue
            pandas_dtype = _FRICTIONLESS_TO_PANDAS_NULLABLE.get(field.type)
            if pandas_dtype is None:
                # Unknown Frictionless type (datetime, geojson, any, ...) —
                # leave as-is; validation surfaces type errors separately.
                continue
            if field.name in expr.columns:
                cast[field.name] = pandas_dtype
        if cast:
            expr = expr.astype(cast)
        return expr

    # ------------------------------------------------------------------
    # Convenience delegators — route through io.dispatch
    # ------------------------------------------------------------------

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Open ``source`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.dispatch` plus a
        short carve-out for dict sources (the dispatcher rejects dicts;
        they're routed to :meth:`from_records` /
        :meth:`read_duckdb_table` directly).

        Args:
            source: Path / URL / ``Path`` / handle dict.
            format: Optional explicit format hint forwarded to dispatch.
            schema: Optional Frictionless schema.
            **kwargs: Forwarded to the resolved adapter's ``read``.

        Returns:
            A materialized :class:`pandas.DataFrame`.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> import pandas as pd
            >>> df = e.scan({"data": [{"a": 1}, {"a": 2}]})
            >>> isinstance(df, pd.DataFrame), len(df)
            (True, 2)
        """
        if isinstance(source, dict):
            return _scan_dict(self, source, schema=schema, **kwargs)
        from datagrove.io import dispatch

        adapter = dispatch(source, format=format)
        return adapter.read(source, engine=self, schema=schema, **kwargs)

    def write(self, expr: pd.DataFrame, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Write ``expr`` to ``dest`` via the FormatAdapter registry.

        3-line convenience over :func:`datagrove.io.get_adapter`.
        """
        from datagrove.io import get_adapter

        adapter = get_adapter(fmt)
        adapter.write(expr, dest, engine=self, **kwargs)

    # ------------------------------------------------------------------
    # materialize / to_pandas / to_polars
    # ------------------------------------------------------------------

    def materialize(self, expr: pd.DataFrame) -> pd.DataFrame:
        """Return ``expr`` unchanged — pandas is already materialized.

        Identity by design. The protocol exists so cross-engine code can
        call ``engine.materialize(expr)`` regardless of which engine
        produced ``expr``; for pandas it is a no-op.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import pandas as pd
            >>> df = pd.DataFrame({"a": [1]})
            >>> PandasEngine().materialize(df) is df
            True
        """
        return expr

    def to_pandas(self, expr: pd.DataFrame) -> pd.DataFrame:
        """Return ``expr`` normalised to the cross-engine dtype contract.

        Per the :class:`~datagrove.engines.base.Engine` protocol,
        ``to_pandas`` returns a frame using pandas **numpy-backed
        nullable dtypes** (``Int64`` / ``Float64`` / ``string`` /
        ``boolean``). For the pandas engine this means routing the
        already-pandas frame through :meth:`pandas.DataFrame.convert_dtypes`
        so its dtypes match what ``IbisEngine.to_pandas`` and
        ``PolarsEngine.to_pandas`` produce for the same source — the
        whole point is round-trip identity. We don't return ``expr``
        itself because that would skip the convention and a caller
        switching engines would see different dtypes on the boundary.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import pandas as pd
            >>> df = pd.DataFrame({"a": [1, 2]})
            >>> out = PandasEngine().to_pandas(df)
            >>> str(out["a"].dtype)
            'Int64'
        """
        return expr.convert_dtypes()

    def to_polars(self, expr: pd.DataFrame) -> pl.DataFrame:
        """Convert to :class:`polars.DataFrame` via :func:`polars.from_pandas`.

        Raises :class:`~datagrove.engines.base.EngineNotAvailableError`
        if polars is not installed; install with
        ``pip install datagrove[polars]``.

        The simple ``polars.from_pandas`` path is sufficient for the
        compatibility-converter use case. An Arrow round-trip
        (``pl.from_arrow(pa.Table.from_pandas(df))``) is slightly faster
        on wide frames but the speedup is not worth the extra dep
        coupling here — users who need it can do the conversion
        themselves.

        Examples:
            Requires ``polars`` to be installed::

                from datagrove.engines.pandas_engine import PandasEngine
                import pandas as pd
                df = pd.DataFrame({"a": [1, 2]})
                PandasEngine().to_polars(df)  # -> polars.DataFrame
        """
        try:
            import polars as pl
        except ImportError as exc:
            raise EngineNotAvailableError(
                "polars is not installed; install with `pip install datagrove[polars]` to use PandasEngine.to_polars()."
            ) from exc
        return pl.from_pandas(expr)


# ---------------------------------------------------------------------------
# Helpers (module-level — small, single-consumer, but worth a name)
# ---------------------------------------------------------------------------


def _scan_dict(
    engine: PandasEngine,
    source: dict[str, Any],
    *,
    schema: Schema | None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Route the two supported dict-source shapes to the right primitive.

    Symmetric with :func:`datagrove.engines.ibis_engine._scan_dict` and
    :func:`datagrove.engines.polars_engine._scan_dict`. Both shapes
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
                f"pandas engine: duckdb dict source requires 'path' (got keys={sorted(source)!r})"
            )
        table = source.get("table") or kwargs.pop("table", None)
        if not table:
            raise InvalidEngineCallError(
                f"pandas engine: duckdb dict source requires 'table' (got keys={sorted(source)!r})"
            )
        return engine.read_duckdb_table(str(path), table=table, schema=schema, **kwargs)

    raise UnsupportedSourceError(
        f"pandas engine: dict source shape not recognised (keys={sorted(source)!r}). "
        "Supported shapes: {'data': [...]} for inline data, or "
        "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
    )


__all__ = ["PandasEngine"]
