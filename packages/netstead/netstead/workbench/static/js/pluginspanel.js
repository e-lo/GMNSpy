// Settings → Plugins (UX principle 8): each plugin's id, version, required API and whether it fits, its load errors,
// and an on/off switch. The switch saves app.disabled_plugins at user scope. It is read at launch, so a change
// applies the next time `netstead app` starts; the row says "restart to apply" until then.
import { dispatch, getJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { pluginRows, withPluginEnabled } from "./pluginlist.js";
import { scopeNote } from "./settingsform.js";
import { store } from "./store.js";

const GUIDE = "https://e-lo.github.io/netstead/netstead/cookbook/workbench-plugins/"; // mkdocs site_url + page

function rowHTML(r) {
  return `<tr><td><b>${esc(r.name)}</b><div class="muted">${esc(r.id)}</div></td><td>${esc(r.version)}</td>` +
    `<td>${esc(r.compat)}</td><td>${esc(r.stateText)}${r.restart ? ' <span class="tag">restart to apply</span>' : ""}` +
    r.errors.map(e => `<div class="err">${esc(e)}</div>`).join("") + "</td>" +
    `<td><label class="sw"><input type="checkbox" data-plugin="${esc(r.id)}"${r.enabled ? " checked" : ""} ` +
    `aria-label="Load ${esc(r.name)} at startup"><span></span></label></td></tr>`;
}

export async function renderPluginsPanel() {
  const settings = await getJSON("/api/settings");
  const disabled = settings.values.app.disabled_plugins || [];
  const s = store.get();
  const rows = pluginRows({ statuses: s.pluginStatus, hostApi: s.hostApi, disabled, browserErrors: s.pluginErrors });
  $("plugins-host").textContent = `This netstead provides plugin API ${s.hostApi || "?"}. Switching a plugin on or off ` +
    "applies the next time netstead app starts.";
  // A project file or NETSTEAD_* variable that sets the list wins over the user value this switch saves.
  const note = scopeNote({ restart: true, source: settings.sources["app.disabled_plugins"] || "default" }, "user");
  $("plugins-note").textContent = note || "";
  $("plugins-note").hidden = !note;
  $("plugins-list").innerHTML = rows.length
    ? "<table><thead><tr><th>Plugin</th><th>Version</th><th>Plugin API</th><th>Status</th><th>Load</th></tr></thead>" +
      `<tbody>${rows.map(rowHTML).join("")}</tbody></table>`
    : `<p class="empty">No plugins installed. See <a href="${GUIDE}" target="_blank" rel="noopener">Write a Workbench plugin</a>.</p>`;
}

export function wirePluginsPanel() {
  // A plugin that fails while the section is open (a badge, a command) shows up at once.
  store.subscribe(["pluginErrors", "pluginStatus"], () => {
    if (!$("settings").hidden && !$("plugins-panel").hidden) renderPluginsPanel().catch(err => toast(err.message));
  });
  $("plugins-list").onchange = async e => {
    const el = e.target.closest("input[data-plugin]");
    if (!el) return;
    el.disabled = true;
    try {
      const settings = await getJSON("/api/settings");
      const value = withPluginEnabled(settings.values.app.disabled_plugins || [], el.dataset.plugin, el.checked);
      await dispatch({ type: "set_setting", key: "app.disabled_plugins", value, scope: "user" });
    } catch (err) {
      toast(err.message);
    }
    await renderPluginsPanel().catch(err => toast(err.message));
  };
}
