"""Configurable query transformation module for RAG pipelines.

Six components:
1. QuerySanitizer          -- security-first input sanitization (P0)
2. HyDETransformer         -- hypothetical document embedding
3. MultiQueryTransformer   -- expand single query into reformulations
4. QueryDecomposer         -- split multi-hop questions into sub-queries
5. QueryRouter             -- classify query complexity for pipeline routing
6. BaseQueryTransformer    -- ABC defining the transformer interface

All components are domain-agnostic. LLM model, prompt templates,
classification thresholds, and injection patterns are all configurable.

SECURITY: QuerySanitizer MUST be applied before any LLM call.
HyDE output is used ONLY for embedding, NEVER shown to users.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum


class TransformStrategy(StrEnum):
    HYDE = "hyde"
    MULTI_QUERY = "multi_query"
    DECOMPOSE = "decompose"


class QueryCategory(StrEnum):
    KEYWORD = "keyword"
    STANDARD = "standard"
    VAGUE = "vague"
    MULTI_HOP = "multi_hop"


class TransformError(Exception):
    """Raised when query transformation fails."""


@dataclass
class TransformResult:
    """Holds original + transformed queries for tracing."""

    original_query: str
    transformed_queries: list[str]
    strategy: str
    metadata: dict = field(default_factory=dict)


@dataclass
class QueryClassification:
    """Result of query routing/classification."""

    category: QueryCategory
    confidence: float
    raw_query: str
    sanitized_query: str


# ---------------------------------------------------------------------------
# QuerySanitizer
# ---------------------------------------------------------------------------

# Type alias for the LLM callable used across all transformers
LLMCallable = Callable[[str], Awaitable[str]]


class QuerySanitizer:
    """Security-first query sanitization. MUST be applied before any LLM call.

    Strips injection patterns, control characters, and truncates to a
    configurable max length. This is the first line of defense against
    prompt injection -- all external user input passes through here.
    """

    DEFAULT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?above",
        r"new\s+instructions",
        r"system\s*:",
        r"assistant\s*:",
        r"<\s*system\s*>",
        r"you\s+are\s+now",
        r"forget\s+(all\s+)?previous",
        r"disregard\s+(all\s+)?previous",
    ]

    def __init__(
        self,
        max_length: int = 500,
        injection_patterns: list[str] | None = None,
    ) -> None:
        self.max_length = max_length
        pattern_list = (
            injection_patterns
            if injection_patterns is not None
            else self.DEFAULT_INJECTION_PATTERNS
        )
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in pattern_list
        ]

    def sanitize(self, query: str) -> str:
        """Sanitize a query string for safe LLM consumption.

        Order of operations:
        1. Strip control characters (keeps printable + standard whitespace)
        2. Remove injection patterns
        3. Truncate to max_length
        """
        if not query:
            return query

        # 1. Strip control characters (keep printable ASCII + unicode + tabs/newlines/spaces)
        sanitized = "".join(
            ch
            for ch in query
            if ch in ("\t", "\n", "\r") or (ord(ch) >= 32 and ord(ch) != 127)
        )

        # 2. Remove injection patterns
        for pattern in self._compiled_patterns:
            sanitized = pattern.sub("", sanitized)

        # 3. Clean up double spaces left by removal
        sanitized = re.sub(r"  +", " ", sanitized).strip()

        # 4. Truncate to max_length
        if len(sanitized) > self.max_length:
            sanitized = sanitized[: self.max_length]

        return sanitized


# ---------------------------------------------------------------------------
# BaseQueryTransformer
# ---------------------------------------------------------------------------


class BaseQueryTransformer(ABC):
    """Abstract base class for all query transformation strategies."""

    @abstractmethod
    async def transform(self, query: str) -> TransformResult:
        """Transform a query. Returns TransformResult with original + transformed."""
        ...


# ---------------------------------------------------------------------------
# HyDETransformer
# ---------------------------------------------------------------------------

_HYDE_DEFAULT_TEMPLATE = (
    "Given the following question, write a short hypothetical answer "
    "that would appear in a relevant document. Do not explain or qualify -- "
    "just write the answer passage.\n\n"
    "Question: {query}\n\n"
    "Hypothetical answer:"
)


class HyDETransformer(BaseQueryTransformer):
    """Generate a hypothetical answer and return it for embedding.

    The hypothetical answer is used ONLY for vector similarity search --
    it is NEVER shown to the user or included in the final context.
    """

    def __init__(
        self,
        llm_fn: Callable[..., Awaitable[str]],
        model: str = "gpt-5-mini",
        sanitizer: QuerySanitizer | None = None,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.model = model
        self.sanitizer = sanitizer or QuerySanitizer()
        self.prompt_template = prompt_template or _HYDE_DEFAULT_TEMPLATE

    async def transform(self, query: str) -> TransformResult:
        sanitized = self.sanitizer.sanitize(query)
        prompt = self.prompt_template.format(query=sanitized)

        try:
            hypothetical = await self.llm_fn(prompt, model=self.model)
        except Exception as exc:
            raise TransformError(
                f"HyDE generation failed: {exc}"
            ) from exc

        return TransformResult(
            original_query=query,
            transformed_queries=[hypothetical],
            strategy="hyde",
            metadata={"model": self.model},
        )


# ---------------------------------------------------------------------------
# MultiQueryTransformer
# ---------------------------------------------------------------------------

_MULTI_QUERY_DEFAULT_TEMPLATE = (
    "Generate {num_queries} alternative search queries for the following "
    "question. Each query should approach the topic from a different angle. "
    "Return one query per line, no numbering, no explanation.\n\n"
    "Original question: {query}\n\n"
    "Alternative queries:"
)


class MultiQueryTransformer(BaseQueryTransformer):
    """Expand a single query into multiple reformulations for broader recall."""

    def __init__(
        self,
        llm_fn: Callable[..., Awaitable[str]],
        model: str = "gpt-5-mini",
        num_queries: int = 3,
        sanitizer: QuerySanitizer | None = None,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.model = model
        self.num_queries = num_queries
        self.sanitizer = sanitizer or QuerySanitizer()
        self.prompt_template = prompt_template or _MULTI_QUERY_DEFAULT_TEMPLATE

    async def transform(self, query: str) -> TransformResult:
        sanitized = self.sanitizer.sanitize(query)
        prompt = self.prompt_template.format(
            query=sanitized, num_queries=self.num_queries
        )

        try:
            response = await self.llm_fn(prompt, model=self.model)
        except Exception as exc:
            raise TransformError(
                f"Multi-query expansion failed: {exc}"
            ) from exc

        # Parse newline-separated queries, filter empty lines
        queries = [
            line.strip()
            for line in response.strip().split("\n")
            if line.strip()
        ]

        # Limit to requested number
        queries = queries[: self.num_queries]

        return TransformResult(
            original_query=query,
            transformed_queries=queries,
            strategy="multi_query",
            metadata={"model": self.model, "num_queries": self.num_queries},
        )


# ---------------------------------------------------------------------------
# QueryDecomposer
# ---------------------------------------------------------------------------

_DECOMPOSE_DEFAULT_TEMPLATE = (
    "Break the following complex question into simpler sub-questions "
    "that can be answered independently. If the question is already simple, "
    "return it as-is. Return one sub-question per line, no numbering.\n\n"
    "Question: {query}\n\n"
    "Sub-questions:"
)


class QueryDecomposer(BaseQueryTransformer):
    """Split multi-hop questions into independent sub-queries."""

    def __init__(
        self,
        llm_fn: Callable[..., Awaitable[str]],
        model: str = "gpt-5-mini",
        sanitizer: QuerySanitizer | None = None,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.model = model
        self.sanitizer = sanitizer or QuerySanitizer()
        self.prompt_template = prompt_template or _DECOMPOSE_DEFAULT_TEMPLATE

    async def transform(self, query: str) -> TransformResult:
        sanitized = self.sanitizer.sanitize(query)
        prompt = self.prompt_template.format(query=sanitized)

        try:
            response = await self.llm_fn(prompt, model=self.model)
        except Exception as exc:
            raise TransformError(
                f"Query decomposition failed: {exc}"
            ) from exc

        sub_queries = [
            line.strip()
            for line in response.strip().split("\n")
            if line.strip()
        ]

        return TransformResult(
            original_query=query,
            transformed_queries=sub_queries,
            strategy="decompose",
            metadata={"model": self.model},
        )


# ---------------------------------------------------------------------------
# QueryRouter
# ---------------------------------------------------------------------------

_ROUTER_DEFAULT_TEMPLATE = (
    "Classify the following search query into exactly one category:\n"
    '- "keyword": exact IDs, codes, contract numbers (e.g. CTR-2024-001)\n'
    '- "standard": clear factual question about a specific topic\n'
    '- "vague": broad, unclear, or exploratory question\n'
    '- "multi_hop": requires comparing or combining info from multiple sources\n\n'
    "Respond with JSON only: "
    '{{"category": "<category>", "confidence": <0.0-1.0>}}\n\n'
    "Query: {query}\n\n"
    "Classification:"
)


class QueryRouter:
    """Classify query complexity to decide which pipeline to use.

    NOT a transformer -- classifies, doesn't transform. Returns
    QueryClassification with category and confidence.
    """

    VALID_CATEGORIES = {c.value for c in QueryCategory}

    def __init__(
        self,
        llm_fn: Callable[..., Awaitable[str]],
        model: str = "gpt-5-nano",
        sanitizer: QuerySanitizer | None = None,
        default_category: QueryCategory = QueryCategory.STANDARD,
        prompt_template: str | None = None,
    ) -> None:
        self.llm_fn = llm_fn
        self.model = model
        self.sanitizer = sanitizer or QuerySanitizer()
        self.default_category = default_category
        self.prompt_template = prompt_template or _ROUTER_DEFAULT_TEMPLATE

    async def classify(self, query: str) -> QueryClassification:
        sanitized = self.sanitizer.sanitize(query)
        prompt = self.prompt_template.format(query=sanitized)

        try:
            response = await self.llm_fn(prompt, model=self.model)
            parsed = json.loads(response.strip())
            category_str = parsed.get("category", "")
            confidence = float(parsed.get("confidence", 0.0))

            if category_str not in self.VALID_CATEGORIES:
                category = self.default_category
                confidence = 0.0
            else:
                category = QueryCategory(category_str)

        except Exception:
            category = self.default_category
            confidence = 0.0

        return QueryClassification(
            category=category,
            confidence=confidence,
            raw_query=query,
            sanitized_query=sanitized,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_transformer(
    strategy: TransformStrategy | str, **kwargs
) -> BaseQueryTransformer:
    """Factory function to create a transformer by strategy name."""
    strategy_str = str(strategy)

    constructors: dict[str, type[BaseQueryTransformer]] = {
        TransformStrategy.HYDE: HyDETransformer,
        TransformStrategy.MULTI_QUERY: MultiQueryTransformer,
        TransformStrategy.DECOMPOSE: QueryDecomposer,
    }

    if strategy_str not in constructors:
        raise ValueError(
            f"Unknown transform strategy: {strategy_str!r}. "
            f"Valid strategies: {list(constructors.keys())}"
        )

    return constructors[strategy_str](**kwargs)
