"""GMNS notebook helpers.

The ``_repr_html_`` methods live directly on the public classes
(:class:`gmnspy.Network` plus everything in :mod:`datagrove.notebook`),
so no opt-in import is needed for the notebook preview. This module
re-exports the shared HTML helpers so domain-specific extensions can
build cards in the same style without reaching into
:mod:`datagrove.notebook` themselves.

Future widget additions (e.g. an ipywidgets-backed scope picker) live
here.
"""

from __future__ import annotations

from datagrove.notebook import card, escape, kv_line, small_table, truncation_note

__all__ = ["card", "escape", "kv_line", "small_table", "truncation_note"]
