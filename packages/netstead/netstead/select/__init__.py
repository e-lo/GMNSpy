"""Natural-language selection of GMNS network elements.

Pipeline: ``parse`` (utterance -> :class:`SelectionIntent`) -> ``resolve``
(intent + network -> :class:`SelectionResult`) -> ``emit`` (result ->
validated GMNS selection fragment). Selection only; no edit is applied.
"""

from __future__ import annotations

from .emit import to_fragment, to_projectcard, validate_fragment
from .intent import DIRECTIONS, Facility, SelectionIntent
from .parse import ClaudeParser, LLMParser, Parser, StubParser, make_parser
from .resolve import resolve, resolve_frames
from .result import AnchorMatch, SelectionResult

__all__ = [
    "DIRECTIONS",
    "AnchorMatch",
    "ClaudeParser",
    "Facility",
    "LLMParser",
    "Parser",
    "SelectionIntent",
    "SelectionResult",
    "StubParser",
    "make_parser",
    "resolve",
    "resolve_frames",
    "to_fragment",
    "to_projectcard",
    "validate_fragment",
]
