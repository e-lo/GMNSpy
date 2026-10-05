// Minimal pub/sub store. `server` mirrors the session state pushed over SSE;
// every other key is per-tab view state that never reaches the server.
export function createStore(initial) {
  const state = { ...initial };
  const subs = new Set();
  return {
    get: () => state,
    set(patch) {
      const changed = Object.keys(patch).filter(k => state[k] !== patch[k]);
      if (!changed.length) return;
      Object.assign(state, patch);
      for (const s of subs) if (s.keys.some(k => changed.includes(k))) s.fn(state);
    },
    subscribe(keys, fn) { const s = { keys, fn }; subs.add(s); return () => subs.delete(s); },
  };
}

export const store = createStore({
  server: null,               // {networks, active, selection, style}
  basemap: null,              // MapLibre style URL from /api/config (shared with the wizard's area map)
  netKey: null,               // "<id>@<version>" of the decoded active network
  net: null, attrs: null, properties: [], prop: null,
  highlightMode: false, highlights: new Set(), marker: null,
});

export function activeSelection(s) {
  const sel = s.server && s.server.selection;
  return sel && sel.net_id === s.server.active ? sel : null;
}
