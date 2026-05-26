"""Tests for :func:`gmnspy.cli._extras.require_extra`.

The helper centralises the prior 5 ad-hoc ``importlib.import_module`` +
``except ImportError`` sites in the gmnspy CLI. These tests pin its
contract so future changes (caching, version probes) don't silently
regress the install-hint UX.
"""

from __future__ import annotations

import os

import pytest
import typer
from gmnspy.cli._extras import require_extra


def test_require_extra_imports_present_module():
    """A module that is already importable returns the module object unchanged."""
    # Use a stdlib module so the test is independent of which gmnspy
    # extras the running environment happens to have installed.
    mod = require_extra("os", "anything")
    assert mod is os


def test_require_extra_exits_with_install_hint_for_missing_module(capsys: pytest.CaptureFixture[str]):
    """A missing module triggers ``typer.Exit(1)`` and a pip-install hint on stderr.

    Validates the user-facing contract: the install hint must name the
    correct extra so the user can self-serve a fix without spelunking the
    source.
    """
    with pytest.raises(typer.Exit) as exc_info:
        require_extra("nonexistent_module_xyz", "clean")
    assert exc_info.value.exit_code == 1

    captured = capsys.readouterr()
    # Suggestion lands on stderr — keeps stdout clean for --json piping.
    assert "pip install 'gmnspy[clean]'" in captured.err
    assert "nonexistent_module_xyz" in captured.err
    assert captured.out == ""


def test_require_extra_error_message_includes_underlying_import_error(capsys: pytest.CaptureFixture[str]):
    """The original ImportError text is appended so the cause is debuggable.

    Useful when the failure is something subtle (a transitive dep missing
    rather than the top-level module) — the user sees the real source of
    the failure right next to the install hint.
    """
    with pytest.raises(typer.Exit):
        require_extra("definitely_missing_module_abc", "server")

    captured = capsys.readouterr()
    # ImportError's str() typically includes "No module named '...'"
    assert "No module named" in captured.err
    assert "definitely_missing_module_abc" in captured.err
