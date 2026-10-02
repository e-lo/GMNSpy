// Area step: Draw / Coordinates / Place / Local file. Every map tab ends in one bbox, previewed on its own small map.
import { getJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { createFileBrowser } from "./filebrowser.js";

const M_PER_DEG_LAT = 111320; // same spherical approximation as gmnspy.osm.query.point_buffer_bbox
const OPPOSITE = [2, 3, 0, 1]; // corner order SW, SE, NE, NW; dragging one keeps its opposite fixed
const FILE_KINDS = { osm: ["osm", "json"], overture: ["overture"] };
const EMPTY = { type: "FeatureCollection", features: [] };

let map = null, markers = [], drawStart = null, drawing = false;
let tab = "draw", area = null, inputFile = null, candidates = [], fileBrowser = null, onChange = () => {};

const round6 = v => Math.round(v * 1e6) / 1e6;
const ring = b => [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]];
const corners = b => [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]];
const polygonFeature = coords => ({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coords] } });
const lonLat = poly => poly.map(([lat, lon]) => [lon, lat]); // place polygons are (lat, lon), like the server's
const bboxOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])].map(round6);

export function pointBbox(lat, lon, m) {
  const dlat = m / M_PER_DEG_LAT, cos = Math.cos((lat * Math.PI) / 180);
  const dlon = cos ? m / (M_PER_DEG_LAT * cos) : dlat;
  return [lon - dlon, lat - dlat, lon + dlon, lat + dlat];
}

export function areaBbox(a) { return a.kind === "point" ? pointBbox(a.lat, a.lon, a.buffer_m) : a.bbox; }

// What the build action needs from this step: {area} or {input_file}, or null when nothing is chosen yet.
export function areaChoice() {
  if (tab === "file") return inputFile ? { input_file: inputFile } : null;
  if (!area) return null;
  const b = areaBbox(area); // a click without a drag (or a corner dragged onto its opposite) has no extent
  return b[0] < b[2] && b[1] < b[3] ? { area } : null;
}

function setArea(next, { fit = false, quiet = false } = {}) {
  area = next;
  render();
  if (fit && area) { const b = areaBbox(area); map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 30, duration: 300 }); }
  if (!quiet) onChange();
}

function render() {
  if (!map || !map.getSource("ap-area")) return;
  const shape = !area ? null : area.kind === "place" && area.polygon ? lonLat(area.polygon) : ring(areaBbox(area));
  map.getSource("ap-area").setData(shape ? polygonFeature(shape) : EMPTY);
  const editable = area && area.kind === "bbox";
  markers.forEach((m, i) => {
    if (editable) m.setLngLat(corners(area.bbox)[i]).addTo(map); else m.remove();
  });
  const b = area && areaBbox(area);
  $("ap-summary").textContent = b ? `W,S,E,N = ${b.map(v => v.toFixed(5)).join(", ")}` : "No area yet.";
}

function makeMarkers() {
  markers = [0, 1, 2, 3].map(i => {
    const m = new maplibregl.Marker({ draggable: true, color: "#2dd2e6", scale: 0.6 });
    let fixed = null; // captured at dragstart, so dragging past the opposite corner cannot swap which one is fixed
    m.on("dragstart", () => { fixed = corners(area.bbox)[OPPOSITE[i]]; });
    m.on("drag", () => {
      const p = m.getLngLat();
      area = { kind: "bbox", bbox: bboxOf([p.lng, p.lat], fixed) };
      map.getSource("ap-area").setData(polygonFeature(ring(area.bbox)));
    });
    m.on("dragend", () => setArea(area));
    return m;
  });
}

function wireDraw() {
  map.on("mousedown", e => {
    if (!drawing) return;
    e.preventDefault();
    drawStart = [e.lngLat.lng, e.lngLat.lat];
  });
  map.on("mousemove", e => {
    if (drawStart) setArea({ kind: "bbox", bbox: bboxOf(drawStart, [e.lngLat.lng, e.lngLat.lat]) }, { quiet: true });
  });
  map.on("mouseup", () => {
    if (!drawStart) return;
    drawStart = null; drawing = false;
    map.dragPan.enable(); map.getCanvas().style.cursor = ""; $("ap-draw").classList.remove("on");
    onChange();
  });
}

