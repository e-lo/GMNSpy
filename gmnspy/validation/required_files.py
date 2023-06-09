"""Functions which test GMNS file requirement constraints."""

from os.path import exists

import pandas as pd

from gmnspy.utils import logger


def check_required_files(resource_df: pd.DataFrame, raise_error=False) -> None:
    """
    Check required files exist. Will fail if they don't.

    Args:
        resource_df: Dataframe with a row for each GMNS table including
            the the columns "fullpath", "name", and "required" (boolean).
        raise_error: Raises error if missing folder
    """
    req_files = resource_df[resource_df["required"]]

    missing_required_files = req_files[req_files["fullpath"].apply(lambda x: not exists(x))][["name", "fullpath"]]

    if not missing_required_files.shape[0]:
        return

    if raise_error:
        msg = f"FAIL Missing Required Files: {missing_required_files}"
        logger.error(msg)
        raise Exception(msg)
