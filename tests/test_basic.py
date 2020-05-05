import os
import gmnspy
import pytest

base_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# https://github.com/zephyr-data-specs/GMNS/edit/master/Small_Network_Examples/Multiple_Bike_Facilities/road_link.csv


def test_read_schema():
    schema_file = os.path.join(base_path, "spec", "link.schema.json")
    s = gmnspy.read_schema(schema_file)
    print(s)

@pytest.mark.elo
def test_validate_road_link_df():
    road_link_df = gmnspy.in_out.read_gmns_csv(
        "tests/data/link.csv", validate=False,
    )
    print(road_link_df[0:3])
    v = gmnspy.apply_schema_to_df(
        road_link_df, schema_file=os.path.join(base_path, "spec", "link.schema.json")
    )
    print(v)
