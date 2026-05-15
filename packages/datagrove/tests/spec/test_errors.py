"""Error-path tests for the loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from datagrove.spec import SpecLoadError, load_package, load_schema


def test_missing_path_raises_with_path_in_message(tmp_path: Path):
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(SpecLoadError) as exc_info:
        load_package(missing)
    assert str(missing) in str(exc_info.value)


def test_invalid_json_raises_spec_load_error(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json }", encoding="utf-8")
    with pytest.raises(SpecLoadError) as exc_info:
        load_package(bad)
    assert "Invalid JSON" in str(exc_info.value)


def test_missing_resources_key_raises_spec_load_error(tmp_path: Path):
    """A package missing 'resources' must raise SpecLoadError, not leak ValidationError."""
    no_resources = tmp_path / "no_resources.json"
    no_resources.write_text('{"name": "x", "title": "no resources"}', encoding="utf-8")
    with pytest.raises(SpecLoadError) as exc_info:
        load_package(no_resources)
    msg = str(exc_info.value)
    assert "resources" in msg
    # Pydantic-validation leak guard
    assert "ValidationError" not in type(exc_info.value).__name__


def test_top_level_array_raises(tmp_path: Path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SpecLoadError):
        load_package(arr)


def test_load_schema_invalid_json(tmp_path: Path):
    bad = tmp_path / "bad.schema.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(SpecLoadError):
        load_schema(bad)


def test_load_schema_dict_invalid_shape():
    """A dict missing 'fields' is not a valid table schema."""
    with pytest.raises(SpecLoadError):
        load_schema({"primaryKey": "id"})
