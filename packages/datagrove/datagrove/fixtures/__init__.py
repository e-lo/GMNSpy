"""Bundled example data for datagrove's own doctests.

See :mod:`datagrove.fixtures.sample` for the canonical small generic
fixture — kept intentionally separate from any domain package (notably
``gmnspy.fixtures.leavenworth``) so the composition boundary stays
visible and the import-linter contract ``datagrove must not depend on
gmnspy`` can be enforced.
"""

from . import sample  # re-export so `from datagrove.fixtures import sample` works

__all__ = ["sample"]
