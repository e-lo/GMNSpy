import glob
from os.path import dirname, join, realpath

import pytest

import gmnspy

base_path = dirname(dirname(realpath(__file__)))

# https://github.com/zephyr-data-specs/GMNS/edit/master/Small_Network_Examples/Multiple_Bike_Facilities/road_link.csv

test_data = [
    "link",
    "geometry",
    "node",
    "use_definition",
    "use_group",
]
schemas = glob.glob("../gmnspy/**/*.schema.json", recursive=True)
test_pth = join(dirname(realpath(__file__)), "data")


def test_read_schema():
    schema_file = join(base_path, "gmnspy", "spec", "link.schema.json")
    _ = gmnspy.read_schema(schema_file)


@pytest.mark.parametrize("test_data_name", test_data)
def test_validate_dfs(test_data_name):
    _ = gmnspy.in_out.read_gmns_csv(join(test_pth, f"{test_data_name}.csv"))


def test_validate_relationships():
    _ = gmnspy.in_out.read_gmns_network(join(base_path, "tests", "data"))


@pytest.mark.parametrize("schema_file", schemas)
def test_read_schema2(schema_file):
    # schema_file = join(base_path, "spec", "link.schema.json")
    s = gmnspy.read_schema(schema_file)
    _ = gmnspy.list_to_md_table(s["fields"])
