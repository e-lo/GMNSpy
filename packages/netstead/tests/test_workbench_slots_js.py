"""Node unit tests for the plugin front end's pure modules (Workbench plugins, Part 2)."""

import json
import shutil

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_node_module_follows_sibling_imports(node_module, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.js").write_text("export const two = () => 2;\n")
    (src / "a.js").write_text('import { two } from "./b.js";\nexport const four = () => two() * 2;\n')
    assert node_module(src / "a.js", ["four"], "four()") == 4


def test_node_module_refuses_a_non_sibling_import(node_module, tmp_path):
    (tmp_path / "c.js").write_text('import x from "https://cdn.example/x.js";\nexport const y = 1;\n')
    with pytest.raises(AssertionError, match="sibling pure modules"):
        node_module(tmp_path / "c.js", ["y"], "y")


GREET_SCHEMA = {
    "title": "Greet",
    "type": "object",
    "properties": {
        "type": {"const": "hello.greet", "default": "hello.greet", "title": "Type", "type": "string"},
        "name": {"title": "Name", "type": "string"},
        "times": {"default": 1, "minimum": 1, "title": "Times", "type": "integer"},
        "where": {"$ref": "#/$defs/Where"},
        "loud": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None, "title": "Loud"},
    },
    "required": ["name", "where"],
    "$defs": {
        "Where": {
            "title": "Where",
            "type": "object",
            "properties": {"city": {"title": "City", "type": "string"}},
            "required": ["city"],
        }
    },
}


def test_fields_skip_constants_and_group_one_level_of_nesting(node_module):
    fields = node_module(
        "schemaform.js",
        ["fieldsFrom"],
        f"fieldsFrom({json.dumps(GREET_SCHEMA)}, {{name: 'Ada', where: {{city: 'Paris'}}}})",
    )
    assert [(f["key"], f["kind"], f["required"], f["group"], f["value"]) for f in fields] == [
        ("name", "text", True, None, "Ada"),
        ("times", "int", False, None, None),
        ("where.city", "text", True, "Where", "Paris"),
        ("loud", "bool", False, None, None),
    ]


def test_set_path_nests_and_null_removes(node_module):
    got = node_module(
        "schemaform.js",
        ["setPath"],
        "[setPath({}, 'where.city', 'Paris'), setPath({a: 1, b: 2}, 'a', null), setPath({w: {c: 1}}, 'w.d', 2)]",
    )
    assert got == [{"where": {"city": "Paris"}}, {"b": 2}, {"w": {"c": 1, "d": 2}}]


def test_form_errors_name_missing_required_fields_and_bounds(node_module):
    schema = json.dumps(GREET_SCHEMA)
    expr = (
        f"(() => {{ const fs = fieldsFrom({schema}); return [formErrors(fs, {{}}), "
        "formErrors(fs, {name: 'A', where: {city: 'P'}, times: 0}), "
        "formErrors(fs, {name: 'A', where: {city: 'P'}})]; })()"
    )
    assert node_module("schemaform.js", ["fieldsFrom", "formErrors"], expr) == [
        ["Name is required", "City is required"],
        ["Times must be at least 1"],
        [],
    ]


def test_input_html_is_what_the_settings_dialog_always_rendered(node_module):
    """The Settings dialog's markup is pinned: moving inputHTML must not change a byte of it."""
    fields = [
        {"key": "viz.show_legend", "kind": "bool", "value": True, "readonly": None},
        {"key": "io.default_format", "kind": "choice", "options": ["parquet", "csv"], "nullable": True, "value": "csv"},
        {"key": "app.port", "kind": "int", "min": 1, "max": 65535, "value": 8850, "default": 8850, "readonly": "r"},
        {"key": "io.allowed_roots", "kind": "list", "value": ["/a", "/b"]},
        {"key": "viz.basemap", "kind": "text", "value": None, "default": None},
        {"key": "validation.rules", "kind": "json", "value": {"a": 1}},
    ]
    got = node_module("schemaform.js", ["inputHTML"], f"{json.dumps(fields)}.map(f => inputHTML(f))")
    assert got == [
        '<input type="checkbox" id="set-viz-show_legend" data-key="viz.show_legend" checked>',
        '<select id="set-io-default_format" data-key="io.default_format"><option value="">(default)</option>'
        '<option value="parquet">parquet</option><option value="csv" selected>csv</option></select>',
        '<input type="number" id="set-app-port" data-key="app.port" disabled step="1" min="1" max="65535" '
        'value="8850" placeholder="8850">',
        '<input id="set-io-allowed_roots" data-key="io.allowed_roots" value="/a, /b" placeholder="comma-separated" '
        'spellcheck="false">',
        '<input id="set-viz-basemap" data-key="viz.basemap" value="" placeholder="default" spellcheck="false">',
        '<textarea id="set-validation-rules" data-key="validation.rules" rows="3" spellcheck="false">'
        "{\n &quot;a&quot;: 1\n}</textarea>",
    ]


