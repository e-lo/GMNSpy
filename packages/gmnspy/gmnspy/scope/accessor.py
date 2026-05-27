"""Chainable scope-builder accessor — :class:`NetworkScopeAccessor`.

Returned by :attr:`gmnspy.Network.scope` so the documented chainable
form (per ``docs/architecture.md`` §6.2) reads naturally::

    net.scope.from_nodes([1, 2, 3]).buffer_network("0.5mi").apply()

Each method partially-applies the source :class:`~gmnspy.Network` as
the first arg of the matching module-level constructor in
:mod:`gmnspy.scope` and returns the resulting :class:`NetworkScope`
unchanged — so the returned value still has the composition surface
(``buffer_network`` / ``buffer_spatial`` / ``union`` / ``intersect`` /
``subtract`` / ``apply``) intact.

The accessor itself is stateless beyond the network reference; it
exists solely to bind ``net`` so callers don't have to type it.

Backward-compat: the accessor is also callable, forwarding to the
inherited :meth:`datagrove.dataset.Package.scope` generic
table/column/bbox subset method. That keeps the pre-existing
``net.scope(tables=[...])`` form working even though ``scope`` is now
a property rather than a method.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package

    from gmnspy.network import Network

    from .scope import NetworkScope


__all__ = ["NetworkScopeAccessor"]


class NetworkScopeAccessor:
    """Partial-applied scope-constructor surface for one :class:`Network`.

    Instantiated by :attr:`gmnspy.Network.scope`; not constructed
    directly. Each method delegates to the matching module-level
    function in :mod:`gmnspy.scope` with ``self.network`` as the first
    positional argument, leaving the rest of the call shape untouched.

    The returned :class:`NetworkScope` is the same value the
    module-level functions return, so chaining
    (``buffer_network`` / ``buffer_spatial`` / ``apply``) keeps
    working::

        >>> import pytest
        >>> _ = pytest.importorskip("igraph")
        >>> from gmnspy import Network
        >>> from gmnspy.fixtures import leavenworth
        >>> from datagrove.engines.pandas_engine import PandasEngine
        >>> net = Network.from_source(leavenworth.csv_dir(), engine=PandasEngine())
        >>> scope = net.scope.from_nodes([1, 2, 3], path_between=False)
        >>> 1 in scope.node_ids
        True
    """

    __slots__ = ("network",)

    def __init__(self, network: Network) -> None:
        """Bind the accessor to a Network; called by `Network.scope`."""
        self.network = network

    def __repr__(self) -> str:
        """Compact repr — useful at the REPL for ``net.scope`` itself."""
        return f"NetworkScopeAccessor(network={self.network!r})"

    def __call__(self, *args: Any, **kwargs: Any) -> Package:
        """Forward to the inherited :meth:`datagrove.dataset.Package.scope`.

        Preserves the pre-existing call shape
        ``net.scope(tables=[...], bbox=..., ...)``. Because
        ``scope`` is now a property on :class:`gmnspy.Network`, the
        bare callable form ``net.scope(...)`` would otherwise be a
        ``TypeError`` — this ``__call__`` proxy keeps it working
        without forcing callers into ``net.scope.subset(...)`` or
        similar.

        See :meth:`datagrove.dataset.Package.scope` for the full
        kwarg surface.
        """
        # Bypass the property descriptor (which would recurse into
        # this accessor) and go straight to the unbound Package.scope
        # method bound to our network instance.
        from datagrove.dataset import Package

        return Package.scope(self.network, *args, **kwargs)

    # ------------------------------------------------------------------
    # Constructor delegates — one per module-level function
    # ------------------------------------------------------------------

    def from_nodes(self, node_ids: Iterable[int], *, path_between: bool = True) -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.from_nodes` with this accessor's network."""
        from .scope import from_nodes

        return from_nodes(self.network, node_ids, path_between=path_between)

    def from_node(self, node_id: int, *, network_buffer: str | float = "0.5mi") -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.from_node` with this accessor's network."""
        from .scope import from_node

        return from_node(self.network, node_id, network_buffer=network_buffer)

    def from_link(
        self,
        link_id: int,
        *,
        spatial_buffer_m: float | None = None,
        network_buffer: str | float | None = None,
    ) -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.from_link` with this accessor's network."""
        from .scope import from_link

        return from_link(
            self.network,
            link_id,
            spatial_buffer_m=spatial_buffer_m,
            network_buffer=network_buffer,
        )

    def from_point(self, xy: tuple[float, float], *, spatial_buffer_m: float = 100.0) -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.from_point` with this accessor's network."""
        from .scope import from_point

        return from_point(self.network, xy, spatial_buffer_m=spatial_buffer_m)

    def connected_component(self, seed_node_id: int) -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.connected_component` with this accessor's network."""
        from .scope import connected_component

        return connected_component(self.network, seed_node_id)

    def from_zone(self, zone_ids: Iterable[int]) -> NetworkScope:
        """Delegate to :func:`gmnspy.scope.from_zone` with this accessor's network."""
        from .scope import from_zone

        return from_zone(self.network, zone_ids)
