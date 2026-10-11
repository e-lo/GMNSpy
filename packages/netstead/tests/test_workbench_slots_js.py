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
        {"key": "x.n", "kind": "float", "min": '0" onfocus="alert(1)', "max": None, "value": None, "default": None},
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
        # A bound that reached the markup unchecked (fieldKind drops these) is still escaped (review I-3).
        '<input type="number" id="set-x-n" data-key="x.n" step="any" min="0&quot; onfocus=&quot;alert(1)" value="" '
        'placeholder="default">',
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


COMMANDS_JS = """
const cmds = [
  {id: "open", title: "Open / Import…", contexts: ["palette"], run() {}},
  {id: "zoom_selection", title: "Zoom to selection", contexts: ["palette"], when: c => c.selectionCount > 0, run() {}},
  {id: "hello.greet", title: "Say hello", contexts: ["palette"], run() {}},
  {id: "hello.rec", title: "Say hello to this record", contexts: ["feature", "row"], run() {}},
  {id: "hello.lane", title: "Lane only", contexts: ["row"], when: c => c.target.table === "lane", run() {}},
  {id: "hello.sel", title: "Hello selection", contexts: ["selection"], run() {}},
  {id: "hello.both", title: "Both", contexts: ["feature", "selection"], run() {}},
  {id: "bad.when", title: "Broken", contexts: ["palette"], when: () => { throw new Error("boom"); }, run() {}},
];
const server = {networks: [{id: "n1", version: 3, derived_from: null}], active: "n1",
                selection: {net_id: "n1", link_ids: [1, 2]}};
const shape = groups => groups.map(g => [g.title, g.items.map(i => (i.command || i).id)]);
"""


def _commands(node_module, body: str, names: list[str]):
    return node_module("commands.js", names, f"(() => {{ {COMMANDS_JS} {body} }})()")


def test_command_context_describes_the_network_selection_and_view(node_module):
    got = _commands(
        node_module,
        'const c = commandContext({server, focus: {table: "link", id: 7, from: "map"}, highlights: new Set([5])});'
        "return [c.network, c.selectionCount, c.highlights, c.workspace, c.target];",
        ["commandContext"],
    )
    assert got == [{"id": "n1", "version": 3, "derived_from": None}, 2, [5], "inspect", None]


def test_menu_sections_for_a_feature_then_the_selection_without_repeats(node_module):
    got = _commands(
        node_module,
        'return [shape(menuSections(cmds, "feature", commandContext({server}, {table: "link", id: 7}))),'
        ' shape(menuSections(cmds, "row",'
        ' commandContext({server: {...server, selection: null}}, {table: "lane", id: 3})))];',
        ["commandContext", "menuSections"],
    )
    assert got == [
        [["link 7", ["hello.rec", "hello.both"]], ["Selection (2 links)", ["hello.sel"]]],
        [["lane 3", ["hello.rec", "hello.lane"]]],
    ]


def test_palette_groups_reach_the_focused_record_and_contain_a_broken_when(node_module):
    got = _commands(
        node_module,
        'const ctx = commandContext({server, focus: {table: "link", id: 7, from: "map"}});'
        "const errors = []; const groups = paletteGroups(cmds, ctx, '', (c, e) => errors.push([c.id, e.message]));"
        "return [shape(groups), errors, groups[1].items[0].ctx.target, shape(paletteGroups(cmds, ctx, 'hello'))];",
        ["commandContext", "paletteGroups"],
    )
    everything, errors, target, hello = got
    assert everything == [
        ["Commands", ["open", "zoom_selection", "hello.greet"]],
        ["For link 7", ["hello.rec", "hello.both"]],
        ["Selection (2 links)", ["hello.sel"]],
    ]
    assert errors == [["bad.when", "boom"]]
    assert target == {"table": "link", "id": 7}
    assert hello == [
        ["Commands", ["hello.greet"]],
        ["For link 7", ["hello.rec"]],
        ["Selection (2 links)", ["hello.sel"]],
    ]


