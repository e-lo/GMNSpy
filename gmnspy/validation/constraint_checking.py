from typing import Union

import pandas as pd

"""
Constraints
------------

Represented by functions with naming pattern `_<constraint_name>_constraint`
    which take a series and a single parameter as input.

Constraints are specified in the gmns spec files for each field are treated
    as mandatory. The same parameters can be specified as warnings and
    will not be treated as mandatory.
"""


def _required_constraint(s: pd.Series, required: bool) -> Union[None, str]:
    """
    Checks if a required field contains all non-null values.
    """
    if s.isna().any():
        err_keys = list(s.isna().index)
        return "Required field has missing values. Index of row(s) with missing values: {}".format(err_keys)


def _unique_constraint(s: pd.Series, _) -> Union[None, str]:
    """
    Checks if series contains unique values.
    ##needstest
    Args:
        s: series that shouldn't exceed maximum value.
        _: boolean specifying unique values needed.
    Returns:
        An error string if there is an error. Otherwise, None.
    """
    dupes = s.dropna().duplicated()
    if dupes.any():
        err_keys = s[s.dropna().duplicated(keep=False)].index.to_list()
        return "Values not unique. List of duplicated values: {}. Index of row(s) with bad values: {}.".format(
            s[dupes].to_list(), err_keys
        )


def _minimum_constraint(s: pd.Series, minimum: Union[float, int]) -> Union[None, str]:
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
        err_keys = list(s[s < minimum].dropna().index)
        return "Values lower than minimum: {}. Index of row(s) with bad values: {}".format(minimum, err_keys)


def _maximum_constraint(s: pd.Series, maximum: Union[float, int]) -> Union[None, str]:
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
        err_keys = list(s[s > maximum].dropna().index)
        return "Values higher than maximum: {}. Index of row(s) with bad values: {}".format(maximum, err_keys)


def _pattern_constraint(s: pd.Series, pattern: str) -> Union[None, str]:
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


def _enum_constraint(s: pd.Series, enum: Union[str, list], sep: str = ",") -> Union[None, str]:
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
    err_i = (s[(~s.dropna().isin(enum)).reindex(index=s.index, fill_value=False)]).drop_duplicates().to_list()
    err_keys = list(s[(~s.dropna().isin(enum)).reindex(index=s.index, fill_value=False)].index)
    if err_i:
        return "Values: {} not in enumerated list: {}. Index of row(s) with bad values: {}".format(
            err_i, enum, err_keys
        )
