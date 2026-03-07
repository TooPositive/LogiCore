"""Tests for re-ranking module — cross-encoder, circuit breaker, factory.

RED phase: all tests written before implementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.rag.reranker import (
    BaseReranker,
    CircuitBreakerReranker,
    CohereReranker,
    LocalCrossEncoderReranker,
    NoOpReranker,
    RerankerError,
    RerankerStrategy,
    RerankResult,
    get_reranker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_results(n: int = 5) -> list:
    """Create fake search result objects with content, score, source, etc."""

    class FakeSearchResult:
        def __init__(self, content, score, source, document_id, chunk_index):
            self.content = content
            self.score = score
            self.source = source
            self.document_id = document_id
            self.chunk_index = chunk_index

    return [
        FakeSearchResult(
            content=f"Document {i} content about logistics topic {i}.",
            score=1.0 - i * 0.1,
            source=f"doc_{i}.pdf",
            document_id=f"DOC-{i:03d}",
            chunk_index=i,
        )
        for i in range(n)
    ]


# ===========================================================================
# RerankResult model tests
# ===========================================================================


class TestRerankResult:
    def test_all_fields_present(self):
        r = RerankResult(
            content="Some text",
            original_score=0.95,
            rerank_score=0.88,
            source="contract.pdf",
            document_id="DOC-001",
            chunk_index=0,
            original_rank=0,
            new_rank=2,
        )
        assert r.content == "Some text"
        assert r.original_score == 0.95
        assert r.rerank_score == 0.88
        assert r.source == "contract.pdf"
        assert r.document_id == "DOC-001"
        assert r.chunk_index == 0
        assert r.original_rank == 0
        assert r.new_rank == 2

    def test_preserves_both_scores(self):
        """Original and rerank scores are independent — for comparison."""
        r = RerankResult(
            content="text",
            original_score=0.9,
            rerank_score=0.3,
            source="a.pdf",
            document_id="D1",
            chunk_index=0,
            original_rank=0,
            new_rank=4,
        )
        assert r.original_score != r.rerank_score
        assert r.original_rank != r.new_rank


# ===========================================================================
# BaseReranker ABC tests
# ===========================================================================


class TestBaseReranker:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseReranker()

    def test_subclass_must_implement_rerank(self):
        class BadReranker(BaseReranker):
            pass

        with pytest.raises(TypeError):
            BadReranker()

    @pytest.mark.asyncio
    async def test_subclass_with_rerank_works(self):
        class GoodReranker(BaseReranker):
            async def rerank(self, query, results, top_k=5):
                return []

        reranker = GoodReranker()
        result = await reranker.rerank("test", [])
        assert result == []


# ===========================================================================
# NoOpReranker tests
# ===========================================================================


class TestNoOpReranker:
    @pytest.mark.asyncio
    async def test_returns_same_order(self):
        """Pass-through: order unchanged, rerank_score = original_score."""
        reranker = NoOpReranker()
        results = _make_search_results(3)
        reranked = await reranker.rerank("query", results)
        assert len(reranked) == 3
        for i, r in enumerate(reranked):
            assert r.original_rank == i
            assert r.new_rank == i
            assert r.rerank_score == r.original_score

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        reranker = NoOpReranker()
        reranked = await reranker.rerank("query", [])
        assert reranked == []

    @pytest.mark.asyncio
    async def test_respects_top_k(self):
        reranker = NoOpReranker()
        results = _make_search_results(10)
        reranked = await reranker.rerank("query", results, top_k=3)
        assert len(reranked) == 3

    @pytest.mark.asyncio
    async def test_preserves_content_and_metadata(self):
        reranker = NoOpReranker()
        results = _make_search_results(2)
        reranked = await reranker.rerank("query", results)
        assert reranked[0].content == results[0].content
        assert reranked[0].source == results[0].source
        assert reranked[0].document_id == results[0].document_id
        assert reranked[0].chunk_index == results[0].chunk_index

    @pytest.mark.asyncio
    async def test_confidence_threshold_filters_low_scores(self):
        reranker = NoOpReranker(confidence_threshold=0.5)
        results = _make_search_results(5)
        # Scores are 1.0, 0.9, 0.8, 0.7, 0.6 — all above 0.5
        reranked = await reranker.rerank("query", results)
        assert len(reranked) == 5

    @pytest.mark.asyncio
    async def test_confidence_threshold_excludes_below(self):
        reranker = NoOpReranker(confidence_threshold=0.85)
        results = _make_search_results(5)
        # Scores: 1.0, 0.9, 0.8, 0.7, 0.6 — only 1.0, 0.9 pass
        reranked = await reranker.rerank("query", results)
        assert len(reranked) == 2

    @pytest.mark.asyncio
    async def test_all_below_threshold_returns_empty(self):
        reranker = NoOpReranker(confidence_threshold=2.0)
        results = _make_search_results(3)
        reranked = await reranker.rerank("query", results)
        assert reranked == []


# ===========================================================================
# CohereReranker tests (mocked HTTP)
# ===========================================================================


class TestCohereReranker:
    @pytest.mark.asyncio
    async def test_calls_cohere_api_correctly(self):
        """Should POST to Cohere rerank endpoint with correct body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.99},
                {"index": 0, "relevance_score": 0.85},
                {"index": 1, "relevance_score": 0.70},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="test-key", model="rerank-v3.5")
            results = _make_search_results(3)
            await reranker.rerank("logistics query", results, top_k=3)

            # Verify API was called
            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            # Check the body has correct structure
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["query"] == "logistics query"
            assert body["model"] == "rerank-v3.5"
            assert len(body["documents"]) == 3

    @pytest.mark.asyncio
    async def test_reorders_by_cohere_score(self):
        """Results should be reordered by Cohere relevance_score, descending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.99},
                {"index": 0, "relevance_score": 0.85},
                {"index": 1, "relevance_score": 0.30},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="test-key")
            results = _make_search_results(3)
            reranked = await reranker.rerank("query", results, top_k=3)

            # The result at original index 2 should now be first
            assert reranked[0].document_id == "DOC-002"
            assert reranked[0].rerank_score == 0.99
            assert reranked[0].new_rank == 0
            # Original index 0 second
            assert reranked[1].document_id == "DOC-000"
            assert reranked[1].rerank_score == 0.85

    @pytest.mark.asyncio
    async def test_respects_top_k(self):
        """Should return at most top_k results even if API returns more."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.99},
                {"index": 1, "relevance_score": 0.85},
                {"index": 2, "relevance_score": 0.70},
                {"index": 3, "relevance_score": 0.50},
                {"index": 4, "relevance_score": 0.30},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="test-key")
            results = _make_search_results(5)
            reranked = await reranker.rerank("query", results, top_k=2)

            assert len(reranked) == 2

    @pytest.mark.asyncio
    async def test_api_error_raises_reranker_error(self):
        """HTTP errors from Cohere should raise RerankerError."""
        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="test-key")
            results = _make_search_results(3)

            with pytest.raises(RerankerError):
                await reranker.rerank("query", results)

    @pytest.mark.asyncio
    async def test_configurable_model(self):
        """Model name should be passed through to the API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"index": 0, "relevance_score": 0.9}]}
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="key", model="rerank-english-v2.0")
            results = _make_search_results(1)
            await reranker.rerank("query", results)

            call_kw = mock_client.post.call_args
            body = call_kw.kwargs.get("json") or call_kw[1].get("json")
            assert body["model"] == "rerank-english-v2.0"

    @pytest.mark.asyncio
    async def test_confidence_threshold_filters(self):
        """Results below confidence_threshold should be excluded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.40},
                {"index": 2, "relevance_score": 0.10},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranker = CohereReranker(api_key="key", confidence_threshold=0.5)
            results = _make_search_results(3)
            reranked = await reranker.rerank("query", results, top_k=10)

            # Only index 0 (score 0.95) passes threshold of 0.5
            assert len(reranked) == 1
            assert reranked[0].rerank_score == 0.95

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        reranker = CohereReranker(api_key="key")
        reranked = await reranker.rerank("query", [])
        assert reranked == []


