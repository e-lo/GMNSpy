"""Generic notebook helpers.

``_repr_html_`` implementations for ``Package``, ``Table``,
``ValidationReport``, and ``EditResult``, plus a notebook-aware progress
wrapper.

Domain packages extend by composition (e.g. ``gmnspy.notebook`` adds
``Network._repr_html_`` and GMNS-specific scope widgets).
"""
