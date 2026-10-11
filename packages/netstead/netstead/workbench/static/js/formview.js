// wb.schemaForm: a form generated from a JSON Schema, with the Settings dialog's field kinds, controls and parsing
// (schemaform.js). Labels are real <label for>; required fields carry aria-required; a bad entry is reported on its
// control (setCustomValidity), and the form's value is never changed by it. Schema text (titles, descriptions, enum
// values) comes from plugins, so every piece of it is escaped.
import { esc } from "./dom.js";
import { fieldsFrom, formErrors, inputHTML, parseControl, setPath } from "./schemaform.js";

let forms = 0;
const copy = v => JSON.parse(JSON.stringify(v || {}));

// Render a form for `schema` into `el`, prefilled from `value`. `onChange(value, {errors})` runs after each edit.
// Returns {value(), errors(), set(value), focus()}.
export function schemaForm(el, schema, value = {}, { onChange = () => {}, omit = [] } = {}) {
  const prefix = `sf${++forms}-`;
  let current = copy(value);
  let fields = [];
  const draw = () => {
    fields = fieldsFrom(schema || {}, current, { omit });
    // A checkbox or a menu always shows a value: make it the form's value too, so what is sent is what is seen.
    for (const f of fields) {
      if (f.value !== null || f.nullable || !(f.kind === "bool" || (f.kind === "choice" && f.options.length))) continue;
      f.value = f.default ?? (f.kind === "bool" ? false : f.options[0]);
      current = setPath(current, f.key, f.value);
    }
    let group = null;
    el.innerHTML = fields.map(f => {
      const head = f.group && f.group !== group ? `<div class="sf-group">${esc(f.group)}</div>` : "";
      group = f.group;
      return `${head}<div class="sf-field"><label for="${prefix}${esc(f.key.replace(/\./g, "-"))}">${esc(f.label)}` +
        `${f.required ? ' <span class="sf-req" aria-hidden="true">*</span>' : ""}</label>${inputHTML(f, prefix)}` +
        (f.description ? `<div class="sf-help">${esc(f.description)}</div>` : "") + "</div>";
    }).join("") || '<p class="empty">Nothing to fill in.</p>';
  };
  const api = {
    value: () => copy(current),
    errors: () => formErrors(fields, current),
    set(next) { current = copy(next); draw(); },
    focus() { const c = el.querySelector("[data-key]:not([disabled])"); if (c) c.focus(); return Boolean(c); },
  };
  el.classList.add("sf");
  el.onchange = e => {
    const control = e.target.closest("[data-key]");
    if (!control) return;
    const field = fields.find(f => f.key === control.dataset.key);
    if (!field) return;
    const parsed = parseControl(field, { type: control.type, value: control.value, checked: control.checked,
      badInput: Boolean(control.validity && control.validity.badInput) });
    control.setCustomValidity(parsed.ok ? "" : parsed.error);
    if (!parsed.ok) { control.reportValidity(); return; }
    current = setPath(current, field.key, parsed.value);
    onChange(api.value(), { errors: api.errors() });
  };
  draw();
  return api;
}
