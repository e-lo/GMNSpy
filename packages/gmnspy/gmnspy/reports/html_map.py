"""Network-on-map HTML viewer — Leaflet map pane + issue table.

This module composes the final interactive HTML report from
:func:`render_network_html`: it materialises one ``links`` /
``nodes`` DataFrame per render via the engine-agnostic
:class:`~gmnspy.network.Network`, resolves each
:class:`~datagrove.reports.Issue` to a ``(lon, lat)`` via
:class:`~gmnspy.reports.geo_resolver.GeoResolver`, attaches an OSM
"Edit in" deep link when the network is OSM-sourced (see
:mod:`gmnspy.osm.edit`), and renders the lot through the vendored
Jinja template under ``templates/map_report.html.j2``. Output is a
single self-contained HTML string — Leaflet itself is inlined from
``templates/leaflet.min.{js,css}``.

The viewer is GMNS-specific only by composition: the underlying issue
container is the engine-agnostic
:class:`~datagrove.reports.ValidationReport`, so any
:class:`~datagrove.reports.Issue` source (validation, quality, graph
topology, custom rules) plugs in here unchanged.
"""

from __future__ import annotations

import contextlib
import json
from importlib import resources
from typing import TYPE_CHECKING, Any

from gmnspy.osm.edit import issue_osm_edit_url

from .geo_resolver import GeoResolver, _parse_linestring_points

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.reports import Issue, ValidationReport

    from gmnspy.network import Network

__all__ = ["render_network_html", "render_validation_html"]


# Number of link polylines we draw for the network underlay. Past a few
# thousand the canvas slows down without clustering — defer that work to
# v2 and just thin the underlay.
_MAX_LINK_UNDERLAY = 2000


