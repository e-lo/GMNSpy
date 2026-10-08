"""GMNS-aware CLI — extends :mod:`corral.cli` with GMNS commands.

Entry point: ``netstead = netstead.cli.app:app``. On top of corral's
generic ``validate`` / ``info`` / ``convert`` (overridden with GMNS-aware
``validate`` and ``info``), it adds ``quality``, ``doctor``, ``bench`` /
``bench-suite``, ``build``, ``select`` / ``select-serve``, ``viz``,
``spec``, ``server``, ``mcp``, ``clean``, ``scope``, and ``index``.
"""

from .app import app

__all__ = ["app"]
