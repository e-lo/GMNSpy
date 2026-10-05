"""Measure how accurately a model parses the NL selection eval set (run by hand, never in CI).

    uv run --all-extras python scripts/eval_nl_selection.py --provider ollama [--model M] [--runs 3]
        [--temperature 0 | --temperature default] [--guide/--no-guide]

Each utterance in ``scripts/data/nl_eval_set.toml`` is parsed ``--runs`` times through the same
:func:`~netstead.select.parse.make_parser` the Workbench and CLI use, and the resulting
:class:`~netstead.select.intent.SelectionIntent` is checked against the expected fields. It prints
a per-utterance and total accuracy table, then the misses.

"correct" is a parse with every expected field right. "resolves" also counts a parse whose only
mistake is a street name in ``facility.ref`` or a route number in ``facility.name``: the resolver
falls back to the other column for those (see ``_facility_links`` in ``netstead/select/resolve.py``)
and selects the same links, with a diagnostic.

Options left out follow your netstead settings (``llm.quality``), so a bare run measures what the
app does today. ``--temperature default`` sends no temperature (the provider's own default).
``--guide`` / ``--no-guide`` turns the shipped assistant guide on or off. Grounding, project notes
and few-shot examples are never sent: the eval set has no network.

It calls whichever provider you name. A remote provider (anything but a local Ollama) spends real
tokens on every call: runs x utterances calls, plus repairs.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx
from netstead.config import load_settings
from netstead.llm import build_registry
from netstead.llm.context import assistant_context
from netstead.select.parse import make_parser
from netstead.select.prompt import PromptContext

EVAL_SET = Path(__file__).resolve().parent / "data" / "nl_eval_set.toml"
_ANCHORS = {"from": "from_anchor", "to": "to_anchor"}
#: llm.quality fields the command line can override -> argparse attribute.
_QUALITY_ARGS = {"temperature": "temperature", "assistant_context": "guide"}


class _Counting(httpx.BaseTransport):
    """A real transport that counts requests, so a parse that needed a repair shows up."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return self._inner.handle_request(request)


def _norm(value: Any) -> str:
    return re.sub(r"[\s\-]+", "", str(value or "")).casefold()


def _contains(values: tuple, want: str) -> bool:
    return any(_norm(v) == _norm(want) for v in values)


#: Marks a miss the resolver's ref <-> name fallback recovers.
FALLBACK = " (resolver fallback recovers)"


def check(intent, expected: dict[str, Any]) -> list[str]:
    """The fields of ``intent`` that don't match ``expected`` (empty when the parse is right).

    A ref/name swap that the resolver falls back from ends with :data:`FALLBACK`.
    """
    facility = intent.facility
    refs = facility.refs() if facility else ()
    names = facility.names() if facility else ()
    errors = []
    for key, own, other_key, other in (("ref", refs, "name", names), ("name", names, "ref", refs)):
        if key in expected and not _contains(own, expected[key]):
            swapped = _contains(other, expected[key])
            errors.append(f"{key}={list(own)}" + (f" but {other_key}={list(other)}{FALLBACK}" if swapped else ""))
    direction = facility.direction if facility else None
    if "direction" in expected and direction != expected["direction"]:
        errors.append(f"direction={direction}")
    for key, attr in _ANCHORS.items():
        got = getattr(intent, attr)
        if key in expected and not (got and _norm(expected[key]) in _norm(got)):
            errors.append(f"{attr}={got!r}")
    absent = set(expected.get("absent", ()))
    if "direction" in absent and direction is not None:
        errors.append(f"direction={direction} (want none)")
    for key in absent & _ANCHORS.keys():
        if getattr(intent, _ANCHORS[key]) is not None:
            errors.append(f"{_ANCHORS[key]}={getattr(intent, _ANCHORS[key])!r} (want none)")
    if expected.get("select_all") and not intent.select_all:
        errors.append("select_all=False")
    if "condition" in expected and expected["condition"] not in (intent.conditions or {}):
        errors.append(f"conditions={intent.conditions}")
    if "link_ids" in expected and list(intent.link_ids or []) != expected["link_ids"]:
        errors.append(f"link_ids={intent.link_ids}")
    if "mode" in expected and expected["mode"] not in (intent.modes or []):
        errors.append(f"modes={intent.modes}")
    return errors


