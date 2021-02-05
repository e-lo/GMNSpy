def osmnx_to_gmns():
    pass


def gmns_to_gdf(gmns_dict: dict, espg: int = 4326, allowed_use: str = '') :
    """
    Converts a dictionary of gmns dataframes to a dictionary of
    geodataframes where relevant.

    Args:
        gmns_dict: dictionary of gmns dataframes keyed by their name (i.e. "node")
        espg: the coordinate system in espg format (default: 4326 which is WGS 84). See: https://epsg.io for other systems.

    Returns:
        tuple of node geodataframe and link geodataframe
    """

    node_gdf = gmns_to_gdf_node(gmns_dict["node"], espg=espg)

    link_gdf = gmns_to_gdf_link(
        gmns_link_df=gmns_dict["link"],
        geometry_df=gmns_dict.get(
            "geometry", pd.DataFrame(columns=["geometry_id", "geometry"])
        ),
        espg=espg,
        allowed_use = allowed_use,
    )
    return node_gdf,link_gdf


def gmns_to_gdf_node(gmns_node_df: pd.DataFrame, espg: int = 4326)->gpd.GeoDataFrame:
    """
    Converts a GMNS formatted node dataframe into a GeoPandas dataframe.

    Does following steps:
    1. Converts geometry to a Shapely Point from x_coord and y_coord
    2. Converts dataframe to GeoDataFrame
    3. Denotes GeoDataFrame CRS (coordinate system) and name.

    Args:
        gmns_node_df: gmns formatted node GeoDataFrame
        espg: the coordinate system in  espg format (see espg.io). Default  =  4326 which is WGS 84

    Returns: a GeoDataFrame of nodes
    """
    print("converting node to gdf")
    node_gdf = gpd.GeoDataFrame(
        gmns_node_df,
        geometry=gpd.points_from_xy(gmns_node_df.x_coord, gmns_node_df.y_coord),
    )
    node_gdf.crs = espg
    node_gdf.gdf_name = "network_nodes"
    return node_gdf

def geometry_from_a_b(node_df: pd.DataFrame, A, B, geometry=np.nan)->LineString:
    """
    Creates a straightline geometry from the a coordinate and b coordinate.

    Args:
        node_df: gmns node dataframe
        A: start node_id
        B: end node_id

    Returns: a shapely LineString instance
    """
    if not np.isnan(geometry):
        return geometry

    ##todo good error checking
    A_geom = (node_df.loc[node_df['node_id']==A,'x_coord'].iloc[0], node_df.loc[node_df['node_id']==A,'y_coord'].iloc[0])
    B_geom = (node_df.loc[node_df['node_id']==B,'x_coord'].iloc[0], node_df.loc[node_df['node_id']==B,'y_coord'].iloc[0])
    linestring = LineString([A_geom,B_geom])
    return linestring

def geometry_strings_to_shapely_linestring(geo_string: str)->LineString:
    """
    Convert a string into a shapely LineString instance by trying several
    formats including WKT and strings of LineString.

    Args:
        geo_string: string representing geometry in well known text (wkt) or something that can be converted to a LineString

    Returns: A shapely linestring instance
    """
    print("GEOSTRING: {}".format(geo_string))
    if not geo_string:
        return geo_string

    if type(geo_string)==LineString:
        return geostring

    try:
        feature_shape = loads(geo_string)
    except:
        feature_shape = LineString(geo_string)

    if type(feature_shape)==LineString:
        return feature_shape

    msg = "Not a recognized geometry type: {}".format(geo_string)
    print(msg)
    ValueError(msg)

