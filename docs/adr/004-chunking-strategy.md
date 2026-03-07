# ADR-004: Semantic Chunking over Fixed-Size for Contract Documents

## Status
Accepted

## Context
Phase 1 used character-based fixed-size chunking (512 chars, 50 overlap). This splits contract clauses across chunk boundaries — the PharmaCorp penalty clause gets split between chunk 23 ("In the event of late delivery") and chunk 24 ("a penalty of 15% of shipment value applies"). The AI returns "penalties may apply" instead of "EUR 486 penalty." At 3-5 incidents/month, that's EUR 17,496-29,160/year in vague answers leading to wrong prioritization.

## Decision
**Three chunking strategies, selected per document type:**

| Strategy | Use Case | When |
|----------|----------|------|
| **SemanticChunker** (default for contracts) | Detects topic boundaries via sentence embedding similarity | Legal/contract documents where clause integrity is critical |
| **ParentChildChunker** | Section-aware: parent = full section, children = individual clauses | Structured documents with section headers (manuals, regulations) |
| **FixedSizeChunker** | Character-based with word boundary respect | Unstructured text, baseline benchmarks |

All chunkers implement `BaseChunker` ABC and return `ChunkResult` dataclasses. Strategy selection is configurable — not hardcoded to logistics.

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| LangChain RecursiveCharacterTextSplitter | Character-boundary driven — better than naive fixed-size but doesn't understand semantic breaks. Still splits mid-clause. |
| LlamaIndex SentenceSplitter | Sentence-level but doesn't compare embeddings across boundaries. Can't detect topic shifts. |
| Custom regex by section header | Brittle. Breaks on format variations. Requires known document structure at ingestion time. |
| Token-based chunking (tiktoken) | Solves the "consistent size" problem but not the "don't split clauses" problem. Same fundamental issue as character-based. |

## Security Consideration
**Parent-child RBAC**: Parent chunk clearance = max(child clearance levels). A clearance-2 user retrieves child chunks at their level but does NOT get parent context if parent clearance > their clearance. Prevents trust escalation through data structure.

## Consequences
- Semantic chunking adds 200-400ms per document at ingestion (sentence embedding comparison) — acceptable for batch ingestion
- SemanticChunker requires an `embed_fn` at ingestion time — dependency on embedding infrastructure
- ParentChildChunker uses configurable regex for section detection — must be tuned per document format
- Fixed-size chunker preserved as baseline for benchmarks and unstructured text
- All chunking strategies are domain-agnostic — parameters (chunk_size, similarity_threshold, section_pattern) adapt to any corpus
