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
    with open(schema_file, encoding="utf-8") as f:
        schema = json.load(f)
    ## todo validate schema
    return schema


def read_config(config_file: str, data_dir: str = "") -> pd.DataFrame:
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
    print(resource_df)

    resource_df.set_index("name", drop=False, inplace=True)
    return resource_df
