import glob
import json
from os.path import dirname, realpath, join

import pandas as pd

from .utils import list_to_md_table, logger

SCHEMA_TO_PANDAS_TYPES = {
    "integer": "Int64",
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


def document_schema(base_path: str = None, out_path: str = None):
    """ """
    logger.info("DOCUMENTING SCHEMA")

    base_path = base_path or join(dirname(realpath(__file__)), "spec")
    out_path = out_path or join(base_path, "docs")
    logger.info(f"Looking for specs in: {base_path}")

    # Create markdown with a table for each schema file
    file_schema_markdown = ""
    schema_files = glob.glob(join(base_path, "**/*.schema.json"), recursive=True)
    logger.info(f"files: {schema_files}")

    for s in schema_files:
        logger.info(f"Documenting Schema: {s}")
        spec_name = s.split("/")[-1].split(".")[0]
        schema = read_schema(s)
        file_schema_markdown += "\n\n## {}\n".format(spec_name)
        file_schema_markdown += "\n\n{}".format(list_to_md_table(schema["fields"]))

    # Generate a table for overall file requirements
    spec_file = glob.glob(join(base_path, "**/gmns.spec.json"), recursive=True)[0]
    spec_df = read_config(spec_file)
    spec_df = spec_df.drop(columns=["fullpath", "fullpath_schema", "path", "schema", "name"]).reset_index()
    spec_df["name"] = spec_df["name"].apply(lambda x: "[`{}`](#{})".format(x, x))

    spec_markdown = spec_df.to_markdown(index=False)

    # Write it out to file
    with open(join(out_path, "spec_template.md")) as spec_template:
        template = spec_template.read()

    filedata = template.replace("{{ SPEC_TABLE }}", spec_markdown)
    filedata += file_schema_markdown

    with open(join(out_path, "spec.md"), "w") as spec_filename:
        spec_filename.write(filedata)
