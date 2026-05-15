"""Load the vendored GMNS 0.97 data package and exercise its schemas."""

from __future__ import annotations

from pathlib import Path

from datagrove.spec import DataPackage, Schema, load_package, load_schema


def test_load_0_97_data_package(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    assert isinstance(pkg, DataPackage)
    assert pkg.name == "gmns"
    assert len(pkg.resources) >= 25


def test_each_schema_loads_with_typed_fields(spec_097_dir: Path):
    schema_files = sorted(spec_097_dir.glob("*.schema.json"))
    assert schema_files, "expected vendored 0.97 schema files"
    shared = (spec_097_dir / "shared_categories.json").read_text(encoding="utf-8")
    import json

    shared_doc = json.loads(shared)
    for sf in schema_files:
        schema = load_schema(sf, shared_categories=shared_doc)
        assert isinstance(schema, Schema), sf.name
        assert schema.fields, f"{sf.name} has no fields"
        for field in schema.fields:
            assert field.type is not None, f"{sf.name}:{field.name} has no type"


def test_round_trip_data_package_equality(spec_097_dir: Path):
    pkg = load_package(spec_097_dir / "datapackage.json")
    dumped = pkg.model_dump(by_alias=True)
    pkg2 = DataPackage.model_validate(dumped)
    assert pkg2 == pkg

    dumped_json = pkg.model_dump_json(by_alias=True)
    pkg3 = DataPackage.model_validate_json(dumped_json)
    assert pkg3 == pkg
