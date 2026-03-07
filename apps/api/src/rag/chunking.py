"""Configurable chunking strategies for RAG ingestion.

Three strategies:
1. FixedSizeChunker  — character-based with word-boundary respect and overlap
2. SemanticChunker   — splits at semantic similarity breakpoints between sentences
3. ParentChildChunker — section-aware: parent = full section, child = paragraph/clause

All strategies are domain-agnostic. Strategy selection, chunk sizes, overlap,
similarity thresholds, and section patterns are all configurable via parameters.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class ChunkingStrategy(StrEnum):
    FIXED_SIZE = "fixed_size"
    SEMANTIC = "semantic"
    PARENT_CHILD = "parent_child"


@dataclass
class ChunkResult:
    """Result from chunking -- not a domain Chunk yet (no document metadata).

    Domain metadata (document_id, clearance_level, department_id) is applied
    at ingestion time, not here. This keeps the chunker domain-agnostic.
    """

    content: str
    chunk_index: int
    chunk_type: str  # "standalone", "child", "parent"
    parent_index: int | None = None
    metadata: dict | None = None


class BaseChunker(ABC):
    """Abstract base class for all chunking strategies."""

    @abstractmethod
    def chunk(self, text: str) -> list[ChunkResult]:
        """Split text into ChunkResult objects."""
        ...


# ---------------------------------------------------------------------------
# FixedSizeChunker
# ---------------------------------------------------------------------------


class FixedSizeChunker(BaseChunker):
    """Character-based chunking with word-boundary respect and overlap.

    Refactored from the original ``chunk_text()`` in ``ingestion.py``.
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[ChunkResult]:
        if not text or not text.strip():
            return []

        words = text.split()
        if not words:
            return []

        raw_chunks: list[str] = []
        start = 0

        while start < len(words):
            end = start
            current_len = 0
            while end < len(words):
                sep = 1 if current_len > 0 else 0
                if current_len + len(words[end]) + sep > self.chunk_size:
                    break
                current_len += len(words[end]) + sep
                end += 1

            # If we couldn't fit even one word, take at least one
            if end == start:
                end = start + 1

            chunk = " ".join(words[start:end])
            raw_chunks.append(chunk)

            # Overlap: step back by overlap_words
            overlap_words = max(1, self.overlap // 5) if self.overlap > 0 else 0
            advance = max(1, (end - start) - overlap_words)
            start += advance

            if end >= len(words):
                break

        return [
            ChunkResult(content=c, chunk_index=i, chunk_type="standalone")
            for i, c in enumerate(raw_chunks)
        ]


# ---------------------------------------------------------------------------
# SemanticChunker
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using a simple regex.

    Handles common abbreviations poorly (by design -- this is a baseline).
    For production, consider spaCy or NLTK sentence tokenizers.
    """
    # Split on sentence-ending punctuation followed by whitespace
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticChunker(BaseChunker):
    """Split by semantic similarity breakpoints between sentences.

    Uses an embedding function to detect topic boundaries. When cosine
    similarity between consecutive sentence embeddings drops below the
    threshold, a new chunk starts.

    For unit tests: pass a hash-based fake ``embed_fn``.
    In production: pass real embedding function.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.5,
        min_chunk_size: int = 100,
        max_chunk_size: int = 2000,
        embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.embed_fn = embed_fn

    def chunk(self, text: str) -> list[ChunkResult]:
        if not text or not text.strip():
            return []

        if self.embed_fn is None:
            raise ValueError(
                "SemanticChunker requires an embed_fn. "
                "Pass a callable that maps list[str] -> list[list[float]]."
            )

        sentences = _split_sentences(text)
        if not sentences:
            return []

        if len(sentences) == 1:
            return [
                ChunkResult(content=sentences[0], chunk_index=0, chunk_type="standalone")
            ]

        # Embed all sentences at once
        embeddings = self.embed_fn(sentences)

        # Find split points: where similarity between consecutive sentences
        # drops below the threshold
        groups: list[list[str]] = []
        current_group: list[str] = [sentences[0]]

        for i in range(1, len(sentences)):
            sim = _cosine_similarity(embeddings[i - 1], embeddings[i])

            current_text = " ".join(current_group)
            would_exceed_max = (
                len(current_text) + len(sentences[i]) + 1 > self.max_chunk_size
            )

            if sim < self.similarity_threshold or would_exceed_max:
                groups.append(current_group)
                current_group = [sentences[i]]
            else:
                current_group.append(sentences[i])

        # Don't forget the last group
        if current_group:
            groups.append(current_group)

        # Merge groups that are too small with their neighbor
        merged: list[list[str]] = []
        for group in groups:
            group_text = " ".join(group)
            if merged and len(group_text) < self.min_chunk_size:
                # Merge with previous group (if combined doesn't exceed max)
                prev_text = " ".join(merged[-1])
                if len(prev_text) + len(group_text) + 1 <= self.max_chunk_size:
                    merged[-1].extend(group)
                else:
                    merged.append(group)
            else:
                merged.append(group)

        return [
            ChunkResult(
                content=" ".join(group),
                chunk_index=i,
                chunk_type="standalone",
            )
            for i, group in enumerate(merged)
        ]


# ---------------------------------------------------------------------------
# ParentChildChunker
# ---------------------------------------------------------------------------


class ParentChildChunker(BaseChunker):
    """Section-aware chunking producing parent-child hierarchy.

    Detects section boundaries via a configurable regex pattern.
    Parent = full section text. Child = individual paragraph/clause within
    the section.

    SECURITY NOTE: When used with RBAC, parent clearance = max(child clearance
    levels). This is enforced at ingestion time, not in this chunker. The
    chunker produces structure; RBAC metadata is applied later.
    """

    def __init__(
        self,
        section_pattern: str = r"^(?:Section|Article|Chapter|\d+\.)\s",
        min_child_size: int = 50,
        max_parent_size: int = 5000,
    ) -> None:
        self.section_pattern = re.compile(section_pattern, re.MULTILINE)
        self.min_child_size = min_child_size
        self.max_parent_size = max_parent_size

    def chunk(self, text: str) -> list[ChunkResult]:
        if not text or not text.strip():
            return []

        sections = self._split_into_sections(text)
        if not sections:
            return []

        results: list[ChunkResult] = []

        for header, body in sections:
            full_section = f"{header}\n{body}".strip() if header else body.strip()

            # If section exceeds max_parent_size, split it into sub-sections
            parent_chunks = self._split_oversized_parent(full_section, header)

            for parent_text, sub_header in parent_chunks:
                parent_index = len(results)
                parent_meta = {"section_header": sub_header or header or ""}

                results.append(
                    ChunkResult(
                        content=parent_text,
                        chunk_index=parent_index,
                        chunk_type="parent",
                        metadata=parent_meta,
                    )
                )

                # Extract children (paragraphs) from this parent
                # Remove the header line to get body paragraphs
                if sub_header and parent_text.startswith(sub_header):
                    child_body = parent_text[len(sub_header) :].strip()
                else:
                    child_body = parent_text

                paragraphs = self._split_paragraphs(child_body)
                # Merge tiny paragraphs
                merged_paragraphs = self._merge_tiny_paragraphs(paragraphs)

                for para in merged_paragraphs:
                    if para.strip():
                        results.append(
                            ChunkResult(
                                content=para.strip(),
                                chunk_index=len(results),
                                chunk_type="child",
                                parent_index=parent_index,
                                metadata={"section_header": sub_header or header or ""},
                            )
                        )

        return results

    def _split_into_sections(
        self, text: str
    ) -> list[tuple[str, str]]:
        """Split text at section headers. Returns list of (header, body) tuples."""
        matches = list(self.section_pattern.finditer(text))

        if not matches:
            # No section headers found -- treat entire text as one section
            return [("", text)]

        sections: list[tuple[str, str]] = []

        for i, match in enumerate(matches):
            # Find the full header line
            line_start = text.rfind("\n", 0, match.start())
            line_start = line_start + 1 if line_start >= 0 else 0
            line_end = text.find("\n", match.start())
            if line_end < 0:
                line_end = len(text)

            header = text[line_start:line_end].strip()

            # Body = everything from after header to next section (or end)
            body_start = line_end
            if i + 1 < len(matches):
                next_line_start = text.rfind("\n", 0, matches[i + 1].start())
                body_end = next_line_start if next_line_start >= 0 else matches[i + 1].start()
            else:
                body_end = len(text)

            body = text[body_start:body_end].strip()
            sections.append((header, body))

        return sections

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs (by blank lines or single newlines)."""
        # First try splitting on blank lines
        paragraphs = re.split(r"\n\s*\n", text)
        if len(paragraphs) <= 1:
            # Fall back to splitting on single newlines
            paragraphs = text.split("\n")
        return [p.strip() for p in paragraphs if p.strip()]

    def _merge_tiny_paragraphs(self, paragraphs: list[str]) -> list[str]:
        """Merge paragraphs smaller than min_child_size with neighbors."""
        if not paragraphs:
            return []

        merged: list[str] = []
        for para in paragraphs:
            if merged and len(para) < self.min_child_size:
                merged[-1] = merged[-1] + "\n" + para
            elif not merged and len(para) < self.min_child_size:
                merged.append(para)
            else:
                merged.append(para)

        # Second pass: merge any remaining undersized chunks forward
        if len(merged) > 1:
            final: list[str] = []
            for m in merged:
                if final and len(final[-1]) < self.min_child_size:
                    final[-1] = final[-1] + "\n" + m
                else:
                    final.append(m)
            # If the last chunk is too small, merge it backward
            if len(final) > 1 and len(final[-1]) < self.min_child_size:
                final[-2] = final[-2] + "\n" + final[-1]
                final.pop()
            merged = final

        return merged

    def _split_oversized_parent(
        self, section_text: str, header: str
    ) -> list[tuple[str, str]]:
        """Split a section that exceeds max_parent_size into sub-parents."""
        if len(section_text) <= self.max_parent_size:
            return [(section_text, header)]

        # Split into paragraphs and group them into sub-parents
        paragraphs = self._split_paragraphs(section_text)
        sub_parents: list[tuple[str, str]] = []
        current_paras: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 1 > self.max_parent_size and current_paras:
                sub_text = "\n".join(current_paras)
                sub_header = f"{header} (part {len(sub_parents) + 1})" if header else ""
                sub_parents.append((sub_text, sub_header))
                current_paras = [para]
                current_len = len(para)
            else:
                current_paras.append(para)
                current_len += len(para) + 1

        if current_paras:
            sub_text = "\n".join(current_paras)
            sub_header = (
                f"{header} (part {len(sub_parents) + 1})"
                if header and sub_parents
                else header
            )
            sub_parents.append((sub_text, sub_header))

        return sub_parents


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_chunker(strategy: ChunkingStrategy | str, **kwargs) -> BaseChunker:
    """Factory function to create a chunker by strategy name.

    All parameters are passed through as kwargs to the chunker constructor.
    """
    strategy_str = str(strategy)

    constructors: dict[str, type[BaseChunker]] = {
        ChunkingStrategy.FIXED_SIZE: FixedSizeChunker,
        ChunkingStrategy.SEMANTIC: SemanticChunker,
        ChunkingStrategy.PARENT_CHILD: ParentChildChunker,
    }

    if strategy_str not in constructors:
        raise ValueError(
            f"Unknown chunking strategy: {strategy_str!r}. "
            f"Valid strategies: {list(constructors.keys())}"
        )

    return constructors[strategy_str](**kwargs)
