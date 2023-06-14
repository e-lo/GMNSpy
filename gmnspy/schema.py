"""
Functions related to Frictionless Data Schemas for GMNS.

Typical usage:

    ```python
    read_schema(schema_file)
    read_config(config_file)
    document_schemas_to_md(schema_file_dir)
    document_spec_to_md(spec_file)
    ```
"""

import glob
import json
from os.path import dirname, join, realpath
from pathlib import Path

import frictionless
import pandas as pd

from .utils import list_to_md_table, logger

SCHEMA_TO_PANDAS_TYPES = {
    "integer": "int64",
    "number": "float",
    "string": "string",
    "any": "object",
    "boolean": "bool",
}

FORMAT_TO_REGEX = {
    # https://emailregex.com/
    "email": r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    # https://www.regextester.com/94092
    "uri": r"^\w+:(\/?\/?)[^\s]+$",
}


def read_schema(schema_file: str) -> dict:
    """
    Read in schema from schema json file and returns as dictionary.

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
    Read a GMNS config file, adds some full paths and returns as a dataframe.

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
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    ## todo validate config

    resource_df = pd.DataFrame(config["resources"])
    resource_df["required"].fillna(False, inplace=True)

    logger.info(str(resource_df))

    # Add full paths to data files
    if not data_dir:
        data_dir = dirname(config_file)
    resource_df["fullpath"] = resource_df["path"].apply(lambda x: join(data_dir, x))

    # Add full paths to data files
    if not schema_dir:
        schema_dir = dirname(config_file)
    resource_df["fullpath_schema"] = resource_df["schema"].apply(lambda x: join(schema_dir, x))
    logger.info(str(resource_df))

    resource_df.set_index("name", drop=False, inplace=True)
    return resource_df


def document_schemas_to_md(schema_path: str = None, out_path: str = None) -> str:
    """Create markdown for each **.schema.json file in schema_path.

    Args:
        schema_path (str, optional): Path fo tlook for schema files.
            Defaults to join(dirname(realpath(__file__)), "spec")
        out_path (str, optional): If specified, will write out resulting markdown to this file.
            Defaults to None.

    Returns:
        str: Markdown string
    """
    schema_path = schema_path or join(dirname(realpath(__file__)), "spec")
    logger.info(f"Documenting Schemas in:\n {schema_path}")

    schema_files = glob.glob(join(schema_path, "**/*.schema.json"), recursive=True)

    # Create markdown with a table for each schema file
    schema_markdown = ""

    for sf in schema_files:
        logger.info(f"Adding to MD: {sf}")
        s = frictionless.Schema(sf)
        md = s.to_markdown()
        _name = f"## {Path(sf).stem.split('.')[-2]}"
        md = md.replace("## `schema`", _name)

        schema_markdown += f"\n{md}\n"

    if out_path:
        with open(out_path, "w") as f:
            f.write(str(schema_markdown))

    return schema_markdown


def document_spec_to_md(spec_path: str = None, out_path: str = None) -> str:
    """Create markdown for each **.schema.json file in schema_path.

    Args:
        spec_path (str, optional): Path to look for spec file.
            Defaults to join(dirname(realpath(__file__)), "**/gmns.spec.json")
        out_path (str, optional): If specified, will write out resulting markdown to this file.
            Defaults to None.

    Returns:
        str: Markdown string
    """
    DROP_COLS = ["fullpath", "fullpath_schema", "path", "schema", "name"]

    spec_path = spec_path or join(dirname(realpath(__file__)), "spec", "gmns.spec.json")

    logger.info(f"Documenting Spec in:\n {spec_path}")

    # Generate a table for overall file requirements
    spec_df = read_config(spec_path)
    spec_df = spec_df.drop(columns=DROP_COLS).reset_index()
    spec_df["name"] = spec_df["name"].apply(lambda x: f"[`{x}`](#{x})".replace("_", "-"))

    spec_markdown = spec_df.to_markdown(index=False)

    if out_path:
        with open(out_path, "w") as f:
            f.write(str(spec_markdown))

    return spec_markdown
