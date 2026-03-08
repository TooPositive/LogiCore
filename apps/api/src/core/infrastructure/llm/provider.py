"""LLM Provider Protocol and response types.

Defines the contract that all LLM providers (Azure OpenAI, Ollama, etc.)
must satisfy. Domain-agnostic -- works for any use case with different
provider config.

The Protocol uses structural subtyping -- any class with the right methods
automatically satisfies it, no explicit inheritance needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
