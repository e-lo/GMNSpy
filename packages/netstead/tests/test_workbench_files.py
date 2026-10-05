"""Tests for the workbench server-side file browser."""

import pytest
from netstead.config import Settings
from netstead.workbench.errors import PathNotAllowed
from netstead.workbench.files import detect_kind, list_dir


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "gmns_csv").mkdir()
    (tmp_path / "gmns_csv" / "link.csv").write_text("link_id\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "datapackage.json").write_text("{}")
    (tmp_path / "ovt").mkdir()
    for name in ("segment.parquet", "connector.parquet"):
        (tmp_path / "ovt" / name).write_bytes(b"")
    (tmp_path / "plain").mkdir()
    for name in ("net.zip", "net.duckdb", "extract.osm", "export.json", "notes.txt", ".hidden"):
        (tmp_path / name).write_text("")
    return tmp_path


def _settings(root):
    return Settings.model_validate({"io": {"allowed_roots": [str(root)]}})


def test_detect_kind(tree):
    kinds = {p.name: detect_kind(p) for p in tree.iterdir()}
    assert kinds == {
        "gmns_csv": "gmns",
        "pkg": "gmns",
        "ovt": "overture",
        "plain": None,
        "net.zip": "zip",
        "net.duckdb": "duckdb",
        "extract.osm": "osm",
        "export.json": "json",
        "notes.txt": None,
        ".hidden": None,
    }
    assert detect_kind(tree / "pkg" / "datapackage.json") == "datapackage"


def test_list_dir_folders_first_hidden_skipped(tree):
    listing = list_dir(str(tree), _settings(tree))
    names = [e["name"] for e in listing["entries"]]
    assert names == [
        "gmns_csv",
        "ovt",
        "pkg",
        "plain",
        "export.json",
        "extract.osm",
        "net.duckdb",
        "net.zip",
        "notes.txt",
    ]
    assert listing["parent"] is None and listing["truncated"] is False


def test_datapackage_file_targets_its_folder(tree):
    (entry,) = list_dir(str(tree / "pkg"), _settings(tree))["entries"]
    assert entry["kind"] == "datapackage" and entry["target"] == str((tree / "pkg").resolve())


def test_subfolder_has_parent(tree):
    assert list_dir(str(tree / "plain"), _settings(tree))["parent"] == str(tree.resolve())


def test_no_path_lists_roots(tree):
    listing = list_dir(None, _settings(tree))
    assert [e["path"] for e in listing["entries"]] == [str(tree.resolve())]


def test_outside_roots_rejected(tree, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    with pytest.raises(PathNotAllowed):
        list_dir(str(other), _settings(tree))


def test_missing_and_file_paths(tree):
    with pytest.raises(FileNotFoundError):
        list_dir(str(tree / "nope"), _settings(tree))
    with pytest.raises(NotADirectoryError):
        list_dir(str(tree / "net.zip"), _settings(tree))
