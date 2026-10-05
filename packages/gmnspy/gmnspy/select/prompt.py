"""What the selection parser tells the model besides the utterance.

:class:`PromptContext` carries the optional parts, each switched by ``llm.quality``:

* the shipped GMNS assistant guide and the project's notes (:mod:`gmnspy.llm.context`);
* grounding vocabulary: the active network's most common street names and route numbers;
* few-shot examples: this session's earlier selections that resolved;
* a one-off hint, e.g. the closest real names after a facility didn't match (:func:`close_match_hint`).

:func:`render_prompt` splits them into a stable prefix (cacheable: it only changes when the network
or the settings do) and a per-call remainder.
"""

from __future__ import annotations

import difflib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .intent import SelectionIntent

__all__ = ["PromptContext", "close_match_hint", "render_prompt", "vocabulary_from_links"]


@dataclass(frozen=True)
class PromptContext:
    """Everything beyond the utterance that a selection prompt may carry (each part optional)."""

    assistant: str = ""
    project: str = ""
    vocabulary: tuple[str, ...] = ()
    examples: tuple[tuple[str, dict[str, Any]], ...] = ()
    hint: str = ""


def render_prompt(context: PromptContext, system_prompt: str) -> tuple[str, str]:
    r"""``(stable, per_call)`` system text: the cacheable prefix, then examples and hints.

    Examples:
        >>> render_prompt(PromptContext(vocabulary=("I 40",), hint="Try again."), "Be brief.")
        ('Be brief.\n\nStreet names and route numbers in the active network:\nI 40', 'Try again.')
    """
    stable = [system_prompt, context.assistant, context.project]
    if context.vocabulary:
        stable.append("Street names and route numbers in the active network:\n" + "\n".join(context.vocabulary))
    per_call = []
    if context.examples:
        shots = "\n\n".join(
            f"Request: {utterance}\nTool input: {json.dumps(payload, sort_keys=True)}"
            for utterance, payload in context.examples
        )
        per_call.append(f"Earlier requests in this session that selected the right links:\n\n{shots}")
    if context.hint:
        per_call.append(context.hint)
    return "\n\n".join(part for part in stable if part), "\n\n".join(per_call)


def vocabulary_from_links(links: Any, max_names: int) -> tuple[str, ...]:
    """The ``max_names`` most frequent route numbers (``ref``) and street names (``name``) in ``links``."""
    counts: Counter[str] = Counter()
    for column in ("ref", "name"):
        if column in links.columns:
            counts.update(text for text in (str(v).strip() for v in links[column].dropna()) if text)
    return tuple(name for name, _ in counts.most_common(max_names))


def close_match_hint(intent: SelectionIntent, vocabulary: tuple[str, ...], max_candidates: int) -> str:
    """A re-prompt hint naming the closest real names for each facility/anchor name not in ``vocabulary``.

    Empty when every name is known, nothing is close, or there is no vocabulary (grounding off).

    Examples:
        >>> from gmnspy.select.intent import Facility
        >>> intent = SelectionIntent(facility=Facility(name="Airport Blvd"))
        >>> print(close_match_hint(intent, ("Airport Boulevard", "Page Road"), 3))
        The active network has no roadway called 'Airport Blvd'. Closest names: Airport Boulevard.
        If the user meant one of these, use its exact spelling.
    """
    if not vocabulary:
        return ""
    by_folded = {name.casefold(): name for name in vocabulary}
    wanted: list[str] = []
    if intent.facility is not None:
        wanted += [str(v) for v in (*intent.facility.refs(), *intent.facility.names())]
    wanted += [a for a in (intent.from_anchor, intent.to_anchor) if a]
    lines = []
    for name in wanted:
        if name.casefold() in by_folded:
            continue
        close = difflib.get_close_matches(name.casefold(), list(by_folded), n=max_candidates, cutoff=0.5)
        if close:
            names = ", ".join(by_folded[c] for c in close)
            lines.append(f"The active network has no roadway called {name!r}. Closest names: {names}.")
    if not lines:
        return ""
    return "\n".join([*lines, "If the user meant one of these, use its exact spelling."])
