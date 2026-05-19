"""ZipCsvAdapter — bundle of CSV files packaged into a single ``.zip``.

A common distribution format for GMNS (and many other Frictionless data
packages): one ``.csv`` per table, all bundled into one archive. The
single-table case is conventionally named ``<stem>.csv.zip``; the
multi-table case is just ``<stem>.zip`` (often alongside a
``datapackage.json`` describing the bundle).

This module ships the :class:`ZipCsvAdapter` and self-registers it under
the name ``"zipcsv"`` at import time. The adapter owns two extensions:

- ``"csv.zip"`` (compound) — wins over the bare ``"zip"`` extension via
  the dispatcher's longest-suffix-first convention.
- ``"zip"`` (bare) — claims any ``.zip`` whose ``namelist()`` contains
  at least one ``.csv`` member.

Design notes:
    - The read strategy is **extract-to-tempdir, materialize, drop**.
      The engine ``scan()`` opens a path; we then immediately
      ``engine.materialize()`` to sever the dependency on that path,
      then clean up the temp dir. This trades lazy execution for a
      simple, engine-agnostic implementation. The temp-dir lifetime is
      controlled by a single ``contextlib.ExitStack`` whose extent
      brackets just the scan+materialize call — by the time ``read``
      returns, the on-disk file is gone and the engine holds the data
      in its own backend (a duckdb temp table for ibis, a polars
      DataFrame for polars, the DataFrame itself for pandas).
    - The selector kwarg is always ``table=<member-name>`` (the ``.csv``
      suffix is optional). Earlier prototypes accepted ``member=`` and
      ``name=`` as aliases and an implicit single-csv shortcut — both
      were dropped (I10) so the selector contract is identical to the
      duckdb adapter. ``table=`` is required for any zip with one or
      more csv members.
    - The write path implemented here is **single-CSV-into-zip only**.
      Writing a directory of CSVs as a multi-CSV zip is deferred to a
      future task; today the adapter raises
      :class:`NotImplementedError` for any input that would require it.
      Existing destinations are refused unless ``overwrite=True`` is
      passed (I6) — silent clobber was a footgun.

Architecture cross-reference
----------------------------

Once this adapter is registered, the ``NotImplementedError`` branches
in :mod:`datagrove.engines.pandas_engine`,
:mod:`datagrove.engines.polars_engine`, and
:mod:`datagrove.engines.ibis_engine` that point at "task 1.10" become
dead code — engines should delegate through
``datagrove.io.dispatch(source).read(source, engine=self, ...)``
instead. The cleanup is intentionally left for a follow-up PR (it
touches three engine modules and the engine-side tests) so this task
ships with a minimal blast radius.
"""

from __future__ import annotations

import contextlib
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from datagrove.engines.errors import InvalidEngineCallError
from datagrove.io import register_adapter
from datagrove.io._paths import normalize_to_str
from datagrove.io.base import ResourceListing, ResourceRef, SourceRef

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine, TableExpr
    from datagrove.spec.model import Schema


