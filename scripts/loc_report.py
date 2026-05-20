#!/usr/bin/env python3
"""LOC report that separates code from docstrings.

AST-based — uses ``ast.get_docstring`` on every module / class / function
node to identify docstring spans exactly. Counts lines as one of:

- ``docstring``: lines inside a docstring (module / class / function / method)
- ``comment``: lines starting with ``#`` (after leading whitespace)
- ``blank``: empty / whitespace-only
- ``code``: everything else

Why not ruff/cloc/radon: ruff has no LOC mode; cloc treats docstrings as
comments (not separately countable); radon's ``multi`` bucket lumps all
multi-line strings together. For our "is the bloat docstrings or
algorithm?" question we want docstrings called out specifically.

Usage:
    uv run python scripts/loc_report.py packages/datagrove/datagrove/validation/*.py
    uv run python scripts/loc_report.py --recursive packages/datagrove/datagrove/
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def docstring_line_spans(tree: ast.Module) -> set[int]:
    """Return the set of 1-indexed line numbers that fall inside a docstring."""
    spans: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if ast.get_docstring(node) is None:
            continue
        # The docstring is the first statement in the body. It's an Expr
        # wrapping a Constant (string).
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Constant):
            continue
        # Inclusive on both ends.
        for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
            spans.add(ln)
    return spans


def classify(path: Path) -> dict[str, int]:
    src = path.read_text()
    lines = src.splitlines()
    tree = ast.parse(src, filename=str(path))
    doc_lines = docstring_line_spans(tree)

    counts = {"code": 0, "docstring": 0, "comment": 0, "blank": 0}
    for i, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if i in doc_lines:
            counts["docstring"] += 1
        elif not stripped:
            counts["blank"] += 1
        elif stripped.startswith("#"):
            counts["comment"] += 1
        else:
            counts["code"] += 1
    counts["total"] = len(lines)
    return counts


def iter_paths(roots: list[Path], recursive: bool) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            out.append(root)
        elif root.is_dir() and recursive:
            out.extend(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))
        elif root.is_dir():
            out.extend(sorted(root.glob("*.py")))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories")
    parser.add_argument("-r", "--recursive", action="store_true", help="recurse into directories")
    parser.add_argument(
        "--by",
        choices=["file", "dir", "total"],
        default="file",
        help="aggregation level (default: file)",
    )
    args = parser.parse_args(argv)

    paths = iter_paths(args.paths, args.recursive)
    if not paths:
        print("no .py files found", file=sys.stderr)
        return 1

    if args.by == "file":
        rows = [(str(p), classify(p)) for p in paths]
    elif args.by == "dir":
        agg: dict[str, dict[str, int]] = {}
        for p in paths:
            key = str(p.parent)
            d = agg.setdefault(key, {"code": 0, "docstring": 0, "comment": 0, "blank": 0, "total": 0})
            for k, v in classify(p).items():
                d[k] += v
        rows = sorted(agg.items())
    else:  # total
        total = {"code": 0, "docstring": 0, "comment": 0, "blank": 0, "total": 0}
        for p in paths:
            for k, v in classify(p).items():
                total[k] += v
        rows = [("TOTAL", total)]

    label_w = max(len(r[0]) for r in rows) if rows else 10
    header = f"{'path':<{label_w}}  {'total':>6}  {'code':>6}  {'doc':>6}  {'comm':>6}  {'blank':>6}  {'doc%':>5}"
    print(header)
    print("-" * len(header))
    for label, c in rows:
        non_blank = c["total"] - c["blank"]
        doc_pct = (c["docstring"] / non_blank * 100) if non_blank else 0
        print(
            f"{label:<{label_w}}  {c['total']:>6}  {c['code']:>6}  {c['docstring']:>6}  "
            f"{c['comment']:>6}  {c['blank']:>6}  {doc_pct:>4.0f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
