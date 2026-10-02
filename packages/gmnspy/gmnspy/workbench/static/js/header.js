// Header: network switcher, open-by-path, and the utterance box. All via actions.
import { dispatch } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { fitLinks } from "./map.js";

async function run(action, after) {
  try { const result = await dispatch(action); if (after) after(result); } catch (e) { toast(e.message); }
}

export function renderHeader(server) {
  const sel = $("net-select");
  sel.innerHTML = server.networks.length
    ? server.networks.map(n => `<option value="${esc(n.id)}"${n.id === server.active ? " selected" : ""}>${esc(n.label)}</option>`).join("")
    : '<option value="">No network open</option>';
  sel.disabled = !server.networks.length;
  const h = server.networks.find(n => n.id === server.active);
  $("count").textContent = h ? `${h.links.toLocaleString()} links · ${h.nodes.toLocaleString()} nodes` : "";
}

export function wireHeader() {
  $("net-select").onchange = e => run({ type: "set_active_network", net_id: e.target.value });
  const open = () => {
    const source = $("open-src").value.trim();
    if (source) run({ type: "open_network", source }, () => { $("open-src").value = ""; });
  };
  $("open-go").onclick = open;
  $("open-src").onkeydown = e => { if (e.key === "Enter") open(); };
  const select = async () => {
    const utterance = $("utterance").value.trim();
    if (!utterance) return;
    $("go").disabled = true;
    await run({ type: "select", utterance }, sel => fitLinks(sel.link_ids));
    $("go").disabled = false;
  };
  $("go").onclick = select;
  $("utterance").onkeydown = e => { if (e.key === "Enter") select(); };
}
