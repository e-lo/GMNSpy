"""Node unit tests for the plugin front end's pure modules (Workbench plugins, Part 2)."""

import enum
import json
import shutil
from typing import Literal

import pytest
from netstead.workbench.server import STATIC_DIR
from pydantic import BaseModel, Field

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


def test_node_module_follows_multi_line_imports_and_re_exports(node_module, tmp_path):
    src = tmp_path / "multi"
    src.mkdir()
    (src / "b.js").write_text("export const two = () => 2;\nexport const three = () => 3;\n")
    (src / "c.js").write_text('export { three } from "./b.js";\n')
    (src / "a.js").write_text(
        'import {\n  two,\n} from "./b.js";\nimport { three } from "./c.js";\n'
        "export const five = () => two() + three();\n"
    )
    assert node_module(src / "a.js", ["five"], "five()") == 5


def test_node_module_names_an_import_it_cannot_read(node_module, tmp_path):
    (tmp_path / "d.js").write_text("import { y } from './e.js';\nexport const z = 1;\n")
    with pytest.raises(AssertionError, match="can't read this import"):
        node_module(tmp_path / "d.js", ["z"], "z")


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


def test_slots_remove_owner_clears_all_three_registries_and_stale_disposers_are_no_ops(node_module):
    expr = """(() => {
      const sl = createSlots(), ids = () => [sl.workspaces, sl.panels, sl.commands].map(r => r.list().map(x => x.id));
      sl.addWorkspace("core", {id: "inspect", title: "Inspect"});
      sl.addWorkspace("hello", {id: "hello.ws", title: "W"});
      sl.addPanel("hello", {id: "hello.p", title: "P", workspace: "*"});
      const stale = sl.addCommand("hello", {id: "hello.c", title: "C", run() {}});
      const before = ids();
      sl.removeOwner("hello");
      const after = ids();
      sl.addCommand("other", {id: "other.c", title: "Mine", run() {}});
      const again = sl.addCommand("hello", {id: "hello.c", title: "Again", run() {}});
      const removed = [stale(), sl.commands.list().map(c => c.title)];  // the first disposer must not remove "Again"
      return [before, after, removed, again(), again(), sl.commands.list().map(c => c.id)];
    })()"""
    before, after, removed, first, second, left = node_module("slots.js", ["createSlots"], expr)
    assert before == [["inspect", "hello.ws"], ["hello.p"], ["hello.c"]]
    assert after == [["inspect"], [], []]
    assert removed == [False, ["Mine", "Again"]]
    assert (first, second, left) == (True, False, ["other.c"])


def test_check_id_wants_a_name_after_the_plugin_prefix(node_module):
    expr = """(() => { try { checkId("hello", "hello."); return null; } catch (e) { return e.message; } })()"""
    assert node_module("slots.js", ["checkId"], expr) == 'hello: id "hello." must name something after "hello."'


def test_layer_registry_remove_owner_and_disposers(node_module):
    expr = """(() => {
      const reg = createLayerRegistry(), L = id => () => ({id});
      reg.register("core", "roadway", "base", L("base"));
      const stale = reg.register("hello", "roadway", "hello.a", L("hello.a"));
      reg.register("hello", "transit", "hello.t", L("hello.t"));
      reg.removeOwner("hello");
      const afterOwner = reg.ids();
      const again = reg.register("hello", "roadway", "hello.a", L("hello.a2"));
      const staleResult = stale();
      const kept = reg.build("roadway", {}).layers.map(l => l.id);
      return [afterOwner, staleResult, kept, again(), reg.ids()];
    })()"""
    after_owner, stale, kept, first, left = node_module("layers.js", ["createLayerRegistry"], expr)
    assert after_owner == ["base"] and stale is False and kept == ["base", "hello.a2"]
    assert first is True and left == ["base"]


class _Color(enum.StrEnum):
    red = "red"
    blue = "blue"


class _Size(enum.IntEnum):
    S = 1
    M = 2


class _Where(BaseModel):
    city: str = "Paris"


class _Shapes(BaseModel):
    """The pydantic shapes a plugin Action's schema commonly has."""

    tint: _Color | None = None  # anyOf [{$ref}, {type: null}]
    color: _Color = Field(_Color.blue, description="The colour.")  # {$ref, default, description}
    size: _Size = _Size.M
    lanes: Literal[1, 2] = 1
    where: _Where = Field(default_factory=_Where, description="Where to.")


