"""Parquet FormatAdapter — single-file and Hive-partitioned directories.

Two physical layouts share one logical "parquet table":

1. **Single file** — ``foo.parquet``. Trivial: pass the path through to
   ``engine.scan(..., format='parquet')`` and let the engine call its
   native reader.
2. **Hive-partitioned directory** — ``mynet.gmns/link/h3=8829a0c00b/part-0.parquet``
   etc. This is the **recommended persistent layout**
   (see :doc:`architecture` §6.1). Reads here must enable Hive partition
   discovery so the partition columns (``h3`` in the example above) are
   reinjected into the result, and so that a downstream filter on those
   columns becomes a true partition prune.

The adapter does no I/O itself — it routes the source through to the
engine, attaching the right kwargs per engine (duckdb auto-detects Hive
style; polars wants a glob + explicit flag; pandas uses pyarrow under
the hood and handles directories natively). Partitioned writes use
pyarrow's ``write_to_dataset`` because not every engine exposes
partitioned-write through its own writer.

Examples:
    Single-file roundtrip with the default ibis engine::

        >>> from pathlib import Path
        >>> import tempfile
        >>> import pyarrow as pa
        >>> import pyarrow.parquet as pq
        >>> from datagrove.engines import get_engine
        >>> from datagrove.io.parquet_adapter import ParquetAdapter
        >>> tmp = Path(tempfile.mkdtemp())
        >>> _ = pq.write_table(pa.table({"a": [1, 2, 3]}), tmp / "t.parquet")
        >>> adapter = ParquetAdapter()
        >>> engine = get_engine("ibis")
        >>> df = engine.to_pandas(adapter.read(tmp / "t.parquet", engine))
        >>> int(df["a"].sum())
        6
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from datagrove.io import register_adapter
from datagrove.io.base import ResourceListing, ResourceRef, SourceRef

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import Schema


# ---------------------------------------------------------------------------
# Module-level helpers (no state — easier to read inline than as methods)
# ---------------------------------------------------------------------------


def _as_path(source: SourceRef) -> Path:
    """Coerce ``source`` to a :class:`Path` for filesystem checks.

    The adapter only handles local-path-ish sources (single file or local
    directory). Remote URLs are the ``remote`` adapter's job.
    """
    if isinstance(source, Path):
        return source
    if isinstance(source, str):
        return Path(source)
    if isinstance(source, dict) and "path" in source:
        return Path(str(source["path"]))
    raise TypeError(
        f"ParquetAdapter: cannot coerce source {source!r} to a path (expected str, Path, or dict with 'path' key)"
    )


def _looks_partitioned(path: Path) -> bool:
    """Heuristic: does ``path`` look like a parquet dataset directory?

    True when ``path`` is a directory and either:

    * contains at least one ``key=value`` Hive-style subdirectory with a
      ``.parquet`` file under it, or
    * has a pyarrow ``_metadata`` / ``_common_metadata`` sidecar, or
    * has at least one direct-child ``.parquet`` file.

    The check is shallow (one level deep into Hive subdirs) — partitioned
    datasets in the wild can nest several levels, but a single hit on the
    first level is enough to identify the directory as parquet-shaped.
    """
    if not path.is_dir():
        return False
    # Pyarrow dataset sidecars.
    if (path / "_metadata").exists() or (path / "_common_metadata").exists():
        return True
    # Walk one level of children.
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() == ".parquet":
            return True
        # Hive-style subdir like ``h3=abc``.
        if child.is_dir() and "=" in child.name:
            for grandchild in child.iterdir():
                if grandchild.is_file() and grandchild.suffix.lower() == ".parquet":
                    return True
                # One more level for nested partitions like h3=x/zone=y/part.parquet
                if grandchild.is_dir() and "=" in grandchild.name:
                    for great in grandchild.iterdir():
                        if great.is_file() and great.suffix.lower() == ".parquet":
                            return True
    return False


def _engine_scan_args(path: Path, engine_name: str) -> tuple[str, dict[str, Any]]:
    """Build ``(source_str, kwargs)`` for ``engine.scan`` given path + engine.

    Each engine wants partitioned-directory reads expressed differently:

    * ibis (duckdb) — ``read_parquet(directory, hive_partitioning=True)``.
      duckdb auto-detects Hive style with the flag.
    * polars — ``scan_parquet("dir/**/*.parquet", hive_partitioning=True)``.
      polars needs a glob, not a directory, for multi-file reads.
    * pandas — ``read_parquet(directory)``. pyarrow under the hood already
      handles partitioned directories with no extra kwargs.

    For single files, all three engines accept the path verbatim; no
    kwargs added.
    """
    is_dir = path.is_dir()
    if not is_dir:
        return str(path), {}

    if engine_name == "polars":
        return f"{path}/**/*.parquet", {"hive_partitioning": True}
    if engine_name == "ibis":
        return str(path), {"hive_partitioning": True}
    # pandas / unknown engines: directory path alone is enough (pyarrow).
    return str(path), {}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ParquetAdapter:
    """Adapter for single-file and partitioned parquet datasets.

    The adapter declares the ``parquet`` extension only — Hive-partitioned
    directories are matched via :meth:`probe`, since they have no extension
    of their own.

    Attributes:
        name: ``"parquet"`` — registry key.
        extensions: ``("parquet",)`` — single-file extension binding.
        schemes: ``()`` — no URL schemes (the remote adapter handles
            ``s3://``/``https://``).
    """

    name: str = "parquet"
    extensions: tuple[str, ...] = ("parquet",)
    schemes: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # probe
    # ------------------------------------------------------------------

    def probe(self, source: SourceRef) -> bool:
        """Return True if ``source`` looks like parquet.

        Accepts a ``.parquet`` extension (single-file case) OR an existing
        directory that looks parquet-shaped (Hive-style ``key=value``
        subdirs containing ``.parquet`` files, or a ``_metadata`` sidecar,
        or direct-child ``.parquet`` files). Never raises.

        Args:
            source: Candidate source — string path, ``Path``, or dict
                handle with a ``"path"`` key.

        Returns:
            True if the adapter is willing to read ``source``.

        Examples:
            >>> from pathlib import Path
            >>> ParquetAdapter().probe(Path("foo.parquet"))
            True
            >>> ParquetAdapter().probe("foo.csv")
            False
        """
        try:
            path = _as_path(source)
        except TypeError:
            return False

        # Cheap path: extension match — no filesystem touch needed.
        if path.suffix.lower() == ".parquet":
            return True

        # Slow path: directory check + shallow walk.
        try:
            return _looks_partitioned(path)
        except (OSError, PermissionError):
            return False

    # ------------------------------------------------------------------
    # scan — single ResourceRef whether single file or partitioned dir
    # ------------------------------------------------------------------

    def scan(self, source: SourceRef, engine: Engine) -> ResourceListing:
        """Enumerate the (single) resource at ``source``.

        Parquet is single-table-per-file (and single-table-per-dataset for
        the partitioned case), so this always returns a one-element
        listing. The resource's ``name`` is the file stem for single files
        and the directory basename for partitioned dirs.

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            engine: Unused — kept for protocol parity.

        Returns:
            A one-element :data:`ResourceListing`.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile, pyarrow as pa, pyarrow.parquet as pq
            >>> from datagrove.engines import get_engine
            >>> tmp = Path(tempfile.mkdtemp())
            >>> _ = pq.write_table(pa.table({"a": [1]}), tmp / "t.parquet")
            >>> refs = ParquetAdapter().scan(tmp / "t.parquet", get_engine("ibis"))
            >>> refs[0].name
            't'
        """
        del engine  # protocol parity; we don't need it for scan
        path = _as_path(source)
        # Single file: use the stem (strip ``.parquet``). Directory: use the
        # basename so the dataset's logical name matches the folder name.
        # ``Path("dataset/").name`` is ``""``; fall back to ``parent.name``
        # so trailing slashes don't change the logical name.
        name = path.stem if path.suffix.lower() == ".parquet" else path.name or path.parent.name
        return [ResourceRef(name=name or "parquet", path=str(path), format=self.name)]

    # ------------------------------------------------------------------
    # read — delegates to engine.scan with format=parquet + Hive kwargs
    # ------------------------------------------------------------------

    def read(
        self,
        source: SourceRef,
        engine: Engine,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> TableExpr:
        """Return a lazy table expression for ``source``.

        For single files this is a plain pass-through. For directories the
        adapter injects the right engine-specific kwargs to enable Hive
        partition discovery (see :func:`_engine_scan_args`).

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            engine: Engine whose ``scan`` performs the actual read.
            schema: Optional Frictionless schema forwarded to the engine.
            **kwargs: Extra options forwarded verbatim to ``engine.scan``.
                For partitioned reads, engine-specific Hive kwargs are
                merged in first; caller kwargs win on conflict.

        Returns:
            An engine-native lazy table expression.
        """
        path = _as_path(source)
        engine_name = getattr(engine, "name", "")
        source_str, scan_kwargs = _engine_scan_args(path, engine_name)
        # Caller kwargs override our injected defaults (e.g. ``columns=``).
        merged = {**scan_kwargs, **kwargs}
        return engine.scan(source_str, format="parquet", schema=schema, **merged)

    # ------------------------------------------------------------------
    # write — single file via engine; partitioned via pyarrow
    # ------------------------------------------------------------------

    def write(
        self,
        expr: TableExpr,
        dest: SourceRef,
        engine: Engine,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` to ``dest`` as parquet.

        Two modes:

        * **Single file** (default) — delegates to
          ``engine.write(expr, dest, fmt='parquet', **kwargs)``.
        * **Partitioned** — caller passes ``partition_by=['col', ...]``.
          We materialize ``expr`` through pyarrow and call
          :func:`pyarrow.parquet.write_to_dataset` with a Hive-style
          partitioning. We use pyarrow directly (rather than per-engine
          partitioned writers) so the on-disk layout is consistent across
          engines and the partition columns end up encoded in directory
          names rather than the data files.

        Args:
            expr: Engine-native table expression.
            dest: Path to write to. For partitioned writes this is the
                root directory; partition subdirs are created under it.
            engine: Engine for the single-file path; for partitioned
                writes only used to convert to pandas/pyarrow.
            **kwargs: Forwarded to the writer.

                * ``partition_by`` (``list[str]``, optional) — Hive
                  partition columns. Triggers the partitioned-write path.

        Examples:
            >>> from pathlib import Path
            >>> import tempfile, pyarrow as pa, pyarrow.parquet as pq
            >>> from datagrove.engines import get_engine
            >>> tmp = Path(tempfile.mkdtemp())
            >>> _ = pq.write_table(pa.table({"a": [1, 2]}), tmp / "in.parquet")
            >>> adapter = ParquetAdapter()
            >>> engine = get_engine("ibis")
            >>> expr = adapter.read(tmp / "in.parquet", engine)
            >>> adapter.write(expr, tmp / "out.parquet", engine)
            >>> (tmp / "out.parquet").exists()
            True
        """
        partition_by = kwargs.pop("partition_by", None)

        if partition_by:
            self._write_partitioned(expr, dest, engine, partition_by, **kwargs)
            return

        # Single-file: defer to the engine's parquet writer.
        dest_path = _as_path(dest)
        engine.write(expr, str(dest_path), fmt="parquet", **kwargs)

    def _write_partitioned(
        self,
        expr: TableExpr,
        dest: SourceRef,
        engine: Engine,
        partition_by: list[str],
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` as a Hive-partitioned parquet dataset under ``dest``.

        Implementation note — we hop through pandas → pyarrow rather than
        let each engine's writer do its own partitioning, because:

        * The polars and pandas engines don't expose partitioned-write at
          the ``engine.write`` level.
        * Pyarrow's ``write_to_dataset`` produces Hive layout
          (``col=value/part-N.parquet``) by default, which is exactly what
          duckdb auto-detects on read.
        """
        # Local import keeps the cold-import time of this module small —
        # pyarrow is in datagrove deps so this never fails in practice.
        import pyarrow as pa
        import pyarrow.parquet as pq

        dest_path = _as_path(dest)
        dest_path.mkdir(parents=True, exist_ok=True)

        # All three engines support to_pandas; pyarrow.Table.from_pandas
        # is the cheapest cross-engine convergence point. For ibis we
        # could avoid the pandas round-trip via ``.to_pyarrow()``, but
        # ``to_pandas`` is the documented cross-engine contract.
        df = engine.to_pandas(expr)
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_to_dataset(
            table,
            root_path=str(dest_path),
            partition_cols=list(partition_by),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Self-registration on import
# ---------------------------------------------------------------------------

register_adapter(ParquetAdapter())


__all__ = ["ParquetAdapter"]
