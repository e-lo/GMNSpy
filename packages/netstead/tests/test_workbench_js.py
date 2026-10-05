"""Unit tests for the workbench's pure (import-free) front-end modules, run under node."""

import json
import shutil

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SCHEMA = {
    "properties": {
        "viz": {"$ref": "#/$defs/VizSettings"},
        "app": {"$ref": "#/$defs/AppSettings"},
        "llm": {"$ref": "#/$defs/LLMSettings"},
        "validation": {"$ref": "#/$defs/ValidationSettings"},
        "io": {"$ref": "#/$defs/IOSettings"},
    },
    "$defs": {
        "VizSettings": {
            "description": "Map rendering.",
            "properties": {
                "basemap": {"default": "positron", "enum": ["positron", "esri"], "title": "Basemap", "type": "string"}
            },
        },
        "AppSettings": {
            "properties": {
                "port": {"default": 8850, "title": "Port", "type": "integer"},
                "approve_above_s": {"default": 90.0, "minimum": 0, "title": "Approve Above S", "type": "number"},
                "console": {"default": False, "title": "Console", "type": "boolean"},
            }
        },
        "LLMSettings": {"properties": {}},
        "ValidationSettings": {
            "properties": {"rules": {"additionalProperties": {}, "title": "Rules", "type": "object"}}
        },
        "IOSettings": {
            "properties": {
                "allowed_roots": {"items": {"type": "string"}, "title": "Allowed Roots", "type": "array"},
                "spec_version": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "Spec"},
            }
        },
    },
}
PAYLOAD = {
    "schema": SCHEMA,
    "values": {
        "viz": {"basemap": "esri"},
        "app": {"port": 9000, "approve_above_s": 90.0, "console": False},
        "llm": {},
        "validation": {"rules": {"r1": {"enabled": False}}},
        "io": {"allowed_roots": ["/data"], "spec_version": None},
    },
    "sources": {
        "viz.basemap": "project",
        "app.port": "env",
        "app.approve_above_s": "default",
        "app.console": "default",
        "validation.rules.r1.enabled": "user",
        "io.allowed_roots": "env",
        "io.spec_version": "default",
    },
    "readonly": {"io.allowed_roots": "config only"},
    "restart": ["app.port", "app.console"],
    "notes": {"validation": "not used yet"},
}


def test_sections_skip_folded_llm_and_describe_each_field(node_module):
    secs = node_module("settingsform.js", ["sectionsFrom"], f"sectionsFrom({json.dumps(PAYLOAD)})")
    assert [s["name"] for s in secs] == ["viz", "app", "validation", "io"]
    viz, app, validation, io = secs
    assert viz["title"] == "Map" and viz["description"] == "Map rendering."
    assert (
        viz["fields"][0].items()
        >= {"key": "viz.basemap", "kind": "choice", "value": "esri", "source": "project"}.items()
    )
    port, approve, console = app["fields"]
    assert (port["kind"], port["restart"], approve["kind"], approve["min"], console["kind"]) == (
        "int",
        True,
        "float",
        0,
        "bool",
    )
    assert validation["note"] == "not used yet" and validation["fields"][0]["kind"] == "json"
    assert validation["fields"][0]["source"] == "user"  # the highest layer among its nested keys
    roots, spec = io["fields"]
    assert (roots["kind"], roots["readonly"]) == ("list", "config only")
    assert (spec["kind"], spec["nullable"]) == ("text", True)


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ({"kind": "int", "label": "Port"}, "9100", {"ok": True, "value": 9100}),
        ({"kind": "int", "label": "Port"}, "9.5", {"ok": False, "error": "Port: enter a whole number"}),
        ({"kind": "float", "label": "S"}, "", {"ok": True, "value": None}),
        ({"kind": "bool", "label": "C"}, False, {"ok": True, "value": False}),
        ({"kind": "list", "label": "T"}, " a, b ,,c ", {"ok": True, "value": ["a", "b", "c"]}),
        ({"kind": "json", "label": "R"}, '{"x": 1}', {"ok": True, "value": {"x": 1}}),
        ({"kind": "json", "label": "R"}, "{x", {"ok": False, "error": "R: not valid JSON"}),
        ({"kind": "choice", "label": "B"}, "esri", {"ok": True, "value": "esri"}),
    ],
)
def test_parse_input(node_module, field, raw, expected):
    assert (
        node_module("settingsform.js", ["parseInput"], f"parseInput({json.dumps(field)}, {json.dumps(raw)})")
        == expected
    )


