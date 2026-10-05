"""Get one validated tool call out of any provider, with a bounded repair loop.

PRD §15(e): when the model's output fails validation, re-prompt with the error instead of
surfacing a raw failure. Models without tool calling get the same tool as a "reply with
JSON only" instruction (JSON mode) on the *same* provider and model, never another provider.
Provider failures (:class:`~gmnspy.llm.errors.LLMError`: keys, rate limits, timeouts) are
never retried here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from .errors import ToolsUnsupported
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool

__all__ = ["JSON_MODE_INSTRUCTIONS", "REPAIR_PROMPT", "StructuredOutputError", "ToolResult", "request_tool_call"]

Mode = Literal["tools", "json"]

#: Appended to the system prompt in JSON mode.
JSON_MODE_INSTRUCTIONS = (
    "Reply with ONLY one JSON object, with no prose and no code fences, that is valid input for the tool "
    "{name!r} ({description}). Its JSON schema:\n{schema}"
)
#: The user turn that asks the model to fix its previous reply.
REPAIR_PROMPT = "Your previous reply was not usable: {error}\nTry again: {how}"


class StructuredOutputError(ValueError):
    """The model never produced a valid tool call within the repair budget."""


@dataclass(frozen=True)
class ToolResult:
    """Validated tool arguments, the mode that produced them, and how many calls it took."""

    arguments: dict[str, Any]
    mode: Mode
    attempts: int


def request_tool_call(
    provider: LLMProvider,
    *,
    model: str,
    tool: Tool,
    user: str,
    system: str = "",
    context: str = "",
    validate: Callable[[dict[str, Any]], object] | None = None,
    json_mode: bool = False,
    max_repairs: int = 1,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> ToolResult:
    """Ask ``provider`` to call ``tool`` for ``user``; validate, and repair until valid or out of budget.

    Args:
        provider: Any :class:`~gmnspy.llm.types.LLMProvider`.
        model: Model id.
        tool: The tool the model must call. Its ``input_schema`` is enforced with jsonschema.
        user: The user's text.
        system: The per-call part of the system prompt.
        context: The stable, cacheable part of the system prompt (sent first).
        validate: Extra check on the arguments; raise ``ValueError`` to trigger a repair.
        json_mode: Start in JSON mode (for models known to lack tool calling).
        max_repairs: Extra calls allowed after an invalid reply.
        max_tokens: Output token cap per call.
        temperature: Sampling temperature; ``None`` keeps the provider's default.

    Returns:
        The validated arguments, the mode used, and the number of calls made.

    Raises:
        StructuredOutputError: Still invalid after ``max_repairs`` repairs.
    """
    base = CompletionRequest(
        model=model, messages=(), system=system, context=context, max_tokens=max_tokens, temperature=temperature
    )
    mode: Mode = "json" if json_mode else "tools"
    messages = [Message("user", user)]
    error = ""
    for attempt in range(1, max_repairs + 2):
        completion, mode = _complete(provider, replace(base, messages=tuple(messages)), tool, mode)
        try:
            arguments = _arguments(completion, tool, mode)
            _check_schema(arguments, tool.input_schema)
            if validate is not None:
                validate(arguments)
        except ValueError as exc:
            error = str(exc)
            how = (
                f"call {tool.name} with corrected arguments."
                if mode == "tools"
                else "reply with only the corrected JSON object."
            )
            messages += [
                Message("assistant", _echo(completion)),
                Message("user", REPAIR_PROMPT.format(error=error, how=how)),
            ]
            continue
        return ToolResult(arguments, mode, attempt)
    raise StructuredOutputError(f"the model's reply was still invalid after {max_repairs + 1} attempts: {error}")


def _complete(provider: LLMProvider, base: CompletionRequest, tool: Tool, mode: Mode) -> tuple[Completion, Mode]:
    if mode == "tools":
        try:
            return provider.complete(replace(base, tools=(tool,), force_tool=tool.name)), "tools"
        except ToolsUnsupported:
            pass  # same provider, same model, JSON mode instead: a change of mode, never of provider
    instructions = JSON_MODE_INSTRUCTIONS.format(
        name=tool.name, description=tool.description, schema=json.dumps(tool.input_schema)
    )
    # The JSON instructions go in the per-call part, so the cacheable ``context`` prefix stays identical.
    system = f"{base.system}\n\n{instructions}".strip()
    return provider.complete(replace(base, system=system, json_schema=tool.input_schema)), "json"


def _arguments(completion: Completion, tool: Tool, mode: Mode) -> dict[str, Any]:
    for call in completion.tool_calls:
        if call.name == tool.name:
            return _drop_nulls(dict(call.arguments))
    if completion.tool_calls:
        raise ValueError(f"the model called {completion.tool_calls[0].name!r}, not {tool.name!r}")
    parsed = _json_object(completion.text)
    if parsed is None:
        raise ValueError(
            f"the model did not call {tool.name!r}" if mode == "tools" else "the reply was not a JSON object"
        )
    return _drop_nulls(parsed)


def _json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _drop_nulls(value: Any) -> Any:
    """Treat ``null`` as "absent": several providers emit explicit nulls for unused optional fields."""
    if isinstance(value, dict):
        return {key: _drop_nulls(item) for key, item in value.items() if item is not None}
    return value


def _check_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    from jsonschema import Draft202012Validator  # the [nl] extra; lazy so gmnspy.llm imports without it
    from jsonschema.exceptions import best_match

    error = best_match(Draft202012Validator(schema).iter_errors(arguments))
    if error is not None:
        where = "/".join(str(part) for part in error.absolute_path) or "(top level)"
        raise ValueError(f"{where}: {error.message}")


def _echo(completion: Completion) -> str:
    if completion.tool_calls:
        call = completion.tool_calls[0]
        return f"(called {call.name} with {json.dumps(call.arguments)})"
    return completion.text[:2000] or "(empty reply)"
