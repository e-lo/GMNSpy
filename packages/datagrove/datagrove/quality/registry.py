"""In-process rule registry + entry-point plugin discovery.

Registry is a module-level dict keyed by :attr:`Rule.code`; re-registration
replaces silently. Discovery walks the ``datagrove.quality.rules`` group;
each loaded callable returns a list of :class:`Rule` instances. Idempotent
and lazy — first :func:`run_quality` call triggers it.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from .base import Rule

__all__ = ["discover_rules", "get_rule", "list_rules", "register_rule"]

_log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "datagrove.quality.rules"

_registry: dict[str, Rule] = {}
_discovered: bool = False


def register_rule(rule: Rule) -> None:
    """Register ``rule`` under :attr:`rule.code` (replaces silently on dup)."""
    _registry[rule.code] = rule


def get_rule(code: str) -> Rule:
    """Return the registered rule for ``code``.

    Raises:
        KeyError: If no rule with that code is registered.
    """
    return _registry[code]


def list_rules() -> list[str]:
    """Return all registered rule codes in registration order."""
    return list(_registry)


def discover_rules() -> None:
    """Walk ``datagrove.quality.rules`` entry points and register every rule.

    Each entry point loads a zero-arg callable returning ``list[Rule]``.
    Idempotent — repeat calls short-circuit. Called once automatically
    by :func:`~datagrove.quality.run_quality`.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            factory = ep.load()
            for rule in factory():
                register_rule(rule)
        except Exception:
            _log.exception("Failed to load quality rules from entry point %r", ep.name)


def _reset_for_tests() -> None:
    """Clear registry + discovery flag. Test-only."""
    global _discovered
    _registry.clear()
    _discovered = False
