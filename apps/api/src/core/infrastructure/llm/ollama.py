"""Ollama LLM provider for local inference.

Wraps LangChain's ChatOllama behind the LLMProvider Protocol.
Handles error cases: connection refused, model not pulled, timeout.

No external API calls -- all inference runs on localhost or
a configured Ollama host within the network.
"""

from __future__ import annotations

import time

from langchain_ollama import ChatOllama

from apps.api.src.core.infrastructure.llm.provider import LLMResponse


class OllamaProvider:
    """Ollama LLM provider wrapping LangChain ChatOllama.

    Satisfies the LLMProvider Protocol via structural subtyping.
    Provides clear error messages for common failure modes:
    - Connection refused (Ollama not running)
    - Model not found (needs `ollama pull`)
    - Timeout (model too large for available hardware)
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen3:8b",
    ) -> None:
        self._model = model
        self._host = host
        self._llm = ChatOllama(
            base_url=host,
            model=model,
        )

    @property
    def model_name(self) -> str:
        """The Ollama model identifier."""
        return self._model

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a free-form text response via Ollama."""
        start = time.perf_counter()
        try:
            response = await self._llm.ainvoke(prompt, **kwargs)
        except ConnectionError as e:
            raise ConnectionError(
                f"Ollama at {self._host} is not reachable. "
                f"Is the Ollama service running? Original error: {e}"
            ) from e
        except TimeoutError as e:
            raise TimeoutError(
                f"Ollama request timed out for model '{self._model}'. "
                f"The model may be too large for available hardware. "
                f"Original error: {e}"
            ) from e
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg:
                raise ValueError(
                    f"Model '{self._model}' not found in Ollama. "
                    f"Run: ollama pull {self._model}"
                ) from e
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000

        usage = response.usage_metadata or {}
        return LLMResponse(
            content=response.content,
            model=self._model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=elapsed_ms,
        )

    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a structured (JSON) response via Ollama."""
        return await self.generate(prompt, **kwargs)