# ===========================================================================
# LocalCrossEncoderReranker tests (mocked model)
# ===========================================================================


class TestLocalCrossEncoderReranker:
    @pytest.mark.asyncio
    async def test_calls_cross_encoder_predict(self):
        """Should call model.predict with query-document pairs."""
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_model = MagicMock()
            # predict returns scores for each query-doc pair
            mock_model.predict.return_value = [0.9, 0.3, 0.7]
            mock_ce_cls.return_value = mock_model

            reranker = LocalCrossEncoderReranker(
                model_name="cross-encoder/ms-marco-MiniLM-L-12-v2"
            )
            results = _make_search_results(3)
            await reranker.rerank("logistics query", results, top_k=3)

            mock_model.predict.assert_called_once()
            call_args = mock_model.predict.call_args[0][0]
            # Should be list of [query, doc_content] pairs
            assert len(call_args) == 3
            assert call_args[0][0] == "logistics query"

    @pytest.mark.asyncio
    async def test_reorders_by_cross_encoder_score(self):
        """Results should be sorted by cross-encoder score descending."""
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_model = MagicMock()
            mock_model.predict.return_value = [0.3, 0.9, 0.6]
            mock_ce_cls.return_value = mock_model

            reranker = LocalCrossEncoderReranker()
            results = _make_search_results(3)
            reranked = await reranker.rerank("query", results, top_k=3)

            # Index 1 had highest score (0.9) -> should be first
            assert reranked[0].document_id == "DOC-001"
            assert reranked[0].rerank_score == 0.9
            assert reranked[0].new_rank == 0
            # Index 2 had second highest (0.6)
            assert reranked[1].document_id == "DOC-002"
            assert reranked[1].rerank_score == 0.6
            assert reranked[1].new_rank == 1

    @pytest.mark.asyncio
    async def test_respects_top_k(self):
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_model = MagicMock()
            mock_model.predict.return_value = [0.9, 0.8, 0.7, 0.6, 0.5]
            mock_ce_cls.return_value = mock_model

            reranker = LocalCrossEncoderReranker()
            results = _make_search_results(5)
            reranked = await reranker.rerank("query", results, top_k=2)

            assert len(reranked) == 2

    @pytest.mark.asyncio
    async def test_model_loading_failure_raises_reranker_error(self):
        """If the cross-encoder model fails to load, raise RerankerError."""
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_ce_cls.side_effect = OSError("Model not found")

            reranker = LocalCrossEncoderReranker(model_name="nonexistent/model")
            results = _make_search_results(3)

            with pytest.raises(RerankerError):
                await reranker.rerank("query", results)

    @pytest.mark.asyncio
    async def test_configurable_model_name(self):
        """Model name should be passed to CrossEncoder constructor."""
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_model = MagicMock()
            mock_model.predict.return_value = [0.5]
            mock_ce_cls.return_value = mock_model

            reranker = LocalCrossEncoderReranker(model_name="custom/model-v2")
            results = _make_search_results(1)
            await reranker.rerank("query", results)

            mock_ce_cls.assert_called_once_with("custom/model-v2")

    @pytest.mark.asyncio
    async def test_confidence_threshold_filters(self):
        with patch("apps.api.src.rag.reranker.CrossEncoder") as mock_ce_cls:
            mock_model = MagicMock()
            mock_model.predict.return_value = [0.9, 0.2, 0.1]
            mock_ce_cls.return_value = mock_model

            reranker = LocalCrossEncoderReranker(confidence_threshold=0.5)
            results = _make_search_results(3)
            reranked = await reranker.rerank("query", results, top_k=10)

            assert len(reranked) == 1
            assert reranked[0].rerank_score == 0.9

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        reranker = LocalCrossEncoderReranker()
        reranked = await reranker.rerank("query", [])
        assert reranked == []


