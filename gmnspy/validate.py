import os
from typing import Union, Dict

import pandas as pd

from .schema import read_schema, SCHEMA_TO_PANDAS_TYPES, FORMAT_TO_REGEX


def apply_schema_to_df(
    df: pd.DataFrame, schema_file: str = None, originating_file: str = None
) -> pd.DataFrame:
    """
    Evaluates a gmns table against a specified data schema.
    (1) Checks required fields exist
    (2) Coerces field types
    (3) Evaluates constraints that are firmly enforced
    (4) Evaluates warnings for strange values

    Args:
        df: Dataframe of the gmns table
        schema_file: The table schema that will be applied.  If not supplied,
            will look for the schema in the directory that matches the name in
            originating_file (i.e. link, node)

        originating_file: base name of the originating file (i.e. link.csv, node)

    Returns:
        DataFrame with fields coerced to appropriate type and constraints
            and warnings evaluated.
    """
    if not schema_file:
        schema_filename = (
            os.path.split(originating_file)[-1].split(".")[0] + ".schema.json"
        )
        schema_file = os.path.join("spec", schema_filename)
    print("SCHEMA", schema_file)
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

    ##TODO: enforce formats
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
        # print(field_name,field_constraints)
        error_list += [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param)
            for c_name, c_param in field_constraints.items()
        ]
    error_list = [i for i in error_list if i]

    if error_list:
        print(error_list)
    else:
        print("Passed Field Required Constraint Validation")

    """
    4. Check field warnings
    """
    fields_with_warnings = [
        f["name"]
        for f in schema["fields"]
        if f["name"] in df.columns and f.get("warnings")
    ]
    warnings = [
        f["warnings"]
        for f in schema["fields"]
        if f["name"] in df.columns and f.get("warnings")
    ]

    warning_list = []
    for field_name, field_warnings in zip(fields_with_warnings, warnings):
        # print(field_name,field_constraints)
        warning_list += [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param)
            for c_name, c_param in field_warnings.items()
        ]
    warning_list = [i for i in error_list if i]

    if warning_list:
        print(warning_list)
    else:
        print("No Field Warnings")

    return df


"""
Constraints
------------

Represented by functions with naming pattern `_<constraint_name>_constraint`
    which take a series and a single parameter as input.

Constraints are specified in the gmns spec files for each field are treated
    as mandatory. The same parameters can be specified as warnings and
    will not be treated as mandatory.
"""


def _required_constraint(_s, _p) -> Union[None,str]:
    """
    Currently tested somewhere else.
    """
    pass


def _unique_constraint(s: pd.Series, _) -> Union[None,str]:
    """
    Checks if series contains unique values.

    ##needstest

    Args:
        s: series that shouldn't exceed maximum value.
        _: boolean specifying unique values needed.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s.dropna().duplicated():
        return "Values not unique."


def _minimum_constraint(s: pd.Series, minimum: Union[float, int]) -> Union[None,str]:
    """
    Checks if series contains value under the specified minimum.

    ##needstest

    Args:
        s: series that shouldn't be under the minimum value.
        minimum: minimum value for the series.

        Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s[s < minimum].dropna().to_list():
        return "Values lower than minimum: {}".format(minimum)


def _maximum_constraint(s: pd.Series, maximum: Union[float, int]) -> Union[None,str]:
    """
    Checks if series contains value above the specified maximum.

    ##needstest

    Args:
        s: series that shouldn't exceed maximum value.
        maximum: maximum value for the series.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s[s > maximum].dropna().to_list():
        return "Values higher than maximum: {}".format(maximum)


def _pattern_constraint(s: pd.Series, pattern: str)-> Union[None,str]:
    """
    Checks if series contains values conforming to specified pattern.

    ##needstest

    Args:
        s: series that shouldn't be under the minimum value.
        pattern: regex string.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if ~s.str.contains(pattern):
        return "Doesn't match pattern: {}".format(pattern)


