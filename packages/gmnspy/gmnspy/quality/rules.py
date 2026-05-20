"""GMNS data-quality rule pack — registered into :mod:`datagrove.quality`.

Each rule is a plain class with the four fields required by
:class:`datagrove.quality.Rule`:

* ``code`` — stable dotted identifier (e.g. ``"quality.high_speed_residential"``).
* ``description`` — one-line plain-English explanation.
* ``severity`` — default :class:`~datagrove.reports.Severity`.
* ``applies_to(package)`` — cheap pre-check (usually "is the required
  table present?").
* ``run(package, report)`` — does the work, emits zero or more
  :class:`~datagrove.reports.Issue` records into ``report``.

Rules read their thresholds from
:attr:`datagrove.quality.RuleConfig.thresholds` (a plain dict). Each
rule documents its keys + defaults in its docstring.

All rules in this module emit ``Issue.category = Category.DATA_QUALITY``
and ``Severity.WARNING`` (or ``INFO``) by default — they are not spec
violations. Callers wanting hard errors should override via
``RuleConfig(severity_override=Severity.ERROR)``.

Why one file: all 7 rules read a thin slice of the network, compute a
predicate, emit issues. The patterns are similar enough that side-by-side
reading helps; spreading them across 7 files would obscure the shared
shape. Total LOC including docstrings ~600.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datagrove.quality import RuleConfig, register_rule
from datagrove.reports import Category, Issue, Severity

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package
    from datagrove.reports import ValidationReport

__all__ = [
    "DisconnectedComponentsRule",
    "DuplicateNearNodesRule",
    "HighSpeedResidentialRule",
    "ImplausibleVcRule",
    "LaneCountMismatchRule",
    "MissingCriticalFieldsRule",
    "SharpAngleBendsRule",
    "register_all",
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _to_arrow(table) -> Any:
    """Materialise a :class:`~datagrove.dataset.Table` to pyarrow.

    Same two-hop pattern as the rest of gmnspy.* — ``to_pandas`` then
    ``pa.Table.from_pandas`` so we stay backend-agnostic.
    """
    import pyarrow as pa

    return pa.Table.from_pandas(table.to_pandas(), preserve_index=False)


def _threshold(rc: RuleConfig | None, key: str, default: float) -> float:
    """Return the configured threshold for ``key`` (or default).

    Rules accept either a :class:`RuleConfig` (forwarded from
    :func:`datagrove.quality.run_quality`) or ``None`` (test/CLI
    direct-call). Threshold values can be int or float — coerce.
    """
    if rc is None:
        return float(default)
    return float(rc.thresholds.get(key, default))


# ---------------------------------------------------------------------------
# Rule 1 — high speed on residential street
# ---------------------------------------------------------------------------


class HighSpeedResidentialRule:
    """Flag residential links with implausibly high ``free_speed``.

    Threshold keys:

    * ``speed_limit_mph`` (default ``35``) — anything above is flagged.

    Looks at ``link.facility_type`` (matched against ``residential`` /
    ``local`` case-insensitively) and ``link.free_speed``. Skips links
    with null facility type or null free_speed (those belong to the
    ``MissingCriticalFieldsRule``).

    The ``free_speed`` unit is whatever the spec's
    ``long_distance_units`` field declares — GMNS defaults to mph, so
    the threshold key is named ``speed_limit_mph`` for clarity. If your
    network uses km/h, set ``speed_limit_mph`` to your km/h threshold;
    the comparison is unit-agnostic from the rule's point of view.
    """

    code = "quality.high_speed_residential"
    description = "Residential / local street with free_speed above threshold."
    severity = Severity.WARNING
    _FACILITY_TYPES = frozenset({"residential", "local"})

    def applies_to(self, package: Package) -> bool:
        """We need both the link table AND its facility_type + free_speed columns."""
        link = package.tables.get("link")
        if link is None:
            return False
        cols = set(link.columns())
        return {"link_id", "facility_type", "free_speed"} <= cols

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """Walk the link table; emit one issue per offending row."""
        threshold = _threshold(rc, "speed_limit_mph", 35.0)
        arrow = _to_arrow(package.tables["link"])
        for i, row in enumerate(arrow.to_pylist()):
            ftype = row.get("facility_type")
            speed = row.get("free_speed")
            if ftype is None or speed is None:
                continue
            if str(ftype).strip().lower() not in self._FACILITY_TYPES:
                continue
            if float(speed) <= threshold:
                continue
            report.add_issue(
                Issue(
                    severity=self.severity,
                    category=Category.DATA_QUALITY,
                    code=self.code,
                    message=(
                        f"link row {i} (link_id={row.get('link_id')!r}): "
                        f"facility_type={ftype!r} with free_speed={speed} > threshold {threshold}."
                    ),
                    table="link",
                    column="free_speed",
                    row=i,
                    fix_hint=(
                        "If the speed is correct, change facility_type to a higher class "
                        "(e.g. 'tertiary', 'secondary')."
                    ),
                )
            )


# ---------------------------------------------------------------------------
# Rule 2 — disconnected components
# ---------------------------------------------------------------------------


class DisconnectedComponentsRule:
    """Flag networks with more than one weakly-connected component.

    Threshold keys: none (the presence of any extra component is the
    quality concern).

    Emits a single ``Severity.INFO`` issue (not per-component) listing
    the component count + sizes. ``connected_components`` is delegated
    to :mod:`gmnspy.semantics.connectivity` so the same igraph build is
    shared with any other connectivity caller in the session.
    """

    code = "quality.disconnected_components"
    description = "Network has more than one weakly-connected component."
    severity = Severity.INFO

    def applies_to(self, package: Package) -> bool:
        """We need link + node tables AND the columns GraphIndex.build needs.

        Skips silently on non-Network packages (no GMNS accessors) and on
        networks missing ``length`` on the link table — the upstream
        GraphIndex requires it and we'd rather no-op than blow up.
        """
        if not (hasattr(package, "links") and hasattr(package, "nodes")):
            return False
        link = package.tables.get("link")
        node = package.tables.get("node")
        if link is None or node is None:
            return False
        required_link_cols = {"from_node_id", "to_node_id", "length"}
        return required_link_cols <= set(link.columns()) and "node_id" in node.columns()

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """Build (or reuse) the GraphIndex, count components."""
        # Local import: connectivity pulls in igraph which is a clean-extra.
        from gmnspy.semantics import connected_components

        comps = connected_components(package)
        if len(comps) <= 1:
            return
        sizes = sorted((len(c) for c in comps), reverse=True)
        report.add_issue(
            Issue(
                severity=self.severity,
                category=Category.DATA_QUALITY,
                code=self.code,
                message=(
                    f"Network has {len(comps)} weakly-connected components "
                    f"(sizes: {sizes[:10]}{'…' if len(sizes) > 10 else ''})."
                ),
                table="link",
                fix_hint=(
                    "Use gmnspy.clean.connect_disconnected_components to add bridge links, or drop small components."
                ),
                extra={"component_sizes": sizes},
            )
        )


# ---------------------------------------------------------------------------
# Rule 3 — lane-count mismatch between link.lanes and lane table
# ---------------------------------------------------------------------------


class LaneCountMismatchRule:
    """Flag links where ``link.lanes`` disagrees with the ``lane`` table row count.

    Threshold keys: none — any non-zero mismatch is flagged.

    Skips links where either ``link.lanes`` is null OR the ``lane``
    table has zero rows for that link (those cases are
    "underspecified", not "wrong" — caught by :class:`MissingCriticalFieldsRule`).
    """

    code = "quality.lane_count_mismatch"
    description = "link.lanes disagrees with the row count in the lane table."
    severity = Severity.WARNING

    def applies_to(self, package: Package) -> bool:
        """Needs both the link table AND a lane table."""
        link = package.tables.get("link")
        lane = package.tables.get("lane")
        if link is None or lane is None:
            return False
        return "lanes" in link.columns() and "link_id" in lane.columns()

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """Compare declared link.lanes against actual lane row counts; flag mismatches."""
        link_arrow = _to_arrow(package.tables["link"])
        lane_arrow = _to_arrow(package.tables["lane"])

        # Build per-link lane counts from the lane table.
        lane_count: dict[Any, int] = {}
        for lid in lane_arrow.column("link_id").to_pylist():
            if lid is None:
                continue
            lane_count[lid] = lane_count.get(lid, 0) + 1

        for i, row in enumerate(link_arrow.to_pylist()):
            declared = row.get("lanes")
            lid = row.get("link_id")
            if declared is None or lid is None:
                continue
            actual = lane_count.get(lid, 0)
            if actual == 0:
                # No lane rows for this link — underspecified, not a mismatch.
                continue
            if int(declared) == actual:
                continue
            report.add_issue(
                Issue(
                    severity=self.severity,
                    category=Category.DATA_QUALITY,
                    code=self.code,
                    message=(
                        f"link row {i} (link_id={lid!r}): link.lanes={declared} "
                        f"but lane table has {actual} rows for this link."
                    ),
                    table="link",
                    column="lanes",
                    row=i,
                    fix_hint="Either correct link.lanes or add/remove lane rows.",
                )
            )


# ---------------------------------------------------------------------------
# Rule 4 — duplicate/near-duplicate nodes (within ε meters)
# ---------------------------------------------------------------------------


class DuplicateNearNodesRule:
    """Flag pairs of nodes within ``epsilon_units`` of each other.

    Threshold keys:

    * ``epsilon_units`` (default ``1e-5``) — distance threshold in the
      node coordinate CRS units. The default is deliberately tiny so
      it means "effectively duplicate" in any CRS: ~1m for WGS84 at
      mid-latitudes; a hair's breadth for projected coords. **Tune it
      for your CRS.** For projected networks (UTM, state plane) where
      coordinates are meters, ``5.0`` is a reasonable "near-duplicate"
      threshold. For WGS84 degrees, ``0.0001`` is roughly 10m.

    Implementation: quadratic O(n²) scan — fine for typical GMNS
    networks (<100k nodes). For regional-scale we'd swap in a node-
    points STRtree; tracked as future work.
    """

    code = "quality.duplicate_near_nodes"
    description = "Pairs of nodes within epsilon distance of each other."
    severity = Severity.WARNING

    def applies_to(self, package: Package) -> bool:
        """Needs a node table with node_id + x_coord + y_coord columns."""
        node = package.tables.get("node")
        if node is None:
            return False
        cols = set(node.columns())
        return {"node_id", "x_coord", "y_coord"} <= cols

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """O(n^2) scan over node points; flag every pair within epsilon."""
        epsilon = _threshold(rc, "epsilon_units", 1e-5)
        # Quadratic scan is fine for typical GMNS networks (<100k nodes).
        # For regional-scale we'd reach for a STRtree over the node points;
        # task 3.9 ships one for links — we'll add the node-points index
        # in a follow-up if profiling demands it (filed as future work).
        arrow = _to_arrow(package.tables["node"])
        rows = list(
            zip(
                arrow.column("node_id").to_pylist(),
                arrow.column("x_coord").to_pylist(),
                arrow.column("y_coord").to_pylist(),
                strict=True,
            )
        )
        # Drop nulls + numeric-coerce up front.
        clean = [(nid, float(x), float(y)) for nid, x, y in rows if nid is not None and x is not None and y is not None]
        epsilon_sq = epsilon * epsilon
        seen_pairs: set[tuple[Any, Any]] = set()
        for i in range(len(clean)):
            id_i, xi, yi = clean[i]
            for j in range(i + 1, len(clean)):
                id_j, xj, yj = clean[j]
                dx, dy = xi - xj, yi - yj
                if dx * dx + dy * dy > epsilon_sq:
                    continue
                pair = (id_i, id_j) if str(id_i) < str(id_j) else (id_j, id_i)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                report.add_issue(
                    Issue(
                        severity=self.severity,
                        category=Category.DATA_QUALITY,
                        code=self.code,
                        message=(
                            f"node_id={id_i!r} and node_id={id_j!r} are within "
                            f"epsilon={epsilon} of each other "
                            f"(distance ~ {(dx * dx + dy * dy) ** 0.5:.4g})."
                        ),
                        table="node",
                        fix_hint="If they represent the same intersection, merge via gmnspy.clean.merge_close_nodes.",
                        extra={"node_ids": [id_i, id_j]},
                    )
                )


# ---------------------------------------------------------------------------
# Rule 5 — sharp interior angles on link geometries
# ---------------------------------------------------------------------------


class SharpAngleBendsRule:
    """Flag links whose geometry contains an interior turn angle below threshold.

    Threshold keys:

    * ``min_angle_degrees`` (default ``30.0``) — any interior vertex
      with a turn angle below this is flagged.

    Skips links without inline ``geometry`` (the geometry-table case is
    handled by :func:`gmnspy.semantics.assemble_link_geometry` callers
    who run this rule after assembly).

    Requires shapely (clean extra).
    """

    code = "quality.sharp_angle_bends"
    description = "Link geometry has a sharp interior turn angle."
    severity = Severity.WARNING

    def applies_to(self, package: Package) -> bool:
        """Needs a link table with an inline ``geometry`` column."""
        link = package.tables.get("link")
        if link is None:
            return False
        return "geometry" in link.columns()

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """Parse each link's WKT, compute interior turn angles, flag those below threshold."""
        import math

        from shapely import from_wkt

        min_angle = _threshold(rc, "min_angle_degrees", 30.0)
        arrow = _to_arrow(package.tables["link"])
        for i, row in enumerate(arrow.to_pylist()):
            wkt = row.get("geometry")
            if wkt is None or not str(wkt).strip():
                continue
            try:
                geom = from_wkt(str(wkt))
            except Exception:  # pragma: no cover - shapely raises broadly
                continue
            if geom is None or geom.is_empty or geom.geom_type != "LineString":
                continue
            coords = list(geom.coords)
            if len(coords) < 3:
                continue
            sharpest = _min_interior_angle_deg(coords)
            if sharpest is None or sharpest >= min_angle:
                continue
            report.add_issue(
                Issue(
                    severity=self.severity,
                    category=Category.DATA_QUALITY,
                    code=self.code,
                    message=(
                        f"link row {i} (link_id={row.get('link_id')!r}): "
                        f"sharpest interior angle {sharpest:.1f}° < threshold {min_angle}°."
                    ),
                    table="link",
                    column="geometry",
                    row=i,
                    fix_hint="Verify the bend; consider splitting at the vertex with split_link_at_node.",
                    extra={"angle_degrees": sharpest},
                )
            )

        del math  # keep the local import scoped — math is only used in the helper.


