// deck.gl-over-MapLibre network rendering, picking, and camera moves.
import { $, esc } from "./dom.js";
import { widthForLanes } from "./netbuf.js";
import { buildLinkColors } from "./palette.js";
import { activeSelection, store } from "./store.js";

const OFFSET_EXT = typeof deck.PathStyleExtension === "function" ? new deck.PathStyleExtension({ offset: true }) : null;
const OFFSET_AMT = 0.8, ARROW_ZOOM = 13;
const PICK_COLOR = [45, 210, 230];
const ARROW_SVG = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><polygon points="12,3 20,21 12,16 4,21" fill="white"/></svg>');
const TOOLTIP_STYLE = { background: "#11151a", color: "#e6e8ec", fontSize: "12px", padding: "6px 8px",
  borderRadius: "6px", border: "1px solid #2a2f3a" };

let map = null, overlay = null, onLinkClick = () => {};
let colorCache = { key: null, colors: null };
let labelsShown = true;

export const hasOffset = () => OFFSET_EXT !== null;

export function initMap(style, handlers) {
  onLinkClick = handlers.onLinkClick;
  map = new maplibregl.Map({ container: "map", style, center: [-98.5, 39.8], zoom: 3 });
  map.addControl(new maplibregl.NavigationControl(), "top-left");
  overlay = new deck.MapboxOverlay({ interleaved: false, layers: [], getTooltip });
  map.addControl(overlay);
  new ResizeObserver(() => map.resize()).observe($("map"));
  map.on("zoomend", () => { const s = store.get(); if (s.server && s.server.style.show_direction) render(); });
  map.on("load", handlers.onReady);
  wireBoxSelect();
}

export function resizeSoon() { if (map) setTimeout(() => map.resize(), 60); }

function linkColors(s) {
  const st = s.server.style;
  const key = JSON.stringify([s.netKey, st.color_by, st.ramp, st.colors.links, s.prop && s.prop.name]);
  if (colorCache.key !== key) colorCache = { key, colors: buildLinkColors(s.net, st, s.prop) };
  return colorCache.colors;
}

function baseLayers(net, style, colors) {
  const layers = [];
  if (style.show.nodes) layers.push(new deck.ScatterplotLayer({ id: "nodes",
    data: { length: net.N.count, attributes: { getPosition: { value: net.nodePositions, size: 2 } } },
    getRadius: 1.8, radiusUnits: "pixels", radiusMinPixels: 1,
    getFillColor: [...style.colors.nodes, 150], pickable: false }));
  if (style.show.links) {
    const props = { id: "links", _pathType: "open",
      data: { length: net.L.count, startIndices: net.linkStart,
        attributes: { getPath: { value: net.linkPositions, size: 2 }, getWidth: { value: net.linkWidths, size: 1 },
                      getColor: { value: colors, size: 4 } } },
      widthUnits: "pixels", widthMinPixels: 1, capRounded: true, jointRounded: true,
      pickable: true, autoHighlight: true, highlightColor: [255, 140, 59, 235],
      onClick: info => { if (info && info.index >= 0) onLinkClick(store.get().attrs.link_id[info.index]); } };
    if (OFFSET_EXT) { props.extensions = [OFFSET_EXT]; props.getOffset = style.offset ? OFFSET_AMT : 0; }
    layers.push(new deck.PathLayer(props));
    if (style.show_direction && map.getZoom() >= ARROW_ZOOM) layers.push(new deck.IconLayer({ id: "arrows",
      data: net.arrows, getIcon: () => ({ url: ARROW_SVG, width: 24, height: 24, anchorY: 12 }),
      getPosition: d => d.position, getAngle: d => d.angle, getSize: 13, sizeUnits: "pixels",
      getColor: [40, 52, 78, 230], pickable: false }));
  }
  return layers;
}

// A highlight PathLayer over a set of link ids (shared by selection + picks).
function idPathLayer(net, layerId, ids, color, extraWidth) {
  const positions = [], startIndices = [0], widths = [];
  for (const id of ids) {
    const i = net.id2idx.get(id);
    if (i == null) continue;
    const w = widthForLanes(net.linkLanes[i]) + extraWidth;
    for (let k = net.linkStart[i] * 2; k < net.linkStart[i + 1] * 2; k += 2) {
      positions.push(net.linkPositions[k], net.linkPositions[k + 1]); widths.push(w);
    }
    startIndices.push(positions.length / 2);
  }
  if (startIndices.length < 2) return null;
  return new deck.PathLayer({ id: layerId, _pathType: "open",
    data: { length: startIndices.length - 1, startIndices: new Uint32Array(startIndices),
      attributes: { getPath: { value: new Float32Array(positions), size: 2 }, getWidth: { value: new Float32Array(widths), size: 1 } } },
    getColor: color, widthUnits: "pixels", widthMinPixels: 3, capRounded: true, jointRounded: true,
    parameters: { depthTest: false } });
}

function selectionLayers(net, style, sel) {
  const layers = [];
  const path = idPathLayer(net, "selection", sel.link_ids, [...style.colors.selection, 255], 3);
  if (path) layers.push(path);
  if (sel.anchors.length) layers.push(new deck.ScatterplotLayer({ id: "anchors", data: sel.anchors,
    getPosition: a => [a.lon, a.lat], getRadius: 7, radiusUnits: "pixels",
    getFillColor: a => (a.role === "from" ? [53, 196, 106] : [224, 82, 77]),
    getLineColor: [17, 21, 26], lineWidthMinPixels: 2, stroked: true, parameters: { depthTest: false } }));
  return layers;
}

