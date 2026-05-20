"""Documentation generators: markdown, llms.txt, machine-readable api-index.json.

The markdown generators (:mod:`datagrove.docgen.markdown`) are the v1.0
port of the v0.3 ``gmnspy.schema.document_*_to_md`` functions, now
generic over the spec model and free of the pandas / frictionless
dependencies the legacy path needed. ``llms.txt`` / ``api-index.json``
generation lives alongside in sibling modules (task 3.5).
"""

from .markdown import field_to_md_row, package_to_md, schemas_to_md

__all__ = ["field_to_md_row", "package_to_md", "schemas_to_md"]
