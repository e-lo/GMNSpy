// Settings dialog: a form generated from the Settings JSON schema; every change is a set_setting action.
// Other modules add their own sections with registerSection (the Language models panel is one).
import { dispatch, getJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";
import { parseInput, resetScope, scopeNote, sectionsFrom } from "./settingsform.js";

const extra = new Map(); // id -> {label, element, onShow}
let payload = null, sections = [], current = null;

export function registerSection(id, label, element, onShow) { extra.set(id, { label, element, onShow }); }

export const settingsOpen = () => !$("settings").hidden;
export function closeSettings() { $("settings").hidden = true; }

export async function openSettings(section) {
  $("settings").hidden = false;
  await refreshSettings();
  showSection(section || current || (sections[0] && sections[0].name));
}

export async function refreshSettings() {
  payload = await getJSON("/api/settings");
  sections = sectionsFrom(payload);
  $("set-paths").textContent = `User file: ${payload.paths.user} · Project file: ${payload.paths.project}`;
  renderNav();
  if (current && !extra.has(current)) renderForm();
}

function renderNav() {
  const items = sections.map(s => [s.name, s.title]).concat([...extra].map(([id, e]) => [id, e.label]));
  $("set-nav").innerHTML = items
    .map(([id, label]) => `<button data-sec="${esc(id)}"${id === current ? ' class="on"' : ""}>${esc(label)}</button>`)
    .join("");
}

function showSection(id) {
  current = id;
  for (const b of $("set-nav").querySelectorAll("button")) b.classList.toggle("on", b.dataset.sec === id);
  const ext = extra.get(id);
  $("set-form").hidden = Boolean(ext);
  // A registered section saves on its own terms (Language models: user), so the Save to menu goes, label and all.
  for (const el of [$("set-scope"), document.querySelector(".set-scope-lbl")]) el.hidden = Boolean(ext);
  for (const [key, e] of extra) $(e.element).hidden = key !== id;
  if (ext) Promise.resolve(ext.onShow()).catch(e => toast(e.message));
  else renderForm();
}

function inputHTML(f) {
  const attrs = `id="set-${esc(f.key.replace(/\./g, "-"))}" data-key="${esc(f.key)}"${f.readonly ? " disabled" : ""}`;
  if (f.kind === "bool") return `<input type="checkbox" ${attrs}${f.value ? " checked" : ""}>`;
  if (f.kind === "choice") {
    const opts = (f.nullable ? [""] : []).concat(f.options);
    return `<select ${attrs}>${opts.map(o => `<option value="${esc(o)}"${o === (f.value ?? "") ? " selected" : ""}>` +
      `${esc(o === "" ? "(default)" : o)}</option>`).join("")}</select>`;
  }
  if (f.kind === "int" || f.kind === "float") {
    const bounds = (f.min != null ? ` min="${f.min}"` : "") + (f.max != null ? ` max="${f.max}"` : "");
    return `<input type="number" ${attrs} step="${f.kind === "int" ? 1 : "any"}"${bounds} value="${esc(f.value ?? "")}" ` +
      `placeholder="${esc(f.default ?? "default")}">`;
  }
  if (f.kind === "json") return `<textarea ${attrs} rows="3" spellcheck="false">${esc(JSON.stringify(f.value ?? null, null, 1))}</textarea>`;
  const text = f.kind === "list" ? (f.value || []).join(", ") : f.value ?? "";
  const hint = f.kind === "list" ? "comma-separated" : f.default ?? "default";
  return `<input ${attrs} value="${esc(text)}" placeholder="${esc(hint)}" spellcheck="false">`;
}

function fieldHTML(f, scope) {
  const reset = !f.readonly && resetScope(f);
  const note = !f.readonly && scopeNote(f, scope);
  return `<div class="set-field"><label for="set-${esc(f.key.replace(/\./g, "-"))}">${esc(f.label)}` +
    `${f.restart ? ' <span class="tag">applies on next launch</span>' : ""}</label>${inputHTML(f)}` +
    `<span class="src src-${esc(f.source)}" title="Where the current value comes from">${esc(f.source)}</span>` +
    (reset ? `<button class="mini ghost" data-reset="${esc(f.key)}" data-scope="${reset}" ` +
      `title="Remove it from the ${reset} layer">Reset</button>` : "<span></span>") +
    (f.readonly ? `<div class="set-why">${esc(f.readonly)}</div>` : "") +
    (note ? `<div class="set-why">${esc(note)}</div>` : "") + "</div>";
}

function renderForm() {
  const sec = sections.find(s => s.name === current);
  if (!sec) return;
  const scope = $("set-scope").value;
  $("set-form").innerHTML = (sec.description ? `<p class="llm-note">${esc(sec.description)}</p>` : "") +
    (sec.note ? `<p class="set-note">${esc(sec.note)}</p>` : "") + sec.fields.map(f => fieldHTML(f, scope)).join("");
}

async function save(key, value, scope) {
  try {
    await dispatch({ type: "set_setting", key, value, scope });
  } catch (e) {
    toast(e.message);
    await refreshSettings().catch(() => {}); // put the control back to the real value (a 422 is not in history)
  }
}

// Any set_setting, from this dialog, Python, another tab or the assistant, refreshes an open dialog.
export function onSettingsHistory(entry) {
  if (entry.action.type === "set_setting" && settingsOpen()) refreshSettings().catch(e => toast(e.message));
}

export function wireSettings() {
  $("settings-btn").onclick = () => openSettings().catch(e => toast(e.message));
  $("set-close").onclick = closeSettings;
  $("set-nav").onclick = e => { const b = e.target.closest("button[data-sec]"); if (b) showSection(b.dataset.sec); };
  $("set-scope").onchange = () => renderForm();
  $("set-form").onchange = e => {
    const el = e.target.closest("[data-key]");
    if (!el) return;
    const field = sections.flatMap(s => s.fields).find(f => f.key === el.dataset.key);
    const parsed = parseInput(field, el.type === "checkbox" ? el.checked : el.value);
    if (parsed.ok) save(field.key, parsed.value, $("set-scope").value);
    else toast(parsed.error);
  };
  $("set-form").onclick = e => {
    const b = e.target.closest("button[data-reset]");
    if (b) save(b.dataset.reset, null, b.dataset.scope);
  };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && settingsOpen()) closeSettings(); });
}
