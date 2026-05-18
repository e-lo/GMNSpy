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

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from datagrove.spec.model import Schema


def _suffix(source: SourceRef) -> str:
    """Return the file suffix (lowercase, no dot) for a path-like source.

    Handles compound extensions specifically for ``.csv.zip`` (the zipcsv
    adapter, task 1.10, is the eventual owner of that format).
    """
    if isinstance(source, dict):
        return str(source.get("format", "")).lower()
    p = Path(str(source))
    # Compound: ".csv.zip" must be detected before plain ".zip".
    name = p.name.lower()
    if name.endswith(".csv.zip"):
        return "csv.zip"
    return p.suffix.lstrip(".").lower()


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

        Resolution order:
            1. Explicit ``format=`` kwarg (overrides everything).
            2. Filename extension on ``source`` (handles ``.csv``, ``.parquet``,
               ``.duckdb``, ``.csv.zip`` / ``.zip``).
            3. ``dict`` sources: ``{"data": [...]}`` or ``{"format": ...,
               "path": ..., "table": ...}`` (the latter for duckdb refs).

        Args:
            source: Path / URL / dict. URLs are forwarded to polars's
                scanners, which support fsspec when ``storage_options=``
                is passed in ``kwargs``.
            format: Optional override (``"csv"`` / ``"parquet"`` /
                ``"duckdb"``). Bypasses extension sniffing.
            schema: Optional Frictionless :class:`~datagrove.spec.model.Schema`.
                When provided, columns are cast after scan per a small
                Frictionless-to-polars type map.
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

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl, tempfile, pathlib
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     p = pathlib.Path(tmp) / "t.csv"
            ...     _ = p.write_text("a,b\n1,2\n")
            ...     isinstance(PolarsEngine().scan(p), pl.LazyFrame)
            True
        """
        # dict source — explicit handle. The "data" arm lets callers build
        # in-memory frames the same way they pass file paths; "table" + "path"
        # is the duckdb-relation arm.
        if isinstance(source, dict):
            if "data" in source:
                return pl.LazyFrame(source["data"])
            fmt = (format or source.get("format") or "").lower()
            if fmt == "duckdb":
                path = source.get("path")
                table = source.get("table") or kwargs.get("table")
                if not path or not table:
                    raise ValueError(
                        f"polars engine: duckdb dict source requires 'path' and 'table' keys (got {sorted(source)})"
                    )
                return self._scan_duckdb(path, table)
            raise NotImplementedError(
                f"polars engine: dict source with format={fmt!r} not supported "
                "(pass 'data' for inline data or use a duckdb handle)"
            )

        ext = (format or _suffix(source)).lower()

        # Compound zip — owned by zipcsv adapter (task 1.10). Polars has no
        # native zip reader; failing fast keeps the migration path obvious.
        if ext in {"csv.zip", "zip"}:
            raise NotImplementedError(
                f"polars engine: scanning {ext!r} files requires the zipcsv format "
                "adapter (planned for task 1.10). For now: extract the csv first, "
                "or use the ibis engine."
            )

        if ext == "csv":
            lf = pl.scan_csv(source, **kwargs)
        elif ext == "parquet":
            lf = pl.scan_parquet(source, **kwargs)
        elif ext == "duckdb":
            table = kwargs.pop("table", None)
            if not table:
                raise ValueError(
                    "polars engine: scanning a .duckdb file requires a 'table=' kwarg "
                    "naming the table to open (e.g. engine.scan(path, table='link'))"
                )
            return self._apply_schema(self._scan_duckdb(source, table), schema)
        else:
            raise NotImplementedError(
                f"polars engine: format={ext!r} is not supported by the built-in "
                "polars scanners. Format adapters (tasks 1.7-1.11) will broaden this; "
                "for now use csv, parquet, or .duckdb (with table= kwarg), or fall "
                "back to the ibis engine."
            )

        return self._apply_schema(lf, schema)

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
        """Materialize ``expr`` and return a ``pandas.DataFrame`` via Arrow.

        The Arrow path (``use_pyarrow_extension_array=True``) preserves
        nullable integers and avoids the float64 upcasting that pandas's
        legacy code-path applies to columns with nulls; it is also faster
        for wide / long frames.

        Examples:
            >>> from datagrove.engines.polars_engine import PolarsEngine
            >>> import polars as pl
            >>> lazy = pl.LazyFrame({"a": [1, 2]})
            >>> pdf = PolarsEngine().to_pandas(lazy)
            >>> list(pdf.columns), len(pdf)
            (['a'], 2)
        """
        return expr.collect().to_pandas(use_pyarrow_extension_array=True)

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

    def _scan_duckdb(self, source: SourceRef, table: str) -> pl.LazyFrame:
        """Open ``table`` inside a .duckdb file as a LazyFrame.

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
        con = duckdb.connect(str(source), read_only=True)
        # con.table(name) is the Python relation API — no SQL string.
        return con.table(table).pl().lazy()

    def _apply_schema(self, lf: pl.LazyFrame, schema: Schema | None) -> pl.LazyFrame:
        """Cast columns in ``lf`` per a Frictionless ``schema``.

        Inlined per Lens C: the type map is small, used only here, and
        reads more clearly at point-of-use than imported from elsewhere.
        Unknown Frictionless types are skipped (no cast) rather than
        erroring — the v0.3 ``apply_schema_to_df`` bug was a reminder
        that silent-but-noisy is the safer default for partial schemas.
        """
        if schema is None or not schema.fields:
            return lf
        # Frictionless → polars dtype. Conservative subset; columns whose
        # Frictionless type isn't in this map are left as polars inferred.
        type_map: dict[str, type[pl.DataType]] = {
            "integer": pl.Int64,
            "number": pl.Float64,
            "string": pl.Utf8,
            "boolean": pl.Boolean,
        }
        present = set(lf.collect_schema().names())
        casts: dict[str, type[pl.DataType]] = {
            f.name: type_map[f.type] for f in schema.fields if f.type in type_map and f.name in present
        }
        if not casts:
            return lf
        # polars' .cast() Mapping type uses an internal ColumnNameOrSelector /
        # PolarsDataType union; the runtime accepts dict[str, type[DataType]]
        # but the stubs don't model that overload. Safe at runtime.
        return lf.cast(casts)  # type: ignore[arg-type]


__all__ = ["PolarsEngine"]
