"""SelectionIntent — the structured, validated request the parser emits.

The LLM (or a stub) produces a :class:`SelectionIntent`; it never produces
link/node ids. Resolution against a network happens downstream in
:mod:`gmnspy.select.resolve`.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import IntentError

__all__ = ["Facility", "SelectionIntent", "DIRECTIONS"]

#: Recognised travel directions on a facility.
DIRECTIONS = frozenset({"EB", "WB", "NB", "SB"})


@dataclass(frozen=True)
class Facility:
    """The named route to select along.

    At least one of ``ref`` (route number, e.g. ``"I 40"``) or ``name``
    (street name, e.g. ``"Main Street"``) must be given. ``direction`` is one
    of :data:`DIRECTIONS` or ``None`` when unspecified.
    """

    ref: str | None = None
    name: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class SelectionIntent:
    """A validated, structured selection request.

    Attributes:
        facility: The route to select along.
        from_anchor / to_anchor: Human anchor descriptions (cross-streets,
            interchanges) bounding the selection.
        utterance: The cleaned natural-language request, retained for the
            output ``notes`` field.
    """

    facility: Facility
    from_anchor: str
    to_anchor: str
    utterance: str | None = None

    def __post_init__(self) -> None:
        if not (self.facility.ref or self.facility.name):
            raise IntentError("facility requires a 'ref' or a 'name'")
        d = self.facility.direction
        if d is not None and d not in DIRECTIONS:
            raise IntentError(f"direction {d!r} not one of {sorted(DIRECTIONS)}")
        for label, anchor in (("from_anchor", self.from_anchor), ("to_anchor", self.to_anchor)):
            if not anchor or not anchor.strip():
                raise IntentError(f"{label} must be a non-empty string")
