"""Tests for the generic data-quality rule framework (task 3.11a / issue #79)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from datagrove.quality import (
    Rule,
    RuleConfig,
    discover_rules,
    get_rule,
    list_rules,
    register_rule,
    run_quality,
)
from datagrove.quality.registry import _registry, _reset_for_tests
from datagrove.reports import Category, Severity, ValidationReport

# ---------------------------------------------------------------------------
# Test rules (concrete Rule-protocol implementations)
# ---------------------------------------------------------------------------


@dataclass
class _FakeRule:
    """Concrete Rule used in tests; emits one fixed Issue on run()."""

    code: str = "test.always_fires"
    description: str = "Always emits one DATA_QUALITY issue."
    severity: Severity = Severity.WARNING
    applies: bool = True
    calls: list[str] = field(default_factory=list)

    def applies_to(self, package: Any) -> bool:
        self.calls.append("applies_to")
        return self.applies

    def run(self, package: Any, report: ValidationReport) -> None:
        self.calls.append("run")
        report.add(
            severity=self.severity,
            category=Category.DATA_QUALITY,
            code=self.code,
            message=f"{self.code} fired",
        )


@pytest.fixture(autouse=True)
def _clear_registry(monkeypatch):
    """Each test starts with an empty registry + a no-op entry-point walk by default.

    The entry-point default is a no-op so that any sibling distribution
    declaring a ``datagrove.quality.rules`` group (e.g. the installed
    ``gmnspy`` package at dev time) does not leak its rules into the
    registry on the first :func:`run_quality` call. Tests that
    explicitly exercise discovery use their own ``with patch(...)``
    block which shadows this default for the duration of the call.
    """
    _reset_for_tests()
    monkeypatch.setattr("datagrove.quality.registry.entry_points", lambda *, group: [])
    yield
    _reset_for_tests()


# ---------------------------------------------------------------------------
# Rule protocol
# ---------------------------------------------------------------------------


def test_fake_rule_satisfies_rule_protocol():
    """A concrete dataclass with the right attributes is a structural Rule."""
    rule: Rule = _FakeRule()
    assert rule.code == "test.always_fires"
    assert rule.severity is Severity.WARNING


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_register_and_list_rule():
    register_rule(_FakeRule(code="q.alpha"))
    assert "q.alpha" in list_rules()
    assert get_rule("q.alpha").code == "q.alpha"


def test_register_rule_is_idempotent_on_same_code():
    """Registering the same code twice replaces silently (no duplicate listings)."""
    register_rule(_FakeRule(code="q.alpha"))
    register_rule(_FakeRule(code="q.alpha"))
    assert list_rules().count("q.alpha") == 1


def test_get_rule_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        get_rule("not.registered")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_run_quality_emits_issues_into_report():
    register_rule(_FakeRule(code="q.alpha"))
    report = run_quality(package=object())
    issues = report.by_category(Category.DATA_QUALITY)
    assert len(issues) == 1
    assert issues[0].code == "q.alpha"


def test_run_quality_skips_disabled_rules():
    rule = _FakeRule(code="q.disabled")
    register_rule(rule)
    config = {"q.disabled": RuleConfig(enabled=False)}
    report = run_quality(package=object(), config=config)
    assert report.count() == 0
    assert "run" not in rule.calls


def test_run_quality_skips_rule_when_applies_to_false():
    rule = _FakeRule(code="q.does_not_apply", applies=False)
    register_rule(rule)
    report = run_quality(package=object())
    assert report.count() == 0
    assert "applies_to" in rule.calls
    assert "run" not in rule.calls


def test_run_quality_applies_severity_override():
    register_rule(_FakeRule(code="q.warn", severity=Severity.WARNING))
    config = {"q.warn": RuleConfig(severity_override=Severity.INFO)}
    report = run_quality(package=object(), config=config)
    [issue] = report.issues
    assert issue.severity is Severity.INFO


def test_run_quality_appends_to_existing_report():
    """A caller may pass an existing ValidationReport (e.g. one with schema issues)."""
    register_rule(_FakeRule(code="q.alpha"))
    existing = ValidationReport(spec_version="0.97", source="x")
    existing.add(
        severity=Severity.ERROR,
        category=Category.SCHEMA,
        code="schema.required",
        message="seed",
    )
    out = run_quality(package=object(), report=existing)
    assert out is existing
    assert out.count() == 2  # seed + quality issue


# ---------------------------------------------------------------------------
# Entry-point discovery
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """Stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, factory):
        self.name = name
        self._factory = factory

    def load(self):
        return self._factory


def test_discover_rules_registers_from_entry_points():
    """discover_rules() walks the datagrove.quality.rules group and registers."""

    def _factory():
        return [_FakeRule(code="q.from_entry")]

    fake_eps = [_FakeEntryPoint("gmnspy", _factory)]

    def _entry_points_mock(*, group):
        assert group == "datagrove.quality.rules"
        return fake_eps

    with patch("datagrove.quality.registry.entry_points", _entry_points_mock):
        discover_rules()

    assert "q.from_entry" in list_rules()


def test_discover_rules_is_idempotent():
    """Calling discover_rules() twice does not duplicate registrations."""

    def _factory():
        return [_FakeRule(code="q.from_entry")]

    fake_eps = [_FakeEntryPoint("gmnspy", _factory)]

    def _entry_points_mock(*, group):
        return fake_eps

    with patch("datagrove.quality.registry.entry_points", _entry_points_mock):
        discover_rules()
        discover_rules()

    assert list_rules().count("q.from_entry") == 1


def test_run_quality_triggers_entry_point_discovery_once():
    """First run_quality() call auto-discovers; second does not re-walk EPs."""
    call_count = {"n": 0}

    def _factory():
        return [_FakeRule(code="q.auto")]

    def _entry_points_mock(*, group):
        call_count["n"] += 1
        return [_FakeEntryPoint("gmnspy", _factory)]

    with patch("datagrove.quality.registry.entry_points", _entry_points_mock):
        run_quality(package=object())
        run_quality(package=object())

    assert call_count["n"] == 1
    # Registry holds the auto-discovered rule
    assert "q.auto" in _registry
