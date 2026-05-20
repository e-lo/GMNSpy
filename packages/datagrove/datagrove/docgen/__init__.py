"""Documentation generators for human + AI consumers.

Architecture §6.9. Two clusters of generators:

* :mod:`datagrove.docgen.markdown` — v1.0 port of the v0.3
  ``gmnspy.schema.document_*_to_md`` functions, now generic over the
  spec model. Used by the mkdocs site for human-readable spec pages.
* :mod:`datagrove.docgen.llms` — AI-consumable static artifacts
  (``llms.txt``, ``llms-full.txt``, ``ai/api-index.json``) emitted at
  ``mkdocs build`` time via the project's mkdocs ``main.py`` hook.
"""

from .llms import (
    API_INDEX_SCHEMA_VERSION,
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
)
from .markdown import field_to_md_row, package_to_md, schemas_to_md

__all__ = [
    "API_INDEX_SCHEMA_VERSION",
    "field_to_md_row",
    "generate_api_index_json",
    "generate_llms_full_txt",
    "generate_llms_txt",
    "package_to_md",
    "schemas_to_md",
]
