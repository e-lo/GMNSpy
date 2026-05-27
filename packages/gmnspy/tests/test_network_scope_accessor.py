"""Regression tests for :attr:`Network.scope` accessor + :meth:`Network.build_indexes`.

Covers the architecture-spec'd chainable surface
(``docs/architecture.md`` §6.2):

    net.build_indexes(spatial=True, graph=True)
    net.scope.from_nodes([1, 2, 3]).buffer_network("0.5mi").apply()

Pre-1.0 these were either free functions (``gmnspy.indexes.build_indexes``)
or required passing ``net`` explicitly to each scope constructor —
neither matched the documented chainable form.
"""

from __future__ import annotations

import pytest
from datagrove.engines.pandas_engine import PandasEngine
from gmnspy import Network
from gmnspy.fixtures import leavenworth

pytest.importorskip("igraph")
pytest.importorskip("shapely")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _net() -> Network:
    """Fresh Leavenworth Network — small + cheap."""
    return Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())


# ---------------------------------------------------------------------------
# Network.build_indexes
# ---------------------------------------------------------------------------


def test_build_indexes_returns_self_for_chaining() -> None:
    """:meth:`build_indexes` returns ``self`` so callers can chain."""
    net = _net()
    assert net.build_indexes(spatial=True, graph=True) is net


def test_build_indexes_populates_metadata_cache() -> None:
    """Built indexes land on ``net.metadata`` under the scope module's cache keys.

    Same keys :mod:`gmnspy.scope` reads, so a subsequent scope op
    finds the indexes without rebuilding.
    """
    from gmnspy.scope.scope import _GRAPH_INDEX_KEY, _SPATIAL_INDEX_KEY

    net = _net().build_indexes(spatial=True, graph=True)
    assert _GRAPH_INDEX_KEY in net.metadata
    # Spatial may legitimately be absent if Leavenworth links carry no
    # inline geometry column — guard the assertion.
    if "geometry" in net.links.columns():
        assert _SPATIAL_INDEX_KEY in net.metadata


def test_build_indexes_skip_flags_respected() -> None:
    """``graph=False`` skips graph build; ``spatial=False`` skips spatial."""
    from gmnspy.scope.scope import _GRAPH_INDEX_KEY, _SPATIAL_INDEX_KEY

    net = _net().build_indexes(spatial=False, graph=True)
    assert _GRAPH_INDEX_KEY in net.metadata
    assert _SPATIAL_INDEX_KEY not in net.metadata


def test_build_indexes_noop_when_both_false() -> None:
    """``spatial=False, graph=False`` is a no-op — metadata stays empty."""
    from gmnspy.scope.scope import _GRAPH_INDEX_KEY, _SPATIAL_INDEX_KEY

    net = _net().build_indexes(spatial=False, graph=False)
    assert _GRAPH_INDEX_KEY not in net.metadata
    assert _SPATIAL_INDEX_KEY not in net.metadata


# ---------------------------------------------------------------------------
# Network.scope accessor
# ---------------------------------------------------------------------------


def test_scope_accessor_from_nodes_returns_networkscope() -> None:
    """``net.scope.from_nodes(...)`` returns the same value as the free function."""
    from gmnspy.scope import NetworkScope, from_nodes

    net = _net()
    via_accessor = net.scope.from_nodes([1, 2, 3], path_between=False)
    via_function = from_nodes(net, [1, 2, 3], path_between=False)

    assert isinstance(via_accessor, NetworkScope)
    # Same construction → same id sets (provenance string also matches).
    assert via_accessor.node_ids == via_function.node_ids
    assert via_accessor.link_ids == via_function.link_ids


def test_scope_accessor_chain_compose_and_apply() -> None:
    """Full chain: accessor → constructor → composition → apply.

    Matches the architecture-doc example::

        net.scope.from_nodes([...]).buffer_network("0.5mi").apply()
    """
    net = _net()
    scoped = net.scope.from_nodes([1, 2, 3], path_between=False).buffer_network("200m")
    sub = scoped.apply()
    # The scoped network should never exceed the source on link count.
    assert sub.links.count() <= net.links.count()


def test_scope_accessor_each_constructor_delegates() -> None:
    """Every documented constructor (sans connected_component / from_point) is reachable.

    Smoke test that the accessor surface covers each free function.
    ``from_point`` + ``connected_component`` need specific seeds the
    Leavenworth fixture may or may not have; covered by the dedicated
    test_scope.py suite.
    """
    net = _net()
    # from_node
    scope_n = net.scope.from_node(1, network_buffer="100m")
    assert 1 in scope_n.node_ids
    # from_link — pick any link id in the network
    sample_link_id = net.links.to_pandas()["link_id"].iloc[0]
    scope_l = net.scope.from_link(int(sample_link_id), network_buffer="100m")
    assert int(sample_link_id) in scope_l.link_ids


def test_scope_accessor_callable_preserves_package_scope() -> None:
    """``net.scope(tables=[...])`` still routes to inherited :meth:`Package.scope`.

    Backward-compat: pre-existing callers using the callable form
    must keep working even though ``scope`` is now a property.
    """
    net = _net()
    sub = net.scope(tables=["link"])
    assert sub.keys() == ["link"]


def test_scope_accessor_returns_fresh_instance_each_access() -> None:
    """Each ``net.scope`` access returns a new accessor — no shared state."""
    net = _net()
    a, b = net.scope, net.scope
    assert a is not b
    # But both bound to the same network.
    assert a.network is b.network is net


# ---------------------------------------------------------------------------
# Module-level free-function form still works (don't break existing callers)
# ---------------------------------------------------------------------------


def test_module_level_from_nodes_still_works() -> None:
    """The pre-existing ``gmnspy.scope.from_nodes(net, ...)`` form must not regress."""
    from gmnspy.scope import from_nodes

    net = _net()
    scope = from_nodes(net, [1, 2, 3], path_between=False)
    assert 1 in scope.node_ids
