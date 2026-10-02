// Right-hand panel: selection result, link details, and interactive picks.
import { dispatch, getJSON, netPath } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { store } from "./store.js";

const HINT = '<span class="empty">Click a link for details; hover to inspect; type an utterance to select.</span>';
const DETAILS_HINT = '<span class="empty">Click a link on the map.</span>';

export function clearDetails() { $("details").innerHTML = DETAILS_HINT; }

export function renderSelection(sel) {
  $("status-wrap").innerHTML = sel
    ? `<span class="status ${esc(sel.status)}">${esc(sel.status.replace("_", " "))}</span>` +
      (sel.utterance ? ` <span class="diag">${esc(sel.utterance)}</span>` : "")
    : HINT;
  const anchors = sel ? sel.anchors : [];
  $("anchors").innerHTML = anchors.length
    ? anchors.map(a => `<div><span class="dot" style="background:${a.role === "from" ? "#35c46a" : "#e0524d"}"></span>` +
        `<b>${esc(a.role)}</b> · node ${esc(a.node_id)} · ${esc(a.kind)} <span class="diag">(${esc(a.detail)})</span></div>`).join("")
    : '<span class="empty">—</span>';
  $("fragment").textContent = sel && sel.fragment ? JSON.stringify(sel.fragment, null, 2) : "—";
  const diags = sel ? sel.diagnostics : [];
  $("diag").innerHTML = diags.length ? diags.map(d => `<div class="diag">• ${esc(d)}</div>`).join("") : '<span class="empty">—</span>';
}

export async function showLinkDetails(linkId) {
  const el = $("details"), head = `<div class="lid">link ${esc(linkId)}</div>`;
  el.innerHTML = `${head}<span class="empty">loading…</span>`;
  try {
    const j = await getJSON(netPath(store.get().server.active, `feature/link/${encodeURIComponent(linkId)}`));
    const rows = Object.entries(j.attributes).filter(([k, v]) => k !== "link_id" && v !== null && v !== "")
      .map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join("");
    el.innerHTML = `${head}<table>${rows}</table>`;
  } catch (e) {
    el.innerHTML = `${head}<span class="empty">error: ${esc(e.message)}</span>`;
  }
}

export function renderPicks(picks) {
  $("pick-count").textContent = picks.size;
  $("pick-hint").style.display = picks.size ? "none" : "";
  $("pick-actions").style.display = picks.size ? "flex" : "none";
}

export function wireSide() {
  $("pick-select").onclick = async () => {
    const ids = [...store.get().picks];
    if (!ids.length) return;
    try { await dispatch({ type: "select", link_ids: ids }); } catch (e) { toast(e.message); }
  };
  $("pick-clear").onclick = () => store.set({ picks: new Set() });
}