def test_match_score_and_the_palette_shortcut(node_module):
    got = node_module(
        "commands.js",
        ["matchScore", "isPaletteShortcut"],
        '[[matchScore("Say hello", "hello"), matchScore("Hello selection", "hello"), matchScore("Othello", "hello"),'
        ' matchScore("Zoom to selection", "zts"), matchScore("Open", "x"), matchScore("Open", "")],'
        ' [isPaletteShortcut({key: "k", ctrlKey: true}), isPaletteShortcut({key: "K", metaKey: true}),'
        ' isPaletteShortcut({key: "k"}), isPaletteShortcut({key: "k", ctrlKey: true, shiftKey: true})]]',
    )
    assert got == [[2, 3, 1, 0.5, -1, 0], [True, True, False, False]]


def test_run_command_reports_sync_and_async_failures(node_module):
    expr = """await (async () => {
      const errors = [], report = (c, e) => errors.push([c.id, e.message]);
      await runCommand({id: "x", run: () => { throw new Error("bad"); }}, {}, report);
      await runCommand({id: "y", run: async () => { throw new Error("later"); }}, {}, report);
      return errors;
    })()"""
    assert node_module("commands.js", ["runCommand"], expr) == [["x", "bad"], ["y", "later"]]


def test_every_plugin_action_gets_a_form_command(node_module):
    catalog = [
        {
            "type": "open_network",
            "name": "OpenNetwork",
            "description": "Open",
            "plugin": None,
            "mutates": False,
            "schema": {},
        },
        {
            "type": "hello.greet",
            "name": "Greet",
            "description": "Greet someone.",
            "plugin": "hello",
            "mutates": False,
            "schema": {"properties": {}},
        },
    ]
    got = node_module(
        "commands.js", ["actionCommands"], f'actionCommands({json.dumps(catalog)}, [{{id: "hello", name: "Hello"}}])'
    )
    assert got == [
        {
            "owner": "hello",
            "id": "hello.greet:form",
            "title": "Hello: Greet…",
            "contexts": ["palette"],
            "entry": {
                "type": "hello.greet",
                "label": "Hello: Greet",
                "description": "Greet someone.",
                "schema": {"properties": {}},
            },
        }
    ]


def test_a_selection_with_no_links_offers_no_selection_commands(node_module):
    """An utterance that resolved to nothing leaves a selection with ``link_ids: []``: nothing to act on."""
    got = _commands(
        node_module,
        "const empty = {...server, selection: {net_id: 'n1', link_ids: []}};"
        'const ctx = commandContext({server: empty}, {table: "link", id: 7});'
        'return [shape(menuSections(cmds, "feature", ctx)), selectionSections(cmds, ctx),'
        " shape(paletteGroups(cmds, ctx, '')).map(g => g[0])];",
        ["commandContext", "menuSections", "selectionSections", "paletteGroups"],
    )
    assert got == [[["link 7", ["hello.rec", "hello.both"]]], [], ["Commands"]]


def test_layer_registry_orders_core_and_plugin_layers_and_contains_failures(node_module):
    expr = """(() => {
      const reg = createLayerRegistry(), L = id => ({id});
      for (const id of ["marker", "focus", "highlighted", "related", "selection", "base"])
        reg.register("core", "roadway", id, () => [L(id + "-deck")]);      // registered out of order on purpose
      reg.register("hello", "roadway", "hello.dots", () => L("hello.dots"), {title: "Hello dots"});
      reg.register("hello", "roadway", "hello.top", () => L("hello.top"), {order: 700});
      reg.register("hello", "roadway", "hello.bad", () => L("links"));
      reg.register("hello", "roadway", "hello.throws", () => { throw new Error("nope"); });
      reg.register("hello", "transit", "hello.stops", () => L("hello.stops"));
      reg.register("hello", "roadway", "hello.none", () => null);
      const all = reg.build("roadway", {}), hidden = reg.build("roadway", {}, new Set(["hello.dots"]));
      const refused = [];
      try { reg.register("hello", "rail", "hello.x", () => null); } catch (e) { refused.push(e.message); }
      try { reg.register("hello", "roadway", "dots", () => null); } catch (e) { refused.push(e.message); }
      return [all.layers.map(l => l.id), all.errors, hidden.layers.map(l => l.id),
              reg.build("transit", {}).layers.map(l => l.id), reg.toggleable().map(l => l.id), refused];
    })()"""
    layers, errors, hidden, transit, toggleable, refused = node_module("layers.js", ["createLayerRegistry"], expr)
    assert layers == [
        "base-deck",
        "selection-deck",
        "related-deck",
        "hello.dots",
        "highlighted-deck",
        "focus-deck",
        "marker-deck",
        "hello.top",
    ]
    assert errors == [
        {"owner": "hello", "id": "hello.bad", "error": 'deck layer id "links" must start with "hello."'},
        {"owner": "hello", "id": "hello.throws", "error": "nope"},
    ]
    assert hidden == [layer for layer in layers if layer != "hello.dots"]
    assert transit == ["hello.stops"] and toggleable == ["hello.dots"]
    assert refused == ['unknown component "rail": use roadway or transit', 'hello: id "dots" must start with "hello."']


