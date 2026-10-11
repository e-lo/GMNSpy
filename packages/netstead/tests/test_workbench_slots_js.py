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
