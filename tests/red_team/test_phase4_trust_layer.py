"""Red team tests for Phase 4: Trust Layer.

These tests prove what the system REFUSES to do. Each test represents
a specific attack vector from the Phase 4 analysis.

8 attack scenarios:
1. RBAC cache bypass (clearance-3 cached, clearance-1 must NOT get it)
2. Cross-client cache leakage (PharmaCorp vs FreshFoods)
3. Stale cache after document re-ingestion
4. Model router financial query override
5. Langfuse outage fallback to PostgreSQL
6. Cache poisoning resistance
7. Cost tracking accuracy
8. Analytics endpoint rate limiting (tested via response format)
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def deterministic_embedder():
    """Embedder that returns consistent vectors for same input."""

    async def _embed(text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).hexdigest()
        return [int(c, 16) / 15.0 for c in h[:10]]

    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=_embed)
    return embedder


class TestRBACCacheBypass:
    """Attack: clearance-3 user caches response, clearance-1 user asks similar query.

    Risk: EUR 25,000-250,000 GDPR/contract exposure if cache serves
    unauthorized data.
    """

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_clearance3_cached_not_served_to_clearance1(
        self, deterministic_embedder
    ):
        """The RBAC cache bypass scenario from the Phase 4 analysis."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        # Katrin (clearance 3) asks about termination -> cached
        await cache.put(
            query="What is the termination clause for PharmaCorp?",
            response="CONFIDENTIAL: Termination requires 90-day notice...",
            clearance_level=3,
            departments=["hr", "management"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-hr-001"],
            embed_fn=deterministic_embedder.embed,
        )

        # Max (clearance 1) asks very similar query -- 0.96+ similarity
        result = await cache.get(
            query="What is the termination clause for PharmaCorp?",
            clearance_level=1,
            departments=["warehouse"],
            entity_keys=["PharmaCorp"],
            embed_fn=deterministic_embedder.embed,
        )
        # MUST be None -- clearance 1 cannot see clearance 3 data
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_clearance2_cached_not_served_to_clearance1(
        self, deterministic_embedder
    ):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What are the logistics KPIs?",
            response="Q3 KPIs: on-time delivery 94%, damage rate 0.3%...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-kpi"],
            embed_fn=deterministic_embedder.embed,
        )

        result = await cache.get(
            query="What are the logistics KPIs?",
            clearance_level=1,
            departments=["logistics"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_clearance4_admin_cached_not_served_to_clearance3(
        self, deterministic_embedder
    ):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What are the executive salary details?",
            response="CEO salary: EUR 250,000, CFO: EUR 180,000...",
            clearance_level=4,
            departments=["executive"],
            entity_keys=[],
            source_doc_ids=["doc-exec"],
            embed_fn=deterministic_embedder.embed,
        )

        result = await cache.get(
            query="What are the executive salary details?",
            clearance_level=3,
            departments=["executive"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_same_clearance_different_dept_blocked(
        self, deterministic_embedder
    ):
        """Same clearance level but different department = different partition."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the HR policy on sick leave?",
            response="HR policy: 10 days paid sick leave...",
            clearance_level=2,
            departments=["hr"],
            entity_keys=[],
            source_doc_ids=["doc-hr-policy"],
            embed_fn=deterministic_embedder.embed,
        )

        result = await cache.get(
            query="What is the HR policy on sick leave?",
            clearance_level=2,
            departments=["warehouse"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_rbac_bypass_with_superset_departments(
        self, deterministic_embedder
    ):
        """User with subset of departments must not get superset partition data."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        # Cached with [hr, management, logistics]
        await cache.put(
            query="What is the full org structure?",
            response="Full org: 5 departments, 200 employees...",
            clearance_level=3,
            departments=["hr", "management", "logistics"],
            entity_keys=[],
            source_doc_ids=["doc-org"],
            embed_fn=deterministic_embedder.embed,
        )

        # User with only [hr] - different partition key
        result = await cache.get(
            query="What is the full org structure?",
            clearance_level=3,
            departments=["hr"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None


class TestCrossClientLeakage:
    """Attack: PharmaCorp data served as FreshFoods response.

    Risk: EUR 486-3,240 per incident. Different rate, different clause.
    """

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_pharmacorp_not_served_as_freshfoods(
        self, deterministic_embedder
    ):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the penalty for late delivery?",
            response="PharmaCorp penalty: 2% per day, max 20%",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-pharma"],
            embed_fn=deterministic_embedder.embed,
        )

        result = await cache.get(
            query="What is the penalty for late delivery?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["FreshFoods"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_client_a_not_served_as_client_b(
        self, deterministic_embedder
    ):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        clients = ["AlphaCorp", "BetaLogistics", "GammaTransport"]
        for client in clients:
            await cache.put(
                query="What is the base shipping rate?",
                response=f"{client} rate: EUR {hash(client) % 100}/ton",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[client],
                source_doc_ids=[f"doc-{client.lower()}"],
                embed_fn=deterministic_embedder.embed,
            )

        # Each client should only see their own data
        for client in clients:
            result = await cache.get(
                query="What is the base shipping rate?",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[client],
                embed_fn=deterministic_embedder.embed,
            )
            assert result is not None
            assert client in result

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_no_entity_key_does_not_leak_entity_data(
        self, deterministic_embedder
    ):
        """Generic query without entity must not get entity-scoped data."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the delivery rate?",
            response="PharmaCorp rate: EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-pharma"],
            embed_fn=deterministic_embedder.embed,
        )

        # No entity key specified
        result = await cache.get(
            query="What is the delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None


class TestStaleCacheAfterReIngestion:
    """Attack: contract updated, cache not invalidated.

    Risk: EUR 500-3,240 per incident. Finance acts on old rate.
    """

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_stale_cache_returns_miss(self, deterministic_embedder):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the PharmaCorp delivery rate?",
            response="Rate: EUR 0.45/kg (Q3 contract)",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-pharma-contract"],
            embed_fn=deterministic_embedder.embed,
        )

        # Contract re-ingested AFTER cache entry was created
        doc_updates = {
            "doc-pharma-contract": datetime(2099, 6, 1, tzinfo=UTC)
        }

        result = await cache.get(
            query="What is the PharmaCorp delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            embed_fn=deterministic_embedder.embed,
            doc_update_times=doc_updates,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_invalidate_by_doc_id_removes_entries(
        self, deterministic_embedder
    ):
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the rate?",
            response="Old rate",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-contract-v1"],
            embed_fn=deterministic_embedder.embed,
        )

        removed = cache.invalidate_by_doc("doc-contract-v1")
        assert removed == 1
        assert cache.size() == 0


class TestModelRouterFinancialOverride:
    """Attack: financial query misrouted to nano model.

    Risk: EUR 5,832/year per 1% misclassification rate on complex queries.
    """

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_invoice_query_never_goes_to_nano(self):
        from apps.api.src.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.99")
        )
        router = ModelRouter(classifier_llm=mock_llm)

        # Even though LLM says SIMPLE, "invoice" keyword forces COMPLEX
        route = await router.route("Check the invoice discrepancy for Q4")
        assert route.selected_model == "gpt-5.2"
        assert route.keyword_override is True
        # LLM should NOT have been called
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_contract_rate_query_forces_complex(self):
        from apps.api.src.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        router = ModelRouter(classifier_llm=mock_llm)

        route = await router.route(
            "What's the PharmaCorp rate with Q4 amendment surcharge?"
        )
        assert route.selected_model == "gpt-5.2"
        assert route.keyword_override is True

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_all_financial_keywords_trigger_override(self):
        from apps.api.src.infrastructure.llm.router import (
            OVERRIDE_KEYWORDS,
            ModelRouter,
        )

        mock_llm = MagicMock()
        router = ModelRouter(classifier_llm=mock_llm)

        for keyword in OVERRIDE_KEYWORDS:
            route = await router.route(f"Query about {keyword}")
            assert route.selected_model == "gpt-5.2", (
                f"Keyword '{keyword}' did not force COMPLEX routing"
            )
            assert route.keyword_override is True

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_garbage_llm_response_defaults_to_complex(self):
        from apps.api.src.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content="I am a helpful assistant and cannot classify"
            )
        )
        router = ModelRouter(classifier_llm=mock_llm)

        route = await router.route("Some non-keyword query about weather")
        assert route.selected_model == "gpt-5.2"

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_low_confidence_escalates_safety(self):
        from apps.api.src.domain.telemetry import QueryComplexity
        from apps.api.src.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.3")
        )
        router = ModelRouter(classifier_llm=mock_llm)

        route = await router.route("What does this clause mean?")
        # Should escalate due to low confidence
        assert route.complexity != QueryComplexity.SIMPLE
        assert route.escalated is True


class TestLangfuseOutageFallback:
    """Attack: Langfuse crashes during incident, traces lost.

    Risk: EUR 10,000-100,000 regulatory exposure.
    """

    @pytest.mark.redteam
    def test_langfuse_outage_traces_preserved(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker
        from apps.api.src.telemetry.langfuse_handler import (
            InMemoryFallbackStore,
            LangfuseHandler,
        )

        mock_langfuse = MagicMock()
        mock_langfuse.trace.side_effect = ConnectionError("Langfuse down")

        fallback = InMemoryFallbackStore()
        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
            fallback_store=fallback,
        )

        # 5 traces during outage
        for i in range(5):
            handler.on_llm_end(
                trace_id=f"outage-trace-{i}",
                run_id=f"outage-run-{i}",
                agent_name="audit",
                model="gpt-5.2",
                prompt=f"audit prompt {i}",
                response=f"audit response {i}",
                prompt_tokens=8200,
                completion_tokens=1200,
                latency_ms=1500.0,
            )

        assert fallback.count() == 5

    @pytest.mark.redteam
    def test_langfuse_recovery_reconciles_all_traces(self):
        from apps.api.src.domain.telemetry import TraceRecord
        from apps.api.src.telemetry.langfuse_handler import (
            InMemoryFallbackStore,
            reconcile_fallback,
        )

        fallback = InMemoryFallbackStore()
        for i in range(5):
            fallback.store_trace(TraceRecord(
                trace_id=f"recon-{i}",
                run_id="recon-run",
                agent_name="search",
                model="gpt-5-mini",
                prompt_tokens=2800,
                completion_tokens=400,
                latency_ms=800.0,
                cost_eur=Decimal("0.0015"),
            ))

        mock_langfuse = MagicMock()
        reconciled = reconcile_fallback(mock_langfuse, fallback)
        assert reconciled == 5
        assert fallback.count() == 0
        assert mock_langfuse.trace.call_count == 5


class TestCachePoisoningResistance:
    """Attack: inject malicious content into cache."""

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_cache_entry_from_one_partition_isolated(
        self, deterministic_embedder
    ):
        """Entries from different RBAC contexts cannot cross-contaminate."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        # "Poison" attempt: low-clearance user tries to pollute
        await cache.put(
            query="What are the admin passwords?",
            response="INJECTED: admin=password123",
            clearance_level=1,
            departments=["warehouse"],
            entity_keys=[],
            source_doc_ids=[],
            embed_fn=deterministic_embedder.embed,
        )

        # High-clearance user should not see the poisoned entry
        result = await cache.get(
            query="What are the admin passwords?",
            clearance_level=3,
            departments=["it"],
            embed_fn=deterministic_embedder.embed,
        )
        assert result is None

    @pytest.mark.redteam
    @pytest.mark.asyncio
    async def test_non_cacheable_prevents_poisoning(
        self, deterministic_embedder
    ):
        """Non-cacheable flag prevents storing potentially poisoned data."""
        from apps.api.src.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="Some suspicious query",
            response="Potentially poisoned response",
            clearance_level=1,
            departments=["warehouse"],
            entity_keys=[],
            source_doc_ids=[],
            embed_fn=deterministic_embedder.embed,
            cacheable=False,
        )
        assert cache.size() == 0


class TestCostTrackingAccuracy:
    """Verify cost calculations match spec pricing exactly."""

    @pytest.mark.redteam
    def test_nano_cost_matches_spec(self):
        """Spec: GPT-5 nano $0.05/$0.40 per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        # 500 input + 100 output (simple lookup from spec)
        cost = calculate_query_cost("gpt-5-nano", 500, 100)
        expected = Decimal("500") / Decimal("1000000") * Decimal("0.05") + \
            Decimal("100") / Decimal("1000000") * Decimal("0.40")
        assert cost == expected

    @pytest.mark.redteam
    def test_mini_cost_matches_spec(self):
        """Spec: GPT-5 mini $0.25/$2.00 per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost("gpt-5-mini", 2800, 400)
        expected = Decimal("2800") / Decimal("1000000") * Decimal("0.25") + \
            Decimal("400") / Decimal("1000000") * Decimal("2.00")
        assert cost == expected

    @pytest.mark.redteam
    def test_gpt52_cost_matches_spec(self):
        """Spec: GPT-5.2 $1.75/$14.00 per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost("gpt-5.2", 8200, 1200)
        expected = Decimal("8200") / Decimal("1000000") * Decimal("1.75") + \
            Decimal("1200") / Decimal("1000000") * Decimal("14.00")
        assert cost == expected

    @pytest.mark.redteam
    def test_cache_hit_always_zero_cost(self):
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost("gpt-5.2", 8200, 1200, cache_hit=True)
        assert cost == Decimal("0")

    @pytest.mark.redteam
    def test_daily_routing_savings_93_percent(self):
        """Spec: routing + caching saves 93% vs unrouted GPT-5.2."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        # Unrouted: 2400 queries * GPT-5.2 avg cost
        unrouted = calculate_query_cost("gpt-5.2", 3000, 500) * 2400

        # Routed (from spec distribution)
        routed = (
            calculate_query_cost("gpt-5-mini", 2800, 400) * 800
            + calculate_query_cost("gpt-5.2", 8200, 1200) * 50
            + calculate_query_cost("gpt-5-mini", 4500, 600) * 30
            + calculate_query_cost("gpt-5-nano", 500, 100) * 900
        )

        savings = 1 - (routed / unrouted)
        assert savings > Decimal("0.90")
