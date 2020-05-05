import os
from typing import Union

from pandas import DataFrame, Series

from .schema import read_schema, SCHEMA_TO_PANDAS_TYPES, FORMAT_TO_REGEX

def apply_schema_to_df(df: DataFrame, schema_file: str = None, originating_file: str = None):
    """

    """
    if not schema_file:
        schema_filename = os.path.split(originating_file)[-1].split(".")[0]+".schema.json"
        schema_file = os.path.join("spec",schema_filename)
    print("SCHEMA",schema_file)
    print("...validating {} against {}".format(df, schema_file))
    schema = read_schema(schema_file=schema_file)

    """
    1. Check field names and requirements
    - Required fields present (strict)
    - Extra fields that aren't in spec (warn)
    """
    print(schema)

    required_fields = [
        f["name"] for f in schema["fields"] if f.get("constraints", {}).get("required")
    ]
    missing_required_fields = set(required_fields) - set(df.columns)
    if missing_required_fields:
        msg = "FAIL. Missing required fields {}".format(missing_required_fields)
        print(msg)

    fields = [f["name"] for f in schema["fields"]]
    extra_fields = set(df.columns) - set(fields)
    if extra_fields:
        msg = "WARN. Extra fields outside of spec: {}".format(extra_fields)
        print(msg)

    """
    2. Coerce types

    TODO: enforce formats
    """
    used_fields = [f["name"] for f in schema["fields"] if f["name"] in df.columns]
    types = [
        SCHEMA_TO_PANDAS_TYPES[f["type"]]
        for f in schema["fields"]
        if f["name"] in df.columns
    ]
    fmt = [FORMAT_TO_REGEX.get(f.get("format", None), None) for f in schema["fields"]]

    field_types = dict(zip(used_fields, types))
    field_formats = dict(zip(used_fields, fmt))

    # print(field_types)
    try:
        df = df.astype(field_types)
        print("Passed field type coercion")
    except:
        print("ouch")

    """
    3. Check field constraints
    """
    fields_with_constraints = [
        f["name"]
        for f in schema["fields"]
        if f["name"] in df.columns and f.get("constraints")
    ]
    constraints = [
        f["constraints"]
        for f in schema["fields"]
        if f["name"] in df.columns and f.get("constraints")
    ]

    # iterate through all the constraints for all the fields
    error_list = []
    for field_name, field_constraints in zip(fields_with_constraints, constraints):
        #print(field_name,field_constraints)
        error_list += [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param)
            for c_name, c_param in field_constraints.items()
        ]
    error_list = [i for i in error_list if i]

    if error_list:
        print(error_list)
    else:
        print("Passed Field Constraint Validation")

    return df


"""
Constraints
Represented by functions with naming pattern `_<constraint_name>_constraint`
    which take a series and a single parameter as input
"""


def _required_constraint(_s, _p):
    pass


def _unique_constraint(s: Series, _):
    if s.dropna().duplicated():
        return "Values not unique"


def _minimum_constraint(s: Series, minimum: Union[float, int]):
    if s[s < minimum].dropna().to_list():
        return "Values lower than minimum: {}".format(minimum)


def _maximum_constraint(s: Series, maximum: Union[float, int]):
    """
    s:
    maximum:
    """
    if s[s > maximum].dropna().to_list():
        return "Values higher than maximum: {}".format(maximum)


def _pattern_constraint(s: Series, pattern: str):
    """
    Needs to be tested
    """
    if ~s.str.contains(pattern):
        return "Doesn't match pattern: {}".format(pattern)


def _enum_constraint(s: Series, enum: str):
    if not isinstance(enum, list):
        enum = enum.split(",")
    err_i = (s[~s.isin(enum)]).to_list()
    if err_i:
        return "Values: {} not in enumerated list: {}".format(err_i, enum)


def validate_foreign_key(
    source_df: DataFrame, reference_df: DataFrame, field_name: str
) -> bool:
    """
    source_df:

    reference_df:

    field_name:


    Returns:
    """