def _min_interior_angle_deg(coords: list[tuple[float, float] | tuple[float, float, float]]) -> float | None:
    """Return the smallest interior turn angle (degrees) along ``coords``.

    Returns ``None`` for collinear / degenerate sequences. 180° means
    straight-through (no turn); 0° means a U-turn.
    """
    import math

    smallest = 180.0
    found = False
    for i in range(1, len(coords) - 1):
        ax, ay = coords[i - 1][:2]
        bx, by = coords[i][:2]
        cx, cy = coords[i + 1][:2]
        v1x, v1y = ax - bx, ay - by
        v2x, v2y = cx - bx, cy - by
        n1 = math.hypot(v1x, v1y)
        n2 = math.hypot(v2x, v2y)
        if n1 == 0.0 or n2 == 0.0:
            continue
        cos_t = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))
        angle = math.degrees(math.acos(cos_t))
        if angle < smallest:
            smallest = angle
            found = True
    return smallest if found else None


# ---------------------------------------------------------------------------
# Rule 6 — implausible volume / capacity ratio
# ---------------------------------------------------------------------------


class ImplausibleVcRule:
    """Flag links with ``volume / capacity > threshold``.

    Threshold keys:

    * ``vc_max`` (default ``1.5``) — anything above is flagged.
    * ``volume_column`` (default ``"volume"``) — column name to read
      for volume. The base spec doesn't define one; loaded networks
      often add it as an extension. The rule skips silently if the
      column is absent.

    Skips rows where either ``capacity`` is null or zero (would be a
    divide-by-zero) — those should surface via the schema validator,
    not here.
    """

    code = "quality.implausible_vc"
    description = "Link volume / capacity above plausibility threshold."
    severity = Severity.WARNING

    def applies_to(self, package: Package) -> bool:
        """Needs a link table with a ``capacity`` column (volume column is configurable)."""
        link = package.tables.get("link")
        if link is None:
            return False
        return "capacity" in link.columns()

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """Compute volume / capacity per link; flag rows above ``vc_max``."""
        vc_max = _threshold(rc, "vc_max", 1.5)
        volume_col = rc.thresholds.get("volume_column", "volume") if rc else "volume"
        arrow = _to_arrow(package.tables["link"])
        if volume_col not in arrow.column_names:
            return  # No volume column — nothing to check.
        for i, row in enumerate(arrow.to_pylist()):
            cap = row.get("capacity")
            vol = row.get(volume_col)
            if cap is None or vol is None or float(cap) == 0.0:
                continue
            vc = float(vol) / float(cap)
            if vc <= vc_max:
                continue
            report.add_issue(
                Issue(
                    severity=self.severity,
                    category=Category.DATA_QUALITY,
                    code=self.code,
                    message=(
                        f"link row {i} (link_id={row.get('link_id')!r}): "
                        f"volume={vol} / capacity={cap} = {vc:.2f} > threshold {vc_max}."
                    ),
                    table="link",
                    column=volume_col,
                    row=i,
                    fix_hint="Verify the volume estimate or recompute capacity.",
                    extra={"vc_ratio": vc},
                )
            )


