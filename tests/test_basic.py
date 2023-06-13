import glob
import logging
from os.path import dirname, join, realpath

import frictionless
import pytest

import gmnspy

base_path = dirname(dirname(realpath(__file__)))
logger = logging.getLogger()


test_data = [
    "link",
    "geometry",
    "node",
    "use_definition",
    "use_group",
]


test_pth = join(dirname(realpath(__file__)), "data")
local_schemas = glob.glob("../gmnspy/**/*.schema.json", recursive=True)


@pytest.mark.parametrize("schema_path", local_schemas)
def test_local_schema(schema_path):
    _ = frictionless.Schema(schema_path)


def test_read_local_spec():
    local_spec = gmnspy.SpecConfig(gmnspy.defaults.LOCAL_SPEC)
    assert local_spec._location_type == "local"


def test_read_validate_local_spec():
    local_spec = gmnspy.SpecConfig(gmnspy.defaults.LOCAL_SPEC)
    assert local_spec.schema_errors == []


def test_read_official_spec():
    official_spec = gmnspy.SpecConfig()
    logger.info(f"Spec Location: {official_spec._spec_source.github_file_url}")
    logger.info(f"official_spec.resources_df:\n{official_spec.resources_df}")
    assert official_spec._location_type == "github"
    assert official_spec.version == "master"


def test_read_remote_version_spec():
    version = "development"
    official_spec = gmnspy.SpecConfig(official_version=version)
    assert official_spec._location_type == "github"
    assert official_spec.version == version


@pytest.mark.parametrize("test_data_name", test_data)
def test_validate_dfs_local_spec(test_data_name):
    _ = gmnspy.in_out.read_gmns_csv(join(test_pth, f"{test_data_name}.csv"))


@pytest.mark.parametrize("test_data_name", test_data)
def test_validate_dfs_official_spec(test_data_name):
    _ = gmnspy.in_out.read_gmns_csv(join(test_pth, f"{test_data_name}.csv"))

@pytest.mark.menow
def test_validate_example_network_local_spec():
    from gmnspy.defaults import LOCAL_SPEC
    _ = gmnspy.in_out.read_gmns_network(join(base_path, "tests", "data"), config_path=LOCAL_SPEC)


def test_validate_example_network_official_spec():
    _ = gmnspy.in_out.read_gmns_network(join(base_path, "tests", "data"))
