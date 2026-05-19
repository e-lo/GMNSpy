"""Polars engine — lazy-frame execution adapter (Phase 1 task 1.4, issue #51).

Polars is the lighter-weight alternative to the default ibis engine: the same
``Engine`` protocol, but every ``scan`` returns a :class:`polars.LazyFrame`
that defers work until ``.collect()`` (the per-method ``materialize`` /
``to_polars`` / ``to_pandas`` / ``write`` paths). Lazy by default is the key
Lens-A contract — pushdown happens inside polars's optimizer, not here.

This module deliberately uses polars's built-in scanners (``scan_csv`` /
``scan_parquet``) **directly** rather than going through the ``FormatAdapter``
layer. The adapter layer is still being implemented (tasks 1.7-1.11); once
those land, ``scan`` will migrate to::

    from datagrove.io import dispatch
    return dispatch(source, format=format).read(source, engine=self, schema=schema, **kwargs)

For now this engine handles the small set of formats polars knows natively
and raises a NotImplementedError with a clear pointer for everything else.

No raw SQL appears in this module. The single integration point that *might*
have needed SQL — scanning a duckdb file — uses the duckdb Python relation
API (``con.table(name).pl()``); writing a duckdb table requires a
table-creation statement which is not available here, so duckdb writes are
explicitly deferred to :class:`datagrove.engines.ibis_engine.IbisEngine`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from datagrove.types import SourceRef

from .errors import InvalidEngineCallError, UnsupportedSourceError

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
    r"""Polars-backed engine. ``scan`` returns lazy frames; ``collect`` is on you.

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

    def scan(
        self,
        source: SourceRef,
        format: str | None = None,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> pl.LazyFrame:
        r"""Open ``source`` as a :class:`polars.LazyFrame`.

        Same shape as :meth:`IbisEngine.scan` / :meth:`PandasEngine.scan`:
        a single :func:`_resolve_kind` helper picks the dispatch key,
        then a flat if/elif calls the per-kind reader, then
        :func:`_apply_schema_casts` runs once at the end on every path.

        Args:
            source: Path / URL / dict. URLs are forwarded to polars's
                scanners, which support fsspec when ``storage_options=``
                is passed in ``kwargs``. Accepted dict shapes:

                - ``{"data": [...]}`` — inline data (list of row dicts
                  or columnar dict). Returned as a lazy frame.
                - ``{"format": "duckdb", "path": "x.duckdb", "table":
                  "link"}`` — a duckdb table handle.
            format: Optional override (``"csv"`` / ``"parquet"`` /
                ``"duckdb"`` / ``"data"``). Bypasses extension sniffing.
            schema: Optional Frictionless :class:`~datagrove.spec.model.Schema`.
                When provided, columns are cast after scan per
                :data:`_FRICTIONLESS_TO_POLARS`. Applied uniformly on
                EVERY return path (dict + duckdb + file).
            **kwargs: Forwarded verbatim to the underlying polars scanner.
                Common keys: ``storage_options`` (fsspec creds),
                ``separator``, ``has_header``, ``n_rows``, ``table`` (for
                duckdb sources — names the table to open).

        Returns:
            A ``polars.LazyFrame``. Materialization happens only on
            ``.collect()`` / ``materialize()`` / ``to_polars()`` /
            ``to_pandas()``.

        Raises:
            NotImplementedError: For formats this engine doesn't (yet)
                support directly (zip, unknown extensions). The message
                points at the follow-up task (1.7-1.11) that will add
                adapter support.
            InvalidEngineCallError: For valid formats with missing
                required kwargs (e.g. ``.duckdb`` without ``table=``).
            UnsupportedSourceError: For dict sources whose shape matches
                neither ``{"data": ...}`` nor the duckdb handle.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl, tempfile, pathlib
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     p = pathlib.Path(tmp) / "t.csv"
            ...     _ = p.write_text("a,b\n1,2\n")
            ...     isinstance(PolarsEngine().scan(p), pl.LazyFrame)
            True
        """
        kind = _resolve_kind(source, format)

        if kind == "data":
            # _resolve_kind only returns "data" when source is a dict
            # carrying a "data" key — narrow for the type checker.
            assert isinstance(source, dict)
            lf = pl.LazyFrame(source["data"])
        elif kind == "csv":
            # _resolve_kind has already rejected dict sources for file-based
            # kinds; narrow to str/Path so polars's typed scanners accept it.
            lf = pl.scan_csv(str(source), **kwargs)
        elif kind == "parquet":
            # I3: detect Hive-partitioned directories here rather than in
            # the parquet adapter, so the adapter stays engine-agnostic.
            # Polars wants an explicit glob for multi-file reads; pass
            # ``hive_partitioning=True`` so partition columns survive.
            src_str = str(source)
            if not kwargs.get("hive_partitioning") and Path(src_str).is_dir():
                lf = pl.scan_parquet(f"{src_str}/**/*.parquet", hive_partitioning=True, **kwargs)
            else:
                lf = pl.scan_parquet(src_str, **kwargs)
        elif kind == "duckdb":
            lf = self._scan_duckdb(source, **kwargs)
        else:  # pragma: no cover - _resolve_kind raises before reaching here
            raise NotImplementedError(f"polars engine: source kind {kind!r} not supported")

        return _apply_schema_casts(lf, schema)

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

    def write(
        self,
        expr: pl.LazyFrame,
        dest: SourceRef,
        fmt: str,
        **kwargs: Any,
    ) -> None:
        """Persist ``expr`` to ``dest`` in format ``fmt``.

        Supported formats: ``csv``, ``parquet``. ``duckdb`` writes require
        a table-creation SQL statement which is banned from this module —
        use :class:`~datagrove.engines.ibis_engine.IbisEngine` for that path.

        Args:
            expr: A LazyFrame to materialize and write.
            dest: Target path (or fsspec URL when polars is built with
                that support and ``storage_options`` is forwarded).
            fmt: ``"csv"`` or ``"parquet"``.
            **kwargs: Forwarded to ``write_csv`` / ``write_parquet``.

        Raises:
            NotImplementedError: For ``duckdb`` (deferred to IbisEngine)
                or any other format (no adapter yet — tasks 1.7-1.11).

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl, tempfile, pathlib
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     out = pathlib.Path(tmp) / "out.csv"
            ...     PolarsEngine().write(pl.LazyFrame({"a": [1]}), out, fmt="csv")
            ...     out.exists()
            True
        """
        fmt = fmt.lower()
        if fmt == "csv":
            expr.collect().write_csv(str(dest), **kwargs)
            return
        if fmt == "parquet":
            expr.collect().write_parquet(str(dest), **kwargs)
            return
        if fmt == "duckdb":
            raise NotImplementedError(
                "polars engine: writing to duckdb requires a table-creation SQL "
                "statement which is not available in this module (no-raw-SQL rule). "
                "Use IbisEngine for duckdb writes, or export via parquet and load "
                "separately."
            )
        raise NotImplementedError(
            f"polars engine: write format={fmt!r} not supported. "
            "Use 'csv' or 'parquet'; broader format support arrives with the "
            "FormatAdapter layer (tasks 1.7-1.11)."
        )

    # ------------------------------------------------------------------
    # Internal helpers — kept inline-private since they're 1-call-site
    # ------------------------------------------------------------------

    def _scan_duckdb(self, source: SourceRef, **kwargs: Any) -> pl.LazyFrame:
        """Open one table inside a .duckdb file (path or handle dict) as a LazyFrame.

        Uses the duckdb Python relation API (``con.table(name).pl()``) so
        no SQL string is constructed. Imports duckdb lazily because it's
        only required for this one path.
        """
        # Lazy import: duckdb is a polars-optional dep at this engine's
        # boundary. We do NOT want importing polars_engine to hard-require it.
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - duckdb ships with the default install
            raise NotImplementedError(
                "polars engine: scanning .duckdb files requires the 'duckdb' package "
                "(install with `pip install duckdb`, or use the ibis engine)."
            ) from exc

        if isinstance(source, dict):
            path = source.get("path")
            table = source.get("table") or kwargs.pop("table", None)
            if not path or not table:
                raise InvalidEngineCallError(
                    f"polars engine: duckdb dict source requires 'path' and 'table' keys (got {sorted(source)})"
                )
            path_str = str(path)
        else:
            table = kwargs.pop("table", None)
            if not table:
                raise InvalidEngineCallError(
                    "polars engine: scanning a .duckdb file requires a 'table=' kwarg "
                    "naming the table to open (e.g. engine.scan(path, table='link'))"
                )
            path_str = str(source)

        con = duckdb.connect(path_str, read_only=True)
        # con.table(name) is the Python relation API — no SQL string.
        return con.table(table).pl().lazy()


# ---------------------------------------------------------------------------
# Helpers (module-level — symmetric with ibis_engine + pandas_engine)
# ---------------------------------------------------------------------------


def _suffix(source: SourceRef) -> str:
    """Return the file suffix (lowercase, no dot) for a path-like source.

    Handles compound extensions specifically for ``.csv.zip`` (the zipcsv
    adapter, task 1.10, is the eventual owner of that format).
    """
    p = Path(str(source))
    name = p.name.lower()
    # Compound: ".csv.zip" must be detected before plain ".zip".
    if name.endswith(".csv.zip"):
        return "csv.zip"
    return p.suffix.lstrip(".").lower()


def _resolve_kind(source: SourceRef, format: str | None) -> str:
    """Decide which in-engine reader to use for ``source``.

    Returns one of ``"data"`` / ``"csv"`` / ``"parquet"`` / ``"duckdb"``.
    Raises :class:`NotImplementedError` for unsupported formats (naming
    the task that will add the adapter), or
    :class:`UnsupportedSourceError` for unrecognised dict shapes.

    Same shape as :func:`datagrove.engines.ibis_engine._resolve_kind` and
    :func:`datagrove.engines.pandas_engine._resolve_kind` — symmetry is
    the whole point (Lens C: a reader who understands one engine should
    predict the others).
    """
    if format is not None:
        f = format.lower()
        if f in {"csv", "parquet", "duckdb", "data"}:
            return f
        # Compound zip — owned by zipcsv adapter (task 1.10). Polars has
        # no native zip reader; failing fast keeps the migration path
        # obvious.
        if f in {"csv.zip", "zip"}:
            raise NotImplementedError(
                f"polars engine: scanning {f!r} files requires the zipcsv format "
                "adapter (planned for task 1.10). For now: extract the csv first, "
                "or use the ibis engine."
            )
        raise NotImplementedError(
            f"polars engine: format={format!r} is not supported by the built-in "
            "polars scanners. Format adapters (tasks 1.7-1.11) will broaden this; "
            "for now use csv, parquet, or .duckdb (with table= kwarg), or fall "
            "back to the ibis engine."
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
            f"polars engine: dict source shape not recognised (keys={sorted(source)!r}). "
            "Supported shapes: {'data': [...]} for inline data, or "
            "{'format': 'duckdb', 'path': '...', 'table': '...'} for a duckdb handle."
        )

    ext = _suffix(source)
    if ext in {"csv.zip", "zip"}:
        raise NotImplementedError(
            f"polars engine: scanning {ext!r} files requires the zipcsv format "
            "adapter (planned for task 1.10). For now: extract the csv first, "
            "or use the ibis engine."
        )
    if ext == "csv":
        return "csv"
    if ext == "parquet":
        return "parquet"
    if ext == "duckdb":
        return "duckdb"
    raise NotImplementedError(
        f"polars engine: format={ext!r} is not supported by the built-in "
        "polars scanners. Format adapters (tasks 1.7-1.11) will broaden this; "
        "for now use csv, parquet, or .duckdb (with table= kwarg), or fall "
        "back to the ibis engine."
    )


def _apply_schema_casts(lf: pl.LazyFrame, schema: Schema | None) -> pl.LazyFrame:
    """Cast columns in ``lf`` per a Frictionless ``schema``.

    Unknown Frictionless types are skipped (no cast) rather than
    erroring — the v0.3 ``apply_schema_to_df`` bug was a reminder that
    silent-but-noisy is the safer default for partial schemas. Same
    naming as :func:`datagrove.engines.ibis_engine._apply_schema_casts`
    and :func:`datagrove.engines.pandas_engine._apply_schema_casts` —
    symmetric API surface across the three engines.
    """
    if schema is None or not schema.fields:
        return lf
    present = set(lf.collect_schema().names())
    casts: dict[str, type[pl.DataType]] = {
        f.name: _FRICTIONLESS_TO_POLARS[f.type]
        for f in schema.fields
        if f.type in _FRICTIONLESS_TO_POLARS and f.name in present
    }
    if not casts:
        return lf
    # polars' .cast() Mapping type uses an internal ColumnNameOrSelector /
    # PolarsDataType union; the runtime accepts dict[str, type[DataType]]
    # but the stubs don't model that overload. Safe at runtime.
    return lf.cast(casts)  # type: ignore[arg-type]


__all__ = ["PolarsEngine"]
