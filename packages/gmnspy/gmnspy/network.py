"""GMNS-aware :class:`Network` — see :class:`Network`.

A :class:`Network` is a thin GMNS subclass of
:class:`datagrove.dataset.Package`. It adds three things on top of the
generic package surface:

* **GMNS spec defaulting.** :meth:`Network.from_source` resolves the
  vendored GMNS spec (via :mod:`gmnspy.spec`) instead of asking the
  caller to pass a ``datapackage.json`` path.
* **Named accessors** for the canonical GMNS tables
  (``links``, ``nodes``, ``segments``, ``lanes``, ``geometry``,
  ``link_tod``, ``zones``, ``movements``, ``signal_*``, …). Required
  GMNS tables raise :class:`NetworkError` when absent; optional tables
  return ``None`` Pythonically.
* **Spec-version stamping** on the validation report so renderers (and
  saved JSON / HTML reports) advertise which GMNS version the data was
  checked against.

Everything else — validation orchestration, scope, write, sync state,
batch — is inherited from :class:`~datagrove.dataset.Package` unchanged.
Network semantics (connectivity / TOD resolution / geometry assembly)
land in :mod:`gmnspy.semantics` (task 3.8); network-aware scope
(``from_nodes``, BFS, network buffer) lands in :mod:`gmnspy.scope`
(task 3.10).

See ``docs/architecture.md`` section 5 ("Module map — gmnspy") for
the planned division of responsibility across ``network.py`` and its
siblings.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from datagrove.dataset import Package, PackageError, Table
from datagrove.reports import ValidationReport

from .spec import DEFAULT_SPEC, SUPPORTED_SPECS, load_gmns_spec

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.engines.base import Engine


__all__ = ["Network", "NetworkError"]


# ---------------------------------------------------------------------------
# Canonical GMNS table → Python attribute mapping
# ---------------------------------------------------------------------------
#
# The values are GMNS resource names exactly as they appear in the
# vendored ``<resource>.schema.json`` files (so the lookup is a direct
# ``Package.tables[name]`` hit). Keys are the Python accessor names we
# expose; plural English where GMNS uses a singular resource name
# (``link`` -> ``links``), bare resource name where pluralising adds
# nothing (``geometry``, ``link_tod``, ``signal_controller``).
#
# Required tables (``link``, ``node``) are kept in :data:`_REQUIRED`
# so the accessor knows whether to raise :class:`NetworkError` or
# return ``None`` when the table is missing. Adding a new GMNS table
# here is the entire change needed to expose a new accessor.

_TABLE_ATTRS: dict[str, str] = {
    # Core link/node graph
    "links": "link",
    "nodes": "node",
    # Geometry + lane detail
    "geometry": "geometry",
    "lanes": "lane",
    "segments": "segment",
    "segment_lanes": "segment_lane",
    # Time-of-day variants
    "link_tod": "link_tod",
    "lane_tod": "lane_tod",
    "segment_tod": "segment_tod",
    "segment_lane_tod": "segment_lane_tod",
    "movement_tod": "movement_tod",
    "time_set_definitions": "time_set_definitions",
    # Movements + zones + locations
    "movements": "movement",
    "zones": "zone",
    "locations": "location",
    "curb_segs": "curb_seg",
    # Signal family
    "signal_controller": "signal_controller",
    "signal_coordination": "signal_coordination",
    "signal_detector": "signal_detector",
    "signal_phase_mvmt": "signal_phase_mvmt",
    "signal_timing_phase": "signal_timing_phase",
    "signal_timing_plan": "signal_timing_plan",
    # Mode + config
    "use_definition": "use_definition",
    "use_group": "use_group",
    "config": "config",
}

_REQUIRED: frozenset[str] = frozenset({"link", "node"})


class NetworkError(PackageError):
    """A GMNS-required resource is missing or violates GMNS semantics.

    Specialises :class:`~datagrove.dataset.PackageError` so generic
    package-error handlers still catch it, while GMNS-aware callers can
    branch on the more specific type. Raised today by
    :attr:`Network.links` / :attr:`Network.nodes` when the underlying
    resource is absent from the loaded package; task 3.8 will reuse it
    for GMNS-semantics violations (broken connectivity, missing TOD
    references, …).
    """


@dataclass
class Network(Package):
    """GMNS-aware :class:`~datagrove.dataset.Package`.

    Subclass of :class:`~datagrove.dataset.Package` that defaults to the
    bundled GMNS spec (see :mod:`gmnspy.spec`) and exposes named
    accessors for the canonical GMNS resources (``link``, ``node``,
    ``segment``, ``lane``, ``geometry``, ``link_tod``,
    ``signal_controller``, …). Validation reports produced by
    :meth:`validate` carry the active :attr:`spec_version` so saved
    JSON / HTML reports are self-describing.

    Attributes:
        spec_version: GMNS spec version this network was loaded
            against — one of :data:`gmnspy.spec.SUPPORTED_SPECS`.
            Populated by :meth:`from_source`; defaults to ``""`` when
            the dataclass is constructed directly (the structural
            check still works, but :meth:`validate`'s stamp will be
            empty until the caller sets it).

    Examples:
        Load the bundled Leavenworth fixture, hit the named accessors,
        and run validation::

            >>> from gmnspy import Network
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
            >>> net.links.name
            'link'
            >>> net.nodes.name
            'node'
            >>> net.segments is None  # Leavenworth has no segment table
            True
            >>> report = net.validate()
            >>> report.spec_version == net.spec_version
            True
    """

    spec_version: str = field(default="")

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_source(  # type: ignore[override]
        cls,
        source: str | Path,
        *,
        engine: Engine | None = None,
        spec_version: str | None = None,
        tables: Iterable[str] | None = None,
    ) -> Network:
        """Load a GMNS network from ``source``, defaulting the spec to gmns@spec_version.

        Resolves ``spec_version`` (caller-provided or
        :data:`gmnspy.spec.DEFAULT_SPEC`), validates it against
        :data:`gmnspy.spec.SUPPORTED_SPECS`, loads the matching
        vendored spec via :func:`gmnspy.spec.load_gmns_spec`, then
        delegates to :meth:`Package.from_source` for the actual I/O.
        The returned :class:`Network` carries the resolved version on
        :attr:`spec_version`.

        Args:
            source: Path / URL / directory pointing at the GMNS package
                — anything :meth:`Package.from_source` accepts.
            engine: Engine to materialise through. Defaults to the
                datagrove default (typically
                :class:`~datagrove.engines.ibis_engine.IbisEngine`).
            spec_version: GMNS spec version to validate against.
                Defaults to :data:`gmnspy.spec.DEFAULT_SPEC`. Must be a
                member of :data:`gmnspy.spec.SUPPORTED_SPECS`.
            tables: Optional subset of resource names to load. Useful
                for memory-efficient partial loads (e.g. ``["link",
                "node"]``).

        Returns:
            A populated :class:`Network` with lazy
            :class:`~datagrove.dataset.Table` entries and
            :attr:`spec_version` stamped.

        Raises:
            ValueError: If ``spec_version`` is not in
                :data:`gmnspy.spec.SUPPORTED_SPECS`.

        Examples:
            >>> from gmnspy import Network
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
            >>> "link" in net
            True
            >>> net.spec_version
            '0.97'
        """
        resolved_version = spec_version if spec_version is not None else DEFAULT_SPEC
        if resolved_version not in SUPPORTED_SPECS:
            raise ValueError(
                f"Unsupported GMNS spec version: {resolved_version!r}. Supported versions: {', '.join(SUPPORTED_SPECS)}"
            )
        gmns_spec = load_gmns_spec(resolved_version)
        # Delegate to Package.from_source — composition over copy-paste.
        # Package returns a `Package` instance; we re-pack into `cls`
        # (always `Network` in practice) so the named accessors light up.
        base = Package.from_source(source, engine=engine, spec=gmns_spec, tables=tables)
        return cls(
            spec=base.spec,
            tables=base.tables,
            engine=base.engine,
            source=base.source,
            dirty_tracker=base.dirty_tracker,
            metadata=dict(base.metadata),
            spec_version=resolved_version,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, **kwargs) -> ValidationReport:  # type: ignore[override]
        """Run the inherited :meth:`Package.validate` and stamp :attr:`spec_version` on the report.

        Pure composition — the orchestration (structural / schema / FK /
        sync-state passes) lives in :class:`~datagrove.dataset.Package`
        and is not duplicated here. The override exists solely so the
        returned :class:`~datagrove.reports.ValidationReport` advertises
        which GMNS spec version the data was checked against (renderers
        and saved JSON / HTML reports surface this in the header).

        Args:
            **kwargs: Forwarded verbatim to :meth:`Package.validate`.

        Returns:
            A :class:`~datagrove.reports.ValidationReport` with
            ``spec_version`` set to :attr:`self.spec_version`.

        Examples:
            >>> from gmnspy import Network
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
            >>> report = net.validate(foreign_keys=False, sync_state=False)
            >>> report.spec_version == net.spec_version
            True
        """
        report = super().validate(**kwargs)
        report.spec_version = self.spec_version
        return report

    # ------------------------------------------------------------------
    # Internal accessor helper
    # ------------------------------------------------------------------

    def _get_table(self, attr_name: str) -> Table | None:
        """Look up a GMNS table by its Python accessor name.

        Returns the :class:`~datagrove.dataset.Table` when present;
        raises :class:`NetworkError` when the underlying GMNS resource
        is in :data:`_REQUIRED` but absent; returns ``None`` for an
        absent optional resource. Keeping every accessor on top of this
        helper means a new GMNS table is exposed by adding one entry
        to :data:`_TABLE_ATTRS` (and :data:`_REQUIRED` if needed).
        """
        resource_name = _TABLE_ATTRS[attr_name]
        table = self.tables.get(resource_name)
        if table is not None:
            return table
        if resource_name in _REQUIRED:
            raise NetworkError(
                f"Required GMNS table {resource_name!r} is missing from this network "
                f"— required by GMNS spec {self.spec_version!r}."
            )
        return None

    # ------------------------------------------------------------------
    # Named accessors — required tables (raise NetworkError when absent)
    # ------------------------------------------------------------------

    @property
    def links(self) -> Table:
        """The ``link`` table (required by GMNS).

        Raises:
            NetworkError: If the ``link`` resource is absent from the
                loaded package.

        Examples:
            >>> from gmnspy import Network
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> Network.from_source(leavenworth.csv_dir(), engine=PandasEngine()).links.name
            'link'
        """
        t = self._get_table("links")
        assert t is not None  # _REQUIRED guarantees a raise on absent
        return t

    @property
    def nodes(self) -> Table:
        """The ``node`` table (required by GMNS).

        Raises:
            NetworkError: If the ``node`` resource is absent from the
                loaded package.
        """
        t = self._get_table("nodes")
        assert t is not None
        return t

    # ------------------------------------------------------------------
    # Named accessors — optional tables (return None when absent)
    # ------------------------------------------------------------------

    @property
    def geometry(self) -> Table | None:
        """The ``geometry`` table or ``None`` when absent."""
        return self._get_table("geometry")

    @property
    def lanes(self) -> Table | None:
        """The ``lane`` table or ``None`` when absent."""
        return self._get_table("lanes")

    @property
    def segments(self) -> Table | None:
        """The ``segment`` table or ``None`` when absent."""
        return self._get_table("segments")

    @property
    def segment_lanes(self) -> Table | None:
        """The ``segment_lane`` table or ``None`` when absent."""
        return self._get_table("segment_lanes")

    @property
    def link_tod(self) -> Table | None:
        """The ``link_tod`` table or ``None`` when absent."""
        return self._get_table("link_tod")

    @property
    def lane_tod(self) -> Table | None:
        """The ``lane_tod`` table or ``None`` when absent."""
        return self._get_table("lane_tod")

    @property
    def segment_tod(self) -> Table | None:
        """The ``segment_tod`` table or ``None`` when absent."""
        return self._get_table("segment_tod")

    @property
    def segment_lane_tod(self) -> Table | None:
        """The ``segment_lane_tod`` table or ``None`` when absent."""
        return self._get_table("segment_lane_tod")

    @property
    def movements(self) -> Table | None:
        """The ``movement`` table or ``None`` when absent."""
        return self._get_table("movements")

    @property
    def movement_tod(self) -> Table | None:
        """The ``movement_tod`` table or ``None`` when absent."""
        return self._get_table("movement_tod")

    @property
    def time_set_definitions(self) -> Table | None:
        """The ``time_set_definitions`` table or ``None`` when absent."""
        return self._get_table("time_set_definitions")

    @property
    def zones(self) -> Table | None:
        """The ``zone`` table or ``None`` when absent."""
        return self._get_table("zones")

    @property
    def locations(self) -> Table | None:
        """The ``location`` table or ``None`` when absent."""
        return self._get_table("locations")

    @property
    def curb_segs(self) -> Table | None:
        """The ``curb_seg`` table or ``None`` when absent."""
        return self._get_table("curb_segs")

    @property
    def signal_controller(self) -> Table | None:
        """The ``signal_controller`` table or ``None`` when absent."""
        return self._get_table("signal_controller")

    @property
    def signal_coordination(self) -> Table | None:
        """The ``signal_coordination`` table or ``None`` when absent."""
        return self._get_table("signal_coordination")

    @property
    def signal_detector(self) -> Table | None:
        """The ``signal_detector`` table or ``None`` when absent."""
        return self._get_table("signal_detector")

    @property
    def signal_phase_mvmt(self) -> Table | None:
        """The ``signal_phase_mvmt`` table or ``None`` when absent."""
        return self._get_table("signal_phase_mvmt")

    @property
    def signal_timing_phase(self) -> Table | None:
        """The ``signal_timing_phase`` table or ``None`` when absent."""
        return self._get_table("signal_timing_phase")

    @property
    def signal_timing_plan(self) -> Table | None:
        """The ``signal_timing_plan`` table or ``None`` when absent."""
        return self._get_table("signal_timing_plan")

    @property
    def use_definition(self) -> Table | None:
        """The ``use_definition`` table or ``None`` when absent."""
        return self._get_table("use_definition")

    @property
    def use_group(self) -> Table | None:
        """The ``use_group`` table or ``None`` when absent."""
        return self._get_table("use_group")

    @property
    def config(self) -> Table | None:
        """The ``config`` table or ``None`` when absent."""
        return self._get_table("config")
