# Phase 1 LinkedIn Post: Corporate Brain (RAG + RBAC)

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft (v2 — rewritten with storytelling rules)

---

A warehouse worker in Gdansk types "towary niebezpieczne" into the company search. Zero results.

The document he needs is right there. Safety procedures for hazardous materials. But it says "hazardous materials" in English. Max doesnt know the English terminology. He walks down the hall to ask someone who also doesnt know.

This is Phase 1 of a 12-phase AI system im building for a logistics company. Each phase solves a real business problem. This one asks the most fundamental question: when your employees search for something, do they actually find it?

I benchmarked 26 queries across 7 categories — synonyms, exact codes, jargon, Polish, typos, negation — each designed to break a specific search mode. BM25 (keyword search, free, 2ms) scored 16/26. "Letting go of staff" returns nothing coz the doc says "termination procedures." "Pharamcorp" with a typo — nothing. BM25 needs you to already know whats in the document. Thats not search, thats lookup.

Dense embeddings (text-embedding-3-small, ~€0.02/1M tokens) scored 23/26. Polish 4/4, synonyms 4/4, typos 4/4. Max types "towary niebezpieczne przepisy" and gets the hazmat contract at rank 1. Thats what search should actually do.

Why keep BM25 at all? Coz when Anna in logistics searches contract ID CTR-2024-001, dense puts it rank 2. BM25 puts it rank 1. Exact codes need exact matching. Hybrid RRF fusion: 24/26.

The expensive model (text-embedding-3-large, ~€0.13/1M tokens)? Same 23/26 across all queries. Zero extra hits at 6.5x cost. Skip it until your corpus exceeds ~1000 semantically similar docs. (Thats my hypothesis though, havent tested at that scale.)

Now the harder problem. Max searches "CEO compensation." Zero results. Not a refusal, not an error. Zero. The LLM never saw the document. RBAC filters at the Qdrant query level BEFORE retrieval — unauthorized docs never enter the pipeline. Same query, three users: Max sees 2 docs, Katrin sees 1, Eva sees 6.

Most RAG tutorials filter AFTER retrieval. By then the LLM already processed the unauthorized content. A prompt injection in one of those docs could leak it.

What breaks: "contract with the largest annual value" — all modes fail. RAG retrieves, it doesnt reason across documents. Thats a multi-agent problem.

Monthly embedding cost at production scale (1000 docs, 200 queries/day): ~€0.01. Qdrant self-hosted: €0. The LLM generation is the expensive part, not retrieval.

Post 1/12 in the LogiCore series. Next up: your chunks are wrong, and re-ranking matters more than you think 😅

---

## Reply Ammo

### 1. "BM25 is fine for most use cases"

For who though? If your users are devs searching codebases with exact function names, sure. For a Polish warehouse worker typing "towary niebezpieczne" when the doc says "hazardous materials"? BM25 scored 2/4 on Polish queries. Thats a coin flip, not enterprise search.

### 2. "What about the latency difference? BM25 is way faster"

2ms vs 147ms. Saving 145ms on wrong results isnt optimization, its saving time on the wrong thing. (And hybrid was actually 128ms — faster than dense-only coz of prefetch parallelization.)

### 3. "26 queries isn't statistically significant"

Fair, its not a research paper. But 7 categories with 4 cases each, where BM25 consistently fails 4 categories and Dense consistently handles them — thats a diagnostic pattern, not noise. Phase 2 expanded to 52 queries and the pattern held.

### 4. "Why not SPLADE instead of basic BM25?"

SPLADE needs a 400MB+ transformer download and inference step. For Phase 1, BM25 with Qdrant's native IDF modifier does the job for exact code matching. The sparse side carries maybe 10% of the value — dont over-engineer it when embeddings do the heavy lifting.

### 5. "The RBAC model seems too simple for production"

Its the demo model. 4 users, in-memory dict. Production would hit an IdP (Entra ID, Okta). But the security model itself is sound: empty department lists throw a ValueError coz MatchAny([]) behavior in Qdrant is undefined — could bypass RBAC entirely. Thats the edge case that matters more than the user store implementation.

### 6. "Why Qdrant over Pinecone/Weaviate?"

Native hybrid search (dense + sparse in same collection with server-side RRF), self-hosted (no vendor lock-in — needed for Phase 6 air-gapped deployment), and RBAC metadata filtering at query time. Swap cost to another vector DB: ~3 days. Wrote an ADR about it.

### 7. "Doesn't every RAG system do RBAC?"

Most filter AFTER retrieval. The LLM already processed unauthorized content by then. Its in the context window. A prompt injection in one of those docs could leak it even if your app hides it from the response. Filtering at the DB level means unauthorized docs never enter the pipeline.

### 8. "What about fine-tuning embeddings for your domain?"

Text-embedding-3-small already handles Polish, logistics jargon, and typos at 4/4 across those categories. Fine-tuning makes sense when you have thousands of domain terms the model confuses. At 12 docs, the off-the-shelf model is already overpowered.

### 9. "How does this scale to 100K docs?"

Honest unknown. Architecture scales (Qdrant handles millions of vectors, RBAC uses payload indexes), but havent proven it. The embedding model comparison (small vs large finding 0 extra at 12 docs) will probably change at scale. Documented as an explicit boundary.

### 10. "Why not just use pgvector and skip the separate vector DB?"

Could work. pgvector handles dense vectors fine. But hybrid search (dense + BM25 with RRF fusion server-side) needs two queries + application-side ranking with pgvector. Qdrant does it in one query. At scale, the dedicated vector DB handles HNSW indexing better. At 12 docs, pgvector would be fine honestly. Its an architecture bet on scale.