def test_fields_resolve_refs_with_their_own_keys_and_inside_any_of(node_module):
    fields = node_module("schemaform.js", ["fieldsFrom"], f"fieldsFrom({json.dumps(_Shapes.model_json_schema())})")
    got = {f["key"]: (f["kind"], f.get("options"), f["nullable"], f["default"], f["description"]) for f in fields}
    assert got == {
        "tint": ("choice", ["red", "blue"], True, None, ""),
        "color": ("choice", ["red", "blue"], False, "blue", "The colour."),
        "size": ("choice", [1, 2], False, 2, ""),
        "lanes": ("choice", [1, 2], False, 1, ""),
        "where.city": ("text", None, False, "Paris", ""),
    }


def test_a_choice_parses_back_to_its_option_value(node_module):
    got = node_module(
        "schemaform.js",
        ["parseInput"],
        '[parseInput({kind: "choice", options: [1, 2], label: "Lanes"}, "2"),'
        ' parseInput({kind: "choice", options: ["a", "b"], label: "Mode"}, "b"),'
        ' parseInput({kind: "choice", options: [true, false], label: "Flag"}, "false"),'
        ' parseInput({kind: "choice", options: ["a"], label: "Mode"}, "")]',
    )
    assert got == [
        {"ok": True, "value": 2},
        {"ok": True, "value": "b"},
        {"ok": True, "value": False},
        {"ok": True, "value": None},
    ]


def test_command_context_hands_out_a_frozen_copy_of_the_state(node_module):
    got = _commands(
        node_module,
        "const c = commandContext({server}); let refused = false;"
        "try { c.state.active = 'other'; } catch (e) { refused = true; }"  # strict mode (ES module): throws
        "return [refused, c.state !== server, server.active, c.state.active, commandContext({server: null}).state];",
        ["commandContext"],
    )
    assert got == [True, True, "n1", "n1", None]


JS_DIR = STATIC_DIR / "js"
HOST_MODULES = ("wbhost.js", "slots.js", "layers.js", "store.js", "hub.js")

WB_HARNESS = """
import { createWb, eventName, keysChanged, pluginPath } from "./wbhost.js";
import { createSlots } from "./slots.js";
import { createLayerRegistry } from "./layers.js";
import { activeSelection, createStore } from "./store.js";
import { createHub } from "./hub.js";

export async function run() {
  const slots = createSlots(), layers = createLayerRegistry(), hub = createHub(), calls = [];
  const server = s => ({ networks: [{ id: "n1", version: 1 }], active: "n1", selection: s,
                         plugins: { hello: { n: 0 } } });
  const store = createStore({ server: server(null) });
  const deps = {
    hostApi: "1.1", store, activeSelection, events: hub, actionTypes: new Set(["hello.greet"]),
    actionSchema: () => null,
    getJSON: async p => (calls.push(["get", p]), {}), postJSON: async (p, b) => (calls.push(["post", p, b]), {}),
    fetch: async p => (calls.push(["fetch", p]), {}), dispatch: async a => (calls.push(["dispatch", a.type]), "ok"),
    addCommand: (o, s) => slots.addCommand(o, s), layers,
    dock: { addWorkspace: (o, s) => slots.addWorkspace(o, s),
            addPanel: (o, s) => ({ dispose: slots.addPanel(o, s), refreshBadge() {} }), showPanel() {} },
    schemaForm: () => null, toast: m => calls.push(["toast", m]),
    onError: (id, phase, e) => calls.push(["error", id, phase, e.message]),
  };
  const { wb, rollback } = createWb("hello", deps);
  const seen = [];
  wb.registerWorkspace({ id: "hello.ws", title: "Hello" });
  wb.registerPanel({ id: "hello.p", title: "P", workspace: "hello.ws", render() {} });
  wb.registerCommand({ id: "hello.c", title: "C", run() {} });
  wb.registerLayer("roadway", "hello.l", () => null);
  wb.store.subscribe(["plugins.hello"], s => seen.push(["store", s.plugins.hello.n]));
  wb.selection.subscribe(sel => seen.push(["selection", sel && sel.link_ids]));
  wb.on("greeted", p => seen.push(["event", p]));
  wb.on("other.thing", () => { throw new Error("listener bug"); });
  let refused = null;
  try { wb.registerCommand({ id: "c2", title: "x", run() {} }); } catch (e) { refused = e.message; }
  await wb.api.get("/count"); await wb.api.post("/echo", { a: 1 }); await wb.api.dispatch({ type: "hello.greet" });
  let badPath = null;
  try { wb.api.get("/../state"); } catch (e) { badPath = e.message; }
  store.set({ server: server(null) });                                                   // nothing watched changed
  store.set({ server: { ...server({ net_id: "n1", link_ids: [4] }), plugins: { hello: { n: 1 } } } });
  hub.emit("hello.greeted", { name: "Ada" }); hub.emit("other.thing", 1); hub.emit("greeted", "not mine");
  const before = [slots.workspaces.list().map(x => x.id), slots.panels.list().map(x => x.id),
                  slots.commands.list().map(x => x.id), layers.ids()];
  rollback();
  const after = [slots.workspaces.list().length, slots.panels.list().length, slots.commands.list().length,
                 layers.ids().length];
  let late = null;
  try { wb.registerCommand({ id: "hello.late", title: "L", run() {} }); } catch (e) { late = e.message; }
  hub.emit("hello.greeted", "after rollback");
  return { before, after, refused, badPath, late, seen, calls,
    has: [wb.hasAction("hello.greet"), wb.hasAction("cards.x")],
    pure: [pluginPath("hello", "/count?x=1"), eventName("hello", "greeted"), eventName("hello", "core.history"),
           keysChanged({ a: { b: 1 } }, { a: { b: 1 }, c: 2 }, ["a.b"]),
           keysChanged({ a: { b: 1 } }, { a: { b: 2 } }, ["a.b"])] };
}
"""


