"""Verify shared-category $refs are inlined to concrete enums on load.

The 0.97 spec uses a sibling ``shared_categories.json`` and references
its values via ``"$ref": "shared_categories.json#/<name>/categories"``
on a field's ``categories`` payload. The loader is expected to:

    1. Resolve the $ref so the resolved categories are concrete.
    2. Promote those resolved values onto the field's
       ``constraints.enum`` so downstream validators see a flat enum.

Older versions (0.95) did not use shared_categories — they carried
inline ``constraints.enum`` directly. Both paths must work.
"""

from __future__ import annotations

import logging
from pathlib import Path

from datagrove.spec import load_package, load_schema


def _node_ctrl_type(pkg) -> object:
    node = next(r for r in pkg.resources if r.name == "node")
    return next(f for f in node.table_schema.fields if f.name == "ctrl_type")


def test_0_97_ctrl_type_resolves_to_concrete_enum(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    field = _node_ctrl_type(pkg)
    assert field.constraints is not None, "ctrl_type should have constraints after inlining"
    enum = field.constraints.enum
    assert isinstance(enum, list), "enum must be a concrete list"
    assert all(isinstance(v, str) for v in enum), "ctrl_type enum should be strings"
    # values from shared_categories.json#/ctrl_type/categories
    assert "signal" in enum
    assert "no_control" in enum


def test_0_97_link_bike_facility_resolves_to_concrete_enum(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    link = next(r for r in pkg.resources if r.name == "link")
    bike = next(f for f in link.table_schema.fields if f.name == "bike_facility")
    assert bike.constraints is not None
    assert isinstance(bike.constraints.enum, list)
    assert "shared lane" in bike.constraints.enum


def test_0_97_inlined_categories_are_not_refs(spec_097_dir: Path):
    """No field's enum should contain a string starting with '$ref' after load."""
    pkg = load_package(spec_097_dir / "datapackage.json")
    for resource in pkg.resources:
        schema = resource.table_schema
        if schema is None:
            continue
        for field in schema.fields:
            if field.constraints is None or field.constraints.enum is None:
                continue
            for v in field.constraints.enum:
                assert not (isinstance(v, str) and v.startswith("$ref")), (
                    f"{resource.name}:{field.name} still has unresolved ref"
                )


def test_0_95_inline_enum_preserved(spec_095_dir: Path):
    """0.95 has no shared_categories; ctrl_type's inline constraints.enum must survive."""
    schema = load_schema(spec_095_dir / "node.schema.json")
    field = next(f for f in schema.fields if f.name == "ctrl_type")
    assert field.constraints is not None
    assert field.constraints.enum == ["none", "yield", "stop", "4_stop", "signal"]


# ---------------------------------------------------------------------------
# Soft-skip + debug log (I11 — no more silent drop without trace)
# ---------------------------------------------------------------------------


def test_unrecognized_category_shape_logs_debug_and_skips(caplog):
    """A categories payload of the wrong shape must NOT raise — and must
    emit a debug-level log naming the field, so a modeler can trace why
    their enum didn't populate."""
    schema_doc = {
        "fields": [
            {
                "name": "weird_field",
                "type": "string",
                # mixed shapes: not all-dict-with-value and not all-scalar
                "categories": ["ok_scalar", {"label": "bad_no_value"}],
            }
        ]
    }
    caplog.set_level(logging.DEBUG, logger="datagrove.spec.loader")
    schema = load_schema(schema_doc)
    # Field still loads — soft skip, not an error.
    field = schema.fields[0]
    assert field.name == "weird_field"
    assert field.constraints is None or field.constraints.enum is None
    # And the debug log names the field so debugging is actually possible.
    assert any("weird_field" in rec.message for rec in caplog.records), (
        f"expected a debug log naming 'weird_field', got records: {[(r.name, r.message) for r in caplog.records]}"
    )
