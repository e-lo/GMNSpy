import os

import pandas as pd
from pandas import DataFrame

from .validate import (
    apply_schema_to_df,
    confirm_required_files,
    update_resources_based_on_existance,
    validate_foreign_keys,
)
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
        apply_schema_to_df(df, schema_file=schema_file, originating_file=filename)
    else:
        print("not validating {}".format(filename))

    return df


def read_gmns_network(
    data_directory: str, config: str = os.path.join("spec", "gmns.spec.json")
):
    """
    filename:
    validate:
    schema_file:
    """
    gmns_net_d = {}
    resource_df = read_config(config, data_dir=data_directory)

    # check required files exist,
    confirm_required_files(resource_df)

    # update resource dictionary based on what files are in the directory
    resource_df = update_resources_based_on_existance(resource_df)

    # read each csv to a df and validate format
    # todo add paired schema
    for _, row in resource_df.iterrows():
        gmns_net_d[row["name"]] = read_gmns_csv(row["fullpath"])

    # print(gmns_net_d["link"][0:5])

    # validate foreign keys
    validate_foreign_keys(gmns_net_d, resource_df)

    return gmns_net_d
