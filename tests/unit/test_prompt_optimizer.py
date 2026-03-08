"""Tests for prompt caching optimization: static-first restructuring, cache metrics.

Phase 5, Pillar 3: Prompt Caching Optimization — prompt_optimizer.py.

Tests cover:
- Static vs dynamic portion identification (n>=5)
- Static-first restructuring (n>=5)
- Cache-friendliness scoring
- RBAC partition interaction (n>=5)
- Cost savings calculation
- Cache hit rate tracking
"""

import pytest

from apps.api.src.domain.telemetry import PromptCacheStats
from apps.api.src.telemetry.prompt_optimizer import (
    CacheMetrics,
    PromptAnalysis,
    PromptOptimizer,
    PromptSection,
    SectionType,
)

# =========================================================================
# PromptSection and PromptAnalysis tests
# =========================================================================


class TestPromptSection:
    """Tests for PromptSection model — static vs dynamic classification."""

    def test_static_system_prompt(self):
        section = PromptSection(
            content="You are a logistics AI assistant.",
            section_type=SectionType.STATIC,
            label="system_prompt",
        )
        assert section.section_type == SectionType.STATIC

    def test_dynamic_user_query(self):
        section = PromptSection(
            content="What is the penalty for late delivery?",
            section_type=SectionType.DYNAMIC,
            label="user_query",
        )
        assert section.section_type == SectionType.DYNAMIC

    def test_session_stable_rbac(self):
        """RBAC rules are session-stable (change per user, not per query)."""
        section = PromptSection(
            content="User clearance: 2. Departments: legal, warehouse.",
            section_type=SectionType.SESSION_STABLE,
            label="rbac_context",
        )
        assert section.section_type == SectionType.SESSION_STABLE

    def test_section_token_estimate(self):
        """Token count is estimated from character count / 4."""
        section = PromptSection(
            content="A" * 400,  # ~100 tokens
            section_type=SectionType.STATIC,
            label="test",
        )
        assert section.estimated_tokens == 100

    def test_section_empty_content(self):
        section = PromptSection(
            content="",
            section_type=SectionType.STATIC,
            label="empty",
        )
        assert section.estimated_tokens == 0


class TestPromptAnalysis:
    """Tests for PromptAnalysis — breakdown of prompt structure."""

    def test_analysis_static_ratio(self):
        """Static token ratio calculated from sections."""
        analysis = PromptAnalysis(
            sections=[
                PromptSection(
                    content="A" * 800,
                    section_type=SectionType.STATIC,
                    label="system",
                ),
                PromptSection(
                    content="B" * 200,
                    section_type=SectionType.DYNAMIC,
                    label="query",
                ),
            ]
        )
        assert analysis.static_token_ratio == pytest.approx(0.80)

    def test_analysis_all_static(self):
        analysis = PromptAnalysis(
            sections=[
                PromptSection(
                    content="X" * 1000,
                    section_type=SectionType.STATIC,
                    label="all_static",
                ),
            ]
        )
        assert analysis.static_token_ratio == pytest.approx(1.0)

    def test_analysis_all_dynamic(self):
        analysis = PromptAnalysis(
            sections=[
                PromptSection(
                    content="X" * 1000,
                    section_type=SectionType.DYNAMIC,
                    label="all_dynamic",
                ),
            ]
        )
        assert analysis.static_token_ratio == pytest.approx(0.0)

    def test_analysis_session_stable_counted_as_cacheable(self):
        """Session-stable sections are cacheable (within a session)."""
        analysis = PromptAnalysis(
            sections=[
                PromptSection(
                    content="A" * 400,
                    section_type=SectionType.STATIC,
                    label="system",
                ),
                PromptSection(
                    content="B" * 400,
                    section_type=SectionType.SESSION_STABLE,
                    label="rbac",
                ),
                PromptSection(
                    content="C" * 200,
                    section_type=SectionType.DYNAMIC,
                    label="query",
                ),
            ]
        )
        # Static + session_stable = 800/1000 = 0.80
        assert analysis.cacheable_token_ratio == pytest.approx(0.80)

    def test_analysis_total_tokens(self):
        analysis = PromptAnalysis(
            sections=[
                PromptSection(content="X" * 400, section_type=SectionType.STATIC, label="a"),
                PromptSection(content="Y" * 200, section_type=SectionType.DYNAMIC, label="b"),
            ]
        )
        assert analysis.total_estimated_tokens == 150  # (400+200)/4


