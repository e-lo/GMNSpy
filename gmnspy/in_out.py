import pandas as pd
from pandas import DataFrame

from .validate import apply_schema_to_df
from .schema import read_config

def read_gmns_csv(
    filename: str, validate: bool = True, schema_file: str = None
) -> DataFrame:
    """
    filename:
    validate:
    schema_file:
    """

    df = pd.read_csv(filename)

    if validate:
        apply_schema_to_df(df, schema_file=schema_file, originating_file = filename)
    else:
        print("not validating {}".format(filename))

    return df

def read_gmns_network(folder: str, config: str = "../spec/gmns.spec.json"):
    config = read_config(config)
    required_files = [
        f["name"] for f in config[]"resources"] if f.get("required", {}) == "true"
    ]
    print(required_files)