# ---------------------------------------------------------------------------
# Rule 7 — missing critical-but-optional fields
# ---------------------------------------------------------------------------


class MissingCriticalFieldsRule:
    """Flag tables where a "should have" but spec-optional column is mostly null.

    Threshold keys:

    * ``coverage_min`` (default ``0.90``) — minimum fraction of
      non-null rows required to NOT flag the column.

    Emits one ``Severity.INFO`` issue per affected (table, column)
    pair. Targets the columns the GMNS community treats as effectively
    required even when the spec marks them optional —
    ``link.length``, ``link.free_speed``, ``link.capacity``,
    ``link.lanes``.
    """

    code = "quality.missing_critical_fields"
    description = "Critical-but-optional column has high null rate."
    severity = Severity.INFO
    _CRITICAL_LINK_FIELDS: frozenset[str] = frozenset({"length", "free_speed", "capacity", "lanes"})

    def applies_to(self, package: Package) -> bool:
        """Needs a link table (we check the critical columns inside :meth:`run`)."""
        return "link" in package.tables

    def run(self, package: Package, report: ValidationReport, rc: RuleConfig | None = None) -> None:
        """For each critical column present, emit an Info issue if non-null coverage < threshold."""
        coverage_min = _threshold(rc, "coverage_min", 0.90)
        arrow = _to_arrow(package.tables["link"])
        if arrow.num_rows == 0:
            return
        for col_name in self._CRITICAL_LINK_FIELDS:
            if col_name not in arrow.column_names:
                continue
            values = arrow.column(col_name).to_pylist()
            non_null = sum(1 for v in values if v is not None)
            coverage = non_null / arrow.num_rows
            if coverage >= coverage_min:
                continue
            report.add_issue(
                Issue(
                    severity=self.severity,
                    category=Category.DATA_QUALITY,
                    code=self.code,
                    message=(
                        f"link.{col_name}: {non_null}/{arrow.num_rows} rows non-null "
                        f"(coverage {coverage:.0%} < threshold {coverage_min:.0%})."
                    ),
                    table="link",
                    column=col_name,
                    fix_hint=(
                        "Backfill from upstream OSM / model data, or document why the column "
                        "is intentionally sparse for this network."
                    ),
                    extra={"coverage": coverage},
                )
            )


# ---------------------------------------------------------------------------
# Entry-point factory
# ---------------------------------------------------------------------------


def register_all() -> list[object]:
    """Construct + register every rule in this module.

    Wired as the ``datagrove.quality.rules`` entry point for the
    ``gmnspy`` distribution (see ``packages/gmnspy/pyproject.toml``).
    Also callable directly from tests / ad-hoc scripts: ``register_all()``
    returns the list of registered rule instances.
    """
    rules: list[object] = [
        HighSpeedResidentialRule(),
        DisconnectedComponentsRule(),
        LaneCountMismatchRule(),
        DuplicateNearNodesRule(),
        SharpAngleBendsRule(),
        ImplausibleVcRule(),
        MissingCriticalFieldsRule(),
    ]
    for r in rules:
        register_rule(r)  # type: ignore[arg-type]
    return rules
