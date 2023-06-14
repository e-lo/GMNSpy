"""Functions used to read in GMNS files and networks.

Typical Usage:

    ```python
    read_gmns_csv('csv_file',validate=True)
    read_gmns_network('gmns_dir_path')
    ```
"""

from os.path import dirname, join, realpath

import pandas as pd

from gmnspy.utils import logger
from gmnspy.validation import (
    apply_schema_to_df,
    check_required_files,
    update_resources_based_on_existance,
    validate_foreign_keys,
)

from .schema import read_config

spec_folder = join(dirname(realpath(__file__)), "spec")


def read_gmns_csv(filename: str, validate: bool = True, schema_file: str = None) -> pd.DataFrame:
    """
    Read csv and returns it as a dataframe.

    Optionally coerced to the types as specified in the data schema.

    Args:
        filename: file location of the csv file to read in.
        validate: boolean whether to apply the specified schema to the dataframe. Default is True.
        schema_file: file location of the schema to validate the file to.

    Returns: Validated dataframe with coerced types according to schema.
    """
    df = pd.read_csv(filename)

    if validate:
        apply_schema_to_df(df, schema_file=schema_file, originating_file=filename)
    else:
        logger.info(f"not validating {filename}")

    return df


def read_gmns_network(data_directory: str, config: str = None, raise_error=False) -> dict:
    """
    Read and validate each GMNS file as specified in the config.

    Validation includes foreign keys between the tables.

    Args:
        data_directory: Directory where GMNS data is.
        config: Configuration file. A json file with a list of "resources"
            specifying the "name", "path", and "schema" for each GMNS table as
            well as a boolean value for "required". If not specified, assumes
            it is in a subdirectory "spec/gmns.spec.json"
        raise_error: Raises error if missing folder

            Example:
            ::
                {
                  "resources": [
                   {
                     "name":"link",
                     "path": "link.csv",
                     "schema": "link.schema.json",
                     "required": true
                   },
                   {
                     "name":"node",
                     "path": "node.csv",
                     "schema": "node.schema.json",
                     "required": true
                   }
                 }
    returns: a dictionary mapping the name of each GMNS table to a
        validated dataframe.
    """
    config = config or join(spec_folder, "gmns.spec.json")
    gmns_net_d = {}

    resource_df = read_config(config, data_dir=data_directory) if config else 1

    # check required files exist,
    check_required_files(resource_df, raise_error)

    # update resource dictionary based on what files are in the directory
    resource_df = update_resources_based_on_existance(resource_df)

    # read each csv to a df and validate format
    # todo add paired schema
    for _, row in resource_df.iterrows():
        gmns_net_d[row["name"]] = read_gmns_csv(row["fullpath"])

    # validate foreign keys
    validate_foreign_keys(gmns_net_d, resource_df, raise_error)

    return gmns_net_d
