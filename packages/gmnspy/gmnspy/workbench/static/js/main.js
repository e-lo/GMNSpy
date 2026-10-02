// Workbench boot: wire modules to the store and the server's SSE stream.
import { getBuffer, getJSON, netPath, subscribe } from "./api.js";
import { $, toast } from "./dom.js";
import { renderHeader, wireHeader } from "./header.js";
import { showEntry, wireHistory } from "./history.js";
import { fitBbox, fitLinks, fitNetwork, initMap, render } from "./map.js";
import { decodeNetwork } from "./netbuf.js";
import { populateColorby, renderLegend, syncControls, wirePanels } from "./panels.js";
import { renderPicks, renderSelection, showLinkDetails, wireSide } from "./side.js";
import { activeSelection, store } from "./store.js";
import { onNetworkChanged, onSelectionChanged, restoreViewMode, wireTable } from "./table.js";

const netKeyFor = server => {
  const h = server.networks.find(n => n.id === server.active);
  return h ? { h, key: `${h.id}@${h.version}` } : { h: null, key: null };
};
const inFlight = new Set();

async function loadActiveNetwork() {
  const { server, netKey } = store.get();
  const { h, key } = netKeyFor(server);
  if (key === netKey || inFlight.has(key)) return;
  if (!h) { store.set({ netKey: null, net: null, attrs: null, properties: [], prop: null, marker: null }); return; }
  inFlight.add(key);
  try {
    const [buf, attrs, props] = await Promise.all([
      getBuffer(netPath(h.id, "network.bin")), getJSON(netPath(h.id, "network.attrs.json")), getJSON(netPath(h.id, "properties")),
    ]);
    if (netKeyFor(store.get().server).key !== key) return; // superseded while fetching
    const switched = !netKey || !netKey.startsWith(`${h.id}@`);
    store.set({ netKey: key, net: decodeNetwork(buf), attrs, properties: props.properties, prop: null, marker: null });
    if (switched) fitNetwork();
  } finally {
    inFlight.delete(key);
  }
}

async function loadColorProperty() {
  const { server, net, netKey, prop } = store.get();
  const name = server.style.color_by;
  if (!net || name === "none" || (prop && prop.name === name && prop.netKey === netKey)) return;
  const p = await getJSON(netPath(server.active, `property/${encodeURIComponent(name)}`));
  const now = store.get();
  if (now.server.style.color_by === name && now.netKey === netKey) store.set({ prop: { ...p, netKey } });
}

async function onState(server) {
  store.set({ server });
  try { await loadActiveNetwork(); await loadColorProperty(); } catch (e) { toast(e.message); }
}

function onNavigate(ev) {
  if (ev.bbox) fitBbox(ev.bbox);
  else if (ev.to_network) fitNetwork();
  else if (ev.to_selection) { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); }
}

function onLinkClick(linkId) {
  const s = store.get();
  if (!s.pickMode) { showLinkDetails(linkId); return; }
  const picks = new Set(s.picks);
  if (picks.has(linkId)) picks.delete(linkId); else picks.add(linkId);
  store.set({ picks });
}

function wireMapButtons() {
  $("btn-fitnet").onclick = () => fitNetwork();
  $("btn-fitsel").onclick = () => { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); };
  $("btn-pick").onclick = () => store.set({ pickMode: !store.get().pickMode });
}

function wireStore() {
  store.subscribe(["server", "net", "prop", "picks", "marker"], () => render());
  store.subscribe(["server"], s => {
    renderHeader(s.server); syncControls(s.server.style); renderSelection(activeSelection(s)); onSelectionChanged();
  });
  store.subscribe(["server", "prop"], s => renderLegend(s.server.style, s.prop));
  store.subscribe(["properties"], s => { populateColorby(s.properties); syncControls(s.server.style); });
  store.subscribe(["netKey"], () => { onNetworkChanged(); store.set({ picks: new Set() }); });
  store.subscribe(["picks"], s => renderPicks(s.picks));
  store.subscribe(["pickMode"], s => { $("btn-pick").classList.toggle("on", s.pickMode); $("map").classList.toggle("picking", s.pickMode); });
}

async function boot() {
  wireStore(); wirePanels(); wireSide(); wireTable(); wireHeader(); wireHistory(); wireMapButtons();
  const [cfg, server] = await Promise.all([getJSON("/api/config"), getJSON("/api/state")]);
  store.set({ server });
  restoreViewMode();
  initMap(cfg.style, {
    onLinkClick,
    onReady: async () => {
      await onState(store.get().server);
      subscribe({ state: e => onState(e.state), history: e => showEntry(e.entry), navigate: onNavigate });
    },
  });
}

boot().catch(e => toast(e.message));
