// Settings → Plugins, as rows: what started (GET /api/plugins), what the browser could not load, and what
// app.disabled_plugins says now. Import-free and DOM-free: unit-tested under node (tests/test_workbench_slots_js.py).

const STATE_TEXT = { loaded: "Loaded", disabled: "Disabled", incompatible: "Incompatible", error: "Failed to load" };

function compatText(requiresApi, compatible, hostApi) {
  if (compatible === null) return "—";
  return compatible ? `${requiresApi} (compatible)` : `${requiresApi} (this netstead provides ${hostApi})`;
}

// One row per installed plugin, plus one per id in app.disabled_plugins that isn't installed (so it can be cleared).
// `enabled` is the saved setting; `restart` is true when it differs from how this run started.
export function pluginRows({ statuses, hostApi, disabled, browserErrors = {} }) {
  const rows = statuses.map(s => {
    const compatible = s.requires_api == null ? null : s.state !== "incompatible";
    const enabled = !disabled.includes(s.id);
    return {
      id: s.id, name: s.name || s.id, version: s.version || "—", compat: compatText(s.requires_api, compatible, hostApi),
      state: s.state, stateText: STATE_TEXT[s.state] || s.state,
      errors: [s.error, ...(browserErrors[s.id] || []).map(e => `${e.phase}: ${e.message}`)].filter(Boolean),
      enabled, restart: enabled !== (s.state !== "disabled"), installed: true,
    };
  });
  for (const id of disabled) {
    if (statuses.some(s => s.id === id)) continue;
    rows.push({ id, name: id, version: "—", compat: "—", state: "missing", stateText: "Not installed", errors: [],
      enabled: false, restart: false, installed: false });
  }
  return rows;
}

// app.disabled_plugins after switching `id` on or off (order kept, no duplicates).
export function withPluginEnabled(disabled, id, enabled) {
  const rest = disabled.filter(x => x !== id);
  return enabled ? rest : [...rest, id];
}
