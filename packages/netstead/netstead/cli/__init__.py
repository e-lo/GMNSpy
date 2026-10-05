"""GMNS-aware CLI — extends :mod:`corral.cli` with GMNS commands.

Entry point: ``netstead = netstead.cli.app:app``. Initial commands shipped
in Phase 4 task 4.1b: GMNS-aware ``info``, ``quality``. Follow-up tasks
add ``read``, ``spec``, ``clean``, ``index``.
"""

from .app import app

__all__ = ["app"]
