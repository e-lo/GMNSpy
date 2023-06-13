"""Applies schema constraints to update a dataframe of data."""

import os
from typing import Union, Tuple
import pandas as pd

from gmnspy.schema import SCHEMA_TO_PANDAS_TYPES, official_spec_config, json_from_path
from gmnspy.utils import logger
from gmnspy.validation.constraint_checking import (
    _enum_constraint,
    _maximum_constraint,
    _minimum_constraint,
    _pattern_constraint,
    _required_constraint,
    _unique_constraint,
)


class SchemaApplicationError(Exception):
    pass

def _check_required_fields(df: pd.DataFrame,schema_dict:dict)->Tuple[list]:
    """Check that required fields present and warn about extra fields

    Args:
        df: dataframe to check
        schema_dict: dictionary of table schema
    
    Returns: tuple of (error_list, warning_list)
    """
    error_list = []
    warning_list = []
    required_fields = [f["name"] for f in schema_dict["fields"] if f.get("constraints", {}).get("required")]
    logger.debug(f"Required Fields:\n{required_fields}")
    missing_required_fields = set(required_fields) - set(df.columns)
    if missing_required_fields:
        msg = f"Missing required fields: {missing_required_fields}"
        error_list.append(msg)
        logger.error(msg)

    fields = [f["name"] for f in schema_dict["fields"]]
    extra_fields = set(df.columns) - set(fields)
    if extra_fields:
        msg = f"Extra fields outside of spec: {extra_fields}"
        warning_list.append(msg)
        logger.warning(msg)

    return error_list,warning_list
    
    
def _check_coerce_types(df: pd.DataFrame,schema_dict:dict)->Tuple[Union[pd.DataFrame,list]]:
    """Check values present and warn about extra fields

    Args:
        df: dataframe to check
        schema_dict: dictionary of table schema
    
    Returns: tuple of (coerced_df,error_list, warning_list)
    """
    error_list = []
    warning_list = []
    used_fields = [f["name"] for f in schema_dict["fields"] if f["name"] in df.columns]
    types = [SCHEMA_TO_PANDAS_TYPES[f["type"]] for f in schema_dict["fields"] if f["name"] in df.columns]
    # fmt = [FORMAT_TO_REGEX.get(f.get("format", None), None) for f in schema["fields"]]

    field_types = dict(zip(used_fields, types))
    # field_formats = dict(zip(used_fields, fmt))

    try:
        coerced_df = df.astype(field_types)
        logger.info("Passed field type coercion")
    except SchemaApplicationError as e:
        msg = f"Type coercion failed: {e.args}"
        error_list.append(msg)
        logger.error(msg)

    return coerced_df, error_list,warning_list

def _check_field_constraints(df: pd.DataFrame,schema_dict:dict)->list:
    """Check field constraints.

    Args:
        df: dataframe to check
        schema_dict: dictionary of table schema
    
    Returns: error_list
    """
    error_list = []
    fields_with_constraints = [
        f["name"] for f in schema_dict["fields"] if f["name"] in df.columns and f.get("constraints")
    ]
    constraints = [f["constraints"] for f in schema_dict["fields"] if f["name"] in df.columns and f.get("constraints")]

    # iterate through all the constraints for all the fields
    field_constraint_validations = []
   
    for field_name, fld_constr in zip(fields_with_constraints, constraints):
        field_constraint_validations += [
            globals()[f"_{c_name}_constraint"](df[field_name], cpar) for c_name, cpar in fld_constr.items()
        ]

    error_list = [i for i in field_constraint_validations if i]
    return error_list

def _check_field_warnings(df: pd.DataFrame,schema_dict:dict)->list:
    """Check field constraints.

    Args:
        df: dataframe to check
        schema_dict: dictionary of table schema
    
    Returns: warning_list
    """
    warning_list = []

    fields_with_warnings = [f["name"] for f in schema_dict["fields"] if f["name"] in df.columns and f.get("warnings")]
    warnings = [f["warnings"] for f in schema_dict["fields"] if f["name"] in df.columns and f.get("warnings")]

    for field_name, field_warnings in zip(fields_with_warnings, warnings):
        warning_list += [
            globals()["_" + c_name + "_constraint"](df[field_name], c_param)
            for c_name, c_param in field_warnings.items()
        ]
    return warning_list


def apply_schema_to_df(
    df: pd.DataFrame,
    schema_path: Union[dict, str] = None,
    schema_dict: dict = None,
    schema_name: str = None,
    fail_fast: bool = False,
) -> pd.DataFrame:
    """
    Evaluate a gmns table against a specified data schema.

    (1) Checks required fields exist
    (2) Coerces field types
    (3) Evaluates constraints that are firmly enforced
    (4) Evaluates warnings for strange values

    Args:
        df: Dataframe of the gmns table
        schema_path: The table schema that will be applied either a json file or dict of parsed json.
            If not supplied, will look for the schema in the directory that matches the name in
            schema_name (i.e. link, node)
        schema_dict: If supplied, will use to do valdiation.
        schema_name: If no schema_path or schema_dict, will use the official default GMNS spec and
            this name  (i.e. link, node)as a way to try and infer which schema to use.
            Can be found by os.path.split(originating_file)[-1].split(".")[0]
        fail_fast: Raises error as soon as error found. Defaults to False.

    Returns:
        DataFrame with fields coerced to appropriate type and constraints
            and warnings evaluated.
    """
    if schema_path and schema_dict:
        ValueError("Should only have one of schema_path and schema_dict")
    if schema_path:
        schema_name = os.path.split(schema_path)[-1].split(".")[0]
        schema_dict = json_from_path(schema_path)
    elif not schema_dict:
        if not schema_name:
            raise ValueError("If Schema not supplied, must supply schema_name")
        schema_dict = official_spec_config().get_schema_as_dict(schema_name)

    logger.debug(f"Validating against:\n{schema_dict}")

    error_list = []
    warning_list = []

    # Fields
    _field_error_list,_field_warning_list = _check_required_fields(df,schema_dict)

    if fail_fast and _field_error_list:
        raise SchemaApplicationError(_field_error_list)
    
    error_list += _field_error_list
    warning_list += _field_warning_list

    # Coerce Types
    df, _type_error_list, _type_warning_list = _check_coerce_types(df,schema_dict)

    if fail_fast and _type_error_list:
        raise SchemaApplicationError(_type_error_list)
    
    error_list += _type_error_list
    warning_list += _type_warning_list

    # Constraints
    _constraint_error_list = _check_field_constraints(df,schema_dict)
    _constraint_warning_list = _check_field_warnings(df,schema_dict)

    if fail_fast and _constraint_error_list:
        raise SchemaApplicationError(_constraint_error_list)
    
    error_list += _constraint_error_list
    warning_list += _constraint_warning_list
    
    # Report
    if warning_list:
        logger.warning(warning_list)
    if error_list:
        raise SchemaApplicationError(f"{len(error_list)} errors applying {schema_name} schema.")
    else:
        logger.info("No Errors or Warnings")

    return df
