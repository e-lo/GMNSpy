// Map <-> table linking rules. Import-free and DOM-free: unit-tested under node (tests/test_workbench_js.py).
//
// Three sets drive the views: the recorded server `selection` (link ids, from NL or "Set as selection"),
// the per-tab `highlights` (link ids, clicked or box-selected in Highlight mode), and the per-tab `focus`
// (the one record last clicked on the map or in the table: {table, id, from}). Focus and highlights are
// view state and are never recorded; only an action changes the selection.

export const TABLE_SCOPES = ["all", "selection", "highlighted", "related"];

// The related-records sources: the highlights plus the focused record, as {table: [ids]}.
export function sourcesFor(focus, highlights) {
  const out = {};
  const add = (table, id) => { const ids = (out[table] ||= []); if (!ids.includes(id)) ids.push(id); };
  for (const id of highlights) add("link", id);
  if (focus) add(focus.table, focus.id);
  return out;
}

export const hasSources = sources => Object.values(sources).some(ids => ids.length > 0);

// The POST rows body fields for a table scope, plus the related tint when anything is focused or highlighted.
export function rowsRequest({ scope, table, selection, highlights, focus, hops = 1 }) {
  const sources = sourcesFor(focus, highlights);
  const tint = hasSources(sources) ? { related: { sources, hops }, related_mode: "tint" } : {};
  if (scope === "selection" || scope === "highlighted") {
    const ids = scope === "selection" ? (selection ? [...selection.link_ids] : []) : [...highlights];
    if (table === "link") return { ids, ...tint };
    return { related: { sources: { link: ids }, hops: 1 }, related_mode: "filter" };
  }
  if (scope === "related") return hasSources(sources) ? { related: { sources, hops }, related_mode: "filter" } : { ids: [] };
  return tint;
}

// CSS classes for one grid row.
export function rowMarks({ table, id, selection, highlights, focus, via }) {
  const marks = [];
  if (table === "link" && selection && selection.link_ids.includes(id)) marks.push("sel");
  if (table === "link" && highlights.has(id)) marks.push("hl");
  if (focus && focus.table === table && focus.id === id) marks.push("focus");
  if (via) marks.push("rel");
  return marks;
}

export const pageOffset = (index, limit) => Math.floor(index / limit) * limit;

// A primary key as the grid shows it (data-pk is a string): numeric keys back to numbers.
export function coerceId(raw) {
  const n = Number(raw);
  return raw !== "" && !Number.isNaN(n) ? n : raw;
}
