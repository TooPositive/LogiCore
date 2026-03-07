"""Lightweight BM25-style sparse vector encoder.

Generates sparse vectors from text using term frequency with IDF-like weighting.
No external SPLADE model needed — Qdrant's server-side IDF modifier handles the
IDF part, so we just need to supply term frequencies.

Why not SPLADE?
- SPLADE needs a 400MB+ transformer model download
- For Phase 1 demo, TF-based sparse vectors + Qdrant IDF modifier achieves
  the key goal: exact keyword matching for codes like "ISO-9001", "CTR-2024-001"
- SPLADE would be a Phase 2 upgrade for learned term expansion

How it works:
1. Tokenize text into terms (lowercase, strip punctuation, keep alphanumeric + hyphens)
2. Compute term frequency per token
3. Map tokens to integer indices (deterministic hash)
4. Return as Qdrant SparseVector (indices + values)
"""

import re
from collections import Counter

from qdrant_client.models import SparseVector

# Simple tokenizer: split on whitespace/punctuation, keep hyphens for codes like ISO-9001
_TOKEN_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?", re.IGNORECASE)

# Vocabulary size for hash-based index mapping
_VOCAB_SIZE = 2**16  # 65536 — large enough to avoid excessive collisions


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase terms, preserving hyphenated codes."""
    return [t.lower() for t in _TOKEN_PATTERN.findall(text)]


def text_to_sparse_vector(text: str) -> SparseVector:
    """Convert text to a BM25-style sparse vector.

    Returns a Qdrant SparseVector with:
    - indices: hash-based token IDs
    - values: term frequency counts (Qdrant applies IDF modifier server-side)
    """
    tokens = tokenize(text)
    if not tokens:
        return SparseVector(indices=[], values=[])

    # Count term frequencies
    tf = Counter(tokens)

    # Map tokens to indices via deterministic hash
    indices = []
    values = []
    for token, count in tf.items():
        idx = hash(token) % _VOCAB_SIZE
        indices.append(idx)
        values.append(float(count))

    return SparseVector(indices=indices, values=values)
