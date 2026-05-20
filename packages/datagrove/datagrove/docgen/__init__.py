"""Documentation generators: markdown, llms.txt, machine-readable api-index.json.

Architecture §6.9 (AI accessibility). The three generators in
:mod:`datagrove.docgen.llms` produce static artifacts consumed by AI
agents — emitted at ``mkdocs build`` time via the project's mkdocs
``main.py`` hook.
"""

from .llms import (
    API_INDEX_SCHEMA_VERSION,
    generate_api_index_json,
    generate_llms_full_txt,
    generate_llms_txt,
)

__all__ = [
    "API_INDEX_SCHEMA_VERSION",
    "generate_api_index_json",
    "generate_llms_full_txt",
    "generate_llms_txt",
]