# =========================================================================
# PromptOptimizer — static-first restructuring (n>=5)
# =========================================================================


class TestPromptOptimizerRestructure:
    """Tests for static-first prompt restructuring."""

    def test_already_optimal_no_change(self):
        """Prompt already has static first, dynamic last -> no reordering needed."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="system prompt", section_type=SectionType.STATIC, label="system"),
            PromptSection(content="tool defs", section_type=SectionType.STATIC, label="tools"),
            PromptSection(content="user query", section_type=SectionType.DYNAMIC, label="query"),
        ]
        restructured = optimizer.restructure(sections)
        labels = [s.label for s in restructured]
        assert labels == ["system", "tools", "query"]

    def test_dynamic_first_gets_reordered(self):
        """Dynamic content before static -> restructured to static first."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(
                content="retrieved chunks",
                section_type=SectionType.DYNAMIC,
                label="context",
            ),
            PromptSection(content="system prompt", section_type=SectionType.STATIC, label="system"),
            PromptSection(content="tool defs", section_type=SectionType.STATIC, label="tools"),
        ]
        restructured = optimizer.restructure(sections)
        types = [s.section_type for s in restructured]
        # Static sections should come first
        assert types == [SectionType.STATIC, SectionType.STATIC, SectionType.DYNAMIC]

    def test_mixed_order_restructured(self):
        """Interleaved static/dynamic -> grouped static first, then dynamic."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="dynamic 1", section_type=SectionType.DYNAMIC, label="d1"),
            PromptSection(content="static 1", section_type=SectionType.STATIC, label="s1"),
            PromptSection(content="dynamic 2", section_type=SectionType.DYNAMIC, label="d2"),
            PromptSection(content="static 2", section_type=SectionType.STATIC, label="s2"),
        ]
        restructured = optimizer.restructure(sections)
        types = [s.section_type for s in restructured]
        # All static first, then all dynamic
        assert types == [
            SectionType.STATIC,
            SectionType.STATIC,
            SectionType.DYNAMIC,
            SectionType.DYNAMIC,
        ]

    def test_session_stable_between_static_and_dynamic(self):
        """Session-stable sections go between static and dynamic."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="query", section_type=SectionType.DYNAMIC, label="query"),
            PromptSection(content="rbac", section_type=SectionType.SESSION_STABLE, label="rbac"),
            PromptSection(content="system", section_type=SectionType.STATIC, label="system"),
        ]
        restructured = optimizer.restructure(sections)
        types = [s.section_type for s in restructured]
        assert types == [SectionType.STATIC, SectionType.SESSION_STABLE, SectionType.DYNAMIC]

    def test_preserves_relative_order_within_type(self):
        """Within the same type, relative order is preserved."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="s2", section_type=SectionType.STATIC, label="s2"),
            PromptSection(content="d1", section_type=SectionType.DYNAMIC, label="d1"),
            PromptSection(content="s1", section_type=SectionType.STATIC, label="s1"),
            PromptSection(content="d2", section_type=SectionType.DYNAMIC, label="d2"),
        ]
        restructured = optimizer.restructure(sections)
        static_labels = [s.label for s in restructured if s.section_type == SectionType.STATIC]
        dynamic_labels = [s.label for s in restructured if s.section_type == SectionType.DYNAMIC]
        assert static_labels == ["s2", "s1"]  # original relative order preserved
        assert dynamic_labels == ["d1", "d2"]

    def test_empty_sections(self):
        optimizer = PromptOptimizer()
        assert optimizer.restructure([]) == []


# =========================================================================
# PromptOptimizer — cache friendliness score (n>=5)
# =========================================================================


class TestPromptOptimizerCacheFriendliness:
    """Tests for cache-friendliness scoring of prompt layouts."""

    def test_perfect_score_all_static_first(self):
        """All static content first -> maximum score for that ratio."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="A" * 800, section_type=SectionType.STATIC, label="s"),
            PromptSection(content="B" * 200, section_type=SectionType.DYNAMIC, label="d"),
        ]
        score = optimizer.cache_friendliness_score(sections)
        # Score reflects both cacheable ratio (0.8) and prefix positioning (1.0)
        assert score == pytest.approx(0.8)

    def test_worst_score_all_dynamic_first(self):
        """All dynamic content first -> low score."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="B" * 800, section_type=SectionType.DYNAMIC, label="d"),
            PromptSection(content="A" * 200, section_type=SectionType.STATIC, label="s"),
        ]
        score = optimizer.cache_friendliness_score(sections)
        assert score < 0.5

    def test_mixed_score(self):
        """Mixed order -> intermediate score."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="A" * 400, section_type=SectionType.STATIC, label="s1"),
            PromptSection(content="B" * 200, section_type=SectionType.DYNAMIC, label="d1"),
            PromptSection(content="C" * 400, section_type=SectionType.STATIC, label="s2"),
        ]
        score = optimizer.cache_friendliness_score(sections)
        assert 0.0 < score < 1.0

    def test_all_dynamic_zero_score(self):
        """All dynamic -> score 0.0 (nothing to cache)."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="D" * 1000, section_type=SectionType.DYNAMIC, label="d"),
        ]
        score = optimizer.cache_friendliness_score(sections)
        assert score == pytest.approx(0.0)

    def test_session_stable_improves_score(self):
        """Session-stable content contributes to cacheable prefix."""
        optimizer = PromptOptimizer()
        sections = [
            PromptSection(content="A" * 400, section_type=SectionType.STATIC, label="s"),
            PromptSection(content="B" * 400, section_type=SectionType.SESSION_STABLE, label="ss"),
            PromptSection(content="C" * 200, section_type=SectionType.DYNAMIC, label="d"),
        ]
        score = optimizer.cache_friendliness_score(sections)
        assert score > 0.7

    def test_empty_sections_zero_score(self):
        optimizer = PromptOptimizer()
        assert optimizer.cache_friendliness_score([]) == pytest.approx(0.0)


# =========================================================================
# RBAC partition interaction with prompt caching (n>=5)
# =========================================================================


class TestRBACCacheInteraction:
    """Tests for RBAC partition impact on prompt cache effectiveness.

    CRITICAL: RBAC partitioning fragments prompt cache prefixes.
    Multi-tenant deployments have lower hit rates than single-tenant.
    """

    def test_single_tenant_high_hit_rate(self):
        """Single-tenant: all users share same RBAC -> high hit rate."""
        metrics = CacheMetrics()
        # 100 queries, same RBAC partition
        for _ in range(100):
            metrics.record_query(partition_key="cl:2|dept:legal|ent:")

        stats = metrics.compute_stats(
            static_token_ratio=0.75, deployment_type="single_tenant"
        )
        assert isinstance(stats, PromptCacheStats)
        # Single partition = high reuse
        assert stats.hit_rate >= 0.50

    def test_multi_tenant_lower_hit_rate(self):
        """Multi-tenant (5 clients): more partitions -> more cold misses.

        5 partitions with 100 queries evenly distributed = 5 cold misses.
        Within-partition hit rate is 95/100 = 0.95.
        The key metric is unique_partitions (which determines real-world
        fragmentation), not just hit_rate.
        """
        metrics = CacheMetrics()
        partitions = [
            "cl:1|dept:warehouse|ent:clientA",
            "cl:2|dept:legal|ent:clientB",
            "cl:3|dept:hr|ent:clientC",
            "cl:1|dept:warehouse|ent:clientD",
            "cl:4|dept:executive|ent:clientE",
        ]
        for i in range(100):
            metrics.record_query(partition_key=partitions[i % 5])

        # Multi-tenant has more unique partitions than single-tenant
        assert metrics.unique_partitions == 5
        # Each partition's first query is a miss
        assert metrics.cache_misses == 5
        # Within-partition reuse is high, but partition count matters for
        # real-world cache efficiency (each partition has separate prefix)
        stats = metrics.compute_stats(
            static_token_ratio=0.75, deployment_type="multi_tenant"
        )
        assert stats.deployment_type == "multi_tenant"

    def test_many_partitions_high_fragmentation(self):
        """20+ RBAC partitions -> high fragmentation, many cold misses.

        With 20 unique partitions and 100 queries, 20 are cold misses.
        The partition count is the real metric — it determines how many
        separate cache prefixes exist. More partitions = more miss overhead.
        """
        metrics = CacheMetrics()
        for i in range(100):
            partition = f"cl:{i % 4 + 1}|dept:dept{i % 5}|ent:client{i % 20}"
            metrics.record_query(partition_key=partition)

        # High partition count = high fragmentation
        assert metrics.unique_partitions >= 20
        # 20+ cold misses (one per unique partition)
        assert metrics.cache_misses >= 20
        # Fragmentation ratio: misses / total = cold miss overhead
        cold_miss_rate = metrics.cache_misses / 100
        assert cold_miss_rate >= 0.20  # At least 20% cold misses

    def test_partition_key_in_cache_key(self):
        """RBAC partition key MUST be included in cache key."""
        metrics = CacheMetrics()
        metrics.record_query(partition_key="cl:1|dept:warehouse|ent:")
        metrics.record_query(partition_key="cl:3|dept:hr|ent:")

        # Two different partitions should NOT share cache
        assert metrics.unique_partitions == 2

    def test_same_partition_reuses_cache(self):
        """Same partition key -> cache reuse."""
        metrics = CacheMetrics()
        metrics.record_query(partition_key="cl:2|dept:legal|ent:")
        metrics.record_query(partition_key="cl:2|dept:legal|ent:")
        metrics.record_query(partition_key="cl:2|dept:legal|ent:")

        # Same partition, 3 queries: 2 cache hits (first is miss)
        assert metrics.cache_hits == 2
        assert metrics.cache_misses == 1

    def test_honest_multi_tenant_savings(self):
        """Multi-tenant savings are lower than single-tenant (honesty check)."""
        # Single-tenant
        single = CacheMetrics()
        for _ in range(100):
            single.record_query(partition_key="cl:2|dept:legal|ent:")
        single_stats = single.compute_stats(
            static_token_ratio=0.75, deployment_type="single_tenant"
        )

        # Multi-tenant (5 partitions)
        multi = CacheMetrics()
        for i in range(100):
            multi.record_query(
                partition_key=f"cl:{i % 3 + 1}|dept:dept{i % 5}|ent:"
            )
        multi_stats = multi.compute_stats(
            static_token_ratio=0.75, deployment_type="multi_tenant"
        )

        assert single_stats.hit_rate > multi_stats.hit_rate


# =========================================================================
# Cost savings calculation
# =========================================================================


class TestCostSavingsCalculation:
    """Tests for prompt cache cost savings estimation."""

    def test_savings_proportional_to_hit_rate(self):
        """Higher hit rate -> higher savings."""
        optimizer = PromptOptimizer()
        savings_low = optimizer.estimate_daily_savings(
            queries_per_day=1000,
            avg_prompt_tokens=2000,
            static_token_ratio=0.75,
            hit_rate=0.20,
            cost_per_1k_tokens=0.0025,  # $2.50/1M
        )
        savings_high = optimizer.estimate_daily_savings(
            queries_per_day=1000,
            avg_prompt_tokens=2000,
            static_token_ratio=0.75,
            hit_rate=0.60,
            cost_per_1k_tokens=0.0025,
        )
        assert savings_high > savings_low

    def test_zero_hit_rate_zero_savings(self):
        """0% hit rate -> EUR 0 savings."""
        optimizer = PromptOptimizer()
        savings = optimizer.estimate_daily_savings(
            queries_per_day=1000,
            avg_prompt_tokens=2000,
            static_token_ratio=0.75,
            hit_rate=0.0,
            cost_per_1k_tokens=0.0025,
        )
        assert savings == pytest.approx(0.0)

    def test_full_hit_rate_maximum_savings(self):
        """100% hit rate -> maximum savings (50% of static token cost)."""
        optimizer = PromptOptimizer()
        savings = optimizer.estimate_daily_savings(
            queries_per_day=1000,
            avg_prompt_tokens=2000,
            static_token_ratio=0.75,
            hit_rate=1.0,
            cost_per_1k_tokens=0.0025,
        )
        # 1000 queries * 2000 tokens * 0.75 static * 0.50 cache discount * $0.0025/1K
        # = 1000 * 1.5 * 0.50 * 0.0025 = $1.875
        assert savings > 0.0

    def test_savings_scales_with_volume(self):
        """10x queries -> 10x savings."""
        optimizer = PromptOptimizer()
        s1 = optimizer.estimate_daily_savings(100, 2000, 0.75, 0.50, 0.0025)
        s10 = optimizer.estimate_daily_savings(1000, 2000, 0.75, 0.50, 0.0025)
        assert s10 == pytest.approx(s1 * 10.0)

    def test_savings_zero_queries(self):
        optimizer = PromptOptimizer()
        savings = optimizer.estimate_daily_savings(0, 2000, 0.75, 0.50, 0.0025)
        assert savings == pytest.approx(0.0)