def test_a_number_the_browser_cannot_parse_is_not_a_reset(node_module):
    """A partial number ("-", "1e") reads as "" with validity.badInput: it must not delete the saved value."""
    got = node_module(
        "settingsform.js",
        ["parseControl"],
        '[parseControl({ kind: "int", label: "Port" }, { type: "number", value: "", badInput: true }),'
        ' parseControl({ kind: "int", label: "Port" }, { type: "number", value: "", badInput: false }),'
        ' parseControl({ kind: "bool", label: "C" }, { type: "checkbox", value: "on", checked: true })]',
    )
    assert got == [
        {"ok": False, "error": "Port: enter a whole number"},
        {"ok": True, "value": None},
        {"ok": True, "value": True},
    ]


def test_clearing_a_value_from_another_layer_points_to_reset(node_module):
    got = node_module(
        "settingsform.js",
        ["clearHint"],
        '[clearHint({ label: "Basemap", source: "project" }, "user"),'
        ' clearHint({ label: "B", source: "user" }, "user"),'
        ' clearHint({ label: "B", source: "default" }, "user"), clearHint({ label: "B", source: "env" }, "user")]',
    )
    assert "project" in got[0] and "Reset" in got[0] and got[1:] == [None, None, None]


def test_field_kind_nullable_enum_and_source_precedence(node_module):
    got = node_module(
        "settingsform.js",
        ["fieldKind", "sourceOf"],
        '[fieldKind({ anyOf: [{ enum: ["a", "b"], type: "string" }, { type: "null" }] }),'
        ' sourceOf({ "x.y": "project" }, "x.y"),'
        ' sourceOf({ "r.a": "user", "r.b": "env", "r.c": "project" }, "r"),'
        ' sourceOf({ "r.a": "session", "r.b": "env" }, "r"), sourceOf({ "rx": "env" }, "r")]',
    )
    assert got[0] == {"kind": "choice", "options": ["a", "b"], "nullable": True}
    assert got[1:] == ["project", "env", "session", "default"]


def test_reset_targets_the_layer_the_value_comes_from(node_module):
    got = node_module(
        "settingsform.js",
        ["resetScope"],
        '["default","user","project","env","session"].map(source => resetScope({ source }))',
    )
    assert got == [None, "user", "project", None, "session"]


def test_scope_note_warns_when_a_higher_layer_wins(node_module):
    got = node_module(
        "settingsform.js",
        ["scopeNote"],
        '[scopeNote({ source: "env" }, "user"), scopeNote({ source: "project" }, "session"),'
        ' scopeNote({ source: "user" }, "project"), scopeNote({ source: "default", restart: true }, "session")]',
    )
    assert "env" in got[0] and got[1] is None and got[2] is None and "launch" in got[3]


def test_sources_merge_focus_and_highlights_without_duplicates(node_module):
    got = node_module(
        "linking.js",
        ["sourcesFor"],
        '[sourcesFor({ table: "node", id: 7 }, new Set([1, 2])), sourcesFor({ table: "link", id: 2 }, new Set([1, 2])),'
        " sourcesFor(null, new Set())]",
    )
    assert got == [{"link": [1, 2], "node": [7]}, {"link": [1, 2]}, {}]


