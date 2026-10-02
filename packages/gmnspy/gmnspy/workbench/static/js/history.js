// History strip: the last action as replayable Python, plus the whole session as a script.
import { getJSON } from "./api.js";
import { $, toast } from "./dom.js";

async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch (e) { toast(`copy failed: ${e.message}`); }
}

export function showEntry(entry) {
  $("hist-seq").textContent = `#${entry.seq}`;
  const py = $("hist-py");
  py.textContent = entry.ok ? entry.python : `${entry.python}  # failed: ${entry.error}`;
  py.classList.toggle("fail", !entry.ok);
}

export function sessionScript(entries) {
  const lines = ["# GMNSpy Workbench session: replay against a live workbench handle named `app`"];
  for (const e of entries) lines.push(e.ok ? e.python : `# failed: ${e.python}  # ${e.error}`);
  return lines.join("\n");
}

export function wireHistory() {
  $("hist-copy").onclick = () => copy($("hist-py").textContent);
  $("hist-all").onclick = async () => {
    if (!$("hist-panel").classList.toggle("open")) return;
    try { $("hist-script").textContent = sessionScript((await getJSON("/api/history")).entries); } catch (e) { toast(e.message); }
  };
  $("hist-copy-all").onclick = () => copy($("hist-script").textContent);
}