def _enum_constraint(s: pd.Series, enum: Union[str,list], sep: str=",") -> Union[None,str]:
    """
    Checks if series contains valid enum values.

    ##needstest

    Args:
        s: series of values that should all have values in  the enumerated
            list
        enum: either a string of allowable values separated by sep, or
            a list of allowable values.
        sep: separator for different values. Default is ","

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if not isinstance(enum, list):
        enum = enum.split(sep)
    err_i = (s[~s.isin(enum)]).to_list()
    if err_i:
        return "Values: {} not in enumerated list: {}".format(err_i, enum)




def confirm_required_files(resource_df: pd.DataFrame) -> None:
    """
    Check required files exist. Will fail if they don't.

    Args:
        resource_df:Dataframe with a row for each GMNS table including
            the the columns "fullpath", "name", and "required" (boolean).
    """
    required_files = resource_df[resource_df["required"]]

    print("Required Files: ", required_files)

    missing_required_files = required_files[
        required_files["fullpath"].apply(lambda x: not os.path.exists(x))
    ][["name", "fullpath"]]

    print("FAIL Missing Required Files: ", missing_required_files)


def update_resources_based_on_existance(resource_df: pd.DataFrame) -> pd.DataFrame:
    """
    Update resource dataframe based on which files exist in the directory.

    Args:
        resource_df:Dataframe with a row for each GMNS table including
            the the columns "fullpath" and "name".

    Returns: Updated version of resource dataframe without non-existant
        files.
    """
    updated_resource_df = resource_df[
        resource_df["fullpath"].apply(lambda x: os.path.exists(x))
    ]

    print(
        "Found following files to define network: \n - {}".format(
            "\n - ".join(updated_resource_df["name"].to_list())
        )
    )
    return updated_resource_df


def validate_foreign_key(
    source_s: pd.Series, reference_s: pd.Series) -> list:
    """
    Checks that the source_s series links to a valid reference_s series
        which has (1) unique IDs, and (2) contains the values of the
        referring series.

    source_s: series containing values that reference foreign key values in reference_s.

    reference_s: series of foreign key values.

    Returns: a list of error messages.
    """

    fkey_errors = []
    # Make sure reference_s is unique
    dupes = reference_s.dropna().duplicated()
    if dupes.any():
        msg = "FAIL. Duplicates exist in foreign key series: {}".format(dupes)
        print(msg)
        fkey_errors.append(msg)

    # Make sure all source have a valid reference
    if not source_s.isin(reference_s.dropna().to_list()).any():
        msg = "FAIL. {} not in foreign key reference.".format(source_s[source_s.isin(reference_s.dropna().to_list())])
        print(msg)
        fkey_errors.append(msg)

    return fkey_errors

def validate_foreign_keys(gmns_net_d: Dict[str,pd.DataFrame], resource_df: pd.DataFrame) -> None:
    """
    Finds foreign keys in schemas of each GMNS table and validates that
    they link to a valid series which has (1) unique IDs, and (2) contains
    the values of the referring series.

    Args:
        gmns_net_d: Dictionary containing dataframes of all the GMNS tables
            for the network keyed to their file names (i.e. "link").
        resource_df:Dataframe with a row for each GMNS table which contains
            the field "fullpath_schema" for the schema locations for
            each GMNS table which is where foreign keys are specified.
    """
    print(gmns_net_d["node"]["node_id"])

    fkey_errors =  []
    for table_name,df in gmns_net_d.items():
        schema = read_schema(schema_file=resource_df[resource_df["name"]==table_name]["fullpath_schema"][0])

        foreign_keys = [
            (f["name"],f["foreign_key"]) for f in schema["fields"] if (f.get("foreign_key") and f["name"] in df.columns)
        ]
        print("FKEYS: ",foreign_keys)

        # find the series for the foreign key
        for field,f_key in foreign_keys:
            #NOTE this requires that field names that are foreign keys not have '.'
            t,f = f_key.split(".")
            # if it is in same table
            if not t:
                reference_s = df[f]
            # or not...
            else:
                try:
                    reference_s = gmns_net_d[t][f]
                except:
                    print("FAIL. {} field in table {} does not exist".format(f,t))
                    continue
            fkey_errors+=validate_foreign_key(df[field], reference_s)
