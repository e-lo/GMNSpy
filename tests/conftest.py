import glob

from os.path import join, dirname, realpath

import pytest

import gmnspy


@pytest.fixture(scope="session")
def test_data_path():
    test_data_path = join(dirname(realpath(__file__)), "data")
    return test_data_path


@pytest.fixture(scope="session")
def base_path():
    base_path = dirname(dirname(realpath(__file__)))
    return base_path


@pytest.fixture(scope="session")
def link_schema_path(base_path):
    link_schema_path = join(base_path, "gmnspy", "spec", "link.schema.json")
    return link_schema_path


@pytest.fixture(scope="session")
def example_nodes_df(test_data_path):
    node_data_path = join(test_data_path, "node.csv")
    nodes_df = gmnspy.in_out.read_gmns_csv(node_data_path)
    return nodes_df


@pytest.fixture(scope="session")
def example_links_df(test_data_path):
    link_data_path = join(test_data_path, "link.csv")
    links_df = gmnspy.in_out.read_gmns_csv(link_data_path)
    return links_df


@pytest.fixture(scope="session")
def example_gmns_net(test_data_path):
    gmns_dict = gmnspy.in_out.read_gmns_network(test_data_path)
    return gmns_dict
