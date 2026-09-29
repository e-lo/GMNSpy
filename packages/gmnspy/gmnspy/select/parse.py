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

__all__ = ["Parser", "StubParser", "ClaudeParser", "INTENT_TOOL"]

_DIR_WORDS = {
    "eb": "EB", "eastbound": "EB", "wb": "WB", "westbound": "WB",
    "nb": "NB", "northbound": "NB", "sb": "SB", "southbound": "SB",
}
# route ref like "I-40", "US 1", "NC 54", "SR-147"
_REF_RE = re.compile(r"^(?:I|US|SR|NC|CR|SH|CA|TX)[-\s]?\d+$", re.IGNORECASE)


@runtime_checkable
class Parser(Protocol):
    def parse(self, utterance: str) -> SelectionIntent: ...


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
        text = utterance.strip()
        m = re.search(r"\bbetween\b(.*)\band\b(.*)$", text, re.IGNORECASE)
        if not m:
            raise IntentError(f"could not parse a 'between A and B' selection from {utterance!r}")
        head = text[: m.start()].strip()
        from_anchor = self._clean_anchor(m.group(1))
        to_anchor = self._clean_anchor(m.group(2))

        direction = None
        tokens = head.split()
        if tokens and tokens[-1].lower() in _DIR_WORDS:
            direction = _DIR_WORDS[tokens[-1].lower()]
            head = " ".join(tokens[:-1]).strip()

        facility = _facility_from_text(head)
        return SelectionIntent(
            facility=Facility(ref=facility.ref, name=facility.name, direction=direction),
            from_anchor=from_anchor, to_anchor=to_anchor, utterance=utterance,
        )

    @staticmethod
    def _clean_anchor(text: str) -> str:
        cleaned = re.sub(r"\b(exits?|interchanges?|ramps?)\b", "", text, flags=re.IGNORECASE)
        return cleaned.strip(" ,.")


#: Anthropic tool schema constraining the model to emit a SelectionIntent.
INTENT_TOOL: dict[str, Any] = {
    "name": "emit_selection_intent",
    "description": "Return the structured network selection described by the user. "
                   "Never invent link or node ids; only describe the facility and anchors.",
    "input_schema": {
        "type": "object",
        "required": ["facility", "from_anchor", "to_anchor"],
        "properties": {
            "facility": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "Route number e.g. 'I 40', 'NC 54'."},
                    "name": {"type": "string", "description": "Street name if not a numbered route."},
                    "direction": {"type": "string", "enum": ["EB", "WB", "NB", "SB"]},
                },
            },
            "from_anchor": {"type": "string", "description": "Upstream cross-street/interchange."},
            "to_anchor": {"type": "string", "description": "Downstream cross-street/interchange."},
        },
    },
}


class ClaudeParser:
    """Parse via the Anthropic Messages API using tool-use structured output."""

    def __init__(self, client: Any = None, model: str = "claude-sonnet-5") -> None:
        if client is None:  # pragma: no cover - exercised only with a real key
            import anthropic  # lazy: optional dependency

            client = anthropic.Anthropic()
        self._client = client
        self._model = model

    def parse(self, utterance: str) -> SelectionIntent:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=512,
            tools=[INTENT_TOOL],
            tool_choice={"type": "tool", "name": INTENT_TOOL["name"]},
            messages=[{"role": "user", "content": utterance}],
        )
        payload = self._extract_tool_input(resp)
        fac = payload.get("facility", {})
        return SelectionIntent(
            facility=Facility(ref=fac.get("ref"), name=fac.get("name"), direction=fac.get("direction")),
            from_anchor=payload["from_anchor"], to_anchor=payload["to_anchor"], utterance=utterance,
        )

    @staticmethod
    def _extract_tool_input(resp: Any) -> dict:
        for block in getattr(resp, "content", []):
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise IntentError("model returned no tool_use block for the selection intent")