def test_rows_request_per_scope(node_module):
    expr = """(() => {
      const base = { selection: { link_ids: [5, 6] }, highlights: new Set([9]),
                     focus: { table: "node", id: 3 }, hops: 1 };
      return {
        all_link: rowsRequest({ ...base, scope: "all", table: "link" }),
        sel_link: rowsRequest({ ...base, scope: "selection", table: "link" }),
        sel_node: rowsRequest({ ...base, scope: "selection", table: "node" }),
        hl_lane: rowsRequest({ ...base, scope: "highlighted", table: "lane" }),
        rel_lane: rowsRequest({ ...base, scope: "related", table: "lane" }),
        empty_sel: rowsRequest({ ...base, selection: null, scope: "selection", table: "link" }),
        nothing: rowsRequest({ scope: "related", table: "lane", selection: null, highlights: new Set(), focus: null }),
      };
    })()"""
    got = node_module("linking.js", ["rowsRequest"], expr)
    sources = {"sources": {"link": [9], "node": [3]}, "hops": 1}
    tint = {"related": sources, "related_mode": "tint"}
    assert got["all_link"] == tint
    assert got["sel_link"] == {"ids": [5, 6], **tint}
    filter_by = {"related_mode": "filter", "tint": sources}  # the other tables are filtered *and* tinted
    assert got["sel_node"] == {"related": {"sources": {"link": [5, 6]}, "hops": 1}, **filter_by}
    assert got["hl_lane"] == {"related": {"sources": {"link": [9]}, "hops": 1}, **filter_by}
    assert got["rel_lane"] == {"related": {"sources": {"link": [9]}, "hops": 1}, **filter_by}  # highlights only
    assert got["empty_sel"] == {"ids": [], **tint}  # nothing selected shows no rows, not every row
    assert got["nothing"] == {"ids": []}


def test_related_scope_survives_a_row_click(node_module):
    """Clicking a row in the Related scope focuses it; the rows listed must not change (review finding)."""
    expr = """(() => {
      const base = { scope: "related", table: "node", selection: null, highlights: new Set([1]), hops: 1 };
      return [rowsRequest({ ...base, focus: null }).related,
              rowsRequest({ ...base, focus: { table: "node", id: 1 } }).related,
              rowsRequest({ ...base, highlights: new Set(), focus: { table: "node", id: 1 } })];
    })()"""
    before, after, focus_only = node_module("linking.js", ["rowsRequest"], expr)
    assert before == after == {"sources": {"link": [1]}, "hops": 1}
    assert focus_only == {"ids": []}  # a focus alone tints; the Related scope lists what is highlighted


def test_scope_hint_and_clamped_offset(node_module):
    got = node_module(
        "linking.js",
        ["scopeHint", "clampOffset"],
        '[scopeHint("selection", 0), scopeHint("related", 0), scopeHint("all", 0), scopeHint("related", 3),'
        " clampOffset(200, 100, 20), clampOffset(200, 100, 0), clampOffset(100, 100, 250), clampOffset(300, 100, 300)]",
    )
    assert got[0] == "Nothing selected." and "Highlight" in got[1] and got[2] == got[3] == ""
    assert got[4:] == [0, 200, 100, 200]


def test_row_marks(node_module):
    expr = """[
      rowMarks({ table: "link", id: 5, selection: { link_ids: [5] }, highlights: new Set([5]),
                 focus: { table: "link", id: 5 }, via: null }),
      rowMarks({ table: "lane", id: 5, selection: { link_ids: [5] }, highlights: new Set([5]),
                 focus: { table: "link", id: 5 }, via: "lane.link_id → link" }),
    ]"""
    assert node_module("linking.js", ["rowMarks"], expr) == [["sel", "hl", "focus"], ["rel"]]


def test_page_offset_and_id_coercion(node_module):
    got = node_module(
        "linking.js",
        ["coerceId", "pageOffset"],
        '[pageOffset(250, 100), pageOffset(0, 100), coerceId("12"), coerceId("A-1"), coerceId(""), coerceId("-4"),'
        ' coerceId("007"), coerceId("007", false), coerceId("12", false), coerceId("1e3"), coerceId("1.5"),'
        ' coerceId("9007199254740993"), coerceId(" 1")]',
    )
    assert got == [200, 0, 12, "A-1", "", -4, 7, "007", "12", "1e3", "1.5", "9007199254740993", " 1"]


def test_a_row_click_never_changes_the_recorded_selection():
    """Carried P1a bug: in filter-to-selection mode a row click collapsed the selection to that row."""
    import re

    from netstead.workbench.server import STATIC_DIR

    table = (STATIC_DIR / "js" / "table.js").read_text()
    body = re.search(r"function rowClick\(pkVal\) \{.*?\n\}", table, re.S)
    assert body, "table.js must define rowClick(pkVal)"
    assert "dispatch(" not in body.group(0) and "focus" in body.group(0)