// Create the preview map the first time the Area step is shown (a hidden container has no size).
export function showAreaMap(style) {
  if (map) { map.resize(); return; }
  map = new maplibregl.Map({ container: "ap-map", style, center: [-98.5, 39.8], zoom: 3 });
  map.on("load", () => {
    map.addSource("ap-area", { type: "geojson", data: EMPTY });
    map.addSource("ap-cands", { type: "geojson", data: EMPTY });
    map.addLayer({ id: "ap-cands-line", type: "line", source: "ap-cands",
      paint: { "line-color": "#9aa3b2", "line-width": 1, "line-dasharray": [2, 2] } });
    map.addLayer({ id: "ap-area-fill", type: "fill", source: "ap-area", paint: { "fill-color": "#2dd2e6", "fill-opacity": 0.12 } });
    map.addLayer({ id: "ap-area-line", type: "line", source: "ap-area", paint: { "line-color": "#2dd2e6", "line-width": 2 } });
    render();
  });
  makeMarkers();
  wireDraw();
}

function setTab(name) {
  tab = name;
  for (const b of document.querySelectorAll("#ap-tabs button")) b.classList.toggle("on", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".ap-pane")) p.hidden = p.dataset.pane !== name;
  $("ap-map").hidden = name === "file";
  $("ap-summary").hidden = name === "file";
  if (name !== "file" && map) map.resize();
  onChange();
}

function applyCoordinates() {
  const nums = s => s.split(",").map(v => Number(v.trim())).filter(v => Number.isFinite(v));
  const bbox = nums($("ap-bbox").value), point = nums($("ap-point").value), buffer = Number($("ap-buffer").value);
  if (bbox.length === 4) {
    if (!(bbox[0] < bbox[2] && bbox[1] < bbox[3])) { toast("bbox must be W,S,E,N with W<E and S<N"); return; }
    setArea({ kind: "bbox", bbox: bbox.map(round6) }, { fit: true });
  } else if (point.length === 2 && buffer > 0) {
    setArea({ kind: "point", lat: point[0], lon: point[1], buffer_m: buffer }, { fit: true });
  } else {
    toast("Enter W,S,E,N, or lat,lon plus a buffer in metres");
  }
}

async function searchPlace() {
  const q = $("ap-q").value.trim();
  if (!q) return;
  $("ap-cands").innerHTML = '<span class="empty">Searching…</span>';
  try {
    candidates = (await getJSON(`/api/geocode?q=${encodeURIComponent(q)}`)).candidates;
  } catch (e) { candidates = []; toast(e.message); }
  $("ap-cands").innerHTML = candidates.length
    ? candidates.map((c, i) => `<div class="cand" data-i="${i}">${esc(c.display_name)} <span class="fb-kind">${esc(c.type)}</span></div>`).join("")
    : '<span class="empty">No matches.</span>';
  const outlines = candidates.map(c => polygonFeature(c.polygon ? lonLat(c.polygon) : ring(c.bbox)));
  if (map && map.getSource("ap-cands")) map.getSource("ap-cands").setData({ type: "FeatureCollection", features: outlines });
}

function pickCandidate(i) {
  const c = candidates[i];
  for (const el of document.querySelectorAll("#ap-cands .cand")) el.classList.toggle("on", Number(el.dataset.i) === i);
  setArea({ kind: "place", name: c.display_name, bbox: c.bbox, polygon: c.polygon }, { fit: true });
}

// Reset for a new build of `source` ("osm" | "overture").
export function resetAreaPicker(source) {
  area = null; inputFile = null; candidates = []; drawing = false; drawStart = null;
  $("ap-draw").classList.remove("on");
  if (map) { map.dragPan.enable(); map.getCanvas().style.cursor = ""; }
  $("ap-cands").innerHTML = "";
  $("ap-file-note").textContent = source === "osm" ? "A .osm XML file or an Overpass JSON export." : "A folder holding segment.parquet + connector.parquet.";
  fileBrowser.configure({ kinds: FILE_KINDS[source] });
  fileBrowser.reset();
  if (map && map.getSource("ap-cands")) map.getSource("ap-cands").setData(EMPTY);
  render();
  setTab("draw");
}

export function wireAreaPicker(handler) {
  onChange = handler;
  fileBrowser = createFileBrowser($("ap-file-fb"), { kinds: [], onPick: e => { inputFile = e.target; onChange(); } });
  for (const b of document.querySelectorAll("#ap-tabs button")) b.onclick = () => setTab(b.dataset.tab);
  $("ap-draw").onclick = () => {
    if (!map) return;
    drawing = !drawing;
    $("ap-draw").classList.toggle("on", drawing);
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) map.dragPan.disable(); else map.dragPan.enable();
  };
  $("ap-apply").onclick = applyCoordinates;
  $("ap-search").onclick = searchPlace;
  $("ap-q").onkeydown = e => { if (e.key === "Enter") searchPlace(); };
  $("ap-cands").onclick = e => { const c = e.target.closest(".cand"); if (c) pickCandidate(Number(c.dataset.i)); };
}
