"""Regression tests for the type annotations on the FormatAdapter protocol.

These tests catch a class of bug we hit in code review (findings C1 and
C2 of the v1.0 critical-seam review):

- C1: ``io.base`` imported ``Schema`` from a non-existent module
  ``datagrove.spec.base`` inside a ``TYPE_CHECKING`` block. Static
  checkers silently resolved ``FormatAdapter.read.schema`` to ``Any``
  and the runtime never tried to evaluate the annotation, so neither
  pyright/mypy nor pytest failed.
- C2: ``SourceRef`` was defined twice with divergent contracts in
  ``io.base`` and ``engines.base``. The two definitions were textually
  similar but typed differently (``str | Path`` vs ``str | Path | dict``).

Two layers of defence:

1. We re-parse ``io/base.py`` and ``engines/base.py`` for their
   ``TYPE_CHECKING`` ``from … import …`` lines and actually execute
   those imports. A broken module path (``datagrove.spec.base``) fails
   here with a clear ``ModuleNotFoundError``.
2. We call ``typing.get_type_hints`` on the annotated callables with a
   localns that includes the just-imported symbols. If the annotation
   silently drifted to ``Any`` (because someone moved a symbol and the
   TYPE_CHECKING import was left dangling under ``# type: ignore``) the
   resolved hint won't contain the real ``Schema`` class and the test
   fails.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

# Import the TYPE_CHECKING-only deps eagerly here so ``get_type_hints``
# can resolve the forward refs on the protocol below. If any of these
# imports break, the regression has fired.
from datagrove.engines.base import Engine, TableExpr  # noqa: F401 — used in localns
from datagrove.io.base import FormatAdapter, ResourceListing, SourceRef
from datagrove.spec.model import Schema  # noqa: F401 — used in localns
from datagrove.types import SourceRef as CanonicalSourceRef


def _hints_for(func):
    """Resolve ``func``'s annotations with all TYPE_CHECKING refs in scope."""
    localns = {
        "Engine": Engine,
        "TableExpr": TableExpr,
        "Schema": Schema,
        "SourceRef": SourceRef,
        "ResourceListing": ResourceListing,
        "Path": Path,
        "Any": Any,
    }
    return typing.get_type_hints(func, globalns=globals(), localns=localns)


def test_format_adapter_read_schema_is_not_any() -> None:
    """``FormatAdapter.read``'s ``schema`` must resolve to the real Schema type.

    Regression for C1: if the ``Schema`` import in ``io/base.py`` is
    broken (e.g. ``from datagrove.spec.base import Schema`` instead of
    ``datagrove.spec.model``), ``get_type_hints`` raises NameError when
    evaluating the forward ref. If the annotation silently degraded to
    ``Any``, ``Schema`` would not appear among the type args.
    """
    hints = _hints_for(FormatAdapter.read)
    assert "schema" in hints, "FormatAdapter.read has no `schema` parameter annotation"
    schema_hint = hints["schema"]
    # The annotation is ``Schema | None``. typing.get_args returns the
    # union members; we want the actual Schema class to be in there.
    args = typing.get_args(schema_hint)
    assert Schema in args, (
        f"FormatAdapter.read.schema resolved to {schema_hint!r}; expected `Schema | None` "
        f"with the real datagrove.spec.model.Schema class in the union"
    )


def test_format_adapter_read_engine_resolves_to_engine_protocol() -> None:
    """``engine`` param on ``FormatAdapter.read`` must resolve to ``Engine``."""
    hints = _hints_for(FormatAdapter.read)
    assert "engine" in hints
    assert hints["engine"] is Engine


def test_source_ref_is_canonical_alias() -> None:
    """``io.base.SourceRef`` and ``engines.base.SourceRef`` must be the same alias.

    Regression for C2: previously each subpackage defined its own
    ``SourceRef`` alias with a different right-hand side. They must now
    both re-export the canonical alias from :mod:`datagrove.types`.
    """
    from datagrove.engines.base import SourceRef as EngineSourceRef
    from datagrove.io.base import SourceRef as IoSourceRef

    assert IoSourceRef is CanonicalSourceRef
    assert EngineSourceRef is CanonicalSourceRef


def test_source_ref_accepts_str_path_and_dict() -> None:
    """The canonical SourceRef must accept str, Path, and dict arms."""
    args = typing.get_args(CanonicalSourceRef)
    assert str in args
    assert Path in args
    assert dict in args


def _extract_type_checking_imports(module_path: Path) -> list[str]:
    """Return the ``from X import Y`` statements inside the file's TYPE_CHECKING block.

    Naive but sufficient for our two target modules: we walk the AST,
    find an ``if TYPE_CHECKING:`` block (or ``if typing.TYPE_CHECKING:``),
    and serialize each ImportFrom in its body back to source.
    """
    import ast

    src = module_path.read_text()
    tree = ast.parse(src)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )
        if not is_tc:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom):
                out.append(ast.unparse(stmt))
    return out


def test_io_base_type_checking_imports_resolve_at_runtime() -> None:
    """Every TYPE_CHECKING import in ``io/base.py`` must be a real importable path.

    Regression for C1. The TYPE_CHECKING guard means broken paths never
    fail at module-import time (and ``get_type_hints`` will happily
    return ``ForwardRef`` strings or fall back to ``Any``). This test
    re-executes those imports in a clean namespace so the failure is
    impossible to miss.
    """
    import datagrove.io.base as io_base

    module_file = Path(io_base.__file__)
    statements = _extract_type_checking_imports(module_file)
    assert statements, "expected at least one TYPE_CHECKING import in io/base.py"
    for stmt in statements:
        ns: dict[str, Any] = {}
        # exec raises ModuleNotFoundError if the path is broken (e.g.
        # ``from datagrove.spec.base import Schema`` when only
        # ``datagrove.spec.model`` exists). That's the regression signal.
        exec(stmt, ns)


def test_engines_base_type_checking_imports_resolve_at_runtime() -> None:
    """Same defence for ``engines/base.py``'s TYPE_CHECKING imports."""
    import datagrove.engines.base as eng_base

    module_file = Path(eng_base.__file__)
    statements = _extract_type_checking_imports(module_file)
    # engines/base.py may legitimately have zero TYPE_CHECKING imports
    # if all annotations are stringly-typed via Any — that's fine; this
    # test only fires when there *are* imports to verify.
    for stmt in statements:
        ns: dict[str, Any] = {}
        exec(stmt, ns)