# ===========================================================================
# CircuitBreakerReranker tests
# ===========================================================================


class TestCircuitBreakerReranker:
    def _make_primary_fallback(self):
        """Create mock primary and fallback rerankers."""
        primary = AsyncMock(spec=BaseReranker)
        fallback = AsyncMock(spec=BaseReranker)

        # Default: primary succeeds, fallback succeeds
        primary.rerank = AsyncMock(return_value=[
            RerankResult(
                content="primary result",
                original_score=0.9,
                rerank_score=0.95,
                source="p.pdf",
                document_id="P1",
                chunk_index=0,
                original_rank=0,
                new_rank=0,
            )
        ])
        fallback.rerank = AsyncMock(return_value=[
            RerankResult(
                content="fallback result",
                original_score=0.9,
                rerank_score=0.80,
                source="f.pdf",
                document_id="F1",
                chunk_index=0,
                original_rank=0,
                new_rank=0,
            )
        ])
        return primary, fallback

    @pytest.mark.asyncio
    async def test_uses_primary_when_healthy(self):
        """In CLOSED state, should use the primary reranker."""
        primary, fallback = self._make_primary_fallback()
        cb = CircuitBreakerReranker(primary=primary, fallback=fallback)

        results = _make_search_results(1)
        reranked = await cb.rerank("query", results)

        primary.rerank.assert_called_once()
        fallback.rerank.assert_not_called()
        assert reranked[0].content == "primary result"

    @pytest.mark.asyncio
    async def test_falls_back_after_n_consecutive_failures(self):
        """After failure_threshold consecutive failures, switch to fallback."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary, fallback=fallback, failure_threshold=3
        )

        results = _make_search_results(1)

        # First 3 calls: primary fails, falls back each time
        for _ in range(3):
            reranked = await cb.rerank("query", results)
            assert reranked[0].content == "fallback result"

        # After 3 failures, circuit should be OPEN
        # 4th call should go directly to fallback (not try primary)
        primary.rerank.reset_mock()
        fallback.rerank.reset_mock()

        reranked = await cb.rerank("query", results)
        primary.rerank.assert_not_called()
        fallback.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_configurable_failure_threshold(self):
        """failure_threshold=5 means 5 failures before circuit opens."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary, fallback=fallback, failure_threshold=5
        )

        results = _make_search_results(1)

        # After 4 failures, primary should still be tried (threshold is 5)
        for _ in range(4):
            await cb.rerank("query", results)

        primary.rerank.reset_mock()
        await cb.rerank("query", results)
        # 5th failure — primary still tried (this is the 5th)
        primary.rerank.assert_called_once()

        # After 5 failures, circuit opens — primary NOT tried
        primary.rerank.reset_mock()
        fallback.rerank.reset_mock()
        await cb.rerank("query", results)
        primary.rerank.assert_not_called()
        fallback.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_failure_count_on_success(self):
        """A successful primary call should reset the failure counter."""
        primary, fallback = self._make_primary_fallback()

        call_count = 0

        async def flaky_rerank(query, results, top_k=5):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RerankerError("fail")
            return [
                RerankResult(
                    content="primary result",
                    original_score=0.9,
                    rerank_score=0.95,
                    source="p.pdf",
                    document_id="P1",
                    chunk_index=0,
                    original_rank=0,
                    new_rank=0,
                )
            ]

        primary.rerank = flaky_rerank

        cb = CircuitBreakerReranker(
            primary=primary, fallback=fallback, failure_threshold=3
        )

        results = _make_search_results(1)

        # 2 failures, then success — counter should reset
        await cb.rerank("q", results)  # fail 1
        await cb.rerank("q", results)  # fail 2
        await cb.rerank("q", results)  # success -> reset

        # Now 2 more failures should NOT open circuit (threshold is 3)
        call_count = 0  # reset flaky behavior

        async def fail_twice(query, results, top_k=5):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RerankerError("fail again")
            return [
                RerankResult(
                    content="primary result",
                    original_score=0.9,
                    rerank_score=0.95,
                    source="p.pdf",
                    document_id="P1",
                    chunk_index=0,
                    original_rank=0,
                    new_rank=0,
                )
            ]

        primary.rerank = fail_twice
        # 2 more failures — still below threshold (3), primary still tried
        await cb.rerank("q", results)  # fail 1
        await cb.rerank("q", results)  # fail 2
        # 3rd call — primary should still be tried (only 2 failures since reset)
        reranked = await cb.rerank("q", results)
        assert reranked[0].content == "primary result"

    @pytest.mark.asyncio
    async def test_half_open_tries_primary_after_timeout(self):
        """After recovery_timeout, circuit goes HALF_OPEN and tries primary once."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary,
            fallback=fallback,
            failure_threshold=2,
            recovery_timeout=0.1,  # 100ms for fast test
        )

        results = _make_search_results(1)

        # Trigger circuit open
        await cb.rerank("q", results)  # fail 1
        await cb.rerank("q", results)  # fail 2 -> circuit opens

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Now primary should succeed
        primary.rerank = AsyncMock(return_value=[
            RerankResult(
                content="recovered",
                original_score=0.9,
                rerank_score=0.95,
                source="p.pdf",
                document_id="P1",
                chunk_index=0,
                original_rank=0,
                new_rank=0,
            )
        ])

        reranked = await cb.rerank("q", results)
        primary.rerank.assert_called_once()
        assert reranked[0].content == "recovered"

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """If the half-open probe fails, circuit goes back to OPEN."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary,
            fallback=fallback,
            failure_threshold=2,
            recovery_timeout=0.1,
        )

        results = _make_search_results(1)

        # Trigger circuit open
        await cb.rerank("q", results)  # fail 1
        await cb.rerank("q", results)  # fail 2 -> open

        # Wait for recovery timeout
        await asyncio.sleep(0.15)

        # Half-open probe — primary still fails
        reranked = await cb.rerank("q", results)
        assert reranked[0].content == "fallback result"  # fell back

        # Circuit should be back to OPEN — next call should NOT try primary
        primary.rerank.reset_mock()
        fallback.rerank.reset_mock()

        reranked = await cb.rerank("q", results)
        primary.rerank.assert_not_called()
        fallback.rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """If half-open probe succeeds, circuit returns to CLOSED."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary,
            fallback=fallback,
            failure_threshold=2,
            recovery_timeout=0.1,
        )

        results = _make_search_results(1)

        # Trigger circuit open
        await cb.rerank("q", results)
        await cb.rerank("q", results)

        # Wait for recovery
        await asyncio.sleep(0.15)

        # Fix primary
        primary.rerank = AsyncMock(return_value=[
            RerankResult(
                content="back online",
                original_score=0.9,
                rerank_score=0.95,
                source="p.pdf",
                document_id="P1",
                chunk_index=0,
                original_rank=0,
                new_rank=0,
            )
        ])

        # Half-open probe succeeds
        await cb.rerank("q", results)

        # Circuit should now be CLOSED — next calls go to primary
        primary.rerank.reset_mock()
        reranked = await cb.rerank("q", results)
        primary.rerank.assert_called_once()
        assert reranked[0].content == "back online"

    @pytest.mark.asyncio
    async def test_stays_open_within_timeout(self):
        """While within recovery_timeout, circuit stays OPEN."""
        primary, fallback = self._make_primary_fallback()
        primary.rerank = AsyncMock(side_effect=RerankerError("fail"))

        cb = CircuitBreakerReranker(
            primary=primary,
            fallback=fallback,
            failure_threshold=2,
            recovery_timeout=10.0,  # very long — won't expire in test
        )

        results = _make_search_results(1)

        # Open circuit
        await cb.rerank("q", results)
        await cb.rerank("q", results)

        # Still within timeout — should use fallback only
        primary.rerank.reset_mock()
        fallback.rerank.reset_mock()

        await cb.rerank("q", results)
        primary.rerank.assert_not_called()
        fallback.rerank.assert_called_once()


# ===========================================================================
# Factory function tests
# ===========================================================================


class TestGetReranker:
    def test_returns_noop_reranker(self):
        reranker = get_reranker(RerankerStrategy.NOOP)
        assert isinstance(reranker, NoOpReranker)

    def test_returns_cohere_reranker(self):
        reranker = get_reranker(RerankerStrategy.COHERE, api_key="test-key")
        assert isinstance(reranker, CohereReranker)

    def test_returns_local_cross_encoder_reranker(self):
        reranker = get_reranker(RerankerStrategy.LOCAL_CROSS_ENCODER)
        assert isinstance(reranker, LocalCrossEncoderReranker)

    def test_invalid_strategy_raises(self):
        with pytest.raises((ValueError, KeyError)):
            get_reranker("nonexistent_strategy")

    def test_passes_kwargs_to_noop(self):
        reranker = get_reranker(RerankerStrategy.NOOP, confidence_threshold=0.5)
        assert isinstance(reranker, NoOpReranker)

    def test_passes_kwargs_to_cohere(self):
        reranker = get_reranker(
            RerankerStrategy.COHERE, api_key="k", model="rerank-english-v2.0"
        )
        assert isinstance(reranker, CohereReranker)

    def test_passes_kwargs_to_local(self):
        reranker = get_reranker(
            RerankerStrategy.LOCAL_CROSS_ENCODER,
            model_name="custom/model",
            confidence_threshold=0.3,
        )
        assert isinstance(reranker, LocalCrossEncoderReranker)


# ===========================================================================
# RerankerStrategy enum tests
# ===========================================================================


class TestRerankerStrategy:
    def test_values(self):
        assert RerankerStrategy.COHERE == "cohere"
        assert RerankerStrategy.LOCAL_CROSS_ENCODER == "local_cross_encoder"
        assert RerankerStrategy.NOOP == "noop"
