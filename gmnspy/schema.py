import json
import os

import pandas as pd

SCHEMA_TO_PANDAS_TYPES = {
    "integer": "int64",
    "number": "float",
    "string": "string",
    "any": "object",
}

FORMAT_TO_REGEX = {
    # https://emailregex.com/
    "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    # https://www.regextester.com/94092
    "uri": r"^\w+:(\/?\/?)[^\s]+$",
}


def read_schema(schema_file: str) -> dict:
    """
    Reads in schema from schema json file and returns as dictionary.

    ##TODO validate schema itself

    Args:
        schema_file: File location of the schema json file.

    Returns: The schema as a dictionary
    """
    with open(schema_file, encoding="utf-8") as f:
        schema = json.load(f)
    return schema


def read_config(config_file: str, data_dir: str = "", schema_dir: str = "") -> pd.DataFrame:
    """
    Reads a GMNS config file, adds some full paths and returns as a dataframe.

    Args:
        config_file: Configuration file. A json file with a list of "resources"
            specifying the "name", "path", and "schema" for each GMNS table as
            well as a boolean value for "required".
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
        data_dir: Directory where GMNS files are. If not specified, assumes
            the same directory as the config_file.
        schema_dir: Directory where GMNS schema files are. If not specified, assumes
            the same directory as the config_file.

    Returns: GMNS configuration file as a DataFrame.
    """
    with open(config_file, encoding="utf-8") as f:
        config = json.load(f)
    ## todo validate config
    resource_dict = {i["name"]: i for i in config["resources"]}
    # print(config["resources"])

    resource_df = pd.DataFrame(config["resources"])
    resource_df["required"].fillna(False, inplace=True)

    print(resource_df)

    # Add full paths to data files
    if not data_dir:
        data_dir = os.path.dirname(config_file)
    resource_df["fullpath"] = resource_df["path"].apply(
        lambda x: os.path.join(data_dir, x)
    )

    # Add full paths to data files
    if not schema_dir:
        schema_dir = os.path.dirname(config_file)
    resource_df["fullpath_schema"] = resource_df["schema"].apply(
        lambda x: os.path.join(schema_dir, x)
    )
    print(resource_df)

    resource_df.set_index("name", drop=False, inplace=True)
    return resource_df
