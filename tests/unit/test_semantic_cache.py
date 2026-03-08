"""Unit tests for Phase 4 semantic cache.

SECURITY-CRITICAL: RBAC-aware cache keys ensure that cached responses
are scoped to clearance_level + departments + entity keys.

Tests: cache hit/miss, RBAC partitioning, entity awareness, staleness
detection, TTL, invalidation, cacheable flag, LRU eviction.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_embedder():
    """Mock embedder that returns consistent vectors for same input."""
    import hashlib

    async def _embed(text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).hexdigest()
        # Deterministic 10-dim vector from hash
        return [int(c, 16) / 15.0 for c in h[:10]]

    embedder = MagicMock()
    embedder.embed = AsyncMock(side_effect=_embed)
    return embedder


class TestCacheCreation:
    """SemanticCache creation and basic operations."""

    def test_cache_creation(self):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(
            similarity_threshold=0.95,
            ttl_seconds=86400,
            max_entries=10000,
        )
        assert cache is not None
        assert cache.similarity_threshold == 0.95

    def test_cache_configurable_threshold(self):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.97)
        assert cache.similarity_threshold == 0.97


class TestCacheHitMiss:
    """Cache lookup returns hit for similar queries, miss for dissimilar."""

    @pytest.mark.asyncio
    async def test_cache_miss_on_empty(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)
        result = await cache.get(
            query="What is the penalty?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_on_exact_match(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)
        await cache.put(
            query="What is the penalty for late delivery?",
            response="The penalty is 2% per day...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )
        result = await cache.get(
            query="What is the penalty for late delivery?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            embed_fn=mock_embedder.embed,
        )
        assert result is not None
        assert "penalty" in result.lower() or "2%" in result

    @pytest.mark.asyncio
    async def test_cache_miss_on_different_query(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)
        await cache.put(
            query="What is the penalty for late delivery?",
            response="The penalty is 2% per day...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )
        # Completely different query
        result = await cache.get(
            query="How many trucks are in the fleet?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_stores_multiple_entries(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)
        for i in range(5):
            await cache.put(
                query=f"Unique query number {i}",
                response=f"Response {i}",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[],
                source_doc_ids=[],
                embed_fn=mock_embedder.embed,
            )
        assert cache.size() == 5


class TestRBACPartitioning:
    """RBAC-aware cache keys -- this is the EUR 250,000 security decision."""

    @pytest.mark.asyncio
    async def test_different_clearance_different_partition(self, mock_embedder):
        """Clearance-3 cached response must NOT be served to clearance-1 user."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        # Clearance 3 user caches a response
        await cache.put(
            query="What is the termination clause?",
            response="CONFIDENTIAL: The termination clause states...",
            clearance_level=3,
            departments=["hr", "management"],
            entity_keys=[],
            source_doc_ids=["doc-secret"],
            embed_fn=mock_embedder.embed,
        )

        # Clearance 1 user asks same query -- must NOT get the cached response
        result = await cache.get(
            query="What is the termination clause?",
            clearance_level=1,
            departments=["warehouse"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_different_departments_different_partition(self, mock_embedder):
        """HR cache must not leak to warehouse users."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What are the salary bands?",
            response="Salary bands: L1=3000, L2=5000...",
            clearance_level=2,
            departments=["hr"],
            entity_keys=[],
            source_doc_ids=["doc-hr"],
            embed_fn=mock_embedder.embed,
        )

        # Same clearance, different department
        result = await cache.get(
            query="What are the salary bands?",
            clearance_level=2,
            departments=["warehouse"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_same_clearance_same_department_hits(self, mock_embedder):
        """Same RBAC context should hit the cache."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What are the delivery procedures?",
            response="Standard delivery procedures are...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        result = await cache.get(
            query="What are the delivery procedures?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_department_order_does_not_affect_partition(self, mock_embedder):
        """Same departments in different order must hit same partition."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is company policy?",
            response="Company policy states...",
            clearance_level=2,
            departments=["management", "hr"],
            entity_keys=[],
            source_doc_ids=[],
            embed_fn=mock_embedder.embed,
        )

        # Different order
        result = await cache.get(
            query="What is company policy?",
            clearance_level=2,
            departments=["hr", "management"],
            embed_fn=mock_embedder.embed,
        )
        assert result is not None


class TestEntityAwareness:
    """Entity-aware cache keys prevent cross-client data leakage."""

    @pytest.mark.asyncio
    async def test_different_entity_different_partition(self, mock_embedder):
        """PharmaCorp cache must NOT serve FreshFoods responses."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the penalty for late delivery?",
            response="PharmaCorp penalty: 2% per day",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-pharma"],
            embed_fn=mock_embedder.embed,
        )

        # Same query but different entity
        result = await cache.get(
            query="What is the penalty for late delivery?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["FreshFoods"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_same_entity_hits(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the penalty for late delivery?",
            response="PharmaCorp penalty: 2% per day",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-pharma"],
            embed_fn=mock_embedder.embed,
        )

        result = await cache.get(
            query="What is the penalty for late delivery?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            embed_fn=mock_embedder.embed,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_entity_does_not_match_entity_entry(self, mock_embedder):
        """Query without entity must not match entity-scoped cache entry."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the penalty?",
            response="PharmaCorp penalty: 2%",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=[],
            embed_fn=mock_embedder.embed,
        )

        # No entity keys
        result = await cache.get(
            query="What is the penalty?",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            embed_fn=mock_embedder.embed,
        )
        assert result is None


class TestStalenessDetection:
    """Cache entries become stale when source documents are updated."""

    @pytest.mark.asyncio
    async def test_stale_entry_returns_miss(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the delivery rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        # Simulate doc update after cache entry
        doc_updates = {"doc-001": datetime(2099, 1, 1, tzinfo=UTC)}
        result = await cache.get(
            query="What is the delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
            doc_update_times=doc_updates,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_fresh_entry_returns_hit(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the delivery rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        # Doc update BEFORE cache entry -> still fresh
        doc_updates = {"doc-001": datetime(2000, 1, 1, tzinfo=UTC)}
        result = await cache.get(
            query="What is the delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
            doc_update_times=doc_updates,
        )
        assert result is not None


    @pytest.mark.asyncio
    async def test_multi_source_doc_one_stale_returns_miss(self, mock_embedder):
        """Entry with 3 source docs — if ANY one is updated, entry is stale."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What are the combined contract terms?",
            response="Terms from docs 1, 2, and 3...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-A", "doc-B", "doc-C"],
            embed_fn=mock_embedder.embed,
        )

        # Only doc-B was updated — entry should still be stale
        doc_updates = {"doc-B": datetime(2099, 6, 15, tzinfo=UTC)}
        result = await cache.get(
            query="What are the combined contract terms?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
            doc_update_times=doc_updates,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_doc_update_times_treats_as_fresh(self, mock_embedder):
        """When doc_update_times is None, skip staleness check (treat as fresh)."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the delivery rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        # No doc_update_times passed — should return cached response
        result = await cache.get(
            query="What is the delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
            doc_update_times=None,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_unrelated_doc_update_does_not_stale(self, mock_embedder):
        """Doc update for unrelated doc_id should NOT stale the entry."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the delivery rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        # Different doc updated — entry's source (doc-001) is unchanged
        doc_updates = {"doc-999": datetime(2099, 1, 1, tzinfo=UTC)}
        result = await cache.get(
            query="What is the delivery rate?",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
            doc_update_times=doc_updates,
        )
        assert result is not None


class TestCacheInvalidation:
    """Explicit cache invalidation by document ID or full flush."""

    @pytest.mark.asyncio
    async def test_invalidate_by_document_id(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001", "doc-002"],
            embed_fn=mock_embedder.embed,
        )
        await cache.put(
            query="What is the policy?",
            response="Policy states...",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-003"],
            embed_fn=mock_embedder.embed,
        )

        # Invalidate entries from doc-001
        removed = cache.invalidate_by_doc("doc-001")
        assert removed >= 1
        # doc-003 entry should still exist
        assert cache.size() >= 1

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_doc_returns_zero(self, mock_embedder):
        """Invalidating a doc_id not in any cache entry returns 0, no error."""
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is the rate?",
            response="Rate is EUR 0.45/kg",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            embed_fn=mock_embedder.embed,
        )

        removed = cache.invalidate_by_doc("doc-nonexistent")
        assert removed == 0
        assert cache.size() == 1  # Original entry untouched

    @pytest.mark.asyncio
    async def test_flush_all(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        for i in range(5):
            await cache.put(
                query=f"Query {i}",
                response=f"Response {i}",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[],
                source_doc_ids=[],
                embed_fn=mock_embedder.embed,
            )
        assert cache.size() == 5
        cache.flush()
        assert cache.size() == 0


class TestCacheableFlag:
    """Non-cacheable queries must not be stored."""

    @pytest.mark.asyncio
    async def test_non_cacheable_query_not_stored(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(similarity_threshold=0.95)

        await cache.put(
            query="What is shipment XYZ status?",
            response="In transit",
            clearance_level=2,
            departments=["logistics"],
            entity_keys=[],
            source_doc_ids=[],
            embed_fn=mock_embedder.embed,
            cacheable=False,
        )
        assert cache.size() == 0


class TestLRUEviction:
    """LRU eviction when max_entries is reached."""

    @pytest.mark.asyncio
    async def test_lru_evicts_oldest(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(
            similarity_threshold=0.95,
            max_entries=3,
        )

        for i in range(4):
            await cache.put(
                query=f"Unique eviction query {i}",
                response=f"Response {i}",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[],
                source_doc_ids=[],
                embed_fn=mock_embedder.embed,
            )

        # Only 3 entries should remain
        assert cache.size() == 3

    @pytest.mark.asyncio
    async def test_lru_keeps_most_recent(self, mock_embedder):
        from apps.api.src.core.infrastructure.llm.cache import SemanticCache

        cache = SemanticCache(
            similarity_threshold=0.95,
            max_entries=3,
        )

        for i in range(4):
            await cache.put(
                query=f"LRU query {i}",
                response=f"LRU Response {i}",
                clearance_level=2,
                departments=["logistics"],
                entity_keys=[],
                source_doc_ids=[],
                embed_fn=mock_embedder.embed,
            )

        # Most recent (query 3) should still be there
        result = await cache.get(
            query="LRU query 3",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
        )
        assert result is not None

        # Oldest (query 0) should be evicted
        result = await cache.get(
            query="LRU query 0",
            clearance_level=2,
            departments=["logistics"],
            embed_fn=mock_embedder.embed,
        )
        assert result is None
