// JSON Schema -> form fields, and form input -> values. The Settings dialog (settingsform.js, settings.js) and
// wb.schemaForm (formview.js) share it, so every form looks and parses alike (plugins design, UX principle 5).
// Import-free and DOM-free: unit-tested under node (tests/test_workbench_slots_js.py).

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
// dom.js's `esc`, repeated because a pure module can't import dom.js.
const esc = v => String(v).replace(/[&<>"']/g, c => ESC[c]);

// A `$ref` node -> its definition, with the node's own keys (a field's default, description, title) on top.
export function resolveRef(schema, node) {
  if (!node || !node.$ref) return node;
  const { $ref, ...own } = node;
  return { ...((schema.$defs || {})[$ref.split("/").pop()] || {}), ...own };
}

// resolveRef, and also inside `anyOf` (pydantic writes Optional[SomeEnum] as anyOf [{$ref}, {type: null}]).
const resolveField = (schema, node) => {
  const p = resolveRef(schema, node);
  return p && Array.isArray(p.anyOf) ? { ...p, anyOf: p.anyOf.map(o => resolveRef(schema, o)) } : p;
};

// A schema bound, kept only when it is a finite number: plugin schemas pass `json_schema_extra` through verbatim.
const bound = v => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function fieldKind(prop) {
  const options = prop.anyOf ? prop.anyOf.filter(o => o.type !== "null") : [prop];
  const nullable = Boolean(prop.anyOf && prop.anyOf.some(o => o.type === "null"));
  const p = options.length === 1 ? options[0] : null;
  if (!p) return { kind: "json", nullable };
  if (p.enum) return { kind: "choice", options: p.enum, nullable };
  if (p.type === "boolean") return { kind: "bool", nullable };
  if (p.type === "integer" || p.type === "number") {
    return { kind: p.type === "integer" ? "int" : "float", nullable,
      min: bound(p.minimum) ?? bound(p.exclusiveMinimum), max: bound(p.maximum) ?? bound(p.exclusiveMaximum) };
  }
  if (p.type === "string") return { kind: "text", nullable };
  if (p.type === "array" && p.items && p.items.type === "string") return { kind: "list", nullable };
  return { kind: "json", nullable };
}

// A JSON Schema object (an Action's, a plugin's) -> one field per property:
// {key, label, kind, options, nullable, min, max, value, default, required, description, group}.
// A `const` property (an Action's `type`) is fixed, so it gets no field; `omit` drops others by name. One level of
// nested object becomes a group of dotted keys ("where.city"); anything deeper is a JSON field.
export function fieldsFrom(schema, value = {}, { omit = [] } = {}) {
  const required = new Set(schema.required || []);
  const fields = [];
  for (const [name, raw] of Object.entries(schema.properties || {})) {
    const prop = resolveField(schema, raw);
    if (omit.includes(name) || prop.const !== undefined) continue;
    if (prop.type === "object" && prop.properties) {
      const inner = new Set(prop.required || []);
      for (const [sub, subRaw] of Object.entries(prop.properties)) {
        const key = `${name}.${sub}`;
        fields.push(describe(key, resolveField(schema, subRaw), getPath(value, key),
          required.has(name) && inner.has(sub), prop.title || name));
      }
    } else {
      fields.push(describe(name, prop, getPath(value, name), required.has(name), null));
    }
  }
  return fields;
}

function describe(key, prop, value, required, group) {
  return { key, label: prop.title || key.split(".").pop(), ...fieldKind(prop), value: value ?? null,
    default: prop.default ?? null, required, description: prop.description || "", group };
}

export const getPath = (obj, key) => key.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);

// A copy of `obj` with dotted `key` set to `v`; `null` removes the key (an empty input means "not given").
export function setPath(obj, key, v) {
  const out = JSON.parse(JSON.stringify(obj || {}));
  const parts = key.split(".");
  let o = out;
  for (const p of parts.slice(0, -1)) o = o[p] && typeof o[p] === "object" ? o[p] : (o[p] = {});
  if (v === null) delete o[parts[parts.length - 1]];
  else o[parts[parts.length - 1]] = v;
  return out;
}

// What a submit would trip on: required fields left empty, numbers out of bounds ([] when the form can be sent).
// The server validates again; this only saves a round trip.
export function formErrors(fields, value) {
  const errors = [];
  for (const f of fields) {
    const v = getPath(value, f.key);
    if (v === undefined || v === null || v === "") {
      if (f.required && f.default === null) errors.push(`${f.label} is required`);
      continue;
    }
    if (typeof v === "number" && f.min != null && v < f.min) errors.push(`${f.label} must be at least ${f.min}`);
    if (typeof v === "number" && f.max != null && v > f.max) errors.push(`${f.label} must be at most ${f.max}`);
  }
  return errors;
}

// An input's raw value -> {ok, value} or {ok: false, error}. Empty means "reset": null removes the key from that layer.
export function parseInput(field, raw) {
  if (field.kind === "bool") return { ok: true, value: Boolean(raw) };
  if (raw === "" || raw === null || raw === undefined) return { ok: true, value: null };
  if (field.kind === "choice") {  // back to the option itself: Literal[1, 2] and IntEnum choices stay numbers
    const option = (field.options || []).find(o => String(o) === String(raw));
    return { ok: true, value: option === undefined ? String(raw) : option };
  }
  if (field.kind === "text") return { ok: true, value: String(raw) };
  if (field.kind === "int" || field.kind === "float") {
    const n = Number(raw);
    if (!Number.isFinite(n) || (field.kind === "int" && !Number.isInteger(n))) {
      return { ok: false, error: `${field.label}: enter a ${field.kind === "int" ? "whole " : ""}number` };
    }
    return { ok: true, value: n };
  }
  if (field.kind === "list") return { ok: true, value: String(raw).split(",").map(s => s.trim()).filter(Boolean) };
  try { return { ok: true, value: JSON.parse(raw) }; } catch (e) { return { ok: false, error: `${field.label}: not valid JSON` }; }
}

// A form control's state ({type, value, checked, badInput}) -> parseInput's answer. A number input the browser
// cannot parse ("-", "1e") reports an empty value; that must not read as "reset" and delete the saved value.
export function parseControl(field, { type, value, checked, badInput }) {
  if (badInput) return { ok: false, error: `${field.label}: enter a ${field.kind === "int" ? "whole " : ""}number` };
  return parseInput(field, type === "checkbox" ? checked : value);
}

// One form control for a field. The Settings dialog uses idPrefix "set-"; `data-key` names the field for parseControl.
export function inputHTML(f, idPrefix = "set-") {
  const attrs = `id="${idPrefix}${esc(f.key.replace(/\./g, "-"))}" data-key="${esc(f.key)}"${f.readonly ? " disabled" : ""}` +
    (f.required ? ' aria-required="true"' : "");
  if (f.kind === "bool") return `<input type="checkbox" ${attrs}${f.value ? " checked" : ""}>`;
  if (f.kind === "choice") {
    const opts = (f.nullable ? [""] : []).concat(f.options);
    return `<select ${attrs}>${opts.map(o => `<option value="${esc(o)}"${o === (f.value ?? "") ? " selected" : ""}>` +
      `${esc(o === "" ? "(default)" : o)}</option>`).join("")}</select>`;
  }
  if (f.kind === "int" || f.kind === "float") {
    const bounds = (f.min != null ? ` min="${esc(f.min)}"` : "") + (f.max != null ? ` max="${esc(f.max)}"` : "");
    return `<input type="number" ${attrs} step="${f.kind === "int" ? 1 : "any"}"${bounds} value="${esc(f.value ?? "")}" ` +
      `placeholder="${esc(f.default ?? "default")}">`;
  }
  if (f.kind === "json") return `<textarea ${attrs} rows="3" spellcheck="false">${esc(JSON.stringify(f.value ?? null, null, 1))}</textarea>`;
  const text = f.kind === "list" ? (f.value || []).join(", ") : f.value ?? "";
  const hint = f.kind === "list" ? "comma-separated" : f.default ?? "default";
  return `<input ${attrs} value="${esc(text)}" placeholder="${esc(hint)}" spellcheck="false">`;
}
