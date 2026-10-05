"""Hand-rolled ``httpx`` adapters, one per provider, each implementing :class:`~gmnspy.llm.types.LLMProvider`."""

from ._base import HTTPProvider
from .anthropic import AnthropicProvider

#: Provider name -> adapter class. A catalog provider without an adapter is never offered.
ADAPTERS: dict[str, type[HTTPProvider]] = {
    "anthropic": AnthropicProvider,
}

__all__ = ["ADAPTERS", "AnthropicProvider", "HTTPProvider"]
