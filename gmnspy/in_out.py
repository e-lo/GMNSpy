from os.path import join, dirname, realpath

import pandas as pd

from gmnspy.utils import logger
from gmnspy.validation import validate_foreign_keys, check_required_files, apply_schema_to_df
from gmnspy.validation import check_allowed_uses, update_resources_based_on_existance
from .schema import read_config

spec_folder = join(dirname(realpath(__file__)), "spec")


def read_gmns_csv(filename: str, validate: bool = True, schema_file: str = None) -> pd.DataFrame:
    """
    Reads csv and returns it as a dataframe; optionally coerced to the
    types as specified in the data schema.

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
    Reads each GMNS file as specified in the config and validates it to
    their specified schema including foreign keys between the tables.

    Args:
        data_directory: Directory where GMNS data is.
        config: Configuration file. A json file with a list of "resources"
            specifying the "name", "path", and "schema" for each GMNS table as
            well as a boolean value for "required". If not specified, assumes
            it is in a subdirectory "spec/gmns.spec.json"
        raise_error: Raises error if error found

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
    for _, row in resource_df.iterrows():
        gmns_net_d[row["name"]] = read_gmns_csv(row["fullpath"], schema_file=row["fullpath_schema"])

    # validate foreign keys
    validate_foreign_keys(gmns_net_d, resource_df, raise_error)

    # check allowed uses
    check_allowed_uses(gmns_net_d, raise_error)

    return gmns_net_d