def _temperature(text: str) -> float | None:
    return None if text == "default" else float(text)


def _args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", required=True, help="ollama, anthropic, openai or gemini")
    parser.add_argument("--model", help="model id (default: the one selections use)")
    parser.add_argument("--runs", type=int, default=3, help="parses per utterance (default 3)")
    parser.add_argument(
        "--temperature",
        type=_temperature,
        default=argparse.SUPPRESS,
        help='a number, or "default" for the provider\'s own (default: llm.quality.temperature)',
    )
    parser.add_argument(
        "--guide",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="send the shipped assistant guide (default: llm.quality.assistant_context)",
    )
    parser.add_argument("--eval-set", type=Path, default=EVAL_SET, help=f"default: {EVAL_SET.name}")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the eval; returns 0 when every parse was right, else 1."""
    args = _args(argv)
    quality_overrides = {key: getattr(args, arg) for key, arg in _QUALITY_ARGS.items() if hasattr(args, arg)}
    settings = load_settings(overrides={"select.provider": args.provider, "select.model": args.model}).settings
    # Applied after loading: a None override (--temperature default) would just drop the key there.
    llm = settings.llm.model_copy(update={"quality": settings.llm.quality.model_copy(update=quality_overrides)})
    settings = settings.model_copy(update={"llm": llm})
    quality = settings.llm.quality
    transport = _Counting()
    registry = build_registry(settings, transport=transport)
    parser = make_parser(settings.select, registry)
    guide = assistant_context(quality.assistant_context_max_chars) if quality.assistant_context else ""
    context = PromptContext(assistant=guide)
    cases = tomllib.loads(args.eval_set.read_text())["case"]

    where = "local" if registry.is_local(args.provider) else "REMOTE"
    print(
        f"{args.provider} ({where}) model={parser.model} temperature={quality.temperature} "
        f"guide={'on' if guide else 'off'} max_repairs={quality.max_repairs} runs={args.runs}",
        flush=True,
    )
    if where == "REMOTE":
        print(
            f"NOTE: {args.provider} is a remote provider. This makes about {len(cases) * args.runs} "
            "paid API calls (more with repairs) and spends tokens on your account.",
            flush=True,
        )

    rows, misses = [], []
    for case in cases:
        utterance = case["utterance"]
        right = first_try = resolves = 0
        started = time.monotonic()
        for _ in range(args.runs):
            transport.calls = 0
            try:
                errors = check(parser.parse(utterance, context=context), case)
            except Exception as exc:  # an eval reports every failure; it never stops on one
                errors = [f"{type(exc).__name__}: {str(exc)[:150]}"]
            if errors:
                misses.append((utterance, errors))
            else:
                right += 1
                first_try += transport.calls == 1
            resolves += all(error.endswith(FALLBACK) for error in errors)
        rows.append((utterance, right, first_try, resolves, (time.monotonic() - started) / args.runs))

    width = max(len(row[0]) for row in rows)
    print(f"\n{'utterance':<{width}}  {'correct':<9}  {'first-try':<9}  {'resolves':<9}  s/parse")
    for utterance, *counts, seconds in rows:
        cells = "  ".join(f"{n:>5}/{args.runs:<3}" for n in counts)
        print(f"{utterance:<{width}}  {cells}  {seconds:>7.1f}")
    total = len(rows) * args.runs
    right, first_try, resolves = (sum(row[i] for row in rows) for i in (1, 2, 3))
    cells = "  ".join(f"{n:>5}/{total:<3}" for n in (right, first_try, resolves))
    print(f"{'TOTAL':<{width}}  {cells}  ({right / total:.0%} correct, {resolves / total:.0%} resolve)")
    for utterance, errors in misses:
        print(f"  miss: {utterance!r} -> {', '.join(errors)}")
    return 0 if right == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
