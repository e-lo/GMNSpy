// Workbench boot: wire modules to the store and the server's SSE stream.
import { getBuffer, getJSON, netPath, subscribe } from "./api.js";
import { $, toast } from "./dom.js";
import { rememberRecent, renderHeader, renderRecent, wireHeader } from "./header.js";
import { showEntry, wireHistory } from "./history.js";
import { loadJobs, onJob, wireJobs } from "./jobs.js";
import { onHistoryEntry, onLLMEvent, onLLMJob, refreshLLM, renderLLMPanel, wireLLM } from "./llm.js";
import { fitBbox, fitLinks, fitNetwork, initMap, render, setBasemap } from "./map.js";
import { decodeNetwork } from "./netbuf.js";
import { populateColorby, renderLegend, syncControls, wirePanels } from "./panels.js";
import { clearDetails, renderHighlights, renderSelection, showLinkDetails, wireSide } from "./side.js";
import { onSettingsHistory, registerSection, wireSettings } from "./settings.js";
import { activeSelection, store } from "./store.js";
import { onNetworkChanged, onSelectionChanged, restoreViewMode, wireTable } from "./table.js";
import { onWizardJob, wireWizard } from "./wizard.js";

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
  if (!s.highlightMode) { showLinkDetails(linkId); return; }
  const highlights = new Set(s.highlights);
  if (highlights.has(linkId)) highlights.delete(linkId); else highlights.add(linkId);
  store.set({ highlights });
}

// A viz.* setting (from the Settings dialog, Python, or the assistant) may change the basemap: swap it in place.
async function onSettingChanged(entry) {
  const a = entry.action;
  if (!entry.ok || a.type !== "set_setting" || !/^viz(\.|$)/.test(a.key)) return;
  const cfg = await getJSON("/api/config");
  if (JSON.stringify(cfg.style) === JSON.stringify(store.get().basemap)) return;
  store.set({ basemap: cfg.style });
  setBasemap(cfg.style);
}

function wireMapButtons() {
  $("btn-fitnet").onclick = () => fitNetwork();
  $("btn-fitsel").onclick = () => { const sel = activeSelection(store.get()); if (sel) fitLinks(sel.link_ids); };
  $("btn-highlight").onclick = () => store.set({ highlightMode: !store.get().highlightMode });
}

function wireStore() {
  store.subscribe(["server", "net", "prop", "highlights", "marker"], () => render());
  store.subscribe(["server"], s => {
    renderHeader(s.server); syncControls(s.server.style); renderSelection(activeSelection(s)); onSelectionChanged();
  });
  store.subscribe(["server", "prop"], s => renderLegend(s.server.style, s.prop));
  store.subscribe(["properties"], s => { populateColorby(s.properties); syncControls(s.server.style); });
  store.subscribe(["netKey"], () => { onNetworkChanged(); store.set({ highlights: new Set() }); clearDetails(); });
  store.subscribe(["highlights"], s => renderHighlights(s.highlights));
  store.subscribe(["highlightMode"], s => { $("btn-highlight").classList.toggle("on", s.highlightMode); $("map").classList.toggle("highlighting", s.highlightMode); });
}

async function boot() {
  wireStore(); wirePanels(); wireSide(); wireTable(); wireHeader(); wireHistory(); wireMapButtons(); wireJobs(); wireWizard(); wireLLM(); wireSettings();
  registerSection("llm", "Language models", "llm-panel", () => renderLLMPanel());
  renderRecent();
  const [cfg, server, history] = await Promise.all([getJSON("/api/config"), getJSON("/api/state"), getJSON("/api/history")]);
  store.set({ server, basemap: cfg.style });
  await loadJobs();
  restoreViewMode();
  refreshLLM().catch(e => toast(e.message));
  if (history.entries.length) showEntry(history.entries[history.entries.length - 1]);
  // Subscribe now, not on map load, so job/history events are never missed. Until the map is ready a
  // `state` event is only stored (header, panels and table render from it; the map draws nothing, as no
  // network is decoded yet); onReady then loads the network for whatever state is latest.
  // `navigate` needs the map and is dropped until then.
  let mapReady = false;
  subscribe({
    state: e => { if (mapReady) onState(e.state); else store.set({ server: e.state }); },
    history: e => { showEntry(e.entry); rememberRecent(e.entry); onHistoryEntry(e.entry); onSettingsHistory(e.entry);
      onSettingChanged(e.entry).catch(err => toast(err.message));
    },
    navigate: e => { if (mapReady) onNavigate(e); },
    job: e => { onJob(e.job); onWizardJob(e.job); onLLMJob(e.job); },
    llm: onLLMEvent,
  });
  initMap(cfg.style, {
    onLinkClick,
    onReady: () => { mapReady = true; return onState(store.get().server); },
  });
}

boot().catch(e => toast(e.message));