def gmns_to_gdf_link(
    gmns_link_df: pd.DataFrame,
    geometry_df: pd.DataFrame = pd.DataFrame(columns=["geometry_id", "geometry"]),
    node_df: pd.DataFrame = pd.DataFrame(columns=["node_id","x_coord","y_coord"]),
    espg: int = 4326,
    allowed_use:str = None,
)->gpd.GeoDataFrame:
    """
    Converts a GMNS formatted link dataframe into a GeoPandas dataframe.

    Including the following steps:
    1. Convert any columns with lists into dummy variable columns
    2. Add any geometry from geometry table or create geometry from AB nodes and convert to shapely linestrings
    3. Convert DataFrame to GeoDataFrame
    4. Add coordinate system.

    Args:
        gmns_link_df: gmns link DataFrame
        geometry_df: if have geometry to add to links that isn't in link table, can add a geometry dataframe
        node_df: for adding in missing geometries based on A and B node locations
        espg: the coordinate system in  espg format (see espg.io). Default  =  4326 which is WGS 84
        allowed_uses: if noted, will only use links that allow this use (i.e. "auto")

    Returns: A link GeoDataFrame
    """
    print("converting link to gdf")

    # 1. get rid of any columns with lists and convert them to dummy variable columns
    dummy_allowed_uses_df = convert_list_column_to_dummies(
        gmns_link_df["allowed_uses"].apply(lambda x: x.split(","))
    )
    # if we decide it is better to make a "long" df with dupe rows for each mode, this is how we would do it
    # exploded_df = gmns_link_df.explode('allowed_uses_list').dropna(subset=['allowed_uses_list'])

    _df_all = pd.concat([gmns_link_df, dummy_allowed_uses_df], axis=1)
    # 1a. select the links with
    if allowed_use:
        print("Filtering on: {}".format(allowed_use))
        _df = _df_all.loc[_df_all[allowed_use],:]
        if not len(_df.shape):
            msg = "Nothing left after filtering on allowed use: {}".filter(allowed_use)
            ValueError(msg)
        print("df2",_df)
    else:
        _df = _df_all

    # 2. get updated geometry from geometry dataframe if it is NA
    if "geometry" not in _df.columns: _df["geometry"]=np.nan

    _df_geometry = _df.merge(
        geometry_df, how="left", on="geometry_id", suffixes=("_L", "_G")
    )

    _df_geometry["geometry_txt"] = _df_geometry["geometry_L"].fillna(
        _df_geometry["geometry_G"]
    )

    _df_geometry["geometry"]=_df_geometry["geometry_txt"].apply(lambda x: geometry_strings_to_shapely_linestring(x))
    _df_geometry = _df_geometry.drop(columns=["geometry_L", "geometry_G","geometry_txt"])

    # fill NA values with crow-fly
    na_geom = np.isnan(_df_geometry["geometry"]).sum()
    print("Remaining NA values after joining geometry table: {}".format(na_geom))

    if na_geom:
        print("Calculating remaining geometry using crow-fly lines from A node to B node")

        _df_geometry["geometry"] = _df_geometry.apply(
            lambda row: geometry_from_a_b(node_df,row['from_node_id'],row['to_node_id'],row["geometry"]),
            axis=1,
        )

    # 3. Create GeoDataframe
    link_gdf = gpd.GeoDataFrame(_df_geometry, geometry=_df_geometry["geometry"])

    # 4. make sure coordinate reference system is noted.
    link_gdf.crs = espg

    return link_gdf


def convert_list_column_to_dummies(s: pd.Series) -> pd.DataFrame:
    """
    This is useful for converting things like `allowed_uses` because lists aren't allowed in things like GDFs, GeoJson, or networkxx

    Args:
        s: a series of lists

    Returns: a dataframe
    """
    df = pd.get_dummies(s.apply(pd.Series), prefix="", prefix_sep="").sum(
        level=0, axis=1
    )
    return df


def gmns_to_osmnx(gdf_nodes: gpd.GeoDataFrame, gdf_edges: gpd.GeoDataFrame):
    """
    Converts geodataframes for nodes and links to a networkx network graph

    Args:
        gdf_nodes: geodataframe of network nodes
        gdf_edges: geodataframe of network edges

    Returns: an osmnx flavored network-x graph

    """
    from osmnx import graph_from_gdfs

    graph_nodes = gdf_nodes.rename(columns={"node_id":"id"})

    # have to change this over into u,v b/c this is what osm-nx is expecting
    graph_edges = gdf_edges.copy()
    graph_edges["u"] = graph_edges["from_node_id"]
    graph_edges["v"] = graph_edges["to_node_id"]
    graph_edges["id"] = graph_edges["link_id"]
    graph_edges["key"] = graph_edges["link_id"]

    G = graph_from_gdfs(graph_nodes, graph_edges)
    return G
