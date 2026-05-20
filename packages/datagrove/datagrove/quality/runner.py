"""Run registered :class:`Rule`s against a package and collect issues.

Thin orchestrator: lazily triggers entry-point discovery, walks the
registry, respects per-rule :class:`RuleConfig`, and accumulates issues
into a :class:`~datagrove.reports.ValidationReport`. No parallelism, no
progress; rules do their own work via the lazy ``Package`` / ``Table`` API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datagrove.reports import Severity, ValidationReport

from .base import RuleConfig
from .registry import _registry, discover_rules

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datagrove.dataset import Package

__all__ = ["run_quality"]


def run_quality(
    package: Package,
    *,
    config: dict[str, RuleConfig] | None = None,
    report: ValidationReport | None = None,
) -> ValidationReport:
    """Run all registered quality rules on ``package``.

    Skips rules where :attr:`RuleConfig.enabled` is ``False`` or
    :meth:`Rule.applies_to` returns ``False``. Applies
    :attr:`RuleConfig.severity_override` post-hoc by rewriting the
    severity of every issue the rule emitted in this call.

    Args:
        package: The data package to evaluate. Opaque to the framework;
            rules consume it via the lazy ``Package`` / ``Table`` API.
        config: Optional per-rule config keyed by :attr:`Rule.code`.
            Missing keys use :class:`RuleConfig` defaults.
        report: Existing report to append issues to. When ``None``, a
            fresh :class:`ValidationReport` is constructed.

    Returns:
        The (possibly newly constructed) report, populated with one
        :class:`~datagrove.reports.Issue` per rule violation.
    """
    discover_rules()
    cfg = config or {}
    out = report if report is not None else ValidationReport()

    for code, rule in list(_registry.items()):
        rc = cfg.get(code, RuleConfig())
        if not rc.enabled:
            continue
        if not rule.applies_to(package):
            continue
        before = len(out.issues)
        rule.run(package, out)
        if rc.severity_override is not None:
            _override_severity(out, start=before, new=rc.severity_override)

    return out


def _override_severity(report: ValidationReport, *, start: int, new: Severity) -> None:
    """Rewrite ``report.issues[start:]`` to use ``new`` severity (Issue is frozen)."""
    from dataclasses import replace

    for i in range(start, len(report.issues)):
        report.issues[i] = replace(report.issues[i], severity=new)
