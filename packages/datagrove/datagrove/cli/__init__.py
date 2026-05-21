"""Generic CLI for working with any Frictionless data package.

Phase 4 task 4.1a (this module) ships the foundation: the
:func:`build_app` factory + an ``app`` singleton wired to the
``datagrove`` console-script entry point + two commands (``validate``,
``info``) that prove the pattern. Subsequent Phase 4 tasks layer on
``convert`` / ``scope`` / ``describe``.

Every command honours ``--json`` (machine-readable single-document
stdout for agents) and ``--yes/-y`` (auto-approve gated ops; same as
``DATAGROVE_AUTO_APPROVE=1``). See :mod:`datagrove.cli.prompts` for
the approval-gating semantics.

Domain packages extend this CLI by calling :func:`build_app` then
attaching their own commands — that's how :mod:`gmnspy.cli` adds the
GMNS-aware commands onto the same surface.
"""

from .app import app, build_app
from .prompts import (
    AUTO_APPROVE_ENV_VAR,
    is_auto_approve,
    prompt_approval,
    run_with_approval,
)
from .render import console, render_dict, render_issues, render_table

__all__ = [
    "AUTO_APPROVE_ENV_VAR",
    "app",
    "build_app",
    "console",
    "is_auto_approve",
    "prompt_approval",
    "render_dict",
    "render_issues",
    "render_table",
    "run_with_approval",
]