def _harness(tmp_path, source: str):
    root = tmp_path / "harness"
    root.mkdir()
    for name in HOST_MODULES:
        shutil.copy(JS_DIR / name, root / name)
    (root / "harness.js").write_text(source, encoding="utf-8")
    return root / "harness.js"


def test_wb_registers_namespaced_tracks_and_rolls_back(node_module, tmp_path):
    got = node_module(_harness(tmp_path, WB_HARNESS), ["run"], "await run()")
    assert got["before"] == [["hello.ws"], ["hello.p"], ["hello.c"], ["hello.l"]]
    assert got["after"] == [0, 0, 0, 0]
    assert got["refused"] == 'hello: id "c2" must start with "hello."'
    assert got["badPath"] == 'hello: wb.api paths start with "/" and stay under /api/plugins/hello'
    assert got["late"] == "hello: activation was rolled back; nothing more can be registered"
    assert got["seen"] == [["store", 1], ["selection", [4]], ["event", {"name": "Ada"}]]
    assert got["calls"] == [
        ["get", "/api/plugins/hello/count"],
        ["post", "/api/plugins/hello/echo", {"a": 1}],
        ["dispatch", "hello.greet"],
        ["error", "hello", "event other.thing", "listener bug"],
    ]
    assert got["has"] == [True, False]
    assert got["pure"] == ["/api/plugins/hello/count?x=1", "hello.greeted", "core.history", False, True]


STATUSES = [
    {
        "id": "hello",
        "name": "Hello",
        "version": "0.1.0",
        "requires_api": "1.1",
        "state": "loaded",
        "error": None,
        "frontend": "/plugins/hello/main.js",
    },
    {
        "id": "cards",
        "name": "cards",
        "version": "",
        "requires_api": None,
        "state": "disabled",
        "error": None,
        "frontend": None,
    },
    {
        "id": "old",
        "name": "Old",
        "version": "2.0.0",
        "requires_api": "2.0",
        "state": "incompatible",
        "error": "needs plugin API 2.0; this netstead provides 1.1",
        "frontend": None,
    },
    {
        "id": "boom",
        "name": "boom",
        "version": "",
        "requires_api": None,
        "state": "error",
        "error": "RuntimeError: nope",
        "frontend": None,
    },
]


def test_plugin_rows_show_fit_errors_and_pending_restarts(node_module):
    args = {
        "statuses": STATUSES,
        "hostApi": "1.1",
        "disabled": ["cards", "hello", "gone"],
        "browserErrors": {"hello": [{"phase": "activate", "message": "x"}]},
    }
    rows = node_module("pluginlist.js", ["pluginRows"], f"pluginRows({json.dumps(args)})")
    assert [
        (r["id"], r["version"], r["compat"], r["stateText"], r["enabled"], r["restart"], r["errors"]) for r in rows
    ] == [
        (
            "hello",
            "0.1.0",
            "1.1 (compatible)",
            "Loaded",
            False,
            True,
            ["activate: x"],
        ),  # switched off: restart to apply
        ("cards", "—", "—", "Disabled", False, False, []),
        (
            "old",
            "2.0.0",
            "2.0 (this netstead provides 1.1)",
            "Incompatible",
            True,
            False,
            ["needs plugin API 2.0; this netstead provides 1.1"],
        ),
        ("boom", "—", "—", "Failed to load", True, False, ["RuntimeError: nope"]),
        ("gone", "—", "—", "Not installed", False, False, []),  # listed so it can be cleared
    ]


def test_switching_a_plugin_edits_the_disabled_list(node_module):
    got = node_module(
        "pluginlist.js",
        ["withPluginEnabled"],
        '[withPluginEnabled(["a", "b"], "a", true), withPluginEnabled(["a"], "b", false), '
        'withPluginEnabled(["a"], "a", false)]',
    )
    assert got == [["b"], ["a", "b"], ["a"]]


