// Related records: what is a foreign key away from the focus and the highlights. A read-only view: the
// summary comes from POST /related and nothing is recorded. The map tints the link/node ids it returns;
// the table rail shows a count per related table; grid rows are tinted by the rows request itself.
import { netPath, postJSON } from "./api.js";
import { toast } from "./dom.js";
import { hasSources, sourcesFor } from "./linking.js";
import { store } from "./store.js";

let seq = 0, timer = null;

// Coalesce bursts (a box-select, quick clicks) into one request. Bumping `seq` here drops any reply still in
// flight for the sources being replaced.
export function scheduleRelated() {
  clearTimeout(timer);
  seq++;
  timer = setTimeout(() => refreshRelated().catch(e => toast(e.message)), 150);
}

// A network switch: forget the pending request, and drop a reply about the old network.
export function cancelRelated() { clearTimeout(timer); seq++; }

async function refreshRelated() {
  const s = store.get(), mine = ++seq;
  const sources = sourcesFor(s.focus, s.highlights);
  if (!s.server || !s.server.active || !hasSources(sources)) { store.set({ related: null }); return; }
  const related = await postJSON(netPath(s.server.active, "related"), { sources, hops: s.relHops });
  if (mine === seq) store.set({ related });
}

export function renderRelatedBadges(related) {
  const byTable = new Map((related ? related.tables : []).filter(t => t.count > 0).map(t => [t.table, t]));
  for (const el of document.querySelectorAll(".tbl-item")) {
    const t = byTable.get(el.dataset.name), badge = el.querySelector(".rel-badge");
    if (!badge) continue;
    badge.textContent = t ? `${t.count.toLocaleString()} related${t.partial ? "+" : ""}` : "";
    badge.title = t ? `via ${t.via.join(", ")}${t.hop > 1 ? ` (hop ${t.hop})` : ""}` : "";
  }
}
