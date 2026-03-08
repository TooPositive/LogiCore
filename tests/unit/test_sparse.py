"""Tests for the BM25-style sparse vector encoder."""

from apps.api.src.core.rag.sparse import text_to_sparse_vector, tokenize


class TestTokenize:
    def test_basic_tokenization(self):
        tokens = tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_preserves_hyphenated_codes(self):
        tokens = tokenize("ISO-9001 quality CTR-2024-001")
        assert "iso-9001" in tokens
        assert "ctr-2024-001" in tokens

    def test_strips_punctuation(self):
        tokens = tokenize("Hello, world! Test.")
        assert tokens == ["hello", "world", "test"]

    def test_empty_text(self):
        assert tokenize("") == []
        assert tokenize("   ") == []


class TestTextToSparseVector:
    def test_basic_sparse_vector(self):
        sv = text_to_sparse_vector("hello world hello")
        assert len(sv.indices) == 2  # two unique tokens
        # "hello" appears twice, "world" once
        hello_idx = hash("hello") % (2**16)
        pos = sv.indices.index(hello_idx)
        assert sv.values[pos] == 2.0  # term frequency

    def test_empty_text_returns_empty(self):
        sv = text_to_sparse_vector("")
        assert sv.indices == []
        assert sv.values == []

    def test_exact_code_gets_indexed(self):
        sv = text_to_sparse_vector("Contract CTR-2024-001 penalty clause")
        idx = hash("ctr-2024-001") % (2**16)
        assert idx in sv.indices

    def test_iso_code_gets_indexed(self):
        sv = text_to_sparse_vector("ISO-9001 Section 4.2 quality")
        idx = hash("iso-9001") % (2**16)
        assert idx in sv.indices
