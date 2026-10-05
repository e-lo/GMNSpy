// Language models: the header provider/model picker and the "Language models" panel.
// Keys are write-only. The browser sends a key once (PUT) and only ever reads back status:
// {provider, configured, source}. Key text never enters the store, browser storage, or a lasting DOM node.
// P1b's Settings workspace can mount #llm-panel as a section; until then it floats from "Models…".
import { dispatch, getJSON, sendJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";

const SECRETS = { "X-GMNSpy-Secrets": "1" };
const STUB = { provider: "stub", label: "Offline (pattern)", usable: true, local: true, sends: [] };
const TRI = [["auto", "auto (on for local models only)"], ["on", "on"], ["off", "off"]];
// llm.quality settings shown in the panel: [key, label, kind, options or bounds]. Bounds mirror config.py.
const QUALITY = [
  ["assistant_context", "Send the GMNS assistant guide", "bool"],
  ["assistant_context_max_chars", "…at most this many characters", "int", [0, 100000]],
  ["project_context", "Send project notes (GMNSPY.md, or the ## gmnspy section of AGENTS.md / CLAUDE.md)", "choice", TRI],
  ["project_context_max_chars", "…at most this many characters", "int", [0, 50000]],
  ["grounding", "Send street names and route numbers from the network", "choice", TRI],
  ["grounding_max_names", "…at most this many names", "int", [1, 2000]],
  ["few_shot", "Show the model this session's earlier selections", "bool"],
  ["few_shot_max", "…at most this many", "int", [1, 10]],
  ["match_retry", "If nothing matches, retry once with only the closest real names", "choice", TRI],
  ["match_candidates", "…this many names", "int", [1, 20]],
  ["max_repairs", "Re-prompts after an invalid reply", "int", [0, 5]],
  ["temperature", "Temperature", "float", [0, 2]],
];

let llm = null;          // last /api/llm/providers snapshot: status only, never key values
let settings = null;     // last /api/settings payload: values, sources, paths
let savedDefault = null; // the non-session pair: seen before any session override, or what "Make default" saved
let refreshSeq = 0;      // drop out-of-order refresh responses
let modelsSeq = 0;

const providerRow = name => (name === "stub" ? STUB : llm ? llm.providers.find(p => p.provider === name) : null);
const panelOpen = () => $("llm-panel").classList.contains("open");
const report = e => toast(e.message);

// The model a pair really uses: none for the stub, else the explicit one or the provider's catalog default.
function effectiveModel(provider, model) {
  if (provider === "stub") return null;
  const p = providerRow(provider);
  return model || (p ? p.default_model : null);
}

export function dotClass(p) {
  if (!p) return "off";
  if (p.usable) return p.local ? "ok local" : "ok";
  return p.configured ? "warn" : "off";
}

// What a selection sends to the chosen provider, in words: built from the server's disclosure list,
// which follows the quality settings.
export function privacyNote(p) {
  if (!p || p.provider === "stub") return "Offline pattern parser: nothing leaves this machine.";
  const where = p.local ? `${p.label} runs on this machine, so nothing leaves it.` : `${p.label} is a remote service.`;
  return `${where} Each selection sends: ${p.sends.join("; ")}. Never your network tables or files.`;
}

export async function refreshLLM() {
  const seq = ++refreshSeq;
  const [nextLLM, nextSettings] = await Promise.all([getJSON("/api/llm/providers"), getJSON("/api/settings")]);
  if (seq !== refreshSeq) return; // a newer refresh started meanwhile
  llm = nextLLM;
  settings = nextSettings;
  const src = settings.sources;
  if (src["select.provider"] !== "session" && src["select.model"] !== "session") {
    savedDefault = { ...settings.values.select };
  }
  await renderPicker();
  if (panelOpen()) await renderPanel();
}

export function onLLMEvent(ev) {
  const { type, ...snapshot } = ev;
  llm = snapshot;
  renderPicker().catch(report);
  if (panelOpen()) renderPanel().catch(report);
}

// A set_setting from Python or another tab may change the provider, model, endpoints or quality.
export function onHistoryEntry(entry) {
  const a = entry.action;
  if (entry.ok && a.type === "set_setting" && /^(select|llm)(\.|$)/.test(a.key)) refreshLLM().catch(report);
}

// ------------------------------------------------------------------ header picker

function canMakeDefault() {
  if (!llm || !settings) return false;
  const src = settings.sources;
  if (src["select.provider"] !== "session" && src["select.model"] !== "session") return false;
  if (!savedDefault) return true; // overridden before this page loaded: the saved pair is unknown here
  const { provider, model } = llm.selected;
  return (
    provider !== savedDefault.provider ||
    effectiveModel(provider, model) !== effectiveModel(savedDefault.provider, savedDefault.model)
  );
}

async function renderPicker() {
  if (!llm) return;
  const { provider, model } = llm.selected;
  const options = [STUB, ...llm.providers.filter(p => p.usable)];
  const current = options.find(p => p.provider === provider);
  const html = options.map(
    p => `<option value="${esc(p.provider)}"${p.provider === provider ? " selected" : ""}>${esc(p.label)}</option>`,
  );
  if (!current) {
    const row = providerRow(provider);
    html.push(`<option value="${esc(provider)}" selected disabled>${esc(row ? row.label : provider)} (not set up)</option>`);
  }
  $("nl-provider").innerHTML = html.join("");
  $("nl-dot").className = `dot ${dotClass(current || providerRow(provider))}`;
  $("nl-picker").title = current ? privacyNote(current) : `${provider} is not set up: open Models… to add a key or start it.`;
  $("nl-default").disabled = !canMakeDefault();
  if (panelOpen()) $("llm-privacy").textContent = privacyNote(providerRow(provider));
  await renderModels(provider, model);
}

async function fetchModels(provider) {
  return (await getJSON(`/api/llm/models?provider=${encodeURIComponent(provider)}`)).models;
}

async function renderModels(provider, model) {
  const seq = ++modelsSeq;
  const box = $("nl-model");
  const p = providerRow(provider);
  box.hidden = provider === "stub";
  if (provider === "stub" || !p || !p.usable) {
    box.innerHTML = "";
    box.disabled = true;
    return;
  }
  let models = [];
  try {
    models = await fetchModels(provider);
  } catch (e) {
    report(e);
  }
  if (seq !== modelsSeq) return;
  const chosen = model || p.default_model;
  const label = m => (m.tier ? `${m.label} · ${m.tier}` : m.label);
  const opts = models.map(m => `<option value="${esc(m.id)}"${m.id === chosen ? " selected" : ""}>${esc(label(m))}</option>`);
  if (chosen && !models.some(m => m.id === chosen)) {
    opts.unshift(`<option value="${esc(chosen)}" selected>${esc(chosen)}${p.local ? " (not installed)" : ""}</option>`);
  }
  box.innerHTML = opts.join("");
  box.disabled = !opts.length;
}

// The picker changes this session only; "Make default" saves the current choice to the user file.
async function setSetting(key, value, scope) {
  const result = await dispatch({ type: "set_setting", key, value, scope });
  if (settings) settings.sources = { ...settings.sources, [key]: result.source };
}

// A new provider starts on its catalog default; a local one on an installed model if the default isn't.
async function startingModel(provider) {
  const p = providerRow(provider);
  if (!p) return null;
  if (!p.local) return p.default_model;
  const installed = await fetchModels(provider).catch(() => []);
  return installed.some(m => m.id === p.default_model) || !installed.length ? p.default_model : installed[0].id;
}

async function onProviderChange(provider) {
  try {
    await setSetting("select.provider", provider, "session");
    if (provider !== "stub") {
      const model = await startingModel(provider);
      await setSetting("select.model", model, "session"); // explicit, so history replays the same model
      llm.selected = { provider, model };
    } else {
      llm.selected = { ...llm.selected, provider };
    }
  } catch (e) {
    report(e);
  }
  await renderPicker();
}

async function onModelChange(model) {
  try {
    await setSetting("select.model", model, "session");
    llm.selected = { ...llm.selected, model };
  } catch (e) {
    report(e);
  }
  await renderPicker();
}

async function makeDefault() {
  const { provider, model } = llm.selected;
  const pair = { provider, model: effectiveModel(provider, model) };
  try {
    await setSetting("select.provider", pair.provider, "user");
    if (provider !== "stub") await setSetting("select.model", pair.model, "user");
    savedDefault = pair;
    toast(`Saved ${(providerRow(provider) || { label: provider }).label}${pair.model ? ` · ${pair.model}` : ""} as your default.`);
    await refreshLLM();
  } catch (e) {
    report(e);
  }
}

// ------------------------------------------------------------------ "Language models" panel

function storageNote() {
  if (!llm.key_writes) {
    return "Key changes are disabled because the Workbench is exposed to the network; use `gmnspy llm set-key` in a terminal.";
  }
  return llm.keyring
    ? "Keys are stored in your OS keychain (keyring), or read from environment variables. They are never shown again."
    : "This machine has no OS keychain, so keys can't be stored here: set each provider's environment variable " +
        "(shown below) in the shell that starts `gmnspy app`, then restart it.";
}

function statusText(p) {
  if (p.kind === "local") return p.usable ? `running · ${p.models} model(s)` : p.error || "not reachable";
  if (p.error) return p.error;
  if (p.configured) return `key set · ${p.source}`;
  return llm.keyring && llm.key_writes ? "no key" : `no key · set ${p.key_env.join(" or ")}`;
}

function actionsHTML(p) {
  if (!llm.key_writes) return "";
  if (p.kind === "local") return '<button class="mini ghost" data-act="test">Test</button>';
  const manage = llm.keyring && p.source !== "env"; // env keys are managed in the shell, not here
  return [
    manage ? `<button class="mini" data-act="set">${p.configured ? "Replace" : "Set key"}</button>` : "",
    manage && p.configured ? '<button class="mini ghost" data-act="remove">Remove</button>' : "",
    p.configured ? '<button class="mini ghost" data-act="test">Test</button>' : "",
  ].join("");
}

function rowHTML(p) {
  // A remote-kind provider pointed at a loopback base_url runs here too: say so (Ollama's label already does).
  const tag = p.local && p.kind !== "local" ? ' <span class="tag">local</span>' : "";
  return (
    `<tr data-provider="${esc(p.provider)}" title="${esc(privacyNote(p))}"><td><span class="dot ${dotClass(p)}"></span>${esc(p.label)}${tag}</td>` +
    `<td class="st">${esc(statusText(p))}</td><td class="acts">${actionsHTML(p)}</td></tr>` +
    '<tr class="keyrow" hidden><td colspan="3"></td></tr>'
  );
}

function qualityInput(id, key, kind, opts, v) {
  if (kind === "bool") return `<input type="checkbox" id="${id}" data-q="${esc(key)}" data-kind="bool"${v ? " checked" : ""}>`;
  if (kind === "choice") {
    const options = opts.map(([value, text]) => `<option value="${esc(value)}"${value === v ? " selected" : ""}>${esc(text)}</option>`);
    return `<select id="${id}" data-q="${esc(key)}" data-kind="choice">${options.join("")}</select>`;
  }
  const step = kind === "float" ? "0.1" : "1";
  return (
    `<input type="number" id="${id}" data-q="${esc(key)}" data-kind="${kind}" min="${opts[0]}" max="${opts[1]}" ` +
    `step="${step}" value="${esc(v ?? "")}" placeholder="default">`
  );
}

function qualityHTML(values, sources) {
  return QUALITY.map(([key, label, kind, opts]) => {
    const id = `q-${key}`;
    const src = sources[`llm.quality.${key}`];
    const from = src && src !== "default" && src !== "user" ? ` <span class="muted">(${esc(src)})</span>` : "";
    return `<div class="row"><label class="lbl" for="${id}">${esc(label)}${from}</label>${qualityInput(id, key, kind, opts, values[key])}</div>`;
  }).join("");
}

async function renderPanel() {
  if (!llm || !settings) return;
  $("llm-privacy").textContent = privacyNote(providerRow(llm.selected.provider));
  $("llm-storage").textContent = storageNote();
  $("llm-providers").innerHTML = llm.providers.map(rowHTML).join("");
  const ollama = providerRow("ollama");
  if (ollama && document.activeElement !== $("llm-ollama-url")) $("llm-ollama-url").value = ollama.base_url || "";
  if (!$("llm-quality").contains(document.activeElement)) {
    $("llm-quality").innerHTML = qualityHTML(settings.values.llm.quality, settings.sources);
  }
  const select = $("llm-catalog-provider");
  if (!select.options.length) {
    select.innerHTML = llm.providers.map(p => `<option value="${esc(p.provider)}">${esc(p.label)}</option>`).join("");
  }
  $("llm-catalog-hint").textContent =
    `Add or relabel models in ${settings.paths.user.replace(/config\.toml$/, "llm_models.toml")} (same shape as models.toml).`;
  await renderCatalog(select.value);
}

async function renderCatalog(provider) {
  const table = $("llm-catalog");
  if (!provider) return;
  try {
    const models = await fetchModels(provider);
    const tools = m => (m.tools == null ? "?" : m.tools ? "yes" : "no");
    table.innerHTML =
      "<tr><th>Model id</th><th>Label</th><th>Tier</th><th>Tools</th></tr>" +
      models
        .map(m => `<tr><td><code>${esc(m.id)}</code></td><td>${esc(m.label)}</td><td>${esc(m.tier || "—")}</td><td>${tools(m)}</td></tr>`)
        .join("");
  } catch (e) {
    table.innerHTML = `<tr><td class="st fail">${esc(e.message)}</td></tr>`;
  }
}

// Blank number fields send null, which removes the user setting (back to the default).
function qualityValue(el) {
  const kind = el.dataset.kind;
  if (kind === "bool") return el.checked;
  if (kind === "choice") return el.value;
  if (el.value === "") return null;
  return kind === "int" ? Number.parseInt(el.value, 10) : Number.parseFloat(el.value);
}

async function onQualityChange(el) {
  try {
    await setSetting(`llm.quality.${el.dataset.q}`, qualityValue(el), "user");
    el.blur();
    await refreshLLM(); // the privacy note follows these settings
  } catch (e) {
    report(e);
    await refreshLLM().catch(report); // put the control back to the real value
  }
}

function openKeyForm(tr) {
  const provider = tr.dataset.provider;
  const row = tr.nextElementSibling;
  const cell = row.firstElementChild;
  cell.innerHTML =
    '<div class="row"><input type="password" class="kval grow" autocomplete="off" spellcheck="false" ' +
    `placeholder="Paste API key" aria-label="API key for ${esc(provider)}">` +
    '<button class="mini ksave">Save</button><button class="mini ghost kcancel">Cancel</button></div>';
  row.hidden = false;
  const input = cell.querySelector(".kval");
  const close = () => {
    input.value = "";
    cell.innerHTML = "";
    row.hidden = true;
  };
  const save = async () => {
    const key = input.value.trim();
    close(); // clear and drop the field before the request is even sent
    if (!key) return;
    try {
      onLLMEvent(await sendJSON("PUT", `/api/llm/keys/${encodeURIComponent(provider)}`, { key }, SECRETS));
    } catch (e) {
      report(e);
    }
  };
  cell.querySelector(".ksave").onclick = save;
  cell.querySelector(".kcancel").onclick = close;
  input.onkeydown = e => {
    if (e.key === "Enter") save();
    else if (e.key === "Escape") close();
  };
  input.focus();
}

async function removeKey(tr) {
  const p = providerRow(tr.dataset.provider);
  if (!confirm(`Remove the ${p.label} key from the keyring?`)) return;
  try {
    onLLMEvent(await sendJSON("DELETE", `/api/llm/keys/${encodeURIComponent(p.provider)}`, undefined, SECRETS));
  } catch (e) {
    report(e);
  }
}

async function testProvider(tr) {
  const provider = tr.dataset.provider;
  const cell = tr.querySelector(".st");
  cell.textContent = "testing…";
  cell.className = "st";
  const model = llm.selected.provider === provider ? llm.selected.model : null;
  try {
    const r = await sendJSON("POST", "/api/llm/test", { provider, model }, SECRETS);
    const missing = r.catalog_missing && r.catalog_missing.length ? ` Not served here: ${r.catalog_missing.join(", ")}.` : "";
    cell.textContent = r.message + missing;
    cell.className = `st ${r.ok ? "ok" : "fail"}`;
    if (!r.ok) tr.querySelector(".dot").className = "dot warn";
  } catch (e) {
    cell.textContent = e.message;
    cell.className = "st fail";
  }
}

export function wireLLM() {
  $("nl-provider").onchange = e => onProviderChange(e.target.value);
  $("nl-model").onchange = e => onModelChange(e.target.value);
  $("nl-default").onclick = () => makeDefault();
  $("nl-manage").onclick = () => {
    if ($("llm-panel").classList.toggle("open")) renderPanel().catch(report);
  };
  $("llm-close").onclick = () => $("llm-panel").classList.remove("open");
  $("llm-providers").onclick = e => {
    const button = e.target.closest("button[data-act]");
    if (!button) return;
    const tr = button.closest("tr");
    ({ set: openKeyForm, remove: removeKey, test: testProvider })[button.dataset.act](tr);
  };
  $("llm-quality").onchange = e => {
    if (e.target.dataset.q) onQualityChange(e.target);
  };
  $("llm-ollama-save").onclick = async () => {
    const value = $("llm-ollama-url").value.trim() || null; // empty = back to the default
    try {
      await setSetting("llm.ollama.base_url", value, "user");
      $("llm-ollama-url").blur();
      await refreshLLM();
    } catch (e) {
      report(e);
    }
  };
  $("llm-catalog-provider").onchange = e => renderCatalog(e.target.value);
}
