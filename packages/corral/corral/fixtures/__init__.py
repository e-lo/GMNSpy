"""Bundled example data for corral's own doctests.

See :mod:`corral.fixtures.sample` for the canonical small generic
fixture — kept intentionally separate from any domain package (notably
``netstead.fixtures.leavenworth``) so the composition boundary stays
visible and the import-linter contract ``corral must not depend on
netstead`` can be enforced.
"""

from . import sample  # re-export so `from corral.fixtures import sample` works

__all__ = ["sample"]
