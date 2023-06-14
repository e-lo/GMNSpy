"""Functions used to read in GMNS files and networks.

Typical Usage:

    ```python
    read_gmns_csv('csv_file',validate=True)
    read_gmns_network('gmns_dir_path')
    ```
"""
import os
from pathlib import Path
from typing import Union

import pandas as pd

from gmnspy.utils import logger
from gmnspy.validation import (
    apply_schema_to_df,
    check_required_files,
    update_resources_based_on_existance,
    validate_foreign_keys,
)

from .schema import SpecConfig, json_from_path


def read_gmns_csv(
    filename: str,
    validate: bool = True,
    schema_path: Union[str, Path] = None,
    spec: SpecConfig = None,
    schema_name: str = None,
) -> pd.DataFrame:
    """
    Read csv and returns it as a dataframe.

    Optionally coerced to the types as specified in the data schema.

    Args:
        filename: file location of the csv file to read in.
        validate: boolean whether to apply the specified schema to the dataframe. Default is True.
        schema_path: file location of the schema to validate the file to, if supplied, will ignore
            spec and schema_name.
        spec: SpecConfig instance to use for validation. If spec supplied but not schema_file,
            will use the spec.  If neither spec or schema file supplied, will use official default
            spec.
        schema_name: If supplied and schema_file not supplied, will use to determine which schema
            to apply to file. If neither schema_file or schema_name supplied, will try to determine
            which schema to apply based on the filename.

    Returns: 
        Validated dataframe with coerced types according to schema.
    """
    df = pd.read_csv(filename)

    if not validate:
        logger.info(f"Not validating {filename}")
        return df

    schema_dict = None
    if schema_name is None:
        schema_name = os.path.split(filename)[-1].split(".")[0]
    if spec:
        schema_dict = spec.get_schema_as_dict(schema_name)

    df = apply_schema_to_df(df, schema_path=schema_path, schema_dict=schema_dict, schema_name=schema_name)

    return df


def read_gmns_network(
    data_directory: str, official_version: str = None, config_path: Union[str, Path] = None, raise_error:bool=False
) -> dict:
    """
    Read and validate each GMNS file as specified in the config or specified official version.

    Validation includes foreign keys between the tables.

    Args:
        data_directory: Directory where GMNS data is.
        official_version: if specified, will use the official version number or branch for
            the configuration.
        config_path: Configuration file. Path to a json file with a list of "resources"
            specifying the "name", "path", and "schema" for each GMNS table as
            well as a boolean value for "required". If not specified, assumes
            official version defaults specified in `.defaults`.
        raise_error: If true, raises error if missing folder

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
    config = SpecConfig(spec_source=config_path, official_version=official_version, data_dir=data_directory)
    gmns_net_dict = {}

    # check required files exist,
    check_required_files(config.resources_df, raise_error)

    # update resource dictionary based on what files are in the directory
    resources_df = update_resources_based_on_existance(config.resources_df)

    # read each csv to a df and validate format
    # todo add paired schema
    for _, row in resources_df.iterrows():
        gmns_net_dict[row["name"]] = read_gmns_csv(row["fullpath"])

    # validate foreign keys
    validate_foreign_keys(gmns_net_dict, resources_df, raise_error)

    return gmns_net_dict