def render_network_html(
    network: Network,
    issues: list[Issue] | None = None,
    *,
    title: str | None = None,
    tile_provider: str = "openstreetmap",
    osm_editor: str = "id",
) -> str:
    """Render a self-contained interactive HTML map of ``network`` with ``issues`` overlaid.

    Args:
        network: The :class:`~gmnspy.network.Network` to render. Always
            shown — the network is the primary thing being visualised.
        issues: Optional list of :class:`~datagrove.reports.Issue`
            objects to overlay as clickable markers. ``None`` or empty
            renders the network alone.
        title: Optional override for the ``<title>`` / ``<h1>``. Falls
            back to ``"GMNS network"`` (or a validation-style title from
            :func:`render_validation_html`).
        tile_provider: ``"openstreetmap"`` (default) or
            ``"carto-positron"`` — the basemap tile source.
        osm_editor: ``"id"`` (default) or ``"josm"`` — which editor
            "Edit in OSM" links point to. No-op for non-OSM networks.

    Returns:
        A single self-contained HTML string. Open in a browser as-is,
        or save with ``Path.write_text()``.
    """
    try:
        from jinja2 import Environment, StrictUndefined
    except ImportError as e:  # pragma: no cover - defensive
        raise ImportError(
            "gmnspy.reports.render_network_html requires jinja2 from the [reports] extra: pip install 'gmnspy[reports]'"
        ) from e

    issues = list(issues or [])

    # Resolve coords + OSM edit URL once, in order, so each issue gets a
    # stable issue_id (index in the input list) and table+marker stay in sync.
    resolver = GeoResolver(network)
    enriched: list[dict[str, Any]] = []
    for i, issue in enumerate(issues):
        coord = resolver.resolve(issue)
        edit_url = issue_osm_edit_url(issue, network, editor=osm_editor)  # type: ignore[arg-type]
        enriched.append(
            {
                "issue_id": f"i{i}",
                "severity": issue.severity.value,
                "category": issue.category.value,
                "code": issue.code,
                "message": issue.message,
                "fix_hint": issue.fix_hint,
                "table": issue.table,
                "column": issue.column,
                "row": issue.row,
                "edit_url": edit_url,
                "lon": coord[0] if coord else None,
                "lat": coord[1] if coord else None,
                "located": coord is not None,
            }
        )

    located = [e for e in enriched if e["located"]]
    unlocated = [e for e in enriched if not e["located"]]

    # Counts for the header chips. Mirrors datagrove's severity order.
    counts: list[tuple[str, int]] = []
    if issues:
        from collections import Counter

        sev_counts = Counter(e["severity"] for e in enriched)
        for sev in ("error", "warning", "info"):
            if sev_counts.get(sev):
                counts.append((sev, sev_counts[sev]))

    payload = {
        "tile_provider": tile_provider,
        "links": _link_underlay_coords(network),
        "bbox": _network_bbox(network),
        "markers": [
            {
                "issue_id": e["issue_id"],
                "lon": e["lon"],
                "lat": e["lat"],
                "severity": e["severity"],
                "code": e["code"],
                "message": e["message"],
                "fix_hint": e["fix_hint"],
                "table": e["table"],
                "row": e["row"],
                "edit_url": e["edit_url"],
            }
            for e in located
        ],
    }

    filter_options = {
        "severity": sorted({e["severity"] for e in enriched}),
        "table": sorted({e["table"] for e in enriched if e["table"]}),
    }

    env = Environment(autoescape=True, undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
    template_source = _read_template("map_report.html.j2")
    template = env.from_string(template_source)

    final_title = title or "GMNS network"
    return template.render(
        title=final_title,
        meta_subtitle=_meta_subtitle(network),
        counts=counts,
        leaflet_css=_read_template("leaflet.min.css"),
        leaflet_js=_read_template("leaflet.min.js"),
        map_css=_read_template("map_report.css"),
        map_js=_read_template("map_report.js"),
        payload_json=json.dumps(payload),
        issues=enriched,
        filter_options=filter_options,
        located_count=len(located),
        unlocated=unlocated,
    )


def render_validation_html(
    network: Network,
    report: ValidationReport,
    **opts: Any,
) -> str:
    """Convenience wrapper around :func:`render_network_html` for a validation report.

    Equivalent to::

        render_network_html(
            network,
            report.issues,
            title=f"validation: {report.source}",
            **opts,
        )

    Args:
        network: The network the validation report was raised against.
        report: The :class:`~datagrove.reports.ValidationReport` to render.
        **opts: Forwarded to :func:`render_network_html`.

    Returns:
        Self-contained HTML string.
    """
    title = opts.pop("title", None) or f"validation: {report.source or 'gmns network'}"
    return render_network_html(network, list(report.issues), title=title, **opts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_template(name: str) -> str:
    """Read one of the bundled template assets under ``reports/templates``."""
    return (resources.files("gmnspy.reports") / "templates" / name).read_text(encoding="utf-8")


def _meta_subtitle(network: Network) -> str | None:
    """One-line subtitle under the page H1: spec version + link/node counts when known."""
    bits: list[str] = []
    if getattr(network, "spec_version", None):
        bits.append(f"GMNS {network.spec_version}")
    link = network.tables.get("link")
    node = network.tables.get("node")
    if link is not None:
        with contextlib.suppress(Exception):
            bits.append(f"{link.count()} links")
    if node is not None:
        with contextlib.suppress(Exception):
            bits.append(f"{node.count()} nodes")
    return " · ".join(bits) if bits else None


def _network_bbox(network: Network) -> list[float] | None:
    """Return ``[west, south, east, north]`` from node coords, or ``None``."""
    node = network.tables.get("node")
    if node is None:
        return None
    try:
        df = node.to_pandas()
    except Exception:
        return None
    if "x_coord" not in df.columns or "y_coord" not in df.columns or df.empty:
        return None
    return [
        float(df["x_coord"].min()),
        float(df["y_coord"].min()),
        float(df["x_coord"].max()),
        float(df["y_coord"].max()),
    ]


def _link_underlay_coords(network: Network) -> list[list[list[float]]]:
    """Return the polyline coords to draw as the network underlay.

    Reads the link table's ``geometry`` column when present, otherwise
    synthesises one segment from the from/to node coords. Capped at
    :data:`_MAX_LINK_UNDERLAY` polylines — past that, the underlay
    slows the page down without clustering.
    """
    link = network.tables.get("link")
    node = network.tables.get("node")
    if link is None or node is None:
        return []
    try:
        link_df = link.to_pandas()
        node_df = node.to_pandas()
    except Exception:
        return []
    if link_df.empty or node_df.empty:
        return []

    polylines: list[list[list[float]]] = []
    if "geometry" in link_df.columns:
        for wkt in link_df["geometry"].head(_MAX_LINK_UNDERLAY):
            pts = _parse_linestring_points(wkt)
            if len(pts) >= 2:
                polylines.append([[lon, lat] for lon, lat in pts])
        if polylines:
            return polylines

    if {"node_id", "x_coord", "y_coord"} <= set(node_df.columns) and {"from_node_id", "to_node_id"} <= set(
        link_df.columns
    ):
        coord_by_id = {
            nid: (float(x), float(y))
            for nid, x, y in zip(node_df["node_id"], node_df["x_coord"], node_df["y_coord"], strict=False)
        }
        for f, t in zip(
            link_df["from_node_id"].head(_MAX_LINK_UNDERLAY),
            link_df["to_node_id"].head(_MAX_LINK_UNDERLAY),
            strict=False,
        ):
            a = coord_by_id.get(f)
            b = coord_by_id.get(t)
            if a and b:
                polylines.append([[a[0], a[1]], [b[0], b[1]]])
    return polylines
