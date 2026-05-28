"""Empty-result handling for the OSM build path (regression for the default engine)."""

from __future__ import annotations

import pytest
from gmnspy.osm import build


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)

    def post(self, url, data=None, headers=None, timeout=None):
        return self._responses.pop(0)


def test_network_from_records_empty_builds_valid_network_on_default_engine():
    # Default (ibis/duckdb) engine used to raise "must have at least one column".
    net = build.network_from_records([], [])
    assert net.nodes.count() == 0
    assert net.links.count() == 0
    # Schema columns are still present (so a downstream write/validate works).
    assert "node_id" in net.nodes.to_pandas().columns
    assert "from_node_id" in net.links.to_pandas().columns


def test_build_network_from_osm_raises_clear_error_on_empty_area():
    sess = _Session([_Resp(200, {"elements": []})])
    with pytest.raises(ValueError, match="no OSM"):
        build.build_network_from_osm((0.0, 0.0, 0.01, 0.01), session=sess, sleep=lambda *_: None)
