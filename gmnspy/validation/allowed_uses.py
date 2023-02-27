from typing import Dict

import pandas as pd
from gmnspy.utils.set_logger import logger


def check_allowed_uses(gmns_net_d: Dict[str, pd.DataFrame], raise_error):
    """
    Checks allowed_uses fields to make sure that they only contain values (or lists of
    values) which are defined in use_definition or use_group.

    Args:
        gmns_net_d: Dictionary containing dataframes of all the GMNS tables
            for the network keyed to their file names (i.e. "link").
        raise_error: Raises error if error found
    """

    allowable = list(gmns_net_d.get("use_definition", {}).get("use", [])) + list(
        gmns_net_d.get("use_group", {}).get("use_group", [])
    )
    if not allowable:
        logger.info("No enumeration specified for allowed_uses fields.")
        return

    for table_name, df in gmns_net_d.items():
        au_values = df.get("allowed_uses", pd.Series(dtype="object")).dropna()
        if au_values.empty:
            continue
        logger.debug(f"Checking allowed use values on {table_name} table")

        bad_au = au_values[~au_values.apply(lambda f: {s.strip() for s in f.lower().split(",")}.issubset(allowable))]
        if bad_au.empty:
            continue

        msg = f"FAIL. {set(bad_au)} include values outside of the use_definition or use_group names."
        logger.error(msg)
        if raise_error:
            raise Exception(msg)
