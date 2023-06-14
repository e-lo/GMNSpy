"""Function which establishes which GMNS resources are present."""

from os.path import exists

import pandas as pd

from gmnspy.utils.set_logger import logger


def update_resources_based_on_existance(resource_df: pd.DataFrame) -> pd.DataFrame:
    """
    Update resource dataframe based on which files exist in the directory.

    Args:
        resource_df:Dataframe with a row for each GMNS table including
            the the columns "fullpath" and "name".

    Returns: Updated version of resource dataframe without non-existant
        files.
    """
    updated_resource_df = resource_df[resource_df["fullpath"].apply(lambda x: exists(x))]

    logger.info(f"""Found following files to define network: \n - {updated_resource_df["name"].to_list()}""")
    return updated_resource_df
