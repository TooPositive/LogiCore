"""Prompt caching optimization: static-first restructuring and cache metrics.

Phase 5, Pillar 3: Prompt Caching Optimization.

Domain-agnostic: works with any prompt template by analyzing section types.

Key design decisions:
- Static-first ordering maximizes Azure/Anthropic prompt cache hits
- RBAC partitioning fragments cache prefixes in multi-tenant deployments
- Honest about hit rate: single-tenant 55-65%, multi-tenant 15-25%
- Cache discount: cached static tokens cost 50% of normal input tokens
- Session-stable sections (RBAC context) are cacheable within a session

The 60% hit rate claim from the spec assumes single-tenant. Multi-tenant
with RBAC partitioning realistically achieves 15-25%. This module tracks
both and reports honestly.
"""

from enum import StrEnum

from pydantic import BaseModel

from apps.api.src.domain.telemetry import PromptCacheStats


class SectionType(StrEnum):
    """Classification of prompt sections for cache optimization.

    STATIC: Never changes (system prompt, tool defs, few-shot examples).
    SESSION_STABLE: Changes per user session but not per query (RBAC context).
    DYNAMIC: Changes every query (retrieved chunks, user question).
    """

    STATIC = "STATIC"
    SESSION_STABLE = "SESSION_STABLE"
    DYNAMIC = "DYNAMIC"


# Sort order for restructuring: static first, session_stable middle, dynamic last
_SECTION_ORDER = {
    SectionType.STATIC: 0,
    SectionType.SESSION_STABLE: 1,
    SectionType.DYNAMIC: 2,
}


class PromptSection(BaseModel):
    """A section of a prompt template with type classification."""

    content: str
    section_type: SectionType
    label: str

    @property
    def estimated_tokens(self) -> int:
        """Estimate token count from character count (avg 4 chars per token)."""
        return len(self.content) // 4


class PromptAnalysis(BaseModel):
    """Analysis of a prompt template's cache-friendliness."""

    sections: list[PromptSection]

    @property
    def total_estimated_tokens(self) -> int:
        return sum(s.estimated_tokens for s in self.sections)

    @property
    def static_token_ratio(self) -> float:
        """Ratio of static tokens to total tokens."""
        total = self.total_estimated_tokens
        if total == 0:
            return 0.0
        static = sum(
            s.estimated_tokens
            for s in self.sections
            if s.section_type == SectionType.STATIC
        )
        return static / total

    @property
    def cacheable_token_ratio(self) -> float:
        """Ratio of cacheable tokens (static + session_stable) to total."""
        total = self.total_estimated_tokens
        if total == 0:
            return 0.0
        cacheable = sum(
            s.estimated_tokens
            for s in self.sections
            if s.section_type in (SectionType.STATIC, SectionType.SESSION_STABLE)
        )
        return cacheable / total


class CacheMetrics:
    """Track prompt cache hit/miss rates per RBAC partition.

    RBAC partition key MUST be part of the cache key. Two queries from
    different partitions MUST NOT share cache, even if the prompt text
    is identical. This prevents RBAC bypass via cached prefixes.
    """

    def __init__(self) -> None:
        self._partition_counts: dict[str, int] = {}
        self._total_queries: int = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0

    def record_query(self, partition_key: str) -> None:
        """Record a query for a given RBAC partition.

        First query in a partition is a miss (cache cold).
        Subsequent queries in the same partition are hits.
        """
        self._total_queries += 1

        if partition_key in self._partition_counts:
            self._partition_counts[partition_key] += 1
            self._cache_hits += 1
        else:
            self._partition_counts[partition_key] = 1
            self._cache_misses += 1

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses

    @property
    def unique_partitions(self) -> int:
        return len(self._partition_counts)

    def compute_stats(
        self,
        static_token_ratio: float,
        deployment_type: str = "single_tenant",
    ) -> PromptCacheStats:
        """Compute prompt cache statistics.

        Args:
            static_token_ratio: Fraction of prompt tokens that are static.
            deployment_type: "single_tenant" or "multi_tenant".

        Returns:
            PromptCacheStats with honest hit rate accounting for partitioning.
        """
        if self._total_queries == 0:
            return PromptCacheStats(
                hit_rate=0.0,
                miss_rate=1.0,
                savings_per_day_eur=0.0,
                total_prompts=0,
                static_token_ratio=static_token_ratio,
                deployment_type=deployment_type,
            )

        hit_rate = self._cache_hits / self._total_queries
        miss_rate = self._cache_misses / self._total_queries

        return PromptCacheStats(
            hit_rate=hit_rate,
            miss_rate=miss_rate,
            savings_per_day_eur=0.0,  # Computed separately via PromptOptimizer
            total_prompts=self._total_queries,
            static_token_ratio=static_token_ratio,
            deployment_type=deployment_type,
        )


