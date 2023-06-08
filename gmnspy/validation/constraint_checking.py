"""
Functions which test GMNS schema constraints.

Represented by functions with naming pattern `_<constraint_name>_constraint`
    which take a series and a single parameter as input.

Constraints are specified in the gmns spec files for each field are treated
    as mandatory. The same parameters can be specified as warnings and
    will not be treated as mandatory.
"""

from typing import Union

import pandas as pd


def _required_constraint(_s, _p) -> Union[None, str]:
    """Placeholder for something tested somewhere else."""
    pass


def _unique_constraint(s: pd.Series, _) -> Union[None, str]:
    """
    Check if series contains unique values.

    TODO: ##needstest

    Args:
        s: series that shouldn't exceed maximum value.
        _: boolean specifying unique values needed.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s.dropna().duplicated():
        return "Values not unique."


def _minimum_constraint(s: pd.Series, minimum: Union[float, int]) -> Union[None, str]:
    """
    Check if series contains value under the specified minimum.

    TODO: ##needstest

    Args:
        s: series that shouldn't be under the minimum value.
        minimum: minimum value for the series.

        Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s[s < minimum].dropna().to_list():
        return "Values lower than minimum: {}".format(minimum)


def _maximum_constraint(s: pd.Series, maximum: Union[float, int]) -> Union[None, str]:
    """
    Check if series contains value above the specified maximum.

    TODO: ##needstest

    Args:
        s: series that shouldn't exceed maximum value.
        maximum: maximum value for the series.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if s[s > maximum].dropna().to_list():
        return "Values higher than maximum: {}".format(maximum)


def _pattern_constraint(s: pd.Series, pattern: str) -> Union[None, str]:
    """
    Check if series contains values conforming to specified pattern.

    TODO: ##needstest

    Args:
        s: series that shouldn't be under the minimum value.
        pattern: regex string.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    if ~s.str.contains(pattern):
        return "Doesn't match pattern: {}".format(pattern)


def _enum_constraint(s: pd.Series, enum: Union[str, list], sep: str = ",") -> Union[None, str]:
    """
    Check if series contains valid enum values.

    TODO: ##needstest

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