# Part R (batch-2 review): schema forms.
FORM_FIELDS = [
    {"key": "n", "label": "N", "kind": "float", "nullable": False, "value": 3, "default": None, "required": True},
    {
        "key": "flag",
        "label": "Flag",
        "kind": "bool",
        "nullable": False,
        "value": None,
        "default": None,
        "required": False,
    },
    {
        "key": "mode",
        "label": "Mode",
        "kind": "choice",
        "options": ["a", "b"],
        "nullable": False,
        "value": None,
        "default": "b",
        "required": False,
    },
    {
        "key": "maybe",
        "label": "Maybe",
        "kind": "text",
        "nullable": True,
        "value": None,
        "default": None,
        "required": True,
    },
    {"key": "opt", "label": "Opt", "kind": "text", "nullable": True, "value": None, "default": None, "required": False},
]


def test_fill_shown_makes_what_a_form_shows_its_value(node_module):
    got = node_module("schemaform.js", ["fillShown"], f"fillShown({json.dumps(FORM_FIELDS)}, {{n: 3}})")
    assert got["value"] == {"n": 3, "flag": False, "mode": "b", "maybe": None}  # explicit null; "opt" left out
    assert [f["value"] for f in got["fields"]] == [3, False, "b", None, None]


def test_form_errors_name_bad_entries_explicit_nulls_and_exclusive_bounds(node_module):
    fields = [
        *FORM_FIELDS,
        {
            "key": "gt",
            "label": "Gt",
            "kind": "float",
            "min": 0,
            "max": 10,
            "exclusiveMin": True,
            "exclusiveMax": True,
            "value": None,
            "default": None,
            "required": False,
            "nullable": False,
        },
        {
            "key": "ge",
            "label": "Ge",
            "kind": "float",
            "min": 0,
            "max": 10,
            "value": None,
            "default": None,
            "required": False,
            "nullable": False,
        },
    ]
    expr = (
        f"(() => {{ const f = {json.dumps(fields)};"
        ' return [formErrors(f, {n: 3, maybe: null, gt: 0, ge: 0}, new Set(["n"])),'
        " formErrors(f, {n: 3, gt: 10, ge: 10}), formErrors(f, {n: 3, maybe: null, gt: 5})]; })()"
    )
    assert node_module("schemaform.js", ["formErrors"], expr) == [
        ["N: fix this entry", "Gt must be more than 0"],  # the stale 3 is not sent; Ge 0 is fine (inclusive)
        ["Maybe is required", "Gt must be less than 10"],  # "maybe" missing altogether is not None on purpose
        [],
    ]


def test_generated_form_controls_none_menus_json_placeholders_and_distinct_ids(node_module):
    expr = """[
      inputHTML({key: "a.b", label: "B", kind: "bool", nullable: true, value: null, default: null, required: true},
                "sf1-", {form: true}),
      inputHTML({key: "a-b", label: "B", kind: "bool", nullable: true, value: false, default: true, required: false},
                "sf1-", {form: true}),
      inputHTML({key: "r", label: "R", kind: "json", nullable: false, value: null, default: [1, 2], required: false},
                "sf1-", {form: true}),
      inputHTML({key: "c", label: "C", kind: "choice", options: ["x"], nullable: true, value: null, default: null,
                 required: true}, "sf1-", {form: true}),
      inputHTML({key: "c", label: "C", kind: "choice", options: ["x"], nullable: true, value: null, default: null}),
    ]"""
    got = node_module("schemaform.js", ["inputHTML"], expr)
    assert got[0] == (
        '<select id="sf1-a-002eb" data-key="a.b" aria-required="true"><option value="" selected>None</option>'
        '<option value="true">true</option><option value="false">false</option></select>'
    )
    assert got[1].startswith('<select id="sf1-a-002db" data-key="a-b">') and '<option value="false" selected>' in got[1]
    assert got[2] == '<textarea id="sf1-r" data-key="r" rows="3" spellcheck="false" placeholder="[1,2]"></textarea>'
    assert ">None</option>" in got[3]
    assert got[4] == (  # the Settings dialog's markup is unchanged
        '<select id="set-c" data-key="c"><option value="" selected>(default)</option>'
        '<option value="x">x</option></select>'
    )


def test_a_nullable_bool_menu_parses_to_null_true_or_false(node_module):
    field = '{kind: "bool", nullable: true, label: "B"}'
    got = node_module(
        "schemaform.js",
        ["parseInput"],
        f'[parseInput({field}, ""), parseInput({field}, "true"), parseInput({field}, "false"), '
        'parseInput({kind: "bool", label: "C"}, true)]',
    )
    assert [g["value"] for g in got] == [None, True, False, True]
