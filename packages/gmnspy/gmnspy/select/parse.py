"""Parse a natural-language utterance into a SelectionIntent.

Provider-agnostic seam:

* :class:`StubParser` — deterministic, offline; parses the constrained grammar
  ``<facility> [direction] between <A> and <B>``. Used in tests and when no
  provider is configured.
* :class:`ClaudeParser` — wraps the Anthropic Messages API with tool-use so the
  model returns a structured intent (never ids). The ``client`` is injectable
  for testing; ``anthropic`` is imported lazily so it stays an optional dep.

Both satisfy the :class:`Parser` protocol, so other providers slot in later.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from .errors import IntentError
from .intent import Facility, SelectionIntent

__all__ = ["INTENT_TOOL", "ClaudeParser", "Parser", "StubParser"]

_DIR_WORDS = {
    "eb": "EB",
    "eastbound": "EB",
    "wb": "WB",
    "westbound": "WB",
    "nb": "NB",
    "northbound": "NB",
    "sb": "SB",
    "southbound": "SB",
}
# route ref like "I-40", "US 1", "NC 54", "SR-147"
_REF_RE = re.compile(r"^(?:I|US|SR|NC|CR|SH|CA|TX)[-\s]?\d+$", re.IGNORECASE)


@runtime_checkable
class Parser(Protocol):
    """Protocol for utterance -> SelectionIntent parsers."""

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse an utterance into a validated :class:`SelectionIntent`."""
        ...


def _facility_from_text(text: str) -> Facility:
    """Interpret the facility phrase as a route ref or a street name."""
    stripped = text.strip()
    if _REF_RE.match(stripped):
        ref = re.sub(r"[-\s]+", " ", stripped).upper()  # "I-40" -> "I 40"
        return Facility(ref=ref)
    return Facility(name=stripped)


class StubParser:
    """Deterministic parser for the constrained grammar (offline/testing)."""

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse the constrained grammar into a :class:`SelectionIntent`."""
        text = utterance.strip()
        # optional segment: "<facility> [dir] between A and B" OR "... from A to B";
        # with no segment clause the whole facility is selected.
        m = re.search(r"\b(?:between|from)\b(.*)\b(?:and|to)\b(.*)$", text, re.IGNORECASE)
        if m:
            head = text[: m.start()].strip()
            from_anchor = self._clean_anchor(m.group(1))
            to_anchor = self._clean_anchor(m.group(2))
        else:
            head, from_anchor, to_anchor = text, None, None

        direction = None
        tokens = head.split()
        if tokens and tokens[-1].lower() in _DIR_WORDS:
            direction = _DIR_WORDS[tokens[-1].lower()]
            head = " ".join(tokens[:-1]).strip()
        if not head:
            raise IntentError(f"could not find a facility in {utterance!r}")

        facility = _facility_from_text(head)
        return SelectionIntent(
            facility=Facility(ref=facility.ref, name=facility.name, direction=direction),
            from_anchor=from_anchor,
            to_anchor=to_anchor,
            utterance=utterance,
        )

    @staticmethod
    def _clean_anchor(text: str) -> str:
        cleaned = re.sub(r"\b(exits?|interchanges?|ramps?)\b", "", text, flags=re.IGNORECASE)
        return cleaned.strip(" ,.")


#: Anthropic tool schema constraining the model to emit a SelectionIntent.
#: Mirrors a ProjectCard roadway facility selection (see gmnspy.select.intent).
INTENT_TOOL: dict[str, Any] = {
    "name": "emit_selection_intent",
    "description": (
        "Return the structured roadway selection the user described. Choose ONE primary "
        "selector: a facility (by name and/or ref), select_all, or explicit link_ids. Add "
        "from_anchor/to_anchor ONLY when the user wants a segment between two points; omit "
        "them to select the whole facility. Use conditions for attribute filters (e.g. "
        '"where there are 2 lanes" -> {"lanes": [2]}). Never invent link or node ids '
        "unless the user gave them explicitly."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "facility": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Route number e.g. 'I 40', 'NC 54'."},
                    "name": {"type": "string", "description": "Street/road name, e.g. 'North Harrison Ave'."},
                    "direction": {"type": "string", "enum": ["EB", "WB", "NB", "SB"]},
                },
            },
            "from_anchor": {"type": "string", "description": "Upstream cross-street/interchange (segment start)."},
            "to_anchor": {"type": "string", "description": "Downstream cross-street/interchange (segment end)."},
            "select_all": {"type": "boolean", "description": "Select every link (then narrowed by conditions/modes)."},
            "link_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Explicit link ids, only if the user gave them.",
            },
            "modes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "e.g. ['drive','bike','walk','transit'].",
            },
            "conditions": {
                "type": "object",
                "description": 'Attribute AND-filters, {column: value | [values]}, e.g. {"lanes": [2,3]}.',
            },
        },
    },
}


class ClaudeParser:
    """Parse via the Anthropic Messages API using tool-use structured output."""

    def __init__(self, client: Any = None, model: str = "claude-sonnet-5") -> None:
        """Hold the Anthropic client and model id (lazily constructed)."""
        if client is None:  # pragma: no cover - exercised only with a real key
            import anthropic  # lazy: optional dependency

            client = anthropic.Anthropic()
        self._client = client
        self._model = model

    def parse(self, utterance: str) -> SelectionIntent:
        """Parse via Anthropic tool-use structured output."""
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": INTENT_TOOL["name"]},
            messages=[{"role": "user", "content": utterance}],
        )
        payload = self._extract_tool_input(resp)
        fac = payload.get("facility") or {}
        facility = (
            Facility(ref=fac.get("ref"), name=fac.get("name"), direction=fac.get("direction"))
            if (fac.get("ref") or fac.get("name"))
            else None
        )
        return SelectionIntent(
            facility=facility,
            from_anchor=payload.get("from_anchor"),
            to_anchor=payload.get("to_anchor"),
            select_all=bool(payload.get("select_all", False)),
            link_ids=payload.get("link_ids"),
            modes=payload.get("modes"),
            conditions=payload.get("conditions") or {},
            utterance=utterance,
        )

    @staticmethod
    def _extract_tool_input(resp: Any) -> dict:
        for block in getattr(resp, "content", []):
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise IntentError("model returned no tool_use block for the selection intent")
