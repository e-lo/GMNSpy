"""Resource package for the interactive HTML renderer.

The .j2 / .css / .js siblings of this file are read via
:mod:`importlib.resources` at render time and inlined into the produced
single-file HTML report. Splitting them into separate files (rather than
inlining 250 lines of CSS into a Python string) is a deliberate Lens-C
legibility call: a designer can edit ``report.css`` in their editor with
syntax highlighting, and a reader can grep the JS without parsing Python
string escaping.
"""
