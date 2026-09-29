"""Emit a resolved SelectionResult as a validated GMNS selection fragment.

The v1 artifact is a *fragment* (a ``facility`` object), keyed by GMNS-native
``link_id`` / ``node_id`` and validated against
``schema/gmns_selection.schema.json``. :func:`to_projectcard` adapts it to
ProjectCard's ``model_link_id`` / ``model_node_id`` for interop/export; the
fragment drops into a ProjectCard change's ``facility`` slot when the (later)
edit feature exists.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

import jsonschema

from .errors import SelectError
from .result import SelectionResult

__all__ = ["to_fragment", "validate_fragment", "to_projectcard", "load_schema"]


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Load and cache the GMNS selection JSON schema."""
    text = resources.files(__package__).joinpath("schema/gmns_selection.schema.json").read_text()
    return json.loads(text)


def to_fragment(result: SelectionResult) -> dict[str, Any]:
    """Build the GMNS-native selection fragment from a *resolved* result.

    Raises:
        SelectError: if ``result.status`` is not ``"resolved"``.
    """
    if result.status != "resolved":
        raise SelectError(f"cannot emit a fragment from status {result.status!r}; expected 'resolved'")
    frag: dict[str, Any] = {"links": {"link_id": list(result.link_ids)}}
    if result.from_match and result.from_match.node_id is not None:
        frag["from"] = {"node_id": result.from_match.node_id}
    if result.to_match and result.to_match.node_id is not None:
        frag["to"] = {"node_id": result.to_match.node_id}
    if result.intent.utterance:
        frag["notes"] = result.intent.utterance
    return frag


def validate_fragment(fragment: dict) -> None:
    """Validate a fragment against the GMNS selection schema. Raises on invalid."""
    jsonschema.validate(fragment, load_schema())


def to_projectcard(result: SelectionResult) -> dict[str, Any]:
    """Adapt the GMNS fragment to a ProjectCard roadway-selection facility object."""
    frag = to_fragment(result)
    pc: dict[str, Any] = {"links": {"model_link_id": frag["links"]["link_id"]}}
    if "from" in frag:
        pc["from"] = {"model_node_id": frag["from"]["node_id"]}
    if "to" in frag:
        pc["to"] = {"model_node_id": frag["to"]["node_id"]}
    return pc