function markerLayer(marker) {
  return new deck.ScatterplotLayer({ id: "marker", data: [marker], getPosition: m => [m.lon, m.lat],
    getRadius: 7, radiusUnits: "pixels", getFillColor: [45, 210, 230], getLineColor: [17, 21, 26],
    lineWidthMinPixels: 2, stroked: true, parameters: { depthTest: false } });
}

function setLabels(show) {
  if (show === labelsShown || !map.isStyleLoaded()) return;
  labelsShown = show;
  for (const l of map.getStyle().layers || [])
    if (l.type === "symbol" || l.id === "labels") map.setLayoutProperty(l.id, "visibility", show ? "visible" : "none");
}

export function render() {
  if (!overlay) return;
  const s = store.get();
  if (!s.net || !s.server) { overlay.setProps({ layers: [] }); return; }
  const style = s.server.style, sel = activeSelection(s);
  const layers = baseLayers(s.net, style, linkColors(s));
  if (style.show.selection && sel) layers.push(...selectionLayers(s.net, style, sel));
  if (s.picks.size) { const l = idPathLayer(s.net, "picked", s.picks, [...PICK_COLOR, 255], 2.5); if (l) layers.push(l); }
  if (s.marker) layers.push(markerLayer(s.marker));
  overlay.setProps({ layers });
  setLabels(style.show.labels);
}

function getTooltip({ layer, index }) {
  const attrs = store.get().attrs;
  if (!layer || layer.id !== "links" || index == null || index < 0 || !attrs) return null;
  const id = attrs.link_id[index], nm = attrs.name[index], rf = attrs.ref[index], ft = attrs.facility_type[index];
  return { html: `<b>link ${esc(id)}</b><br>${nm ? esc(nm) : "<i>unnamed</i>"}${rf ? " · " + esc(rf) : ""}` +
    `<br><span style="color:#8a93a3">${ft ? esc(ft) : ""}</span>`, style: TOOLTIP_STYLE };
}

function fit(bounds, padding, retried) {
  if (bounds.isEmpty()) return;
  const el = map.getContainer(), w = el.clientWidth, h = el.clientHeight;
  if (!retried && (w <= padding * 2 || h <= padding * 2)) {
    map.resize();
    requestAnimationFrame(() => fit(bounds, padding, true));
    return;
  }
  const p = Math.min(padding, Math.floor(Math.min(w, h) / 4));
  map.fitBounds(bounds, { padding: p, maxZoom: 15, duration: 500 });
}

export function fitNetwork() {
  const net = store.get().net;
  if (!map || !net) return;
  const b = new maplibregl.LngLatBounds();
  for (let i = 0; i < net.nodePositions.length; i += 2) b.extend([net.nodePositions[i], net.nodePositions[i + 1]]);
  fit(b, 60);
}

export function fitLinks(ids) {
  const net = store.get().net;
  if (!map || !net || !ids || !ids.length) return;
  const b = new maplibregl.LngLatBounds();
  for (const id of ids) {
    const i = net.id2idx.get(id);
    if (i == null) continue;
    for (let k = net.linkStart[i] * 2; k < net.linkStart[i + 1] * 2; k += 2) b.extend([net.linkPositions[k], net.linkPositions[k + 1]]);
  }
  fit(b, 80);
}

export function fitBbox(bbox) { if (map) map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 40, duration: 500 }); }

export function flyToNode(nodeId) {
  const net = store.get().net, i = net && net.nodeId2idx.get(nodeId);
  if (i == null) return;
  const lon = net.nodePositions[i * 2], lat = net.nodePositions[i * 2 + 1];
  store.set({ marker: { lon, lat } });
  map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 15), duration: 500 });
}

// shift-drag box select over the links layer (deck region picking) adds to picks
function wireBoxSelect() {
  const mapEl = $("map"), box = $("boxsel");
  let start = null;
  const deckInstance = () => overlay._deck || (overlay.props && overlay.props.deck) || null;
  mapEl.addEventListener("pointerdown", e => {
    if (!store.get().pickMode || !e.shiftKey || e.button !== 0) return;
    e.preventDefault(); map.dragPan.disable();
    const r = mapEl.getBoundingClientRect();
    start = { x: e.clientX - r.left, y: e.clientY - r.top, rect: r };
    Object.assign(box.style, { display: "block", left: start.x + "px", top: start.y + "px", width: "0px", height: "0px" });
  });
  mapEl.addEventListener("pointermove", e => {
    if (!start) return;
    const x = e.clientX - start.rect.left, y = e.clientY - start.rect.top;
    Object.assign(box.style, { left: Math.min(x, start.x) + "px", top: Math.min(y, start.y) + "px",
      width: Math.abs(x - start.x) + "px", height: Math.abs(y - start.y) + "px" });
  });
  const finish = e => {
    if (!start) return;
    const x = e.clientX - start.rect.left, y = e.clientY - start.rect.top;
    const x0 = Math.min(x, start.x), y0 = Math.min(y, start.y), w = Math.abs(x - start.x), h = Math.abs(y - start.y);
    box.style.display = "none"; map.dragPan.enable(); start = null;
    const dk = deckInstance(), s = store.get();
    if (!dk || !s.net || w <= 2 || h <= 2) return;
    const picks = new Set(s.picks);
    for (const p of dk.pickObjects({ x: x0, y: y0, width: w, height: h, layerIds: ["links"] }))
      if (p.index != null && p.index >= 0) picks.add(s.net.linkIds[p.index]);
    store.set({ picks });
  };
  mapEl.addEventListener("pointerup", finish);
  mapEl.addEventListener("pointerleave", e => { if (start) finish(e); });
}
