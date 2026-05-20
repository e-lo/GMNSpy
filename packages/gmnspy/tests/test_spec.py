"""Tests for :mod:`gmnspy.spec` (task 3.6 / issue #74).

Covers:
    * Module constants ``SUPPORTED_SPECS`` and ``DEFAULT_SPEC``.
    * :func:`gmnspy.spec.get_spec_path` for each supported version
      and rejection of unsupported versions.
    * :func:`gmnspy.spec.load_gmns_spec` for each supported version,
      including version-specific structural differences (notably
      ``shared_categories.json`` shows up in 0.97 but not 0.95) and
      that foreign-key declarations on the link schema parse to
      :class:`datagrove.spec.ForeignKey` instances.
    * Re-export through the top-level :mod:`gmnspy` package.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from datagrove.spec import DataPackage, ForeignKey


def test_supported_specs_constant():
    """``SUPPORTED_SPECS`` is exactly the three vendored versions."""
    from gmnspy.spec import SUPPORTED_SPECS

    assert SUPPORTED_SPECS == ("0.95", "0.96", "0.97")


def test_default_spec_is_latest_supported():
    """``DEFAULT_SPEC`` is 0.97 — the architecture-doc default."""
    from gmnspy.spec import DEFAULT_SPEC, SUPPORTED_SPECS

    assert DEFAULT_SPEC == "0.97"
    assert DEFAULT_SPEC in SUPPORTED_SPECS


@pytest.mark.parametrize("version", ["0.95", "0.96", "0.97"])
def test_get_spec_path_points_at_vendored_dir(version: str):
    """Each supported version resolves to its on-disk spec directory."""
    from gmnspy.spec import get_spec_path

    path = get_spec_path(version)
    assert isinstance(path, Path)
    assert path.is_dir()
    assert path.name == version
    # Every version ships per-resource schema files.
    assert (path / "link.schema.json").is_file()


def test_get_spec_path_default_is_default_spec():
    """Calling ``get_spec_path()`` with no args returns the default version."""
    from gmnspy.spec import DEFAULT_SPEC, get_spec_path

    assert get_spec_path().name == DEFAULT_SPEC


def test_get_spec_path_rejects_unsupported_version():
    """Versions not in ``SUPPORTED_SPECS`` raise ``ValueError``."""
    from gmnspy.spec import get_spec_path

    with pytest.raises(ValueError, match=r"0\.42"):
        get_spec_path("0.42")


@pytest.mark.parametrize("version", ["0.95", "0.96", "0.97"])
def test_load_gmns_spec_returns_datapackage_with_resources(version: str):
    """Every supported version loads as a ``DataPackage`` with resources."""
    from gmnspy.spec import load_gmns_spec

    pkg = load_gmns_spec(version)
    assert isinstance(pkg, DataPackage)
    # GMNS ships ~25 resources at every version; assert a sane lower bound.
    assert len(pkg.resources) >= 20
    names = {r.name for r in pkg.resources}
    # Core tables present in every version.
    assert {"link", "node"}.issubset(names)


def test_load_gmns_spec_default_loads_0_97():
    """No-arg call loads the default version."""
    from gmnspy.spec import DEFAULT_SPEC, load_gmns_spec

    pkg = load_gmns_spec()
    pkg_default = load_gmns_spec(DEFAULT_SPEC)
    # Same set of resources.
    assert {r.name for r in pkg.resources} == {r.name for r in pkg_default.resources}


def test_load_gmns_spec_rejects_unsupported_version():
    """Unsupported versions raise ``ValueError``."""
    from gmnspy.spec import load_gmns_spec

    with pytest.raises(ValueError):
        load_gmns_spec("0.42")


def test_shared_categories_is_0_97_only():
    """``shared_categories.json`` is a 0.97 addition — assert presence/absence."""
    from gmnspy.spec import get_spec_path

    assert (get_spec_path("0.97") / "shared_categories.json").is_file()
    assert not (get_spec_path("0.96") / "shared_categories.json").exists()
    assert not (get_spec_path("0.95") / "shared_categories.json").exists()


@pytest.mark.parametrize("version", ["0.96", "0.97"])
def test_load_gmns_spec_link_foreign_keys_parse(version: str):
    """0.96+ declares FKs on link → node; assert they parse to ForeignKey.

    0.95 predates FK declarations in the vendored schemas — its
    structural integrity check is covered by ``test_v095_has_no_fks``
    below so the version-specific gap is asserted, not silently
    tolerated.
    """
    from gmnspy.spec import load_gmns_spec

    pkg = load_gmns_spec(version)
    link = next(r for r in pkg.resources if r.name == "link")
    assert link.table_schema is not None
    # Stringly-typed schema refs must have been resolved by the loader.
    schema = link.table_schema
    assert not isinstance(schema, str), "loader did not resolve schema ref"
    fks = schema.foreign_keys
    assert any(isinstance(fk, ForeignKey) for fk in fks), "no parsed ForeignKey on link"
    # The link schema FKs all target the node table (from_node_id, to_node_id).
    node_targets = [fk for fk in fks if fk.reference.resource == "node"]
    assert node_targets, "expected FK on link referencing node"


def test_v095_has_no_fks_on_link():
    """0.95 deliberately ships no foreign-key declarations; assert that.

    Pins the version-specific structural difference so future imports
    of an updated 0.95 don't silently change behavior.
    """
    from gmnspy.spec import load_gmns_spec

    pkg = load_gmns_spec("0.95")
    link = next(r for r in pkg.resources if r.name == "link")
    schema = link.table_schema
    assert not isinstance(schema, str)
    assert schema is not None
    assert schema.foreign_keys == []


def test_reexports_from_top_level():
    """Top-level ``gmnspy`` package re-exports the public spec surface."""
    import gmnspy

    assert gmnspy.SUPPORTED_SPECS == ("0.95", "0.96", "0.97")
    assert gmnspy.DEFAULT_SPEC == "0.97"
    assert callable(gmnspy.load_gmns_spec)
    assert callable(gmnspy.get_spec_path)
