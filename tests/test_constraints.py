import pandas as pd
import pytest

from gmnspy.validation.constraint_checking import (
    _enum_constraint,
    _maximum_constraint,
    _minimum_constraint,
    _pattern_constraint,
    _unique_constraint,
)


def test_unique_constraint():
    s_bad = pd.Series([1, 2, 2, 4])
    s_good = pd.Series([1, 2, 3, 4])
    assert _unique_constraint(s_bad) is not None
    assert _unique_constraint(s_good) == None


def test_minimum_constraint():
    s_bad = pd.Series([-5, 4, 5, 6])
    s_good = pd.Series([5, 6, 7, 8])
    min = 5
    assert _minimum_constraint(s_bad, 5) is not None
    assert _minimum_constraint(s_good, 5) == None


def test_maximum_constraint():
    s_bad = pd.Series([0.5, 1, 150])
    s_good = pd.Series([0.2, 1, 15])
    max = 20
    assert _maximum_constraint(s_bad, max) is not None
    assert _maximum_constraint(s_good, max) == None


def test_pattern_constraint():
    s_bad = pd.Series(["00:45:45", "12:12:12", "h:m:s", "1:23:23", "01:23:88"])
    s_good = pd.Series(["01:30:45", "22:33:44"])
    test_pattern = "^((?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$)"
    assert _pattern_constraint(s_bad, test_pattern) is not None
    assert _pattern_constraint(s_good, test_pattern) == None


def test_enum_constraint():
    s_bad = pd.Series(["hi", "hello", "yo", "bye", None])
    s_good = pd.Series(["hello", "yo", "yo"])
    test_enum = ["hi", "hello", "yo"]
    assert _enum_constraint(s_bad, test_enum) is not None
    assert _enum_constraint(s_good, test_enum) == None
