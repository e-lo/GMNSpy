import logging

import pytest

import gmnspy

logger = logging.getLogger()

test_versions = [
    "master",
    "development",
]


@pytest.mark.parametrize("version", test_versions)
def test_read_validate_official_spec(version):
    official_spec = gmnspy.SpecConfig(official_version=version)
    assert official_spec.schema_errors == []
