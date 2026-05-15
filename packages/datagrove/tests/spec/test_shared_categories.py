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
