"""LLM Provider Protocol and response types.

Defines the contract that all LLM providers (Azure OpenAI, Ollama, etc.)
must satisfy. Domain-agnostic -- works for any use case with different
provider config.

The Protocol uses structural subtyping -- any class with the right methods
automatically satisfies it, no explicit inheritance needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from apps.api.src.core.config.settings import Settings


@dataclass(frozen=True)
class LLMResponse:
    """Immutable response from an LLM provider.

    Captures content, model identity, token usage, and latency
    for cost tracking and observability.
    """

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed (input + output)."""
        return self.input_tokens + self.output_tokens


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM inference providers.

    Every provider must implement:
    - generate(): free-form text generation
    - generate_structured(): generation expecting structured output (JSON)
    - model_name: the model identifier for logging/cost tracking
    """

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a free-form text response."""
        ...

    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a structured (JSON) response."""
        ...

    @property
    def model_name(self) -> str:
        """The model identifier (e.g., 'gpt-4o', 'qwen3:8b')."""
        ...


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Factory: create the correct LLM provider based on settings.

    Args:
        settings: Application settings with llm_provider field.

    Returns:
        LLMProvider instance (AzureOpenAI or Ollama).

    Raises:
        ValueError: If llm_provider is not 'azure' or 'ollama'.
    """
    match settings.llm_provider:
        case "azure":
            from apps.api.src.core.infrastructure.llm.azure_openai import (
                AzureOpenAIProvider,
            )

            return AzureOpenAIProvider(
                endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                deployment=settings.azure_openai_deployment,
                api_version=settings.azure_openai_api_version,
            )
        case "ollama":
            from apps.api.src.core.infrastructure.llm.ollama import (
                OllamaProvider,
            )

            return OllamaProvider(
                host=settings.ollama_host,
                model=settings.ollama_model,
            )
        case _:
            raise ValueError(
                f"Unknown LLM provider: {settings.llm_provider!r}. "
                f"Valid providers: 'azure', 'ollama'"
            )
