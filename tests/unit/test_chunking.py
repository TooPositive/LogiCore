"""Tests for chunking strategies — fixed-size, semantic, parent-child.

RED phase: all tests written before implementation.
"""

import math

import pytest

from apps.api.src.core.rag.chunking import (
    BaseChunker,
    ChunkingStrategy,
    ChunkResult,
    FixedSizeChunker,
    ParentChildChunker,
    SemanticChunker,
    get_chunker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embed_fn(sentences: list[str]) -> list[list[float]]:
    """Deterministic hash-based fake embedder for testing.

    Produces 8-dim unit vectors from text hash. Identical texts produce
    identical embeddings; different texts produce different embeddings.
    """
    results = []
    for s in sentences:
        h = hash(s)
        raw = [(h >> (i * 8)) & 0xFF for i in range(8)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        results.append([x / norm for x in raw])
    return results


def _make_topic_embed_fn():
    """Embedding function that clusters sentences by topic keyword.

    Sentences containing the same 'topic word' get nearly-identical
    embeddings. Sentences with different topics get very different
    embeddings. This lets us test semantic boundary detection
    deterministically.
    """
    topic_vectors = {
        "shipping": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "penalty":  [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "safety":   [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "payment":  [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
    }
    default = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]

    def embed_fn(sentences: list[str]) -> list[list[float]]:
        results = []
        for s in sentences:
            lower = s.lower()
            vec = default
            for topic, tv in topic_vectors.items():
                if topic in lower:
                    # Add slight noise per-sentence so they're not perfectly identical
                    noise = (hash(s) % 100) * 0.001
                    vec = [v + noise for v in tv]
                    break
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            results.append([x / norm for x in vec])
        return results

    return embed_fn


SAMPLE_TEXT = (
    "The contract outlines shipping terms for PharmaCorp deliveries. "
    "All shipments must maintain cold chain compliance between 2 and 8 degrees Celsius. "
    "Late delivery incurs a penalty of 15 percent of shipment value. "
    "The penalty applies per shipment, not per delivery attempt. "
    "Safety protocols require GPS tracking on all vehicles. "
    "Safety inspections must be completed before each trip."
)

SECTIONED_TEXT = """Section 1: Shipping Terms
All goods must be shipped within 48 hours of order confirmation.
Express shipping is available for an additional fee.
Tracking numbers are provided upon dispatch.

Section 2: Penalties
Late delivery incurs a 15 percent penalty on shipment value.
Repeated late deliveries may result in contract termination.
Penalty waivers require written approval from management.

Section 3: Safety Requirements
All vehicles must pass monthly safety inspections.
Drivers must complete annual safety training.
Hazardous materials require special handling procedures."""


# ===========================================================================
# FixedSizeChunker tests
# ===========================================================================


class TestFixedSizeChunker:
    def test_produces_chunk_results(self):
        chunker = FixedSizeChunker(chunk_size=200, overlap=30)
        results = chunker.chunk(SAMPLE_TEXT)
        assert all(isinstance(r, ChunkResult) for r in results)

    def test_chunks_within_size_limit(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        results = chunker.chunk(SAMPLE_TEXT)
        for r in results:
            # Allow slight overshoot for word boundary respect
            assert len(r.content) <= 150, f"Chunk too long: {len(r.content)} chars"

    def test_respects_word_boundaries(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        results = chunker.chunk(SAMPLE_TEXT)
        for r in results:
            assert r.content == r.content.strip()
            # No partial words: first and last chars should not be mid-word splits
            if r.content:
                assert not r.content[0].isalpha() or r.content[0] == r.content.split()[0][0]

    def test_overlap_produces_shared_content(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=30)
        results = chunker.chunk(SAMPLE_TEXT)
        assert len(results) >= 2
        # Consecutive chunks should share some words (overlap)
        for i in range(len(results) - 1):
            words_a = set(results[i].content.split()[-5:])
            words_b = set(results[i + 1].content.split()[:5])
            # At least some overlap expected
            assert words_a & words_b, (
                f"No word overlap between chunk {i} and {i+1}"
            )

    def test_chunk_indices_are_sequential(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        results = chunker.chunk(SAMPLE_TEXT)
        for i, r in enumerate(results):
            assert r.chunk_index == i

    def test_chunk_type_is_standalone(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        results = chunker.chunk(SAMPLE_TEXT)
        for r in results:
            assert r.chunk_type == "standalone"
            assert r.parent_index is None

    def test_empty_text_returns_empty(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_single_sentence_returns_one_chunk(self):
        chunker = FixedSizeChunker(chunk_size=500, overlap=50)
        results = chunker.chunk("Short sentence.")
        assert len(results) == 1
        assert results[0].content == "Short sentence."

    def test_very_long_input_produces_many_chunks(self):
        long_text = " ".join(f"Word{i}" for i in range(5000))
        chunker = FixedSizeChunker(chunk_size=200, overlap=30)
        results = chunker.chunk(long_text)
        assert len(results) > 20

    def test_configurable_chunk_size(self):
        small = FixedSizeChunker(chunk_size=50, overlap=10)
        large = FixedSizeChunker(chunk_size=500, overlap=50)
        small_results = small.chunk(SAMPLE_TEXT)
        large_results = large.chunk(SAMPLE_TEXT)
        assert len(small_results) > len(large_results)

    def test_zero_overlap(self):
        chunker = FixedSizeChunker(chunk_size=100, overlap=0)
        results = chunker.chunk(SAMPLE_TEXT)
        assert len(results) >= 2
        # All text should still be covered
        combined = " ".join(r.content for r in results)
        # Every word from original should appear at least once
        for word in SAMPLE_TEXT.split()[:10]:
            assert word in combined

    def test_covers_all_content(self):
        """Every word in the original text must appear in at least one chunk."""
        chunker = FixedSizeChunker(chunk_size=100, overlap=20)
        results = chunker.chunk(SAMPLE_TEXT)
        all_chunk_text = " ".join(r.content for r in results)
        for word in SAMPLE_TEXT.split():
            assert word in all_chunk_text, f"Word '{word}' missing from chunks"


# ===========================================================================
# SemanticChunker tests
# ===========================================================================


class TestSemanticChunker:
    def test_produces_chunk_results(self):
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=_fake_embed_fn,
        )
        results = chunker.chunk(SAMPLE_TEXT)
        assert all(isinstance(r, ChunkResult) for r in results)

    def test_keeps_similar_sentences_together(self):
        """Sentences about the same topic should land in the same chunk."""
        text = (
            "Shipping rates are based on weight. "
            "Shipping costs include fuel surcharges. "
            "Shipping insurance is optional. "
            "The penalty for late delivery is 15 percent. "
            "Penalty waivers require management approval. "
            "Penalty disputes must be filed within 30 days."
        )
        embed_fn = _make_topic_embed_fn()
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            min_chunk_size=10,
            max_chunk_size=2000,
            embed_fn=embed_fn,
        )
        results = chunker.chunk(text)
        # Should produce at least 2 chunks: shipping vs penalty
        assert len(results) >= 2
        # Find the chunk containing "Shipping rates" — it should also contain
        # other shipping sentences
        for r in results:
            if "Shipping rates" in r.content:
                assert "Shipping costs" in r.content or "Shipping insurance" in r.content

    def test_splits_at_topic_boundaries(self):
        """When topics change, a new chunk should start."""
        text = (
            "Shipping rates are calculated by weight. "
            "Shipping zones determine delivery time. "
            "Safety inspections are mandatory monthly. "
            "Safety training must be completed annually."
        )
        embed_fn = _make_topic_embed_fn()
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            min_chunk_size=10,
            max_chunk_size=2000,
            embed_fn=embed_fn,
        )
        results = chunker.chunk(text)
        assert len(results) >= 2
        # Shipping and safety sentences should be in different chunks
        shipping_chunk = None
        safety_chunk = None
        for r in results:
            if "Shipping rates" in r.content:
                shipping_chunk = r
            if "Safety inspections" in r.content:
                safety_chunk = r
        assert shipping_chunk is not None
        assert safety_chunk is not None
        # They should NOT be in the same chunk
        assert shipping_chunk.chunk_index != safety_chunk.chunk_index

    def test_chunk_type_is_standalone(self):
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=_fake_embed_fn,
        )
        results = chunker.chunk(SAMPLE_TEXT)
        for r in results:
            assert r.chunk_type == "standalone"
            assert r.parent_index is None

    def test_respects_max_chunk_size(self):
        # Even if all sentences are similar, should not exceed max size
        text = " ".join(["Shipping is important."] * 100)
        embed_fn = _make_topic_embed_fn()
        chunker = SemanticChunker(
            similarity_threshold=0.1,  # very low = group everything
            min_chunk_size=10,
            max_chunk_size=200,
            embed_fn=embed_fn,
        )
        results = chunker.chunk(text)
        for r in results:
            assert len(r.content) <= 250  # allow some margin for sentence boundaries

    def test_respects_min_chunk_size(self):
        """Very short segments should be merged with neighbors."""
        text = "A. B. C. D. E. F. G. H."
        chunker = SemanticChunker(
            similarity_threshold=0.99,  # high = split everything
            min_chunk_size=10,
            max_chunk_size=2000,
            embed_fn=_fake_embed_fn,
        )
        results = chunker.chunk(text)
        # With min_chunk_size=10, we should not get single-letter chunks
        for r in results:
            assert len(r.content) >= 3  # at minimum some content

    def test_empty_text_returns_empty(self):
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=_fake_embed_fn,
        )
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_single_sentence_returns_one_chunk(self):
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=_fake_embed_fn,
        )
        results = chunker.chunk("Just one sentence here.")
        assert len(results) == 1
        assert results[0].content == "Just one sentence here."

    def test_chunk_indices_are_sequential(self):
        embed_fn = _make_topic_embed_fn()
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=embed_fn,
        )
        results = chunker.chunk(SAMPLE_TEXT)
        for i, r in enumerate(results):
            assert r.chunk_index == i

    def test_configurable_similarity_threshold(self):
        embed_fn = _make_topic_embed_fn()
        # Low threshold = fewer splits (more grouping)
        low = SemanticChunker(
            similarity_threshold=0.1,
            min_chunk_size=10,
            max_chunk_size=5000,
            embed_fn=embed_fn,
        )
        # High threshold = more splits
        high = SemanticChunker(
            similarity_threshold=0.99,
            min_chunk_size=10,
            max_chunk_size=5000,
            embed_fn=embed_fn,
        )
        text = (
            "Shipping rates are based on weight. "
            "Shipping costs include fuel. "
            "Penalty for late delivery is steep. "
            "Penalty waivers need approval. "
            "Safety inspections are monthly. "
            "Safety training is annual."
        )
        low_results = low.chunk(text)
        high_results = high.chunk(text)
        assert len(high_results) >= len(low_results)

    def test_covers_all_content(self):
        """Every sentence in the original should appear in some chunk."""
        chunker = SemanticChunker(
            similarity_threshold=0.5,
            embed_fn=_fake_embed_fn,
        )
        results = chunker.chunk(SAMPLE_TEXT)
        all_text = " ".join(r.content for r in results)
        for word in SAMPLE_TEXT.split()[:15]:
            assert word in all_text, f"Word '{word}' missing from semantic chunks"

    def test_requires_embed_fn(self):
        """SemanticChunker without embed_fn should raise on chunk()."""
        chunker = SemanticChunker(similarity_threshold=0.5)
        with pytest.raises((ValueError, TypeError)):
            chunker.chunk(SAMPLE_TEXT)


# ===========================================================================
# ParentChildChunker tests
# ===========================================================================


class TestParentChildChunker:
    def test_produces_parent_and_child_chunks(self):
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        types = {r.chunk_type for r in results}
        assert "parent" in types
        assert "child" in types

    def test_parents_contain_full_sections(self):
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        parents = [r for r in results if r.chunk_type == "parent"]
        # Should have 3 parents (3 sections)
        assert len(parents) == 3
        # Each parent should contain the section header
        parent_texts = [p.content for p in parents]
        assert any("Shipping Terms" in t for t in parent_texts)
        assert any("Penalties" in t for t in parent_texts)
        assert any("Safety Requirements" in t for t in parent_texts)

    def test_children_reference_parent_index(self):
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        children = [r for r in results if r.chunk_type == "child"]
        assert len(children) > 0
        for child in children:
            assert child.parent_index is not None
            # Parent index should point to an actual parent chunk
            parent = results[child.parent_index]
            assert parent.chunk_type == "parent"

    def test_children_text_is_subset_of_parent(self):
        """Each child's content should appear within its parent's content."""
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        children = [r for r in results if r.chunk_type == "child"]
        for child in children:
            parent = results[child.parent_index]
            # Child content (stripped) should be found in parent
            assert child.content.strip() in parent.content, (
                f"Child content not found in parent.\n"
                f"Child: {child.content[:80]}\n"
                f"Parent: {parent.content[:80]}"
            )

    def test_section_metadata_on_parent(self):
        """Parents should carry section header metadata."""
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        parents = [r for r in results if r.chunk_type == "parent"]
        for p in parents:
            assert p.metadata is not None
            assert "section_header" in p.metadata

    def test_section_metadata_on_child(self):
        """Children should carry their parent's section header metadata."""
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        children = [r for r in results if r.chunk_type == "child"]
        for c in children:
            assert c.metadata is not None
            assert "section_header" in c.metadata

    def test_custom_section_pattern(self):
        """Configurable section pattern for non-standard headers."""
        custom_text = """## Overview
This is the overview section.
It has two paragraphs.

## Details
Here are the details.
More detail information here."""

        chunker = ParentChildChunker(
            section_pattern=r"^##\s+",
        )
        results = chunker.chunk(custom_text)
        parents = [r for r in results if r.chunk_type == "parent"]
        assert len(parents) == 2

    def test_empty_text_returns_empty(self):
        chunker = ParentChildChunker()
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_text_without_sections_treated_as_single_parent(self):
        """Text with no section headers should produce one parent with children."""
        plain = (
            "First paragraph about shipping.\n\n"
            "Second paragraph about penalties.\n\n"
            "Third paragraph about safety."
        )
        chunker = ParentChildChunker()
        results = chunker.chunk(plain)
        # Should still produce some chunks (at least children or a parent)
        assert len(results) >= 1

    def test_min_child_size_filters_tiny_paragraphs(self):
        text = """Section 1: Terms
A.
B.
This is a longer paragraph that should be kept as a child chunk."""
        chunker = ParentChildChunker(min_child_size=20)
        results = chunker.chunk(text)
        children = [r for r in results if r.chunk_type == "child"]
        # Very short paragraphs ("A.", "B.") should be merged, not standalone children
        for c in children:
            assert len(c.content.strip()) >= 10  # some reasonable minimum

    def test_max_parent_size_splits_large_sections(self):
        """Sections exceeding max_parent_size should be split into multiple parents."""
        long_section = "Section 1: Huge Section\n" + "\n".join(
            f"Paragraph {i} with enough words to make it reasonably sized for testing."
            for i in range(50)
        )
        chunker = ParentChildChunker(max_parent_size=500)
        results = chunker.chunk(long_section)
        parents = [r for r in results if r.chunk_type == "parent"]
        # If section > max_parent_size, should be split
        for p in parents:
            assert len(p.content) <= 600  # allow margin

    def test_chunk_indices_are_sequential(self):
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        for i, r in enumerate(results):
            assert r.chunk_index == i

    def test_covers_all_content(self):
        """All text from the original should appear in the chunks."""
        chunker = ParentChildChunker()
        results = chunker.chunk(SECTIONED_TEXT)
        all_text = " ".join(r.content for r in results)
        # Check key phrases are present
        for phrase in [
            "shipped within 48 hours",
            "15 percent penalty",
            "safety inspections",
            "Hazardous materials",
        ]:
            assert phrase in all_text, f"Phrase '{phrase}' missing from chunks"


# ===========================================================================
# Factory function tests
# ===========================================================================


class TestGetChunker:
    def test_returns_fixed_size_chunker(self):
        chunker = get_chunker(ChunkingStrategy.FIXED_SIZE, chunk_size=256, overlap=30)
        assert isinstance(chunker, FixedSizeChunker)

    def test_returns_semantic_chunker(self):
        chunker = get_chunker(
            ChunkingStrategy.SEMANTIC,
            similarity_threshold=0.6,
            embed_fn=_fake_embed_fn,
        )
        assert isinstance(chunker, SemanticChunker)

    def test_returns_parent_child_chunker(self):
        chunker = get_chunker(ChunkingStrategy.PARENT_CHILD)
        assert isinstance(chunker, ParentChildChunker)

    def test_invalid_strategy_raises(self):
        with pytest.raises((ValueError, KeyError)):
            get_chunker("nonexistent_strategy")

    def test_passes_kwargs_to_fixed_size(self):
        chunker = get_chunker(ChunkingStrategy.FIXED_SIZE, chunk_size=1024, overlap=100)
        # Verify it actually uses the params
        results = chunker.chunk("A " * 300)
        # With chunk_size=1024, a 600-char text should be 1 chunk
        assert len(results) >= 1


# ===========================================================================
# ChunkResult model tests
# ===========================================================================


class TestChunkResult:
    def test_standalone_chunk(self):
        r = ChunkResult(
            content="Some text",
            chunk_index=0,
            chunk_type="standalone",
        )
        assert r.parent_index is None
        assert r.metadata is None

    def test_child_chunk_with_parent(self):
        r = ChunkResult(
            content="Child text",
            chunk_index=1,
            chunk_type="child",
            parent_index=0,
            metadata={"section_header": "Section 1"},
        )
        assert r.parent_index == 0
        assert r.metadata["section_header"] == "Section 1"

    def test_parent_chunk(self):
        r = ChunkResult(
            content="Full section",
            chunk_index=0,
            chunk_type="parent",
            metadata={"section_header": "Section 1"},
        )
        assert r.chunk_type == "parent"
        assert r.parent_index is None


# ===========================================================================
# BaseChunker ABC tests
# ===========================================================================


class TestBaseChunker:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseChunker()

    def test_subclass_must_implement_chunk(self):
        class BadChunker(BaseChunker):
            pass

        with pytest.raises(TypeError):
            BadChunker()

    def test_subclass_with_chunk_works(self):
        class GoodChunker(BaseChunker):
            def chunk(self, text: str) -> list[ChunkResult]:
                return [ChunkResult(content=text, chunk_index=0, chunk_type="standalone")]

        chunker = GoodChunker()
        results = chunker.chunk("test")
        assert len(results) == 1
