"""Functions which test GMNS foreign key constraints."""

from typing import Dict

import pandas as pd

from gmnspy.schema import read_schema
from gmnspy.utils import logger


def validate_foreign_keys(gmns_net_d: Dict[str, pd.DataFrame], resource_df: pd.DataFrame, raise_error) -> None:
    """
    Validate foreign keys for each GMNS table.

    Finds foreign keys in schemas of each GMNS table and validates that
    they link to a valid series which has (1) unique IDs, and (2) contains
    the values of the referring series.

    Args:
        gmns_net_d: Dictionary containing dataframes of all the GMNS tables
            for the network keyed to their file names (i.e. "link").
        resource_df:Dataframe with a row for each GMNS table which contains
            the field "fullpath_schema" for the schema locations for
            each GMNS table which is where foreign keys are specified.
        raise_error: Raises error if found
    """
    logger.info(gmns_net_d["node"]["node_id"])

    fkey_errors = []
    for table_name, df in gmns_net_d.items():
        schema = read_schema(schema_file=resource_df[resource_df["name"] == table_name]["fullpath_schema"][0])

        foreign_keys = [
            (f["name"], f["foreign_key"])
            for f in schema["fields"]
            if (f.get("foreign_key") and f["name"] in df.columns)
        ]
        logger.debug("FKEYS: ", foreign_keys)

        # find the series for the foreign keyl
        for field, f_key in foreign_keys:
            # NOTE this requires that field names that are foreign keys not have '.'
            t, f = f_key.split(".")
            if not t:
                reference_s = df[f]
            else:
                reference_s = gmns_net_d.get(t, {}).get(f, None)
                if reference_s is None:
                    msg = f"FAIL. {f} field in table {t} does not exist"
                    logger.error(msg)
                    if raise_error:
                        raise Exception(msg)
                    continue
            fkey_errors += validate_foreign_key(df[field], reference_s, raise_error)


def validate_foreign_key(source_s: pd.Series, reference_s: pd.Series, raise_error: bool) -> list:
    """
    Validate foreign keys of single pair of source and reference series.

    Checks that the source_s series links to a valid reference_s series
        which has (1) unique IDs, and (2) contains the values of the
        referring series.

    source_s: series containing values that reference foreign key values in reference_s.
    reference_s: series of foreign key values.
    raise_error: Raises error if found

    Returns: a list of error messages.
    """
    fkey_errors = []
    # Make sure reference_s is unique
    dupes = reference_s.dropna().duplicated()
    if dupes.any():
        msg = "FAIL. Duplicates exist in foreign key series: {}".format(dupes)
        logger.error(msg)
        if raise_error:
            raise Exception(msg)
        fkey_errors.append(msg)

    # Make sure all source have a valid reference
    if not source_s.isin(reference_s.dropna().to_list()).any():
        msg = "FAIL. {} not in foreign key reference.".format(source_s[source_s.isin(reference_s.dropna().to_list())])
        logger.error(msg)
        if raise_error:
            raise Exception(msg)
        fkey_errors.append(msg)
    return fkey_errors
