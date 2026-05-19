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
from datagrove.io._paths import normalize_to_path
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
    directory). Remote URLs are the ``remote`` adapter's job. Delegates
    to the shared :func:`datagrove.io._paths.normalize_to_path` helper so
    every adapter accepts/rejects the same SourceRef shapes.
    """
    return normalize_to_path(source, adapter="ParquetAdapter")


def _looks_partitioned(path: Path) -> bool:
    """Heuristic: does ``path`` look like a parquet dataset directory?

    True when ``path`` is a directory and either:

    * has a pyarrow ``_metadata`` / ``_common_metadata`` sidecar, or
    * has at least one direct-child ``.parquet`` file, or
    * has at least one ``key=value`` Hive-style subdirectory with a
      direct-child ``.parquet`` file.

    # WHY single-depth: GMNS's recommended Hive layout is a single
    # partition column (``h3=...`` or ``zone_id=...``); multi-level
    # Hive (``h3=x/zone=y/part.parquet``) is uncommon in our schema.
    # If you have a deeper layout, pass ``format='parquet'`` to bypass
    # this probe entirely. Short-circuit on the first hit (S2).
    """
    if not path.is_dir():
        return False
    # Pyarrow dataset sidecars — cheapest signal.
    if (path / "_metadata").exists() or (path / "_common_metadata").exists():
        return True
    # Walk a single level of children. Short-circuit on the first hit.
    for child in path.iterdir():
        if child.is_file() and child.suffix.lower() == ".parquet":
            return True
        if child.is_dir() and "=" in child.name:
            # Hive-style subdir — peek one level for a direct .parquet hit.
            for grandchild in child.iterdir():
                if grandchild.is_file() and grandchild.suffix.lower() == ".parquet":
                    return True
    return False


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

    def scan(self, source: SourceRef, engine: Engine | None = None) -> ResourceListing:
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

        For both single files and partitioned directories the adapter just
        forwards the path to ``engine.scan(source, format="parquet", ...)``.
        Each engine is responsible for detecting "this is a directory" and
        applying its own native Hive-partitioning kwargs (I3) — the adapter
        no longer dispatches on engine name, which previously coupled this
        module to the specific set of engines that existed.

        Args:
            source: Path to a ``.parquet`` file or partitioned directory.
            engine: Engine whose ``scan`` performs the actual read.
            schema: Optional Frictionless schema forwarded to the engine.
            **kwargs: Extra options forwarded verbatim to ``engine.scan``.

        Returns:
            An engine-native lazy table expression.
        """
        path = _as_path(source)
        return engine.scan(str(path), format="parquet", schema=schema, **kwargs)

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
        # ``pyarrow`` is a required datagrove dependency (see
        # ``packages/datagrove/pyproject.toml``). The local import keeps the
        # failure localized to the partitioned-write code path if dependency
        # resolution drifts in a future release.
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
