// Settings form model: /api/settings (JSON schema + values + sources + readonly/restart/notes) -> field
// descriptors, and input parsing. Import-free and DOM-free: unit-tested under node (tests/test_workbench_js.py).

// Sections another Settings section owns (the Language models panel), hidden from the generated form.
export const FOLDED = new Set(["llm", "select"]);

const TITLES = {
  io: "Input & output", engine: "Engine", osm: "OpenStreetMap", overture: "Overture", build: "Build defaults",
  validation: "Validation", viz: "Map", app: "App server", credentials: "Credentials",
};
// Lowest to highest precedence (config.py: defaults < user < project < env < session).
const RANKS = ["default", "user", "project", "env", "session"];
const rank = source => RANKS.indexOf(source);

const resolve = (schema, node) => (node && node.$ref ? schema.$defs[node.$ref.split("/").pop()] : node);

export function fieldKind(prop) {
  const options = prop.anyOf ? prop.anyOf.filter(o => o.type !== "null") : [prop];
  const nullable = Boolean(prop.anyOf && prop.anyOf.some(o => o.type === "null"));
  const p = options.length === 1 ? options[0] : null;
  if (!p) return { kind: "json", nullable };
  if (p.enum) return { kind: "choice", options: p.enum, nullable };
  if (p.type === "boolean") return { kind: "bool", nullable };
  if (p.type === "integer" || p.type === "number") {
    return { kind: p.type === "integer" ? "int" : "float", nullable,
      min: p.minimum ?? p.exclusiveMinimum ?? null, max: p.maximum ?? p.exclusiveMaximum ?? null };
  }
  if (p.type === "string") return { kind: "text", nullable };
  if (p.type === "array" && p.items && p.items.type === "string") return { kind: "list", nullable };
  return { kind: "json", nullable };
}

// A key's source; for a JSON field (e.g. validation.rules), the highest layer among its nested keys.
export function sourceOf(sources, key) {
  if (sources[key]) return sources[key];
  const nested = Object.entries(sources).filter(([k]) => k.startsWith(`${key}.`)).map(([, s]) => s);
  return nested.length ? nested.reduce((a, b) => (rank(b) > rank(a) ? b : a)) : "default";
}

export function sectionsFrom(payload) {
  const { schema, values, sources, readonly = {}, restart = [], notes = {} } = payload;
  return Object.entries(schema.properties).filter(([name]) => !FOLDED.has(name)).map(([name, ref]) => {
    const def = resolve(schema, ref);
    const fields = Object.entries(def.properties || {}).map(([field, prop]) => {
      const key = `${name}.${field}`;
      return { key, label: prop.title || field, ...fieldKind(prop), value: (values[name] || {})[field],
        default: prop.default ?? null, source: sourceOf(sources, key), readonly: readonly[key] || null,
        restart: restart.includes(key) };
    });
    return { name, title: TITLES[name] || name[0].toUpperCase() + name.slice(1), description: def.description || "",
      note: notes[name] || null, fields };
  });
}

// An input's raw value -> {ok, value} or {ok: false, error}. Empty means "reset": null removes the key from that layer.
export function parseInput(field, raw) {
  if (field.kind === "bool") return { ok: true, value: Boolean(raw) };
  if (raw === "" || raw === null || raw === undefined) return { ok: true, value: null };
  if (field.kind === "choice" || field.kind === "text") return { ok: true, value: String(raw) };
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

// Reset removes the value from the layer it comes from; env and defaults can't be reset from the app.
export function resetScope(field) {
  return ["user", "project", "session"].includes(field.source) ? field.source : null;
}

// Why saving `field` at `scope` would not take effect (null when it would).
export function scopeNote(field, scope) {
  if (field.restart && scope === "session") return "Read at launch: a session value has no effect. Save to User or This project.";
  if (rank(field.source) > rank(scope)) {
    const by = field.source === "env" ? "a NETSTEAD_* environment variable" : `the ${field.source} layer`;
    return `Currently set by ${by}; a ${scope} value is saved but won't take effect while that is set.`;
  }
  return null;
}

// A form control's state ({type, value, checked, badInput}) -> parseInput's answer. A number input the browser
// cannot parse ("-", "1e") reports an empty value; that must not read as "reset" and delete the saved value.
export function parseControl(field, { type, value, checked, badInput }) {
  if (badInput) return { ok: false, error: `${field.label}: enter a ${field.kind === "int" ? "whole " : ""}number` };
  return parseInput(field, type === "checkbox" ? checked : value);
}

// Clearing a field resets it only in the "Save to" layer. When the value comes from another layer that
// Reset can remove, say so instead of saving a no-op (null when clearing is fine).
export function clearHint(field, scope) {
  const layer = resetScope(field);
  if (!layer || layer === scope) return null;
  return `${field.label} comes from the ${layer} layer; clearing it in ${scope} changes nothing. Use Reset to remove it.`;
}
