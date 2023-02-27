import os
from os.path import join, dirname, realpath

import pandas as pd

from gmnspy.validation.constraint_checking import _required_constraint, _unique_constraint, _minimum_constraint
from gmnspy.validation.constraint_checking import _maximum_constraint, _pattern_constraint, _enum_constraint
from gmnspy.schema import read_schema, SCHEMA_TO_PANDAS_TYPES
from gmnspy.utils import logger


def apply_schema_to_df(
    df: pd.DataFrame, schema_file: str = None, originating_file: str = None, raise_error=False
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
        raise_error: Raises error if error found

    Returns:
        DataFrame with fields coerced to appropriate type and constraints
            and warnings evaluated.
    """

    if not schema_file:
        schema_filename = os.path.split(originating_file)[-1].split(".")[0] + ".schema.json"
        schema_file = join(join(dirname(realpath(__file__)), "../spec"), schema_filename)
    logger.info(f"SCHEMA: {schema_file}")
    logger.info("...validating {} against {}".format(df, schema_file))
    schema = read_schema(schema_file=schema_file)

    """
    1. Check field names and requirements
    - Required fields present (strict)
    - Extra fields that aren't in spec (warn)
    """
    logger.debug(schema)

    required_fields = [f["name"] for f in schema["fields"] if f.get("constraints", {}).get("required")]
    missing_required_fields = set(required_fields) - set(df.columns)
    if missing_required_fields:
        msg = f"FAIL. Missing required fields {missing_required_fields}"
        logger.error(msg)
        if raise_error:
            raise Exception(msg)

    fields = [f["name"] for f in schema["fields"]]
    extra_fields = set(df.columns) - set(fields)
    if extra_fields:
        logger.warning(f"WARN. Extra fields outside of spec: {extra_fields}")

    """
    2. Coerce types

    ##TODO: enforce formats
    """
    used_fields = [f["name"] for f in schema["fields"] if f["name"] in df.columns]
    types = [SCHEMA_TO_PANDAS_TYPES[f["type"]] for f in schema["fields"] if f["name"] in df.columns]
    # fmt = [FORMAT_TO_REGEX.get(f.get("format", None), None) for f in schema["fields"]]

    field_types = dict(zip(used_fields, types))
    # field_formats = dict(zip(used_fields, fmt))

    # print(field_types)
    try:
        df = df.astype(field_types)
        logger.info("Passed field type coercion")
    except Exception as e:
        logger.critical(f"ouch. {e.args}")
        if raise_error:
            raise Exception(f"ouch. {e.args}")

    """
    3. Check field constraints
    """
    fields_with_constraints = [f["name"] for f in schema["fields"] if f["name"] in df.columns and f.get("constraints")]
    constraints = [f["constraints"] for f in schema["fields"] if f["name"] in df.columns and f.get("constraints")]

    # iterate through all the constraints for all the fields
    error_dict = {}

    for field_name, fld_constr in zip(fields_with_constraints, constraints):
        field_error_list = [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param) for c_name, c_param in fld_constr.items()
        ]
        if [i for i in field_error_list if i]:
            error_dict[field_name] = [i for i in field_error_list if i]

    if error_dict:
        for i in error_dict:
            logger.error("FAIL. {} field has errors. {}".format(i, error_dict[i]))
        if raise_error:
            raise Exception(error_dict)
    else:
        logger.info("Passed Field Required Constraint Validation")

    """
    4. Check field warnings
    """
    fields_with_warnings = [f["name"] for f in schema["fields"] if f["name"] in df.columns and f.get("warnings")]
    warnings = [f["warnings"] for f in schema["fields"] if f["name"] in df.columns and f.get("warnings")]

    warning_dict = {}
    for field_name, field_warnings in zip(fields_with_warnings, warnings):
        field_warning_list = [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param)
            for c_name, c_param in field_warnings.items()
        ]
        if [i for i in field_warning_list if i]:
            warning_dict[field_name] = [i for i in field_warning_list if i]

    if warning_dict:
        for i in warning_dict:
            logger.info("WARN. {} field has warnings. {}".format(i, warning_dict[i]))

    else:
        logger.info("No Field Warnings")
    return df
