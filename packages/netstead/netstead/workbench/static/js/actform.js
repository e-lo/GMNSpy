// One Action's form, generated from its JSON Schema: how a plugin Action runs with no plugin UI (plugins design,
// "declarative first"). Each plugin Action's palette command opens it (plugins.js). Run dispatches the Action, so it
// is recorded in history like any other. A modal dialog: focus moves in, Tab is trapped, Escape closes, and focus
// returns to the opener. The title and description come from the plugin: they are set as text, never as markup.
import { dispatch } from "./api.js";
import { $ } from "./dom.js";
import { schemaForm } from "./formview.js";
import { trapTab } from "./modal.js";

let opener = null, form = null, current = null;

export const actionFormOpen = () => !$("actform").hidden;

export function openActionForm(entry, prefill = {}) {
  if (!actionFormOpen()) opener = document.activeElement;
  current = entry;
  $("actform-title").textContent = entry.label;
  $("actform-desc").textContent = entry.description || "";
  $("actform-result").textContent = "";
  form = schemaForm($("actform-body"), entry.schema, prefill, { omit: ["type"], onChange: () => { $("actform-result").textContent = ""; } });
  $("actform").hidden = false;
  if (!form.focus()) $("actform-run").focus();
}

export function closeActionForm() {
  if (!actionFormOpen()) return;
  $("actform").hidden = true;
  if (opener && opener.isConnected) opener.focus();
  opener = null;
}

async function run() {
  const errors = form.errors();
  if (errors.length) { $("actform-result").textContent = errors.join("; "); return; }
  $("actform-run").disabled = true;
  try {
    const result = await dispatch({ ...form.value(), type: current.type });
    $("actform-result").textContent = result == null ? "Done." : `Done: ${typeof result === "string" ? result : JSON.stringify(result)}`;
  } catch (e) {
    $("actform-result").textContent = e.message;
  } finally {
    $("actform-run").disabled = false;
  }
}

export function wireActionForm() {
  $("actform-close").onclick = closeActionForm;
  $("actform-run").onclick = () => run();
  $("actform").addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeActionForm(); return; }
    trapTab($("actform"), e);
  });
}
