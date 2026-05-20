"""GMNS data-quality rule pack — entry-point registered into :mod:`datagrove.quality`.

Re-exports the rule classes + the :func:`register_all` factory wired
as the ``datagrove.quality.rules`` entry point for the ``gmnspy``
distribution (see ``packages/gmnspy/pyproject.toml``).

Once :mod:`datagrove.quality` runs entry-point discovery on its first
:func:`~datagrove.quality.run_quality` call, every rule in this module
becomes available via ``datagrove.quality.list_rules()`` and runs
against any GMNS :class:`Network` passed to ``run_quality(net)``.

Direct invocation (without the entry-point dance) is supported for
tests + ad-hoc scripts:

    >>> from gmnspy.quality import register_all
    >>> rules = register_all()
    >>> len(rules) >= 7
    True
"""

from .rules import (
    DisconnectedComponentsRule,
    DuplicateNearNodesRule,
    HighSpeedResidentialRule,
    ImplausibleVcRule,
    LaneCountMismatchRule,
    MissingCriticalFieldsRule,
    SharpAngleBendsRule,
    register_all,
)

__all__ = [
    "DisconnectedComponentsRule",
    "DuplicateNearNodesRule",
    "HighSpeedResidentialRule",
    "ImplausibleVcRule",
    "LaneCountMismatchRule",
    "MissingCriticalFieldsRule",
    "SharpAngleBendsRule",
    "register_all",
]