class PromptOptimizer:
    """Optimize prompt structure for maximum cache hit rate.

    Static-first restructuring: system prompt + tool defs + few-shot FIRST,
    dynamic content (retrieved chunks, user query) LAST.

    This maximizes the cacheable prefix length, which is what Azure/Anthropic
    prompt caching requires (cache key = hash of prefix tokens).
    """

    def restructure(self, sections: list[PromptSection]) -> list[PromptSection]:
        """Restructure prompt sections in cache-optimal order.

        Order: STATIC first, SESSION_STABLE middle, DYNAMIC last.
        Within the same type, relative order is preserved (stable sort).

        Args:
            sections: Prompt sections in their current order.

        Returns:
            Reordered sections for maximum cache friendliness.
        """
        if not sections:
            return []

        # Stable sort by section type order
        return sorted(
            sections,
            key=lambda s: _SECTION_ORDER[s.section_type],
        )

    def cache_friendliness_score(
        self, sections: list[PromptSection]
    ) -> float:
        """Score how cache-friendly a prompt layout is (0.0 to 1.0).

        Score is based on:
        1. What fraction of tokens are cacheable (static + session_stable)
        2. Whether cacheable tokens come before dynamic tokens (prefix position)

        A score of 1.0 means all static/session_stable content is first,
        followed by all dynamic content. A score of 0.0 means no cacheable
        content or all dynamic content comes first.

        Args:
            sections: Prompt sections in their current order.

        Returns:
            Cache-friendliness score (0.0 to 1.0).
        """
        if not sections:
            return 0.0

        total_tokens = sum(s.estimated_tokens for s in sections)
        if total_tokens == 0:
            return 0.0

        cacheable_tokens = sum(
            s.estimated_tokens
            for s in sections
            if s.section_type in (SectionType.STATIC, SectionType.SESSION_STABLE)
        )
        if cacheable_tokens == 0:
            return 0.0

        # Factor 1: What fraction is cacheable
        cacheable_ratio = cacheable_tokens / total_tokens

        # Factor 2: How much cacheable content is in the prefix (before first dynamic)
        prefix_cacheable = 0
        for section in sections:
            if section.section_type == SectionType.DYNAMIC:
                break
            prefix_cacheable += section.estimated_tokens

        prefix_ratio = prefix_cacheable / cacheable_tokens if cacheable_tokens > 0 else 0.0

        # Combined score: both factors matter equally
        return cacheable_ratio * prefix_ratio

    def estimate_daily_savings(
        self,
        queries_per_day: int,
        avg_prompt_tokens: int,
        static_token_ratio: float,
        hit_rate: float,
        cost_per_1k_tokens: float,
        cache_discount: float = 0.50,
    ) -> float:
        """Estimate daily cost savings from prompt caching.

        Savings = queries * static_tokens * hit_rate * discount * cost_per_token

        The cache_discount is typically 50% — cached tokens cost half price.

        Args:
            queries_per_day: Number of queries per day.
            avg_prompt_tokens: Average prompt token count.
            static_token_ratio: Fraction of tokens that are static/cacheable.
            hit_rate: Expected cache hit rate.
            cost_per_1k_tokens: Cost per 1,000 input tokens (USD or EUR).
            cache_discount: Fraction of normal cost saved on cache hit (default 50%).

        Returns:
            Estimated daily savings in the same currency as cost_per_1k_tokens.
        """
        if queries_per_day == 0 or hit_rate == 0.0:
            return 0.0

        static_tokens_per_query = avg_prompt_tokens * static_token_ratio
        cached_tokens_per_day = queries_per_day * static_tokens_per_query * hit_rate
        savings = (cached_tokens_per_day / 1000) * cost_per_1k_tokens * cache_discount

        return savings
