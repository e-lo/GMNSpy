"""Rule protocol and per-rule config for the generic quality framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from datagrove.reports import Severity, ValidationReport

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package

__all__ = ["Rule", "RuleConfig"]


@runtime_checkable
class Rule(Protocol):
    """A data-quality rule.

    Domain packages register concrete rules under the
    ``datagrove.quality.rules`` entry-point group. Each rule emits
    :class:`~datagrove.reports.Issue` records with
    ``category=Category.DATA_QUALITY`` into the
    :class:`~datagrove.reports.ValidationReport` it is handed.

    Attributes:
        code: Stable dotted identifier (e.g.
            ``"quality.high_speed_residential"``). Used by config lookup
            and report filters.
        description: One-line plain-English explanation.
        severity: Default severity. Callers may override via
            :attr:`RuleConfig.severity_override`.
    """

    code: str
    description: str
    severity: Severity

    def applies_to(self, package: Package) -> bool:
        """Cheap pre-check: should this rule run on this package at all?"""

    def run(self, package: Package, report: ValidationReport) -> None:
        """Execute the rule; populate ``report`` with issues."""


@dataclass(frozen=True)
class RuleConfig:
    """Per-rule configuration.

    Domain rules may define their own ``Config`` subclass with strongly
    typed thresholds; this base is sufficient for the generic framework.

    Attributes:
        enabled: Set to ``False`` to skip this rule entirely.
        severity_override: Optional severity override (e.g., demote
            ``ERROR`` to ``WARNING``).
        thresholds: Rule-specific thresholds (e.g.,
            ``{"speed_limit_mph": 45}``). Opaque to the framework — the
            rule reads its own keys.
    """

    enabled: bool = True
    severity_override: Severity | None = None
    thresholds: dict[str, Any] = field(default_factory=dict)
