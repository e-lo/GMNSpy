import geopandas as gpd
from osmnx import graph_from_gdfs

from .geopandas import gmns_to_gdf

from gmnspy.utils import logger


def gmns_to_graph(gmns_dict: dict, espg: int = 4326, allowed_use: str = ""):
    """Converts a GMNS dictionry to a NetworkX graph using OSMNX.

    Args:
        gmns_dict: dictionary of gmns dataframes keyed by their name (i.e. "node")
        espg: the coordinate system in espg format. Defaults 4326 which is WGS 84.
            See: https://epsg.io for other systems.

    Returns:
        nx.MultiDiGraph: NetworkX Graph
    """

    nodes_gdf, links_gdf = gmns_to_gdf(gmns_dict, espg=espg, allowed_use=allowed_use)
    G = gdf_to_graph(nodes_gdf, links_gdf)

    return G


def gdf_to_graph(gdf_nodes: gpd.GeoDataFrame, gdf_edges: gpd.GeoDataFrame):
    """
    Converts geodataframes for nodes and links to a networkx network graph
    Args:
        gdf_nodes: geodataframe of network nodes
        gdf_edges: geodataframe of network edges
    Returns: an osmnx flavored network-x graph
    """

    graph_nodes = gdf_nodes.rename(columns={"node_id": "id"})
    # have to change this over into u,v b/c this is what osm-nx is expecting
    graph_edges = gdf_edges.copy()
    graph_edges["u"] = graph_edges["from_node_id"]
    graph_edges["v"] = graph_edges["to_node_id"]
    graph_edges["id"] = graph_edges["link_id"]
    graph_edges["key"] = graph_edges["link_id"]
    G = graph_from_gdfs(graph_nodes, graph_edges)
    return G
