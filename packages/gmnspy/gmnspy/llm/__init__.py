"""Provider-neutral LLM layer for gmnspy's natural-language features.

* :mod:`~gmnspy.llm.types`: :class:`CompletionRequest` / :class:`Completion` and the
  :class:`LLMProvider` protocol every adapter implements.
* :mod:`~gmnspy.llm.providers`: hand-rolled ``httpx`` adapters (anthropic, openai, gemini, ollama).
* :mod:`~gmnspy.llm.structured`: one validated tool call, with a repair loop and JSON mode.
* :mod:`~gmnspy.llm.catalog`: the maintained provider/model catalog (``models.toml``).
* :mod:`~gmnspy.llm.secrets`: write-only API-key storage (env → keyring).
* :mod:`~gmnspy.llm.registry`: :class:`ProviderRegistry`, the entry point.

``httpx``, ``jsonschema`` and ``keyring`` (the ``[nl]`` extra) are imported lazily, so
importing this package never requires them.
"""

from .catalog import Catalog, ModelInfo, ProviderInfo, load_catalog
from .errors import (
    BadRequest,
    BadResponse,
    InvalidKey,
    LLMError,
    MissingKey,
    ModelNotFound,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
    ToolsUnsupported,
)
from .registry import ProviderRegistry, build_registry, default_registry, is_local_url
from .secrets import KeySlot, SecretStore, SecretStoreError, looks_like_secret, redact
from .structured import StructuredOutputError, ToolResult, request_tool_call
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall

__all__ = [
    "BadRequest",
    "BadResponse",
    "Catalog",
    "Completion",
    "CompletionRequest",
    "InvalidKey",
    "KeySlot",
    "LLMError",
    "LLMProvider",
    "Message",
    "MissingKey",
    "ModelInfo",
    "ModelNotFound",
    "ProviderInfo",
    "ProviderRegistry",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimited",
    "SecretStore",
    "SecretStoreError",
    "StructuredOutputError",
    "Tool",
    "ToolCall",
    "ToolResult",
    "ToolsUnsupported",
    "build_registry",
    "default_registry",
    "is_local_url",
    "load_catalog",
    "looks_like_secret",
    "redact",
    "request_tool_call",
]
