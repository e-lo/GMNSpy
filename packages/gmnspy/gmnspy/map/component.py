"""``NetworkMap`` — embeddable Leaflet map component for a GMNS network.

A :class:`NetworkMap` instance is the reusable unit: any host page (a
notebook cell, the validation report, a custom dashboard, a blog post)
can include the shared head assets once and drop in one or more body
fragments — each fragment is just the map's ``<div>`` and an inline
bootstrap script that attaches Leaflet to that specific div.

The split lets the same component appear:

* standalone (see :meth:`NetworkMap.to_html`),
* alongside a findings table (see :func:`gmnspy.map.render_validation_html`),
* inline in a Jupyter cell (see :meth:`NetworkMap._repr_html_`),
* in your own HTML page (call :meth:`head_assets` and
  :meth:`body_fragment` directly and place them wherever you want).

Multiple instances on a single host page coexist via unique UIDs; the
shared head assets are idempotent — including them twice changes nothing
about the rendered page (the JS attach function detects a prior
definition and just drains the queue).
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from html import escape as html_escape
from importlib import resources
from typing import TYPE_CHECKING, Any

from gmnspy.osm.edit import issue_osm_edit_url

from .geo_resolver import GeoResolver

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.reports import Issue

    from gmnspy.network import Network

__all__ = ["NetworkMap"]


# Cap per-layer item rendering. Past a few thousand polylines the canvas
# slows down without clustering — defer that work to a future PR.
_MAX_LAYER_ITEMS = 2000


def _read_asset(name: str) -> str:
    """Read a bundled template / asset file as text."""
    return (resources.files("gmnspy.map") / "templates" / name).read_text(encoding="utf-8")


def _sanitise_leaflet_css(css: str) -> str:
    """Strip Leaflet's dead-weight ``url(images/...)`` refs.

    We use ``L.circleMarker`` and a custom toggle widget — never Leaflet's
    default ``L.Marker`` or ``L.Control.Layers`` — so the marker-icon and
    layer-control PNG references would just 404 and (on ``file://``)
    trigger the unique-origin security warning. Strip them.
    """
    return re.sub(r"url\(images/[^)]*\)", "none", css)


class NetworkMap:
    """Embeddable Leaflet map of a :class:`~gmnspy.network.Network`.

    Args:
        network: The network to render. Always shown.
        issues: Optional :class:`~datagrove.reports.Issue` overlays
            (validation findings, quality rule outputs, custom rules, …).
            ``None`` or empty renders just the network.
        title: Used as ``<title>`` and ``<h1>`` text in
            :meth:`to_html`; ignored by :meth:`body_fragment` (the
            embed has no title — the host page provides one).
        tile_provider: ``"carto-positron"`` (default — muted grey) or
            ``"openstreetmap"``.
        osm_editor: ``"id"`` or ``"josm"`` — which editor "Edit in OSM"
            popup links point to. No-op for non-OSM-sourced networks.
        height: CSS height for the map ``<div>``. Inline-styled so a
            host page can size embeds independently.
        uid: Stable identifier for the instance. Auto-generated if not
            provided. Useful to pin in tests or to deep-link to a
            specific embed on a multi-map page.

    Examples:
        Standalone single-file HTML::

            >>> from gmnspy import Network
            >>> from gmnspy.fixtures import leavenworth
            >>> from datagrove.engines.pandas_engine import PandasEngine
            >>> from gmnspy.map import NetworkMap
            >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
            >>> html = NetworkMap(net, title="Leavenworth").to_html()
            >>> html.lstrip().startswith("<!DOCTYPE html>")
            True

        Compose two maps in one custom page::

            >>> a = NetworkMap(net, uid="left", title="Left").body_fragment()
            >>> b = NetworkMap(net, uid="right", title="Right").body_fragment()
            >>> head = NetworkMap.head_assets()
            >>> page = f"<!DOCTYPE html><html><head>{head}</head><body>{a}{b}</body></html>"
            >>> 'gv-map-left' in page and 'gv-map-right' in page
            True
    """

    def __init__(
        self,
        network: Network,
        *,
        issues: list[Issue] | None = None,
        title: str | None = None,
        tile_provider: str = "carto-positron",
        osm_editor: str = "id",
        height: str = "480px",
        uid: str | None = None,
    ) -> None:
        """Bind the network + optional issue overlay to a fresh NetworkMap instance."""
        self.network = network
        self.issues: list[Issue] = list(issues or [])
        self.title = title or "GMNS network"
        self.tile_provider = tile_provider
        self.osm_editor = osm_editor
        self.height = height
        self.uid = uid or f"m{uuid.uuid4().hex[:10]}"

    # ------------------------------------------------------------------
    # Public composition surface
    # ------------------------------------------------------------------

    @classmethod
    def head_assets(cls) -> str:
        """Shared CSS + JS for any number of :class:`NetworkMap` instances.

        Returns an HTML string containing the inlined Leaflet
        CSS+JS, water.css baseline, our component CSS, and the
        :func:`window.__gmnspyAttach` definition + queue drainer. Include
        ONCE in the host page's ``<head>``; idempotent if included
        multiple times.

        The string contains ``<style>`` and ``<script>`` blocks — drop
        it verbatim. No remote references; the report works offline.
        """
        leaflet_css = _sanitise_leaflet_css(_read_asset("leaflet.min.css"))
        water_css = _read_asset("water.min.css")
        component_css = _read_asset("map_component.css")
        leaflet_js = _read_asset("leaflet.min.js")
        component_js = _read_asset("map_component.js")
        # F-strings (no Jinja autoescape on this path) so CSS child-combinator
        # selectors like ``.leaflet-pane > svg`` survive intact.
        # ``test_head_assets_css_is_safe_against_jinja_autoescape`` pins this.
        return (
            f"<style>{water_css}</style>"
            f"<style>{leaflet_css}</style>"
            f"<style>{component_css}</style>"
            f"<script>{leaflet_js}</script>"
            f"<script>{component_js}</script>"
        )

    def body_fragment(self) -> str:
        """Per-instance embed: the ``<div>`` + bootstrap script.

        Place this anywhere on the host page. Multiple instances can
        coexist — each carries its own UID and its own payload slot in
        ``window.__GMNSPY_INSTANCES__``.
        """
        try:
            from jinja2 import Environment, StrictUndefined
        except ImportError as e:  # pragma: no cover - defensive
            raise ImportError(
                "gmnspy.map.NetworkMap requires jinja2 from the [reports] extra: pip install 'gmnspy[reports]'"
            ) from e

        env = Environment(autoescape=True, undefined=StrictUndefined)
        template = env.from_string(_read_asset("map_fragment.html.j2"))
        return template.render(
            uid=self.uid,
            height=self.height,
            payload_json=json.dumps(self._payload()),
        )

    def to_html(self) -> str:
        """Full standalone ``<!DOCTYPE html>`` document wrapping this map."""
        try:
            from jinja2 import Environment, StrictUndefined
        except ImportError as e:  # pragma: no cover - defensive
            raise ImportError(
                "gmnspy.map.NetworkMap requires jinja2 from the [reports] extra: pip install 'gmnspy[reports]'"
            ) from e

        env = Environment(autoescape=True, undefined=StrictUndefined)
        template = env.from_string(_read_asset("standalone_map.html.j2"))
        return template.render(
            title=self.title,
            meta_subtitle=_meta_subtitle(self.network),
            head_assets=self.head_assets(),
            body_fragment=self.body_fragment(),
        )

    def _repr_html_(self) -> str:
        """Render inline in a Jupyter cell, isolated in an iframe.

        Notebooks ship a lot of their own CSS; rendering the standalone
        document inside an iframe via ``srcdoc`` keeps the host
        notebook's styles from leaking into our chrome (and vice versa).
        """
        # Pull the configured height through to the iframe so the map
        # actually has room to render.
        return (
            f'<iframe srcdoc="{html_escape(self.to_html(), quote=True)}" '
            f'width="100%" height="{html_escape(self.height, quote=True)}" '
            f'style="border:none; min-height: 480px;"></iframe>'
        )

    # ------------------------------------------------------------------
    # Payload construction — pulled out so render.py (the validation
    # report composer) can reuse counts / unlocated / enriched issues.
    # ------------------------------------------------------------------

    def enriched_issues(self) -> list[dict[str, Any]]:
        """Resolve every input issue to coords + OSM edit URL + stable issue_id.

        Re-used by :func:`gmnspy.map.render_validation_html` so the
        findings table and the map markers stay in sync.
        """
        resolver = GeoResolver(self.network)
        out: list[dict[str, Any]] = []
        for i, issue in enumerate(self.issues):
            coord = resolver.resolve(issue)
            edit_url = issue_osm_edit_url(issue, self.network, editor=self.osm_editor)  # type: ignore[arg-type]
            out.append(
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
        return out

    # ------------------------------------------------------------------
    # Internal — payload assembly
    # ------------------------------------------------------------------

    def _payload(self) -> dict[str, Any]:
        """Build the JSON blob the JS reads to attach + populate this instance."""
        resolver = GeoResolver(self.network)
        link_features = resolver.link_features(limit=_MAX_LAYER_ITEMS)
        node_features = resolver.node_features(limit=_MAX_LAYER_ITEMS)

        # Build positional row → props lookups so each marker can carry the
        # full row contents into the popup. The edit log needs the PK
        # (e.g. link_id) to identify the row stably; the editor needs the
        # current values to pre-fill and to drift-check on apply.
        feature_props_by_row = {
            "link": {i: f["props"] for i, f in enumerate(link_features)},
            "node": {i: f["props"] for i, f in enumerate(node_features)},
        }

        layers: list[dict[str, Any]] = []
        if link_features:
            layers.append(
                {
                    "id": "links",
                    "label": "Links",
                    "type": "polyline",
                    "count": len(link_features),
                    "default_on": True,
                    "style": {"color": "#1f77b4", "weight": 3, "opacity": 0.9},
                    "items": link_features,
                }
            )
        if node_features:
            layers.append(
                {
                    "id": "nodes",
                    "label": "Nodes",
                    "type": "point",
                    "count": len(node_features),
                    "default_on": False,
                    "style": {"color": "#1f77b4", "radius": 3, "fillOpacity": 0.85},
                    "items": node_features,
                }
            )

        markers: list[dict[str, Any]] = []
        for e in self.enriched_issues():
            if not e["located"]:
                continue
            row_props = None
            if e["table"] in feature_props_by_row and e["row"] is not None:
                row_props = feature_props_by_row[e["table"]].get(e["row"])
            markers.append(
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
                    # The full props for this row — drives the inline "Propose
                    # fix" editor: pre-fills the suspect column with its
                    # current value and carries the PK (link_id/node_id) used
                    # to write the edit-log entry.
                    "row_props": row_props,
                    "column": e["column"],
                }
            )

        return {
            "tile_provider": self.tile_provider,
            "bbox": _network_bbox(self.network),
            "layers": layers,
            "markers": markers,
        }


# ---------------------------------------------------------------------------
# Module-level helpers (kept here, alongside the only caller)
# ---------------------------------------------------------------------------


def _meta_subtitle(network: Network) -> str | None:
    """One-line subtitle: GMNS spec version + link/node counts."""
    import contextlib

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


def _severity_counts(enriched: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Per-severity counts in canonical display order."""
    sev_counts = Counter(e["severity"] for e in enriched)
    return [(sev, sev_counts[sev]) for sev in ("error", "warning", "info") if sev_counts.get(sev)]