__all__ = ["ZipCsvAdapter"]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ZipCsvAdapter:
    """Read/write a Frictionless tabular data package shipped as a zip of csvs.

    Self-registers under the name ``"zipcsv"`` when this module is
    imported. Owns the ``"csv.zip"`` and ``"zip"`` extensions; the
    compound one is listed first so the dispatcher's longest-suffix-first
    rule routes ``foo.csv.zip`` here before considering a generic
    ``.zip`` adapter (there isn't one today, but future-proofing for a
    second consumer that adds e.g. zipped-parquet costs nothing).

    Attributes:
        name: ``"zipcsv"``.
        extensions: ``("csv.zip", "zip")`` — compound first.
        schemes: ``()`` — no URL scheme.

    Examples:
        >>> adapter = ZipCsvAdapter()
        >>> adapter.name
        'zipcsv'
        >>> adapter.extensions
        ('csv.zip', 'zip')
    """

    name: str = "zipcsv"
    extensions: tuple[str, ...] = ("csv.zip", "zip")
    schemes: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # probe
    # ------------------------------------------------------------------

    def probe(self, source: SourceRef) -> bool:
        """Return True if ``source`` is (or appears to be) a zip of csvs.

        Resolution:

        1. If the source ends in ``.csv.zip`` → True without opening
           the file. The compound extension is unambiguous and the file
           may not exist yet (e.g. the dispatcher is called from a
           ``write()`` path).
        2. If the source ends in ``.zip`` → try to open it and peek at
           ``ZipFile.namelist()``. True iff at least one member ends
           in ``.csv``.
        3. Otherwise → False.

        Must never raise: a corrupt zip, a non-existent file, or even
        ``None`` returns False instead of crashing dispatch (the
        dispatcher's probe loop also catches exceptions, but adapters
        should not depend on that safety net — Lens C, no clever
        Python).

        Args:
            source: The candidate source reference.

        Returns:
            True if this adapter is willing to attempt a read.

        Examples:
            >>> import zipfile, tempfile, pathlib
            >>> d = pathlib.Path(tempfile.mkdtemp())
            >>> p = d / "x.csv.zip"
            >>> _ = p.write_bytes(b"")  # extension alone is enough
            >>> ZipCsvAdapter().probe(p)
            True
            >>> ZipCsvAdapter().probe(d / "missing.zip")  # missing file
            False
        """
        try:
            lower = str(source).lower()
        except Exception:
            return False

        # 1. Compound extension wins without opening — cheap and total.
        if lower.endswith(".csv.zip"):
            return True

        # 2. Bare .zip — peek at the central directory. ZipFile.namelist()
        # only reads the central directory record at the tail of the file,
        # which is cheap (a few KB even for huge archives).
        if lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(str(source)) as z:
                    return any(_is_csv_member(n) for n in z.namelist())
            except (FileNotFoundError, zipfile.BadZipFile, OSError, ValueError):
                # Missing, malformed, or otherwise unreadable — not ours.
                return False

        # 3. Anything else.
        return False

    # ------------------------------------------------------------------
    # scan
    # ------------------------------------------------------------------

    def scan(self, source: SourceRef, engine: Engine | None = None) -> ResourceListing:
        r"""Enumerate csv members in ``source`` as :class:`ResourceRef` entries.

        One ResourceRef per csv member. ``ref.name`` is the member's
        file stem (e.g. ``"link"`` for ``"link.csv"``); ``ref.path`` is
        ``"<source>::<member>"`` so downstream code can re-open the
        right entry; ``ref.format`` is ``"csv"`` (the inner files
        *are* csvs once extracted).

        The ``engine`` argument is unused but kept for protocol parity
        — :class:`~datagrove.io.FormatAdapter` always passes one and
        future adapters may need it for cheap metadata reads.

        Args:
            source: A path to a zip file.
            engine: Unused for this adapter (kept for protocol parity).

        Returns:
            An ordered listing, one entry per csv member. Members
            are returned in zip-file order (which is typically
            insertion order at write time).

        Examples:
            >>> import zipfile, tempfile, pathlib
            >>> d = pathlib.Path(tempfile.mkdtemp())
            >>> p = d / "ex.zip"
            >>> with zipfile.ZipFile(p, "w") as z:
            ...     z.writestr("a.csv", "x,y")
            ...     z.writestr("b.csv", "x,y")
            >>> refs = ZipCsvAdapter().scan(p)
            >>> [r.name for r in refs]
            ['a', 'b']
            >>> refs[0].format
            'csv'
        """
        path_str = normalize_to_str(source, adapter="zipcsv adapter")
        with zipfile.ZipFile(path_str) as z:
            members = [n for n in z.namelist() if _is_csv_member(n)]
        return [
            ResourceRef(
                name=Path(m).stem,
                path=f"{path_str}::{m}",
                format="csv",
            )
            for m in members
        ]

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------

    def read(
        self,
        source: SourceRef,
        engine: Engine,
        schema: Schema | None = None,
        **kwargs: Any,
    ) -> TableExpr:
        r"""Read one csv out of the zip and return an engine expression.

        Strategy: extract the chosen member into a temp directory,
        call ``engine.scan(extracted_path, format="csv", schema=schema,
        **kwargs)``, then ``engine.materialize(expr)`` to sever the
        path dependency, then delete the temp directory. The returned
        expression is engine-managed and outlives the file.

        I10 standardisation: the **only** accepted selector kwarg is
        ``table=<member-name>``. The ``.csv`` suffix is optional. The
        previous ``member=``/``name=`` aliases and the
        single-csv-without-table shortcut were removed so the zipcsv
        contract is identical to the duckdb adapter's.

        Args:
            source: Path to the zip file.
            engine: The execution engine to defer the actual csv read to.
            schema: Optional Frictionless schema, forwarded to the
                engine's csv reader.
            **kwargs: Adapter-specific options. ``table=<name>`` selects
                the csv to read and is **required** even for single-csv
                zips. Any other kwargs are forwarded to
                ``engine.scan(..., format="csv", **kwargs)``.

        Returns:
            An engine-native expression backed by the engine's own
            storage (a duckdb temp table for ibis, a polars
            ``DataFrame`` for polars, a ``pandas.DataFrame`` for
            pandas). Safe to use after this method returns even though
            the on-disk extracted file is gone.

        Raises:
            InvalidEngineCallError: No ``table=`` selector, the named
                table doesn't exist, or the zip has no csv members.

        Examples:
            >>> from datagrove.engines import get_engine
            >>> import zipfile, tempfile, pathlib
            >>> d = pathlib.Path(tempfile.mkdtemp())
            >>> p = d / "x.csv.zip"
            >>> body = chr(10).join(["a,b", "1,2", ""])  # "a,b\n1,2\n"
            >>> with zipfile.ZipFile(p, "w") as z:
            ...     z.writestr("only.csv", body)
            >>> # table= is required even for a single-csv zip
            >>> e = get_engine("pandas")
            >>> expr = ZipCsvAdapter().read(p, engine=e, table="only")
            >>> e.to_pandas(expr).shape
            (1, 2)
        """
        path_str = normalize_to_str(source, adapter="zipcsv adapter")
        # I10: only ``table=`` is accepted. Pop it so we don't forward
        # the selector to ``engine.scan``.
        selector = kwargs.pop("table", None)

        with zipfile.ZipFile(path_str) as z:
            csv_members = [n for n in z.namelist() if _is_csv_member(n)]

            if not csv_members:
                raise InvalidEngineCallError(f"zipcsv adapter: zip at {path_str!r} contains no .csv members")

            chosen = _pick_member(csv_members, selector, path_str)

            # Extract chosen member into a temp dir, hand it to the engine,
            # then materialize so the engine no longer depends on the file.
            with tempfile.TemporaryDirectory(prefix="datagrove_zipcsv_") as td:
                extracted = z.extract(chosen, path=td)
                # An extracted nested-path member lands at td/<member>, with
                # any subdirectories created. extract() returns the full path.
                expr = engine.scan(
                    extracted,
                    format="csv",
                    schema=schema,
                    **kwargs,
                )
                # Force engine-side materialization to cut the file-lifetime
                # dependency before the TemporaryDirectory context exits.
                # For pandas this is a no-op identity; for polars this
                # collects to a DataFrame; for ibis this creates a duckdb
                # temp table. After this line, ``extracted`` may be deleted.
                materialized = engine.materialize(expr)
                # Polars' materialize() returns DataFrame but its
                # to_pandas() / to_polars() / write() all expect a
                # LazyFrame — re-lazify so downstream engine calls keep
                # the contract that scan() produced. Pandas and ibis
                # already round-trip cleanly.
                materialized = _relazy_if_needed(engine, materialized)

        return materialized

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------

    def write(
        self,
        expr: TableExpr,
        dest: SourceRef,
        engine: Engine,
        **kwargs: Any,
    ) -> None:
        """Write ``expr`` as a single csv inside a new zip at ``dest``.

        The inner csv member is named ``<table>.csv`` where ``<table>``
        comes from (in priority order):

        1. ``kwargs['table']`` (per the I10 selector contract; ``member=``
           and ``name=`` aliases are no longer accepted).
        2. The destination filename's stem with the ``.csv.zip`` /
           ``.zip`` suffix stripped (e.g. ``"out.csv.zip"`` →
           ``"out.csv"``).

        Writing a directory of csvs into a multi-csv zip is not yet
        supported — defer until a real consumer needs it.

        I6: an existing ``dest`` is refused with :class:`FileExistsError`
        unless the caller passes ``overwrite=True``. Silent clobber on a
        path the caller probably typed into a notebook by hand is a
        data-loss footgun; the explicit kwarg is the safe default.

        Args:
            expr: A table expression the engine can write as csv.
            dest: Path for the output zip.
            engine: The engine to defer the csv encoding to.
            **kwargs: Optional ``table=`` to choose the inner member's
                name. ``overwrite=False`` (default) refuses an existing
                destination; pass ``overwrite=True`` to clobber. Any
                other kwargs are forwarded to
                ``engine.write(..., fmt="csv", **kwargs)``.

        Raises:
            FileExistsError: If ``dest`` exists and ``overwrite=True``
                was not passed.

        Examples:
            >>> from datagrove.engines import get_engine
            >>> import pandas as pd, pathlib, tempfile, zipfile
            >>> d = pathlib.Path(tempfile.mkdtemp())
            >>> dest = d / "out.csv.zip"
            >>> ZipCsvAdapter().write(
            ...     pd.DataFrame({"a": [1, 2]}),
            ...     dest,
            ...     engine=get_engine("pandas"),
            ...     table="data",
            ... )
            >>> with zipfile.ZipFile(dest) as z:
            ...     z.namelist()
            ['data.csv']
        """
        dest_str = normalize_to_str(dest, adapter="zipcsv adapter")
        # I10: only ``table=`` selector.
        selector = kwargs.pop("table", None)
        # I6: explicit overwrite kwarg; default False refuses an
        # existing destination.
        overwrite = bool(kwargs.pop("overwrite", False))
        if not overwrite and Path(dest_str).exists():
            raise FileExistsError(f"{dest_str!r} exists; pass overwrite=True to clobber")
        inner_name = _resolve_inner_csv_name(selector, dest_str)

        # Encode to a temp csv via the engine, then zip it into dest.
        # Using ExitStack so the TemporaryDirectory cleanup happens even
        # if the engine.write or ZipFile.write below raises.
        with contextlib.ExitStack() as stack:
            td = stack.enter_context(tempfile.TemporaryDirectory(prefix="datagrove_zipcsv_w_"))
            tmp_csv = Path(td) / inner_name
            engine.write(expr, tmp_csv, fmt="csv", **kwargs)
            with zipfile.ZipFile(dest_str, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
                z.write(tmp_csv, arcname=inner_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _relazy_if_needed(engine: Engine, materialized: Any) -> Any:
    """Re-wrap a materialized polars DataFrame into a LazyFrame.

    Polars ``Engine.materialize`` returns ``pl.DataFrame`` (eager) but
    every other Polars Engine method (``to_pandas`` / ``to_polars`` /
    ``write``) signature-types its first argument as ``pl.LazyFrame``
    and calls ``.collect()`` on it. To keep the engine surface
    consistent for adapters that have to materialize early (zipcsv,
    future remote-fsspec), we re-lazify the polars case here. This is
    a single-line workaround keyed on ``engine.name`` rather than
    isinstance — avoids importing polars at module import time when
    the optional dep is not installed.

    Pandas (eager) and ibis (lazy-into-duckdb-temp-table) both round-
    trip materialize() correctly and pass through unchanged.
    """
    if engine.name == "polars":
        # ``.lazy()`` on a polars DataFrame returns a LazyFrame backed
        # by the in-memory frame — no re-read, no file dependency.
        lazy = getattr(materialized, "lazy", None)
        if callable(lazy):
            return lazy()
    return materialized


def _is_csv_member(name: str) -> bool:
    """Whether a zip member name should be treated as a csv table.

    Match is case-insensitive on the suffix; directory-entry names
    (those ending in ``/``) are excluded. Hidden / Mac-metadata members
    starting with ``__MACOSX/`` or ``.`` are also excluded —
    distributing a zip from a Mac via Finder commonly bakes those in
    and we don't want them to show up as phantom tables.
    """
    if not name or name.endswith("/"):
        return False
    if name.startswith("__MACOSX/"):
        return False
    if Path(name).name.startswith("."):
        return False
    return name.lower().endswith(".csv")


def _pick_member(
    csv_members: list[str],
    selector: str | None,
    path_str: str,
) -> str:
    """Resolve ``selector`` to a concrete member name from ``csv_members``.

    I10: ``table=<name>`` is required for every read, even when the zip
    contains exactly one csv member. The implicit "if there's only one,
    use it" shortcut was removed because it diverged from the duckdb
    adapter's selector contract; standardising on always-explicit makes
    cross-adapter code predictable.
    """
    if selector is None:
        sample = ", ".join(sorted(Path(m).stem for m in csv_members))
        raise InvalidEngineCallError(
            f"zipcsv adapter: zip at {path_str!r} contains "
            f"{len(csv_members)} csv file(s); pass table=<name> to choose one "
            f"(the single-csv shortcut was removed for selector-contract parity "
            f"with the duckdb adapter). Available tables: {sample}."
        )

    # Normalise selector — ``.csv`` suffix optional.
    target = selector if selector.lower().endswith(".csv") else f"{selector}.csv"

    # Direct hit on the full member name (handles nested paths too).
    if target in csv_members:
        return target
    # Stem-only match — covers ``table="link"`` when the zip stored
    # ``"link.csv"`` at the top level.
    matches = [m for m in csv_members if Path(m).name == target]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise InvalidEngineCallError(
            f"zipcsv adapter: selector {selector!r} matched multiple members "
            f"in {path_str!r}: {matches!r}. Pass the full member path to "
            "disambiguate."
        )

    sample = ", ".join(sorted(Path(m).stem for m in csv_members))
    raise InvalidEngineCallError(
        f"zipcsv adapter: no member named {selector!r} in {path_str!r}. Available tables: {sample}."
    )


def _resolve_inner_csv_name(selector: str | None, dest_str: str) -> str:
    """Decide the inner csv member name for :meth:`ZipCsvAdapter.write`."""
    if selector is not None:
        return selector if selector.lower().endswith(".csv") else f"{selector}.csv"
    # Strip the compound suffix from the dest stem, then add .csv.
    dest_name = Path(dest_str).name
    lower = dest_name.lower()
    if lower.endswith(".csv.zip"):
        stem = dest_name[: -len(".csv.zip")]
    elif lower.endswith(".zip"):
        stem = dest_name[: -len(".zip")]
    else:
        stem = Path(dest_name).stem
    return f"{stem or 'data'}.csv"


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------

register_adapter(ZipCsvAdapter())
