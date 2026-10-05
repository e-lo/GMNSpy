"""Per-command modules for the netstead CLI.

Each module exposes a :func:`register` callable that wires its commands
(or sub-app) onto the parent typer app. Keeping one module per command
keeps the orchestrator in :mod:`netstead.cli.app` short and means a reader
hunting for ``netstead clean simplify-geometry`` opens ``commands/clean.py``
directly instead of scroll-searching a 900-line file.
"""
