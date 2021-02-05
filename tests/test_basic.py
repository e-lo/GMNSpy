import os
import glob
import gmnspy
import pytest

base_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# https://github.com/zephyr-data-specs/GMNS/edit/master/Small_Network_Examples/Multiple_Bike_Facilities/road_link.csv

test_data = [
    "link",
    "geometry",
    "node",
    "use_definition",
    "use_group",
]
schemas = glob.glob("**/*.schema.json", recursive=True)


@pytest.mark.travis
def test_read_schema():
    schema_file = os.path.join(base_path, "spec", "link.schema.json")
    s = gmnspy.read_schema(schema_file)
    print(s)


@pytest.mark.travis
@pytest.mark.parametrize("test_data_name", test_data)
def test_validate_dfs(test_data_name):
    df = gmnspy.in_out.read_gmns_csv("tests/data/" + test_data_name + ".csv",)
    print(df[0:3])


@pytest.mark.travis
def test_validate_relationships():
    net = gmnspy.in_out.read_gmns_network(os.path.join(base_path, "tests", "data"))

@pytest.mark.travis
@pytest.mark.parametrize("schema_file", schemas)
def test_read_schema(schema_file):
    # schema_file = os.path.join(base_path, "spec", "link.schema.json")
    print("reading" + schema_file)
    s = gmnspy.read_schema(schema_file)
    s_md = gmnspy.list_to_md_table(s["fields"])
    print(s_md)

@pytest.mark.travis
def test_node_df_to_gdf():
    node_df = gmnspy.in_out.read_gmns_csv("tests/data/node.csv",)
    g = gmnspy.geometry_from_a_b(node_df,1,3)
    print(g)

@pytest.mark.travis
def test_node_df_to_gdf():
    node_df = gmnspy.in_out.read_gmns_csv("tests/data/node.csv",)
    node_gdf = gmnspy.gmns_to_gdf_node(node_df)
    print(node_gdf)
    import geopandas as gpd
    assert(type(node_gdf)==gpd.GeoDataFrame)

@pytest.mark.travis
def test_link_df_to_gdf():
    link_df = gmnspy.in_out.read_gmns_csv("tests/data/link.csv",)
    node_df = gmnspy.in_out.read_gmns_csv("tests/data/node.csv",)
    link_gdf = gmnspy.gmns_to_gdf_link(link_df, node_df = node_df)
    print(link_gdf)
    import geopandas as gpd
    assert(type(link_gdf)==gpd.GeoDataFrame)

@pytest.mark.travis
def test_net_to_gdf():
    net_dict = gmnspy.in_out.read_gmns_network(os.path.join(base_path, "tests", "data"))
    node_gdf,link_gdf = gmnspy.gmns_to_gdf(net_dict)
    print(node_gdf,link_gdf)
    import geopandas as gpd
    assert(type(link_gdf)==gpd.GeoDataFrame)
    assert(type(node_gdf)==gpd.GeoDataFrame)

@pytest.mark.travis
def test_net_to_osmnx():
    net_dict = gmnspy.in_out.read_gmns_network(os.path.join(base_path, "tests", "data"))
    node_gdf,link_gdf = gmnspy.gmns_to_gdf(net_dict)
    G = gmnspy.gmns_to_osmnx(node_gdf,link_gdf)
    print(G)

@pytest.mark.travis
@pytest.mark.elo
def test_modal_link_df_to_gdf():
    link_df = gmnspy.in_out.read_gmns_csv("tests/data/link.csv",)
    node_df = gmnspy.in_out.read_gmns_csv("tests/data/node.csv",)
    link_gdf = gmnspy.gmns_to_gdf_link(link_df, node_df = node_df, allowed_use="auto")
    print(link_gdf)
    import geopandas as gpd
    assert(type(link_gdf)==gpd.GeoDataFrame)

@pytest.mark.travis
@pytest.mark.elo
def test_modal_net_to_osmnx():
    net_dict = gmnspy.in_out.read_gmns_network(os.path.join(base_path, "tests", "data"))
    node_gdf,link_gdf = gmnspy.gmns_to_gdf(net_dict, allowed_use="bike")
    G = gmnspy.gmns_to_osmnx(node_gdf,link_gdf)
    print(G)
