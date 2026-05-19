"""Pandas engine — eager DataFrame execution (Phase 1 task 1.5).

The pandas engine is the **compatibility target** of the engine layer:
small, simple, no lazy expressions, and the convergence point every
other engine round-trips through via ``to_pandas``. It is *eager* —
``scan()`` returns a materialized :class:`pandas.DataFrame`, not a lazy
plan. ``materialize()`` and ``to_pandas()`` are identities.

For lazy / regional-scale work use the ibis engine (default) or polars.
This engine exists for:

* notebook users who want a plain pandas object back without a converter
  call;
* cross-engine glue (every other engine implements ``to_pandas``);
* downstream code that depends on pandas-only libraries.

Adapter migration note
----------------------

Today ``scan()`` calls pandas readers directly (``pd.read_csv``,
``pd.read_parquet``, the ``duckdb`` Python API for ``.duckdb``,
``compression="zip"`` for ``.csv.zip``). When the
:class:`~datagrove.io.FormatAdapter` registry is wired up
(tasks 1.7-1.11), the dispatch ladder will move into
``datagrove.io.dispatch`` and this method will delegate to it via
``adapter.read(source, engine=self, schema=schema, **kwargs)``. The
adapter contract (``read`` returns a *lazy* expression for the engine)
collapses for pandas: the pandas FormatAdapter implementations just
return the eager DataFrame. The five extension branches below become
the five default adapters - same code, moved one layer up.

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

    The lowest-common-denominator engine. ``scan()`` returns a
    materialized :class:`pandas.DataFrame`; there is no lazy expression
    layer. Cross-engine code that calls ``engine.to_pandas(expr)`` on
    an arbitrary engine and then runs pandas ops can switch transparently
    to this engine and skip the converter hop entirely.

    Attributes:
        name: ``"pandas"`` — registry key.

    Examples:
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> PandasEngine().name
        'pandas'
    """

    name: str = "pandas"

    # ------------------------------------------------------------------
    # scan
    # ------------------------------------------------------------------

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Read ``source`` eagerly and return a :class:`pandas.DataFrame`.

        Naming note: pandas is eager, so the "scan" verb here is a slight
        misnomer — the returned object is already materialized, not a
        lazy plan. The verb matches the :class:`~datagrove.engines.base.Engine`
        protocol so callers can swap engines without changing call sites.

        Same shape as :meth:`IbisEngine.scan` / :meth:`PolarsEngine.scan`:
        a single :func:`_resolve_kind` helper picks the dispatch key,
        then a flat if/elif calls the per-kind reader, then
        :func:`_apply_schema_casts` runs once at the end on every path.

        Args:
            source: A path, URL, or dict handle. Accepted dict shapes:

                - ``{"data": [...]}`` — inline data (list of row dicts
                  or columnar dict).
                - ``{"format": "duckdb", "path": "x.duckdb", "table":
                  "link"}`` — a duckdb table handle.

                Strings starting with ``http(s)://`` work via pandas'
                fsspec integration; ``s3://`` etc. require the optional
                ``s3fs`` extra. Pass ``storage_options=`` through
                ``**kwargs`` for credentials.
            format: Optional explicit format hint
                (``"csv"`` / ``"parquet"`` / ``"duckdb"`` / ``"csv.zip"``
                / ``"data"``). Wins over extension sniff.
            schema: Optional Frictionless :class:`~datagrove.spec.model.Schema`.
                When provided, integer / number / string / boolean
                columns are cast to pandas **nullable** dtypes
                (``Int64`` / ``Float64`` / ``string`` / ``boolean``)
                so that missing values round-trip correctly.
            **kwargs: Forwarded to the underlying reader
                (e.g. ``sep``, ``encoding``, ``compression``,
                ``storage_options``, plus ``table=`` for duckdb).

        Returns:
            A materialized pandas DataFrame.

        Raises:
            NotImplementedError: For unsupported formats (the message
                names the deferred FormatAdapter task).
            InvalidEngineCallError: For valid formats with missing
                required kwargs (e.g. ``.duckdb`` without ``table=``).
            UnsupportedSourceError: For dict sources whose shape matches
                neither ``{"data": ...}`` nor the duckdb handle.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> e = PandasEngine()
            >>> import pandas as pd
            >>> df = e.scan({"data": [{"a": 1}, {"a": 2}]})
            >>> isinstance(df, pd.DataFrame), len(df)
            (True, 2)
        """
        kind = _resolve_kind(source, format)

        if kind == "data":
            # pd.DataFrame accepts both list-of-row-dicts and a columnar
            # dict natively, so we hand the value through unchanged.
            df = pd.DataFrame(source["data"])  # type: ignore[index]
        elif kind == "csv":
            df = pd.read_csv(str(source), **kwargs)
        elif kind == "parquet":
            # I3: pandas's read_parquet uses pyarrow underneath, which
            # natively handles Hive-partitioned directories and reinjects
            # partition columns — no extra kwarg is needed. The branch is
            # symmetric with the ibis/polars engines so the parquet
            # adapter can forward without engine-specific dispatch.
            df = pd.read_parquet(str(source), **kwargs)
        elif kind in {"csv.zip", "zip"}:
            df = _read_csv_zip(str(source), **kwargs)
        elif kind == "duckdb":
            df = _read_duckdb(source, **kwargs)
        else:  # pragma: no cover - _resolve_kind raises before reaching here
            raise NotImplementedError(f"pandas engine: source kind {kind!r} not supported")

        if schema is not None:
            df = _apply_schema_casts(df, schema)
        return df

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

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(self, expr: pd.DataFrame, dest: SourceRef, fmt: str, **kwargs: Any) -> None:
        """Persist ``expr`` to ``dest`` in the given format.

        Supported formats:

        * ``"csv"``     — :meth:`pandas.DataFrame.to_csv`,
          always ``index=False`` (Frictionless tabular data has no
          row-index concept).
        * ``"parquet"`` — :meth:`pandas.DataFrame.to_parquet` (pyarrow
          backend), ``index=False``.
        * ``"duckdb"``  — :mod:`duckdb` Python API: open ``dest`` as a
          duckdb file, register the DataFrame, and write it as a table
          named ``kwargs['table']`` via the no-SQL relational API
          (``con.from_df(df).create(table)``).

        Args:
            expr: A pandas DataFrame.
            dest: Output path. Coerced to ``str`` for pandas writers
                that don't accept ``Path``.
            fmt: Format identifier.
            **kwargs: Format-specific options
                (``table=`` is required for ``"duckdb"``).

        Raises:
            NotImplementedError: For unsupported formats.
            ValueError: For ``fmt="duckdb"`` without ``kwargs['table']``.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import pandas as pd, tempfile, os
            >>> df = pd.DataFrame({"a": [1, 2]})
            >>> with tempfile.TemporaryDirectory() as d:
            ...     p = os.path.join(d, "x.csv")
            ...     PandasEngine().write(df, p, fmt="csv")
            ...     pd.read_csv(p).shape
            (2, 1)
        """
        dest_str = str(dest)
        if fmt == "csv":
            expr.to_csv(dest_str, index=False, **kwargs)
            return
        if fmt == "parquet":
            expr.to_parquet(dest_str, index=False, **kwargs)
            return
        if fmt == "duckdb":
            _write_duckdb(expr, dest_str, **kwargs)
            return

        raise NotImplementedError(
            f"pandas engine: write fmt={fmt!r} is not supported. "
            "Supported: csv, parquet, duckdb. "
            "Custom formats can be added via the datagrove.io FormatAdapter registry "
            "(tasks 1.7-1.11)."
        )


# ---------------------------------------------------------------------------
# Helpers (module-level — small, single-consumer, but worth a name)
# ---------------------------------------------------------------------------


def _resolve_kind(source: SourceRef, format: str | None) -> str:
    """Decide which in-engine reader to use for ``source``.

    Returns one of ``"data"`` / ``"csv"`` / ``"parquet"`` / ``"duckdb"``
    / ``"csv.zip"`` / ``"zip"``. Raises :class:`NotImplementedError` for
    unsupported formats (naming the task that will add the adapter), or
    :class:`UnsupportedSourceError` for unrecognised dict shapes.

    Same shape as :func:`datagrove.engines.ibis_engine._resolve_kind` and
    :func:`datagrove.engines.polars_engine._resolve_kind` — symmetry is
    the whole point (Lens C: a reader who understands one engine should
    predict the others).
    """
    if format is not None:
        f = format.lower()
        if f in {"csv", "parquet", "duckdb", "data", "csv.zip", "zip"}:
            return f
        raise NotImplementedError(
            f"pandas engine: unsupported format {f!r}. "
            "Supported: csv, parquet, csv.zip, duckdb, data. "
            "Custom formats can be added via the datagrove.io FormatAdapter "
            "registry (tasks 1.7-1.11)."
        )

    if isinstance(source, dict):
        # Cross-engine dict-source contract (see Engine.scan docstring):
        #   {"data": ...}                                  → inline data
        #   {"format": "duckdb", "path": ..., "table": ...} → duckdb handle
        #   {"path": "x.duckdb", "table": ...}             → duckdb handle
        if "data" in source:
            return "data"
        fmt = str(source.get("format", "")).lower()
        if fmt == "duckdb":
            return "duckdb"
        path = source.get("path")
        if isinstance(path, (str, Path)) and str(path).lower().endswith(".duckdb"):
            return "duckdb"
        raise UnsupportedSourceError(
            f"pandas engine: dict source shape not recognised (keys={sorted(source)!r}). "
            "Supported shapes: {'data': [...]} for inline data, or "
            "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
        )

    lower = str(source).lower()
    # Compound extensions first.
    if lower.endswith(".csv.zip"):
        return "csv.zip"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".parquet"):
        return "parquet"
    if lower.endswith(".duckdb"):
        return "duckdb"
    if lower.endswith(".csv"):
        return "csv"
    # Anything else — name the offending extension so the message is helpful.
    suffix = Path(str(source)).suffix.lstrip(".") or "unknown"
    raise NotImplementedError(
        f"pandas engine: unsupported format {suffix!r} for source {str(source)!r}. "
        "Supported: csv, parquet, csv.zip, duckdb. "
        "Custom formats can be added via the datagrove.io FormatAdapter registry "
        "(tasks 1.7-1.11)."
    )


def _read_csv_zip(path_str: str, **kwargs: Any) -> pd.DataFrame:
    """Read a zipped csv. Single-csv-in-zip only; multi-csv defers to task 1.10."""
    import zipfile

    # Peek into the zip to count csvs and refuse the multi-csv case with
    # a helpful pointer. pandas would silently grab the first csv-ish
    # entry which is a footgun for GMNS packages (the leavenworth zip
    # has 9 csvs and a datapackage.json - wrong behavior either way).
    with zipfile.ZipFile(path_str) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if len(csv_names) > 1:
        raise NotImplementedError(
            f"pandas engine: zip contains multiple csv files {csv_names!r}; "
            "multi-table zip support is planned for task 1.10 "
            "(zipcsv FormatAdapter - see docs/architecture.md section 4). "
            "For now, extract the zip and read individual csvs."
        )
    if not csv_names:
        raise InvalidEngineCallError(f"pandas engine: zip at {path_str!r} contains no .csv files")
    # Single-csv case: pandas' compression="zip" auto-decompresses.
    return pd.read_csv(path_str, compression="zip", **kwargs)


def _read_duckdb(source: SourceRef, **kwargs: Any) -> pd.DataFrame:
    """Read a single table out of a duckdb file or handle dict (no SQL).

    Accepts both shapes:

    - A path-like (``str``, ``Path``) plus ``kwargs['table']``.
    - A duckdb handle dict (``{"format": "duckdb", "path": ..., "table": ...}``).

    Pandas has no native duckdb reader, so we use the duckdb Python
    relational API (``con.table(name)``) rather than embedding a SQL
    string — that would violate the no-raw-SQL rule (see
    ``scripts/lint_no_sql.py``).
    """
    import duckdb

    if isinstance(source, dict):
        path_str = str(source["path"])  # _resolve_kind guarantees presence
        table = source.get("table") or kwargs.pop("table", None)
    else:
        path_str = str(source)
        table = kwargs.pop("table", None)

    if table is None:
        raise InvalidEngineCallError(
            f"pandas engine: scanning a .duckdb file requires kwargs['table']; "
            f"got source={path_str!r} with no table name. "
            "Example: engine.scan('mynet.duckdb', table='node')."
        )
    con = duckdb.connect(path_str, read_only=True)
    try:
        return con.table(table).df()
    finally:
        con.close()


def _write_duckdb(df: pd.DataFrame, dest_str: str, **kwargs: Any) -> None:
    """Write ``df`` as a duckdb table via the Python API (no SQL).

    Uses ``con.register(name, df)`` to expose the DataFrame as a virtual
    relation, then ``con.table(name).create(target_table)`` to
    materialize it inside the duckdb file. Both calls are the no-SQL
    relational API: they avoid the equivalent SQL DDL string entirely
    and so stay within the lint_no_sql rule.
    """
    import duckdb

    table = kwargs.pop("table", None)
    if table is None:
        raise InvalidEngineCallError(
            "pandas engine: writing to a .duckdb file requires kwargs['table']; "
            "got no table name. Example: engine.write(df, 'mynet.duckdb', fmt='duckdb', table='node')."
        )
    con = duckdb.connect(dest_str)
    try:
        # Register the in-memory DataFrame as a temporary view, then
        # materialize it as a real table via the relational API. No SQL
        # strings cross our code boundary here.
        con.register("__datagrove_pandas_write", df)
        con.table("__datagrove_pandas_write").create(table)
    finally:
        con.unregister("__datagrove_pandas_write")
        con.close()


def _apply_schema_casts(df: pd.DataFrame, schema: Schema) -> pd.DataFrame:
    """Cast columns named in ``schema`` to pandas nullable dtypes.

    Columns absent from the schema are left untouched. Columns absent
    from the DataFrame are silently skipped (schema may describe more
    columns than the source actually carries; FK / structural validation
    in datagrove.validation surfaces missing-column errors separately).

    Same name as :func:`datagrove.engines.ibis_engine._apply_schema_casts`
    and :func:`datagrove.engines.polars_engine._apply_schema_casts` —
    symmetric API surface across the three engines.
    """
    cast: dict[str, str] = {}
    for field in schema.fields:
        if field.type is None:
            continue
        pandas_dtype = _FRICTIONLESS_TO_PANDAS_NULLABLE.get(field.type)
        if pandas_dtype is None:
            # Unknown Frictionless type (datetime, geojson, any, ...) —
            # leave as-is; validation surfaces type errors separately.
            continue
        if field.name in df.columns:
            cast[field.name] = pandas_dtype
    if cast:
        df = df.astype(cast)
    return df


__all__ = ["PandasEngine"]
