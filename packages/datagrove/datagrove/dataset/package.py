"""Lazy multi-table package wrapper — see :class:`Package`.

A :class:`Package` is the user-facing surface for "a Frictionless data
package opened lazily through one of the datagrove engines". It bundles:

* the parsed :class:`~datagrove.spec.model.DataPackage` (the *spec* —
  what should be at the source);
* a mapping ``{table_name: Table}`` of :class:`~datagrove.dataset.Table`
  instances (the *data* — engine-native lazy expressions plus
  metadata);
* the :class:`~datagrove.engines.base.Engine` that produced them;
* the original ``source`` identifier (path/URL) for round-trip writes;
* an optional :class:`~datagrove.validation.sync_state.DirtyTracker`
  (task 2.6) — when absent the sync-state validation pass and the
  pre-write sync check both no-op gracefully.

The dispatch surface that powers :meth:`Package.from_source` is the
:mod:`datagrove.io` :class:`~datagrove.io.base.FormatAdapter` registry.
Resolution order (per `docs/architecture.md` §6.1 + the io package
docstring):

    1. explicit ``format=`` short-circuits sniffing;
    2. URL scheme (``duckdb://``, ``s3://``, ...);
    3. file extension (``.csv``, ``.parquet``, ``.duckdb``, ``.csv.zip``);
    4. directory-of-known-formats walk (``csv/``, ``parquet/``);
    5. ``probe`` chain (any adapter that recognises the source);
    6. :class:`~datagrove.io.FormatNotDetected`.

The directory-of-files branch deserves its own callout: the Leavenworth
``csv/`` and ``parquet/`` shapes have no extension to dispatch on, so
:meth:`Package.from_source` walks the children and asks each adapter
whose declared extension matches a child to scan that child. This
mirrors :func:`datagrove.validation.structural._scan_directory_of_known_formats`
so the structural validator and the package loader can't drift apart on
"what counts as a directory of tables".

Sync-state contract
-------------------

The :class:`DirtyTracker` (task 2.6) records per-table content hashes
and exposes:

* ``stamp_table(name, expr, engine) -> TableHash`` — record a fresh
  hash after a clean validation pass;
* ``is_table_dirty(name, expr, engine) -> bool`` — compare the live
  expression's hash against the stamped one;
* ``check(current_tables, engine, report, strict) -> ValidationReport``
  — walk every stamped table, emit one ``sync.*`` issue per stale one;
* ``mark_dirty(name)`` — manually flip the stale flag.

:meth:`Package.write` calls :meth:`DirtyTracker.is_table_dirty` (when a
tracker is attached) plus the per-:class:`Table` ``dirty`` flag. Either
signal triggers :class:`OutOfSyncWarning` (or :class:`OutOfSyncError`
under ``strict_sync=True``). When no tracker is attached the per-table
flag alone is consulted — so a user can still flag a mutation via
:meth:`Table.invalidate` without installing the tracker.
"""

from __future__ import annotations

import shutil
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from datagrove.engines import get_engine
from datagrove.io import (
    FormatNotDetected,
    ResourceListing,
    ResourceRef,
    dispatch,
    get_adapter,
    list_adapters,
)
from datagrove.reports import ValidationReport
from datagrove.spec.loader import load_package
from datagrove.spec.model import DataPackage, Resource, Schema
from datagrove.validation import (
    check_foreign_keys,
    check_structural,
)
from datagrove.validation.schema_check import check_schema

from .table import Table

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine

# ---------------------------------------------------------------------------
# Optional sync-state import — task 2.6 may or may not have landed yet.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised by the dirty-tracker-optional test
    from datagrove.validation.sync_state import DirtyTracker as _DirtyTrackerImpl
except ImportError:  # pragma: no cover - task 2.6 not landed yet
    _DirtyTrackerImpl = None  # type: ignore[assignment]


# Re-exported at module level so callers can type-annotate against it
# without caring whether 2.6 has merged. When the import fails, the
# alias is ``None`` and ``Package`` accepts ``None`` as the tracker.
DirtyTracker = _DirtyTrackerImpl


__all__ = ["DirtyTracker", "OutOfSyncError", "OutOfSyncWarning", "Package"]


