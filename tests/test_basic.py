import glob
import os

import pytest

import geopandas as gpd

import gmnspy
from gmnspy.utils import logger


# https://github.com/zephyr-data-specs/GMNS/edit/master/Small_Network_Examples/Multiple_Bike_Facilities/road_link.csv

test_data = [
    "link",
    "geometry",
    "node",
    "use_definition",
    "use_group",
]


def test_read_schema(schema_file_path):
    _ = gmnspy.read_schema(schema_file_path)


@pytest.mark.parametrize("test_data_name", test_data)
def test_validate_dfs(test_data_name, test_data_path):
    _ = gmnspy.in_out.read_gmns_csv(os.path.join(test_data_path, f"{test_data_name}.csv"))


def test_validate_relationships(test_data_path):
    _ = gmnspy.in_out.read_gmns_network(test_data_path)


schemas = glob.glob("../gmnspy/**/*.schema.json", recursive=True)


@pytest.mark.parametrize("schema_file", schemas)
def test_read_schema2(schema_file):
    # schema_file = join(base_path, "spec", "link.schema.json")
    s = gmnspy.read_schema(schema_file)
    _ = gmnspy.list_to_md_table(s["fields"])


def test_node_df_to_gdf(example_nodes_df):
    g = gmnspy.geometry_from_a_b(example_nodes_df, 1, 3)
    logger.debug(g)


def test_node_df_to_gdf(example_nodes_df):
    node_gdf = gmnspy.conversions.geopandas.gmns_to_gdf_node(example_nodes_df)
    logger.debug(node_gdf)
    assert type(node_gdf) == gpd.GeoDataFrame


def test_link_df_to_gdf(example_nodes_df, example_links_df):
    link_gdf = gmnspy.conversions.geopandas.gmns_to_gdf_link(example_links_df, node_df=example_nodes_df)
    logger.debug(link_gdf)
    assert type(link_gdf) == gpd.GeoDataFrame


def test_net_to_gdf(example_gmns_net):
    node_gdf, link_gdf = gmnspy.conversions.gmns_to_gdf(example_gmns_net)
    logger.debug(node_gdf, link_gdf)
    assert type(link_gdf) == gpd.GeoDataFrame
    assert type(node_gdf) == gpd.GeoDataFrame


def test_net_to_graph(example_gmns_net):
    G = gmnspy.conversions.gmns_to_graph(example_gmns_net)
    logger.debug(G)


def test_modal_link_df_to_gdf(example_nodes_df, example_links_df):
    link_gdf = gmnspy.conversions.geopandas.gmns_to_gdf_link(
        example_links_df, node_df=example_nodes_df, allowed_use="auto"
    )
    logger.debug(link_gdf)

    assert type(link_gdf) == gpd.GeoDataFrame


def test_modal_net_to_graph(example_gmns_net):
    G = gmnspy.conversions.gmns_to_graph(example_gmns_net, allowed_use="bike")
    logger.debug(G)
