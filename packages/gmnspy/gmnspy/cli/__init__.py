"""GMNS-aware CLI — extends :mod:`datagrove.cli` with GMNS commands.

Entry point: ``gmnspy = gmnspy.cli.app:app``. Initial commands shipped
in Phase 4 task 4.1b: GMNS-aware ``info``, ``quality``. Follow-up tasks
add ``read``, ``spec``, ``clean``, ``index``.
"""

from .app import app

__all__ = ["app"]
