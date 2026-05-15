"""Generic CLI for working with any Frictionless data package.

Commands: validate, convert, info, scope (bbox/polygon/geometry-buffer
only — network-aware scope is domain-specific), describe.

Entry point: ``datagrove = datagrove.cli.app:app``.

Domain packages (e.g. ``gmnspy``) extend this typer app via the plugin
pattern so users get one unified command surface while the generic
commands remain reusable across data specifications.
"""