def test_input_html_marks_required_fields_under_another_prefix(node_module):
    got = node_module(
        "schemaform.js",
        ["inputHTML"],
        'inputHTML({key: "name", kind: "text", value: "", default: null, required: true}, "sf1-")',
    )
    assert got == (
        '<input id="sf1-name" data-key="name" aria-required="true" value="" placeholder="default" spellcheck="false">'
    )


def test_registry_orders_entries_and_namespaces_plugin_ids(node_module):
    expr = """(() => {
      const r = createRegistry("panel");
      r.add("core", {id: "details", title: "Details", order: 0});
      r.add("hello", {id: "hello.b", title: "B", order: 50});
      r.add("hello", {id: "hello.a", title: "A", order: 50});
      r.add("cards", {id: "cards.x", title: "X", order: 10});
      const errors = [];
      for (const [owner, id] of [["hello", "panel"], ["hello", "cards.y"], ["core", "details"]])
        try { r.add(owner, {id, title: "?"}); } catch (e) { errors.push(e.message); }
      r.removeOwner("cards");
      return [r.list().map(p => p.id), errors];
    })()"""
    ids, errors = node_module("slots.js", ["createRegistry"], expr)
    assert ids == ["details", "hello.b", "hello.a"]
    assert errors == [
        'hello: id "panel" must start with "hello."',
        'hello: id "cards.y" must start with "hello."',
        'panel "details" is already registered',
    ]


def test_command_specs_default_to_the_palette_and_reject_bad_shapes(node_module):
    expr = """(() => {
      const errors = [];
      for (const s of [{id: "hello.x", title: "X", run() {}, contexts: ["menu"]}, {id: "hello.x", title: "X"},
                       {id: "hello.x", title: "X", run() {}, when: true}])
        try { commandSpec(s); } catch (e) { errors.push(e.message); }
      return [commandSpec({id: "hello.x", title: "X", run() {}}).contexts, errors];
    })()"""
    contexts, errors = node_module("slots.js", ["commandSpec"], expr)
    assert contexts == ["palette"]
    assert errors == [
        "command hello.x: unknown context menu (use palette, feature, row, selection)",
        'command "hello.x": run required',
        "command hello.x: when must be a function",
    ]


def test_panels_for_a_workspace_include_shared_ones_and_disposers_undo(node_module):
    expr = """(() => {
      const sl = createSlots();
      sl.addPanel("core", {id: "details", title: "Details", workspace: "*"});
      const off = sl.addPanel("hello", {id: "hello.p", title: "P", workspace: "inspect", order: 5});
      sl.addPanel("cards", {id: "cards.d", title: "Draft", workspace: ["cards.edit"]});
      const ids = w => panelsFor(sl.panels.list(), w).map(p => p.id);
      const before = [ids("inspect"), ids("cards.edit")];
      off();
      let bad = null;
      try { workspaceSpec({id: "cards.edit", title: "Edit", layout: {view: "globe"}}); } catch (e) { bad = e.message; }
      return [before, panelsFor(sl.panels.list(), "inspect").map(p => p.id), bad];
    })()"""
    before, after, bad = node_module("slots.js", ["createSlots", "panelsFor", "workspaceSpec"], expr)
    assert before == [["details", "hello.p"], ["details", "cards.d"]]
    assert after == ["details"]
    assert bad == "workspace cards.edit: layout.view must be one of map, split, table"
