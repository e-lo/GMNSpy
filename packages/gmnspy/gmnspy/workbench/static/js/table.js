// Data-table view: server-paged/sorted/filtered grid linked to the map selection.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { fitLinks, flyToNode, resizeSoon } from "./map.js";
import { showLinkDetails } from "./side.js";
import { activeSelection, store } from "./store.js";

const TBL = { loaded: false, name: null, schema: null, offset: 0, limit: 100, sort: null, dir: "asc",
  filters: {}, total: 0, toSel: false };
const VIEW_KEY = "gmnspy.viewmode";
let filterTimer = null, lastSelKey = null;

const activeId = () => { const s = store.get().server; return s && s.active; };
const fail = e => toast(e.message);

export function setViewMode(mode) {
  $("stage").dataset.mode = mode;
  for (const b of document.querySelectorAll("#viewmode button")) b.classList.toggle("on", b.dataset.mode === mode);
  try { localStorage.setItem(VIEW_KEY, mode); } catch (e) { /* storage unavailable: mode just isn't remembered */ }
  if (mode !== "map" && !TBL.loaded) loadTables().catch(fail);
  resizeSoon();
}

export function onNetworkChanged() {
  Object.assign(TBL, { loaded: false, name: null, schema: null });
  $("tbl-rail").innerHTML = ""; $("tbl-grid").innerHTML = ""; $("tbl-name").textContent = "—";
  if ($("stage").dataset.mode !== "map") loadTables().catch(fail);
}

export function onSelectionChanged() {
  const sel = activeSelection(store.get());
  const key = JSON.stringify(sel ? [sel.link_ids, sel.anchors.map(a => a.node_id)] : null);
  if (key === lastSelKey) return;
  lastSelKey = key;
  if (TBL.schema) loadRows().catch(fail);
}

async function loadTables() {
  const id = activeId();
  if (!id) return;
  TBL.loaded = true;
  const j = await getJSON(netPath(id, "tables"));
  const rail = $("tbl-rail");
  rail.innerHTML = "";
  for (const t of j.tables) {
    const el = document.createElement("div");
    el.className = "tbl-item"; el.dataset.name = t.name;
    el.innerHTML = `<span>${esc(t.name)}</span><span class="rc">${t.rows.toLocaleString()}</span>`;
    el.onclick = () => selectTable(t.name).catch(fail);
    rail.appendChild(el);
  }
  if (j.tables.length) await selectTable(TBL.name || j.tables[0].name);
}

async function selectTable(name) {
  Object.assign(TBL, { name, offset: 0, sort: null, dir: "asc", filters: {} });
  for (const el of document.querySelectorAll(".tbl-item")) el.classList.toggle("on", el.dataset.name === name);
  TBL.schema = await getJSON(netPath(activeId(), `table/${encodeURIComponent(name)}/schema`));
  $("tbl-name").textContent = name;
  buildGridHeader();
  await loadRows();
}

const gridColumns = () => TBL.schema.columns.filter(c => c.kind !== "geom");

function buildGridHeader() {
  const arrow = c => (TBL.sort === c ? `<span class="ar">${TBL.dir === "asc" ? "▲" : "▼"}</span>` : "");
  const th = gridColumns().map(c => `<th><span class="cn" data-col="${esc(c.name)}">${esc(c.name)}${arrow(c.name)}</span>` +
    `<input data-fcol="${esc(c.name)}" placeholder="filter" value="${esc(TBL.filters[c.name] || "")}"></th>`).join("");
  $("tbl-grid").innerHTML = `<thead><tr>${th}</tr></thead><tbody></tbody>`;
  for (const el of document.querySelectorAll("#tbl-grid .cn")) el.onclick = () => toggleSort(el.dataset.col);
  for (const el of document.querySelectorAll("#tbl-grid input[data-fcol]")) el.oninput = () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      const v = el.value.trim();
      if (v) TBL.filters[el.dataset.fcol] = v; else delete TBL.filters[el.dataset.fcol];
      TBL.offset = 0; loadRows().catch(fail);
    }, 250);
  };
}

