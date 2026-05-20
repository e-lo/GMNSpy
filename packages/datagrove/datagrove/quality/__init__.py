"""Generic data-quality rule framework.

Provides:

- :class:`Rule` — Protocol every domain rule satisfies.
- :class:`RuleConfig` — per-rule enable / severity / threshold knobs.
- :func:`register_rule`, :func:`get_rule`, :func:`list_rules` — in-process
  registry.
- :func:`discover_rules` — entry-point plugin walk (``datagrove.quality.rules``).
- :func:`run_quality` — orchestrator that returns a
  :class:`~datagrove.reports.ValidationReport`.

Ships **no** domain rules. ``gmnspy.quality`` registers the GMNS rule
pack via the ``datagrove.quality.rules`` entry-point group, and any
third-party package may do the same.
"""

from .base import Rule, RuleConfig
from .registry import discover_rules, get_rule, list_rules, register_rule
from .runner import run_quality

__all__ = [
    "Rule",
    "RuleConfig",
    "discover_rules",
    "get_rule",
    "list_rules",
    "register_rule",
    "run_quality",
]
