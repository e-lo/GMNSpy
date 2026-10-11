// The browser side of plugins: import each loaded plugin's ES module and call its activate(wb) (plugins design,
// "Front end"). One plugin's failure (a module that won't import, no activate export, activate throwing or not
// finishing) rolls back what it registered, is listed in Settings → Plugins, and never stops the others.
import { openActionForm } from "./actform.js";
import { dispatch, getJSON, postJSON } from "./api.js";
import { actionCommands, addCommandTo, frozenCopy } from "./commands.js";
import { toast } from "./dom.js";
import { schemaForm } from "./formview.js";
import { hub } from "./hub.js";
import { addLayer } from "./map.js";
import { CORE, slots } from "./slots.js";
import { activeSelection, store } from "./store.js";
import { createWb } from "./wbhost.js";
import { addPanel, addWorkspace, restoreWorkspace, showPanel } from "./workspaces.js";

export const ACTIVATE_TIMEOUT_MS = 5000;
const reported = new Set();

// A failure in plugin (or core) front-end code: logged, toasted, and kept for Settings → Plugins. Each distinct
// message is reported once (a broken badge would otherwise repeat on every state change).
export function reportPluginError(owner, phase, error) {
  const message = String((error && error.message) || error);
  const key = `${owner}|${phase}|${message}`;
  if (reported.has(key)) return;
  reported.add(key);
  console.error(`[${owner}] ${phase}:`, error);
  toast(owner === "core" ? message : `Plugin ${owner}: ${message}`);
  if (owner === "core") return;
  const all = store.get().pluginErrors;
  store.set({ pluginErrors: { ...all, [owner]: [...(all[owner] || []), { phase, message }] } });
}

// A command registered by anyone; menus and the "Selection actions" button re-check what applies.
export const addCommand = (owner, spec) => addCommandTo(slots, store, owner, spec);

export async function loadPlugins() {
  const [{ host_api: hostApi, plugins }, { actions }] = await Promise.all([getJSON("/api/plugins"), getJSON("/api/actions")]);
  store.set({ pluginStatus: plugins, hostApi });
  // Declarative first: every plugin Action has a form, whether or not its plugin ships JavaScript.
  for (const spec of actionCommands(actions, plugins)) addCommand(spec.owner, { ...spec, run: () => openActionForm(spec.entry) });
  const shared = { hostApi, actionTypes: new Set(actions.map(a => a.type)), schemas: new Map(actions.map(a => [a.type, a.schema])) };
  for (const status of plugins) {
    // "core" is reserved (spec.problems refuses it too): its owner tag would skip the id prefix check, and a
    // rollback's removeOwner("core") would remove core's own registrations.
    if (status.id === CORE) { reportPluginError(status.id, "activate", 'the plugin id "core" is reserved'); continue; }
    if (status.state === "loaded" && status.frontend) await activatePlugin(status, shared);
  }
  restoreWorkspace();
}

async function activatePlugin(status, shared) {
  const { wb, rollback } = createWb(status.id, hostDeps(shared));
  try {
    const mod = await import(`${status.frontend}?v=${encodeURIComponent(status.version)}`);
    if (typeof mod.activate !== "function") throw new Error(`${status.frontend} exports no activate(wb)`);
    const done = Promise.resolve(mod.activate(wb));
    // One that fails after the time limit (say, registering into its rolled-back wb) is reported too, not left as
    // an unhandled rejection; a failure within the limit is the same message, reported once.
    done.catch(e => reportPluginError(status.id, "activate", e));
    await withTimeout(done, ACTIVATE_TIMEOUT_MS, `activate(wb) did not finish within ${ACTIVATE_TIMEOUT_MS / 1000} s`);
  } catch (e) {
    rollback();
    reportPluginError(status.id, "activate", e);
  }
}

function withTimeout(promise, ms, message) {
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

function hostDeps({ hostApi, actionTypes, schemas }) {
  return {
    hostApi, store, activeSelection, getJSON, postJSON, dispatch, fetch: (url, init) => fetch(url, init),
    events: hub, addCommand, layers: { register: addLayer }, dock: { addWorkspace, addPanel, showPanel },
    schemaForm, actionTypes, actionSchema: type => schemas.get(type) || null, toast, onError: reportPluginError,
    frozenCopy,
  };
}