def test_tab_keys_wrap_and_jump(node_module):
    got = node_module(
        "tabs.js",
        ["nextIndex"],
        '[nextIndex(0, "ArrowRight", 3), nextIndex(2, "ArrowRight", 3), nextIndex(0, "ArrowLeft", 3),'
        ' nextIndex(1, "Home", 3), nextIndex(0, "End", 3), nextIndex(0, "ArrowDown", 3),'
        ' nextIndex(0, "ArrowDown", 3, "vertical"), nextIndex(0, "ArrowUp", 3, "vertical"), nextIndex(0, "a", 3),'
        ' nextIndex(0, "End", 0)]',
    )
    assert got == [1, 0, 2, 0, 2, None, 1, 2, None, None]


def test_badges_normalise_roll_up_and_read_aloud(node_module):
    got = node_module(
        "tabs.js",
        ["normalizeBadge", "workspaceBadge", "tabLabel"],
        "[normalizeBadge(null), normalizeBadge(0), normalizeBadge(3),"
        ' normalizeBadge({dirty: true, title: "2 unsaved"}), normalizeBadge({text: ""}),'
        ' workspaceBadge(null, [null, {text: "4"}, {dirty: true, title: "Draft card"}]),'
        ' workspaceBadge(null, [{text: "4"}]), workspaceBadge("!", [{dirty: true}]),'
        ' tabLabel("Edits", {text: 2, dirty: true, title: "2 unsaved"}), tabLabel("Issues", 5),'
        ' tabLabel("Details", null)]',
    )
    assert got == [
        None,
        None,
        {"text": "3", "dirty": False, "title": ""},
        {"text": "", "dirty": True, "title": "2 unsaved"},
        None,
        {"text": "", "dirty": True, "title": "Draft card"},  # a dirty panel marks its workspace tab
        None,  # a count alone doesn't
        {"text": "!", "dirty": False, "title": ""},
        "Edits, 2 unsaved",
        "Issues, 5",
        "Details",
    ]


def test_view_for_a_workspace_and_the_derived_network_mark(node_module):
    got = node_module(
        "tabs.js",
        ["viewFor", "networkBadge"],
        '[viewFor({id: "cards.edit", layout: {view: "split"}}, {}, "map"),'
        ' viewFor({id: "cards.edit", layout: {view: "split"}}, {"cards.edit": "table"}, "map"),'
        ' viewFor({id: "inspect", layout: {}}, {}, "table"),'
        ' networkBadge({derived_from: "n1"}), networkBadge({derived_from: null}), networkBadge(null)]',
    )
    assert got == ["split", "table", "table", "derived", "", ""]


def test_an_action_without_a_schema_gets_no_form_command(node_module):
    catalog = [{"type": "hello.opaque", "name": "Opaque", "description": "", "plugin": "hello", "schema": None}]
    got = node_module("commands.js", ["actionCommands"], f'actionCommands({json.dumps(catalog)}, [{{id: "hello"}}])')
    assert got == []


def test_field_kind_keeps_only_finite_numeric_bounds(node_module):
    got = node_module(
        "schemaform.js",
        ["fieldKind"],
        '[fieldKind({type: "integer", minimum: "1\\" onfocus=\\"x", maximum: 5}),'
        ' fieldKind({type: "number", exclusiveMinimum: 0, maximum: null})]',
    )
    assert got == [
        {"kind": "int", "nullable": False, "min": None, "max": 5},
        {"kind": "float", "nullable": False, "min": 0, "max": None},
    ]
