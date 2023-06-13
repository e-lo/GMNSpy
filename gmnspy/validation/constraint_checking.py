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

from gmnspy.utils import logger


def _required_constraint(_s, _p) -> Union[None, str]:
    """Placeholder for something tested somewhere else."""
    pass


def _unique_constraint(s: pd.Series) -> Union[None, str]:
    """
    Check if series contains unique values.

    Args:
        s: series to test

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    _dupes = s[s.duplicated(keep="first")]
    if len(_dupes):
        msg = f"{len(_dupes)} sets of duplicate values not unique. Duplicate values: {_dupes.to_list()}"
        logger.warning(msg)
        return msg

def _minimum_constraint(s: pd.Series, minimum: Union[float, int]) -> Union[None, str]:
    """
    Check if series contains value under the specified minimum.

    Args:
        s: series that shouldn't be under the minimum value.
        minimum: minimum value for the series.

        Returns:
        An error string if there is an error. Otherwise, None.
    """
    _bad_vals = s[s < minimum].dropna().to_list()
    if _bad_vals:
        msg = f"{len(_bad_vals)} values lower than minimum value {minimum}: {_bad_vals}"
        logger.warning(msg)
        return msg
    
def _maximum_constraint(s: pd.Series, maximum: Union[float, int]) -> Union[None, str]:
    """
    Check if series contains value above the specified maximum.

    Args:
        s: series that shouldn't exceed maximum value.
        maximum: maximum value for the series.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    _bad_vals = s[s > maximum].dropna().to_list()
    if _bad_vals:
        msg = f"{len(_bad_vals)} values higher than maximum value {maximum}: {_bad_vals}"
        logger.warning(msg)
        return msg

def _pattern_constraint(s: pd.Series, pattern: str) -> Union[None, str]:
    """
    Check if series contains values conforming to specified pattern.

    Args:
        s: series that shouldn't be under the minimum value.
        pattern: regex string.

    Returns:
        An error string if there is an error. Otherwise, None.
    """
    notmatching_s = s.loc[~s.str.fullmatch(pattern)]
    if len(notmatching_s):
        msg = f"{len(notmatching_s)} values don't match pattern: {pattern}: {notmatching_s.to_list()}"
        logger.warning(msg)
        return msg


def _enum_constraint(s: pd.Series, enum: Union[str, list], sep: str = ",") -> Union[None, str]:
    """
    Check if series contains valid enum values.

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
    bad_vals = (s[~s.isin(enum)]).to_list()
    if bad_vals:
        msg = f"Values: {bad_vals} not in enumerated list: {enum}"
        logger.warning(msg)
        return msg
