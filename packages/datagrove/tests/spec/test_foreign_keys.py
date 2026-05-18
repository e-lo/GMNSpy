"""Foreign-key model parsing across the 0.97 spec."""

from __future__ import annotations

from pathlib import Path

from datagrove.spec import ForeignKey, load_package


def test_every_foreign_key_in_0_97_parses(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    seen_any = False
    for resource in pkg.resources:
        schema = resource.table_schema
        if schema is None:
            continue
        for fk in schema.foreign_keys:
            assert isinstance(fk, ForeignKey)
            assert fk.fields, f"{resource.name}: empty foreign-key fields"
            assert fk.reference is not None, f"{resource.name}: missing reference"
            seen_any = True
    assert seen_any, "expected at least one foreign key in the 0.97 spec"


def test_link_node_foreign_keys_resolve_to_node_node_id(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    link = next(r for r in pkg.resources if r.name == "link")
    fks_by_field = {fk.fields: fk for fk in link.table_schema.foreign_keys}

    assert "from_node_id" in fks_by_field
    assert "to_node_id" in fks_by_field

    for field_name in ("from_node_id", "to_node_id"):
        fk = fks_by_field[field_name]
        assert fk.reference.resource == "node"
        assert fk.reference.fields == "node_id"


def test_link_self_reference_parent_link_id(spec_097_dir: Path):
    """parent_link_id self-references the link table via reference.resource = ''."""
    pkg = load_package(spec_097_dir / "datapackage.json")
    link = next(r for r in pkg.resources if r.name == "link")
    fk = next(fk for fk in link.table_schema.foreign_keys if fk.fields == "parent_link_id")
    assert fk.reference.resource == ""
    assert fk.reference.fields == "link_id"