function toggleSort(col) {
  if (TBL.sort === col) TBL.dir = TBL.dir === "asc" ? "desc" : "asc"; else { TBL.sort = col; TBL.dir = "asc"; }
  TBL.offset = 0; buildGridHeader(); loadRows().catch(fail);
}

function selIdsForTable() {
  const pk = TBL.schema && TBL.schema.primary_key, sel = activeSelection(store.get());
  if (!pk || !sel) return null;
  if (pk === "link_id") return sel.link_ids;
  if (pk === "node_id") return sel.anchors.map(a => a.node_id);
  return null;
}

async function loadRows() {
  const p = new URLSearchParams({ offset: TBL.offset, limit: TBL.limit });
  if (TBL.sort) { p.set("sort", TBL.sort); p.set("dir", TBL.dir); }
  const spec = Object.entries(TBL.filters).map(([col, val]) => ({ col, op: "contains", val }));
  if (spec.length) p.set("filter", JSON.stringify(spec));
  if (TBL.toSel) { const ids = selIdsForTable(); if (ids && ids.length) p.set("ids", ids.join(",")); }
  const j = await getJSON(netPath(activeId(), `table/${encodeURIComponent(TBL.name)}/rows?${p}`));
  TBL.total = j.total;
  renderRows(j.columns, j.rows);
  const to = Math.min(TBL.offset + TBL.limit, j.total);
  $("tbl-total").textContent = `· ${j.total.toLocaleString()} row(s)`;
  $("tbl-range").textContent = j.total ? `${TBL.offset + 1}–${to} of ${j.total.toLocaleString()}` : "0";
  $("tbl-prev").disabled = TBL.offset <= 0;
  $("tbl-next").disabled = to >= j.total;
}

function renderRows(cols, rows) {
  const pkIdx = cols.indexOf(TBL.schema.primary_key);
  const selIds = new Set((selIdsForTable() || []).map(String));
  const body = $("tbl-grid").tBodies[0];
  body.innerHTML = rows.map(r => {
    const pv = pkIdx >= 0 ? r[pkIdx] : null;
    const sel = pv != null && selIds.has(String(pv)) ? " sel" : "";
    const tds = r.map(v => `<td>${v === null ? '<span class="empty">·</span>' : esc(v)}</td>`).join("");
    return `<tr class="data${sel}" data-pk="${pv == null ? "" : esc(pv)}">${tds}</tr>`;
  }).join("");
  for (const tr of body.querySelectorAll("tr.data")) tr.onclick = () => tableRowClick(tr.dataset.pk);
}

async function tableRowClick(pkVal) {
  if (pkVal === "" || !TBL.schema) return;
  const n = Number(pkVal), id = Number.isNaN(n) ? pkVal : n;
  const pk = TBL.schema.primary_key, net = store.get().net;
  if (pk === "link_id" && net && net.id2idx.has(id)) {
    try { await dispatch({ type: "select", link_ids: [id] }); fitLinks([id]); showLinkDetails(id); } catch (e) { fail(e); }
  } else if (pk === "node_id") {
    flyToNode(id);
  }
}

export function wireTable() {
  for (const b of document.querySelectorAll("#viewmode button")) b.onclick = () => setViewMode(b.dataset.mode);
  $("tbl-prev").onclick = () => { if (TBL.offset > 0) { TBL.offset = Math.max(0, TBL.offset - TBL.limit); loadRows().catch(fail); } };
  $("tbl-next").onclick = () => { if (TBL.offset + TBL.limit < TBL.total) { TBL.offset += TBL.limit; loadRows().catch(fail); } };
  $("tbl-tosel").onchange = e => { TBL.toSel = e.target.checked; TBL.offset = 0; loadRows().catch(fail); };
}

export function restoreViewMode() {
  try { const m = localStorage.getItem(VIEW_KEY); if (m) setViewMode(m); } catch (e) { /* storage unavailable */ }
}