# ---------------------------------------------------------------------------
# Sync-state errors
# ---------------------------------------------------------------------------


class OutOfSyncWarning(Warning):
    """Raised when :meth:`Package.write` runs against a stale package.

    Demoted from an error to a warning by default so a routine save
    after an unintentional edit still produces a file (with a loud
    warning). Promote to :class:`OutOfSyncError` via
    ``strict_sync=True``.
    """


class OutOfSyncError(Exception):
    """Promoted version of :class:`OutOfSyncWarning`.

    Raised by :meth:`Package.write` when ``strict_sync=True`` and the
    sync-state check detects at least one stale table.
    """


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------


@dataclass
class Package:
    """Lazy wrapper around a multi-table Frictionless data package.

    Composes the spec, the table mapping, the engine, the source
    locator, and (optionally) the sync-state :class:`DirtyTracker`. The
    primary constructors are :meth:`from_source` (load from a path/URL)
    and :meth:`from_tables` (compose from already-built
    :class:`~datagrove.dataset.Table` instances).

    Attributes:
        spec: The parsed :class:`~datagrove.spec.model.DataPackage`.
        tables: Mapping ``{name: Table}``. Insertion order is preserved
            (Python 3.7+) so iteration is deterministic.
        engine: The :class:`~datagrove.engines.base.Engine` that
            produced the table expressions. All materialisation routes
            back through this same engine.
        source: Original source identifier (path / URL). ``None`` for
            in-memory packages built via :meth:`from_tables`.
        dirty_tracker: Optional sync-state tracker. When ``None``, the
            sync-state validation pass is a no-op and :meth:`write`
            consults only the per-table ``dirty`` flag.
        metadata: Free-form bag of extras (engine name, write
            timestamp, etc.); echoed into the JSON validation report.

    Examples:
        Load the bundled Leavenworth GMNS fixture, validate, then
        write to a fresh parquet directory::

            >>> import tempfile, pathlib
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.dataset import Package
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import gmnspy
            >>> spec = pathlib.Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"
            >>> pkg = Package.from_source(
            ...     leavenworth.csv_dir(),
            ...     engine=PandasEngine(),
            ...     spec=spec,
            ...     tables=["link", "node"],
            ... )
            >>> "link" in pkg
            True
            >>> report = pkg.validate()
            >>> isinstance(report.issues, list)
            True
    """

    spec: DataPackage
    tables: dict[str, Table] = field(default_factory=dict)
    engine: Engine | None = None
    source: str | None = None
    dirty_tracker: Any = None  # DirtyTracker | None — Any because the type may be unimportable.
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_source(
        cls,
        source: str | Path,
        *,
        engine: Engine | None = None,
        spec: DataPackage | str | Path | None = None,
        tables: Iterable[str] | None = None,
    ) -> Package:
        """Build a :class:`Package` from a source path/URL.

        Dispatch order:

            1. Resolve ``engine`` (default: registry default).
            2. Resolve ``spec`` — explicit ``DataPackage`` wins;
               otherwise look for a ``datapackage.json`` alongside
               ``source``; otherwise synthesise a minimal spec from
               whatever resources are discovered.
            3. Resolve ``source`` to a :class:`ResourceListing` via the
               :mod:`datagrove.io` dispatcher, falling back to a
               directory-of-known-formats walk for ``csv/``/``parquet/``
               shapes that have no extension.
            4. For each :class:`~datagrove.io.base.ResourceRef`, ask the
               owning adapter to ``read`` it lazily through ``engine``,
               then wrap the resulting :class:`~datagrove.engines.base.TableExpr`
               in a :class:`~datagrove.dataset.Table`. The spec is
               consulted for the matching :class:`~datagrove.spec.model.Schema`
               so the validation layer doesn't have to re-load it.

        Args:
            source: Path / URL / directory pointing at the data
                package. Anything :func:`datagrove.io.dispatch` knows
                about, plus the directory-of-files convention.
            engine: Engine to materialise through. Defaults to the
                registered default (typically
                :class:`~datagrove.engines.ibis_engine.IbisEngine`).
            spec: Either an in-memory :class:`DataPackage`, a path /
                URL to a ``datapackage.json``, or ``None`` to
                auto-discover.
            tables: Optional subset of resource names to load. Useful
                for memory-efficient partial loads.

        Returns:
            A populated :class:`Package` with lazy :class:`Table`
            entries.

        Raises:
            FormatNotDetected: If neither extension dispatch nor the
                directory walk could resolve ``source``.

        Examples:
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.dataset import Package
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import gmnspy, pathlib
            >>> spec = pathlib.Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"
            >>> pkg = Package.from_source(
            ...     leavenworth.csv_dir(),
            ...     engine=PandasEngine(),
            ...     spec=spec,
            ...     tables=["link"],
            ... )
            >>> list(pkg.keys())
            ['link']
        """
        eng = engine if engine is not None else get_engine()
        source_str = str(source)
        # 1. Resolve spec.
        resolved_spec = _resolve_spec(spec, source_str)

        # 2. Discover resources.
        listing = _scan_source(source_str)

        # 3. Filter by requested subset (if any).
        wanted: set[str] | None = set(tables) if tables is not None else None
        if wanted is not None:
            listing = [ref for ref in listing if ref.name in wanted]

        # 4. Build the Table mapping by deferring each read to the
        #    appropriate adapter. The adapter calls the engine's
        #    per-format primitive — we never embed format dispatch here.
        tables_out: dict[str, Table] = {}
        for ref in listing:
            schema = _schema_for(resolved_spec, ref.name)
            adapter = get_adapter(ref.format)
            read_kwargs: dict[str, Any] = {}
            # The duckdb adapter requires a ``table=`` kwarg per its
            # multi-table contract; the ResourceRef.path encodes the
            # ``"file::table"`` sub-locator that scan() produced.
            if ref.format == "duckdb":
                path_str, _, table_name = ref.path.rpartition("::")
                if not path_str:
                    path_str = ref.path
                    table_name = ref.name
                read_kwargs["table"] = table_name
                expr = adapter.read(path_str, engine=eng, schema=schema, **read_kwargs)
            else:
                expr = adapter.read(ref.path, engine=eng, schema=schema, **read_kwargs)
            tables_out[ref.name] = Table(
                name=ref.name,
                expr=expr,
                engine=eng,
                schema=schema,
                source=ref.path,
                format=ref.format,
            )

        return cls(
            spec=resolved_spec,
            tables=tables_out,
            engine=eng,
            source=source_str,
        )

    @classmethod
    def from_tables(
        cls,
        tables: Mapping[str, Table],
        *,
        spec: DataPackage | None = None,
        engine: Engine | None = None,
    ) -> Package:
        """Build a :class:`Package` from already-constructed :class:`Table` instances.

        Useful for tests, ad-hoc compositions, and adapter-less in-memory
        sources. When ``spec`` is not provided, a minimal one is
        synthesised so :meth:`validate` and the dict-like surface still
        work.

        Args:
            tables: Mapping ``{name: Table}``.
            spec: Optional explicit :class:`DataPackage`. Synthesised
                from ``tables`` when ``None``.
            engine: Optional explicit engine. Defaults to the first
                table's engine.

        Returns:
            A new :class:`Package`.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> link = Table(name="link", expr=e.from_records([{"id": 1}]), engine=e)
            >>> p = Package.from_tables({"link": link})
            >>> "link" in p
            True
        """
        if engine is None:
            engine = next(iter(tables.values())).engine if tables else get_engine()
        if spec is None:
            spec = DataPackage(
                name="synthesized",
                resources=[Resource(name=name) for name in tables],
            )
        return cls(spec=spec, tables=dict(tables), engine=engine)

    # ------------------------------------------------------------------
    # Dict-like access
    # ------------------------------------------------------------------

    def __getitem__(self, name: str) -> Table:
        """Return the :class:`Table` named ``name``.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> t = Table(name="link", expr=e.from_records([{"id": 1}]), engine=e)
            >>> Package.from_tables({"link": t})["link"].name
            'link'
        """
        return self.tables[name]

    def __contains__(self, name: object) -> bool:
        """``True`` if ``name`` is a known table name."""
        return name in self.tables

    def __iter__(self):
        """Iterate over table names in insertion order."""
        return iter(self.tables)

    def __len__(self) -> int:
        """Return the number of tables."""
        return len(self.tables)

    def keys(self) -> list[str]:
        """Return the table names as a list (insertion order)."""
        return list(self.tables.keys())

    def values(self) -> list[Table]:
        """Return the tables as a list (insertion order)."""
        return list(self.tables.values())

    def items(self) -> list[tuple[str, Table]]:
        """Return ``(name, table)`` pairs as a list (insertion order)."""
        return list(self.tables.items())

    # ------------------------------------------------------------------
    # Validation orchestration
    # ------------------------------------------------------------------

    def validate(
        self,
        *,
        schema: bool = True,
        structural: bool = True,
        foreign_keys: bool = True,
        sync_state: bool = True,
        strict: bool = False,
    ) -> ValidationReport:
        """Run the selected validation passes and return the combined report.

        Order: structural → schema (per table) → foreign_keys →
        sync_state. Each pass appends issues to the same report. Skip
        any pass by passing ``False`` for its flag.

        Args:
            schema: Run per-table schema validation
                (:func:`datagrove.validation.check_schema`).
            structural: Run structural validation
                (:func:`datagrove.validation.check_structural`).
            foreign_keys: Run FK validation
                (:func:`datagrove.validation.check_foreign_keys`).
            sync_state: Consult the :class:`DirtyTracker` (when attached)
                via its ``check`` method. No-op when no tracker is
                attached.
            strict: Forwarded to validators that accept it (FK
                ``unverifiable`` becomes ERROR instead of WARNING).

        Returns:
            A :class:`~datagrove.validation.ValidationReport` populated
            with one :class:`~datagrove.validation.Issue` per finding.

        Examples:
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.dataset import Package
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> import gmnspy, pathlib
            >>> spec = pathlib.Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"
            >>> pkg = Package.from_source(
            ...     leavenworth.csv_dir(),
            ...     engine=PandasEngine(),
            ...     spec=spec,
            ...     tables=["link", "node"],
            ... )
            >>> r = pkg.validate()
            >>> isinstance(r.issues, list)
            True
        """
        report = ValidationReport(source=self.source)

        # Structural: what the spec says should be here vs. what we
        # actually loaded. The actual_resources list is built from the
        # loaded Tables (not a fresh scan) so partial loads don't
        # spuriously look "missing".
        if structural:
            actual: ResourceListing = [
                ResourceRef(name=t.name, path=t.source or t.name, format=t.format or "") for t in self.tables.values()
            ]
            check_structural(self.spec, source=self.source, actual_resources=actual, report=report)

        # Schema: per-table per-field rules. Iterates only over loaded
        # tables (a partial load skips schemas it can't run).
        if schema and self.engine is not None:
            for table in self.tables.values():
                if table.schema is None:
                    continue
                check_schema(
                    table.expr,
                    table.schema,
                    table_name=table.name,
                    report=report,
                )

        # Foreign keys: needs the full table mapping.
        if foreign_keys and self.engine is not None:
            check_foreign_keys(
                self.spec,
                {name: t.expr for name, t in self.tables.items()},
                report=report,
                strict=strict,
            )

        # Sync state: only meaningful with a tracker. The contract
        # (`DirtyTracker.check`) is documented on task 2.6; we keep
        # the call site minimal so the tracker can grow surfaces
        # without forcing us back here.
        if sync_state and self.dirty_tracker is not None and self.engine is not None:
            self.dirty_tracker.check(
                {name: t.expr for name, t in self.tables.items()},
                engine=self.engine,
                report=report,
                strict=strict,
            )

        return report

    # ------------------------------------------------------------------
    # Scope (table + column subset)
    # ------------------------------------------------------------------

    def scope(
        self,
        *,
        tables: Iterable[str] | None = None,
        columns: Mapping[str, list[str]] | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        polygon: Any = None,
        geometry_buffer: tuple[Any, float] | None = None,
        geometry_column: str = "geometry",
    ) -> Package:
        """Return a new :class:`Package` restricted to a table / column / spatial subset.

        Composes table+column subsetting with the spatial scopes in
        :mod:`datagrove.dataset.view`. The spatial kwargs (``bbox``,
        ``polygon``, ``geometry_buffer``) apply to **every** loaded
        table that carries ``geometry_column``; tables without that
        column are passed through untouched (link/node/use_definition
        in the GMNS convention only the ``geometry`` table holds WKT,
        so an ``bbox=`` scope effectively filters geometry and the
        caller relies on FK trimming in a follow-up pass).

        Exactly one of ``bbox`` / ``polygon`` / ``geometry_buffer`` may
        be supplied per call. The returned :class:`Package` shares the
        same spec + engine + dirty tracker; only the table mapping is
        filtered.

        Args:
            tables: Optional iterable of table names to keep.
            columns: Optional ``{table_name: [col, ...]}`` projection.
            bbox: ``(minx, miny, maxx, maxy)`` — forwarded to
                :func:`datagrove.dataset.view.from_bbox`.
            polygon: A shapely (multi-)polygon or WKT string —
                forwarded to :func:`datagrove.dataset.view.from_polygon`.
            geometry_buffer: ``(geometry, distance_m)`` — forwarded to
                :func:`datagrove.dataset.view.from_geometry_buffer`.
            geometry_column: WKT/WKB column name shared across the
                spatial calls. Default ``"geometry"``.

        Returns:
            A new :class:`Package` carrying the subset.

        Raises:
            ValueError: If more than one spatial scope kwarg is set.

        Examples:
            Table subset (the original surface)::

                >>> from gmnspy.fixtures import leavenworth
                >>> from datagrove.dataset import Package
                >>> from datagrove.engines.pandas_engine import PandasEngine
                >>> import gmnspy, pathlib
                >>> spec = pathlib.Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"
                >>> pkg = Package.from_source(
                ...     leavenworth.csv_dir(),
                ...     engine=PandasEngine(),
                ...     spec=spec,
                ...     tables=["link", "node"],
                ... )
                >>> pkg.scope(tables=["link"]).keys()
                ['link']
        """
        from .view import from_bbox, from_geometry_buffer, from_polygon

        spatial_count = sum(1 for x in (bbox, polygon, geometry_buffer) if x is not None)
        if spatial_count > 1:
            raise ValueError(
                "Package.scope: at most one of bbox=, polygon=, geometry_buffer= may be set per call."
            )

        # Table filter.
        if tables is not None:
            wanted = set(tables)
            scoped = {name: t for name, t in self.tables.items() if name in wanted}
        else:
            scoped = dict(self.tables)

        # Column filter — only touches the named tables.
        if columns:
            for table_name, cols in columns.items():
                if table_name in scoped:
                    scoped[table_name] = scoped[table_name].select(*cols)

        # Spatial filter — applied to every table that has the geometry
        # column. ``from_*`` no-ops on tables that don't, so this is
        # safe to fan out blindly.
        if bbox is not None:
            minx, miny, maxx, maxy = bbox
            scoped = {
                name: from_bbox(t, minx, miny, maxx, maxy, geometry_column=geometry_column)
                for name, t in scoped.items()
            }
        elif polygon is not None:
            scoped = {name: from_polygon(t, polygon, geometry_column=geometry_column) for name, t in scoped.items()}
        elif geometry_buffer is not None:
            geom, distance_m = geometry_buffer
            scoped = {
                name: from_geometry_buffer(t, geom, distance_m, geometry_column=geometry_column)
                for name, t in scoped.items()
            }

        return Package(
            spec=self.spec,
            tables=scoped,
            engine=self.engine,
            source=self.source,
            dirty_tracker=self.dirty_tracker,
            metadata=dict(self.metadata),
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(
        self,
        dest: str | Path,
        *,
        format: str | None = None,
        overwrite: bool = False,
        strict_sync: bool = False,
    ) -> None:
        """Persist every table in the package to ``dest``.

        Before writing, runs the sync-state check (per-table ``dirty``
        flag plus :class:`DirtyTracker.is_table_dirty` if a tracker is
        attached). Any stale table triggers :class:`OutOfSyncWarning`,
        or :class:`OutOfSyncError` under ``strict_sync=True``.

        Format dispatch goes through :mod:`datagrove.io` exactly as on
        the read path:

        * ``format`` explicit → adapter resolved by name;
        * else inferred from ``dest`` extension;
        * else default to ``"parquet"`` when ``dest`` looks like a
          directory.

        For partitioned/multi-table formats (parquet directory, duckdb
        file), each :class:`Table` writes to a per-table location under
        ``dest``. The exact layout matches the read-side scan so a
        round-trip via :meth:`from_source` returns the same logical
        package.

        Args:
            dest: Target directory or file.
            format: Optional explicit format name.
            overwrite: When ``False`` (the default), refuses to clobber
                an existing ``dest``. When ``True``, removes the existing
                target first.
            strict_sync: When ``True``, stale tables raise
                :class:`OutOfSyncError` instead of warning.

        Raises:
            FileExistsError: When ``dest`` exists and
                ``overwrite=False``.
            OutOfSyncError: When ``strict_sync=True`` and any table is
                dirty.

        Examples:
            Roundtrip the Leavenworth fixture through parquet::

                >>> import tempfile, pathlib
                >>> from gmnspy.fixtures import leavenworth
                >>> from datagrove.dataset import Package
                >>> from datagrove.engines.pandas_engine import PandasEngine
                >>> import gmnspy
                >>> spec = pathlib.Path(gmnspy.__file__).parent / "spec" / "0.97" / "datapackage.json"
                >>> with tempfile.TemporaryDirectory() as tmp:
                ...     pkg = Package.from_source(
                ...         leavenworth.csv_dir(),
                ...         engine=PandasEngine(),
                ...         spec=spec,
                ...         tables=["link"],
                ...     )
                ...     out = pathlib.Path(tmp) / "out.gmns"
                ...     pkg.write(out, format="parquet")
                ...     out.exists()
                True
        """
        if self.engine is None:
            raise RuntimeError("Package has no engine attached; cannot write.")

        # 1. Sync-state pre-check. Any dirty signal trips warning/error.
        stale = self._stale_tables()
        if stale:
            msg = (
                f"Package source {self.source!r} has {len(stale)} stale table(s): "
                f"{sorted(stale)}. Writing may produce a snapshot whose FK "
                f"validations are out of date."
            )
            if strict_sync:
                raise OutOfSyncError(msg)
            warnings.warn(msg, OutOfSyncWarning, stacklevel=2)

        # 2. Resolve target format. Explicit wins; else sniff dest tail;
        #    else default to parquet (the recommended persistent layout
        #    per architecture §6.1).
        dest_path = Path(dest)
        target_format = format or _infer_write_format(dest_path)

        # 3. Overwrite guard.
        if dest_path.exists():
            if not overwrite:
                raise FileExistsError(f"Destination {dest_path!r} already exists. Pass overwrite=True to replace it.")
            if dest_path.is_dir():
                shutil.rmtree(dest_path)
            else:
                dest_path.unlink()

        # 4. Per-table write. The layout depends on the format:
        #    * parquet / csv directories: one file per table under dest
        #    * duckdb: a single file with one table per Package.table
        if target_format in {"parquet", "csv"}:
            dest_path.mkdir(parents=True, exist_ok=True)
            ext = "parquet" if target_format == "parquet" else "csv"
            adapter = get_adapter(target_format)
            for name, table in self.tables.items():
                file_path = dest_path / f"{name}.{ext}"
                adapter.write(table.expr, file_path, engine=self.engine)
        elif target_format == "duckdb":
            # DuckDB is a single multi-table file; per-table writes
            # share the dest path and pass table= for the destination
            # name inside the file.
            adapter = get_adapter("duckdb")
            for name, table in self.tables.items():
                adapter.write(table.expr, dest_path, engine=self.engine, table=name)
        else:
            # Unknown / single-table format: route everything through
            # the resolved adapter and let it raise if the layout
            # doesn't fit. This is the seam new formats slot into
            # without editing the central if/elif ladder.
            adapter = get_adapter(target_format)
            for name, table in self.tables.items():
                adapter.write(table.expr, dest_path / name, engine=self.engine)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_table(self, name: str, table: Table) -> None:
        """Insert a new :class:`Table` under ``name`` (or replace an existing one).

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> p = Package.from_tables(
            ...     {"a": Table(name="a", expr=e.from_records([{"x": 1}]), engine=e)}
            ... )
            >>> p.add_table("b", Table(name="b", expr=e.from_records([{"y": 1}]), engine=e))
            >>> sorted(p.keys())
            ['a', 'b']
        """
        self.tables[name] = table

    def remove_table(self, name: str) -> None:
        """Remove the table named ``name``.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> p = Package.from_tables(
            ...     {"a": Table(name="a", expr=e.from_records([{"x": 1}]), engine=e)}
            ... )
            >>> p.remove_table("a")
            >>> "a" in p
            False
        """
        del self.tables[name]

    def invalidate(self, name: str) -> None:
        """Mark a single table dirty.

        Convenience for :meth:`Table.invalidate` on the indexed entry.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> t = Table(name="a", expr=e.from_records([{"x": 1}]), engine=e)
            >>> p = Package.from_tables({"a": t})
            >>> p.invalidate("a")
            >>> p["a"].dirty
            True
        """
        self.tables[name].invalidate()
        if self.dirty_tracker is not None:
            mark = getattr(self.dirty_tracker, "mark_dirty", None)
            if callable(mark):
                mark(name)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """One-line summary: source, table count, dirty count."""
        n_dirty = sum(1 for t in self.tables.values() if t.dirty)
        bits = [f"source={self.source!r}" if self.source else "in_memory"]
        bits.append(f"tables={len(self.tables)}")
        if n_dirty:
            bits.append(f"dirty={n_dirty}")
        return f"Package({', '.join(bits)})"

    def _repr_html_(self) -> str:
        """Minimal Jupyter-friendly HTML rendering.

        A polished view is Phase 4 / notebook polish work; today we
        ship a small list view so a notebook user can see the table
        names + row counts at a glance without forcing a heavy
        materialisation. The HTML is intentionally bare so it
        composes inside DataFrames / docs without style collisions.

        Examples:
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from datagrove.dataset import Package, Table
            >>> e = PandasEngine()
            >>> t = Table(name="a", expr=e.from_records([{"x": 1}]), engine=e)
            >>> "Package" in Package.from_tables({"a": t})._repr_html_()
            True
        """
        rows = "".join(
            f"<tr><td>{_html_escape(name)}</td>"
            f"<td>{_html_escape(t.format or '')}</td>"
            f"<td>{'dirty' if t.dirty else 'clean'}</td></tr>"
            for name, t in self.tables.items()
        )
        src = _html_escape(self.source or "<in-memory>")
        return (
            f"<div><strong>Package</strong> source={src}"
            f"<table><thead><tr><th>name</th><th>format</th><th>state</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stale_tables(self) -> set[str]:
        """Return the set of table names that look out-of-sync.

        Combines two signals:

        * the per-:class:`Table` ``dirty`` flag (always available);
        * the :class:`DirtyTracker`'s ``is_table_dirty`` (when a
          tracker is attached).

        Either signal alone flags the table as stale — the union of
        the two is the conservative thing to report to the user.
        """
        stale: set[str] = {name for name, t in self.tables.items() if t.dirty}
        if self.dirty_tracker is None or self.engine is None:
            return stale
        is_dirty = getattr(self.dirty_tracker, "is_table_dirty", None)
        if not callable(is_dirty):
            return stale
        for name, table in self.tables.items():
            try:
                if is_dirty(name, table.expr, self.engine):
                    stale.add(name)
            except Exception:
                # Bubble the failure through as a stale signal so the
                # user sees the warning rather than a hard crash.
                stale.add(name)
        return stale


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _resolve_spec(
    spec: DataPackage | str | Path | None,
    source_str: str,
) -> DataPackage:
    """Resolve the ``spec`` argument to a :class:`DataPackage`.

    Order:
        1. Explicit :class:`DataPackage` — passed through.
        2. Explicit path / URL — loaded via :func:`load_package`.
        3. ``None`` — look for a sibling ``datapackage.json`` next to
           ``source_str``; if absent, synthesise an empty
           :class:`DataPackage` (the structural validator will surface
           the gap).
    """
    if isinstance(spec, DataPackage):
        return spec
    if isinstance(spec, (str, Path)):
        return load_package(spec)
    # Auto-discover.
    candidate = Path(source_str) / "datapackage.json"
    if candidate.exists():
        return load_package(candidate)
    # Synthesise an empty package — :meth:`Package.from_source` will
    # populate ``tables`` from the scan, but the spec stays empty so
    # downstream FK / schema checks no-op cleanly.
    return DataPackage(name="auto", resources=[])


def _scan_source(source_str: str) -> ResourceListing:
    """Resolve ``source_str`` to a :class:`ResourceListing`.

    Two branches, in order of preference:
        1. The source is a local directory of known-format files
           (``csv/``, ``parquet/``). Walk children and ask each
           matching adapter to scan one.
        2. Otherwise let :func:`datagrove.io.dispatch` resolve the
           source and call the adapter's ``scan`` method.
    """
    source_path = Path(source_str)
    if source_path.exists() and source_path.is_dir() and not _is_partitioned_parquet_dir(source_path):
        return _scan_directory_of_known_formats(source_path)
    try:
        adapter = dispatch(source_str)
    except FormatNotDetected:
        return []
    return adapter.scan(source_str)


def _scan_directory_of_known_formats(source_path: Path) -> ResourceListing:
    """Walk ``source_path`` asking each known format adapter to scan child files.

    Mirrors :func:`datagrove.validation.structural._scan_directory_of_known_formats`
    so the two paths can't drift apart on "what counts as a directory of
    tables". We don't import the helper directly to avoid the
    validation → dataset cycle.
    """
    listings: list[ResourceRef] = []
    seen: set[str] = set()

    ext_owners: list[tuple[str, str]] = []
    for adapter_name in list_adapters():
        adapter = get_adapter(adapter_name)
        for ext in adapter.extensions:
            ext_owners.append((ext.lower().lstrip("."), adapter_name))

    for child in sorted(source_path.iterdir()):
        if not child.is_file():
            continue
        name_lower = child.name.lower()
        for ext, adapter_name in ext_owners:
            if name_lower.endswith("." + ext):
                adapter = get_adapter(adapter_name)
                try:
                    refs = adapter.scan(child)
                except Exception:
                    refs = []
                for ref in refs:
                    if ref.name in seen:
                        continue
                    seen.add(ref.name)
                    listings.append(ref)
                break
    return listings


def _is_partitioned_parquet_dir(path: Path) -> bool:
    """Cheap probe — does ``path`` look like a Hive-partitioned parquet dataset?

    Same heuristic as
    :func:`datagrove.validation.structural._is_partitioned_parquet_dir`.
    """
    if not path.is_dir():
        return False
    try:
        for child in path.iterdir():
            if child.is_dir() and "=" in child.name:
                return True
    except OSError:
        return False
    return False


def _schema_for(spec: DataPackage, table_name: str) -> Schema | None:
    """Return the resolved :class:`Schema` for ``table_name``, or ``None``."""
    for resource in spec.resources:
        if resource.name != table_name:
            continue
        sch = resource.table_schema
        if isinstance(sch, Schema):
            return sch
        return None
    return None


def _infer_write_format(dest: Path) -> str:
    """Infer a write format from ``dest``.

    Order:
        1. Extension match (``.parquet``, ``.csv``, ``.duckdb``).
        2. ``.csv.zip`` compound.
        3. Anything else → default to ``"parquet"`` (the recommended
           persistent layout per architecture §6.1).
    """
    name = dest.name.lower()
    if name.endswith(".duckdb"):
        return "duckdb"
    if name.endswith(".csv.zip"):
        return "zipcsv"
    if name.endswith(".parquet"):
        return "parquet"
    if name.endswith(".csv"):
        return "csv"
    return "parquet"


def _html_escape(value: str) -> str:
    """Tiny stdlib HTML escape — kept inline so :meth:`Package._repr_html_` has no deps."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
