"""Azure OpenAI LLM provider.

Wraps LangChain's AzureChatOpenAI behind the LLMProvider Protocol.
Tracks tokens and latency in LLMResponse for cost/observability.

No hardcoded credentials -- all config via constructor args.
"""

from __future__ import annotations

import time

from langchain_openai import AzureChatOpenAI

from apps.api.src.core.infrastructure.llm.provider import LLMResponse


class AzureOpenAIProvider:
    """Azure OpenAI LLM provider wrapping LangChain AzureChatOpenAI.

    Satisfies the LLMProvider Protocol via structural subtyping.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = "2024-12-01-preview",
    ) -> None:
        self._deployment = deployment
        self._llm = AzureChatOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            azure_deployment=deployment,
            api_version=api_version,
        )

    @property
    def model_name(self) -> str:
        """The Azure deployment name."""
        return self._deployment

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a free-form text response via Azure OpenAI."""
        start = time.perf_counter()
        response = await self._llm.ainvoke(prompt, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000

        usage = response.usage_metadata or {}
        return LLMResponse(
            content=response.content,
            model=self._deployment,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=elapsed_ms,
        )

    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse:
        """Generate a structured (JSON) response via Azure OpenAI."""
        return await self.generate(prompt, **kwargs)
