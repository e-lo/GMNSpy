"""Provider-neutral LLM layer for gmnspy's natural-language features (Task 11 completes this module)."""

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
from .types import Completion, CompletionRequest, LLMProvider, Message, Tool, ToolCall

__all__ = [
    "BadRequest",
    "BadResponse",
    "Completion",
    "CompletionRequest",
    "InvalidKey",
    "LLMError",
    "LLMProvider",
    "Message",
    "MissingKey",
    "ModelNotFound",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RateLimited",
    "Tool",
    "ToolCall",
    "ToolsUnsupported",
]
