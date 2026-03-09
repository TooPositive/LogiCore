---
phase: 1
title: "Embeddings Are Mandatory. BM25 Is a Lookup Tool, Not a Search Engine."
subtitle: "26 queries, 7 failure categories, and zero-trust RBAC that filters before the LLM ever runs."
linkedin_post: docs/content/linkedin/phase-1-post.md
status: draft
date: 2026-03-08
tags: [rag, hybrid-search, rbac, enterprise-ai, qdrant, embeddings, zero-trust]
word_count: ~3500
---

# Embeddings Are Mandatory. BM25 Is a Lookup Tool, Not a Search Engine.

## The Employee Who Walked Down the Hall

Max Weber works on the warehouse floor at LogiCore Transport in Gdansk. A pharmaceutical shipment arrives in two hours and he needs the safety procedures for handling hazardous materials. He types "towary niebezpieczne" (hazardous goods in Polish) into the company search portal.

Zero results.

The document exists. Its right there in the system — safety procedures, clearance level 1, his department. But the document is written in English, and it uses the term "hazardous materials." BM25 — the keyword search engine running under the hood — doesnt understand that "towary niebezpieczne" and "hazardous materials" mean the same thing. It does exact string matching. The strings dont match. Max gets nothing.

So Max walks down the hall. He asks a colleague who doesnt know either. Someone calls the safety officer. The safety officer is on a different shift. The shipment arrives in two hours and nobody on the floor has the procedures they need.

This happens every day in companies with multilingual workforces and English-language documentation. Not catastrophically — nobody dies because Max walked down the hall. But multiply it by 200 searches per day across a company, and you have a quiet, invisible productivity drain that nobody measures because the search engine always "returns results." It just returns the wrong ones. Or zero.

Then theres the other problem, the one that actually ends careers. The CTO at a similar company said it plainly: "Our AI chatbot told a warehouse worker about the CEO's compensation package. We need zero-trust retrieval." Someone typed "compensation" looking for customer compensation policies. The RAG system pulled the executive compensation document instead. Clearance level 1 user, clearance level 4 document. The LLM read it, summarized it, served it. One prompt injection in any retrieved document could have made it worse.

This is Phase 1 of a 12-phase AI system im building for a logistics company. Each phase tackles a real business problem — not a tech demo, a problem someone cant do their job without solving. Phase 1 asks two questions: can your employees actually find what they need? And can you guarantee they ONLY find what theyre authorized to see?

## Why Keyword Search Fails Real Humans

Daniel Kahneman's "Thinking, Fast and Slow" describes two cognitive systems: System 1 (fast, pattern-matching, often wrong on complex tasks) and System 2 (slow, deliberate, more accurate). BM25 is System 1 for search. It pattern-matches tokens at 2ms. If the tokens exist in the document, it finds them instantly. If they dont — different language, synonym, typo — it returns nothing. Fast and confidently wrong.

The naive approach to enterprise search is starting with BM25 because its free, local, and sub-millisecond. Works in demos. Works when the person building the demo types the exact terms they know are in the documents. Breaks immediately when Max types in Polish.

Gene Kim identifies the first step of improvement in "The Phoenix Project" as finding the actual constraint. The constraint here isnt search speed. BM25's 2ms is meaningless when 10 out of 26 queries return garbage. The constraint is search accuracy for humans who dont know (and shouldnt need to know) the exact terminology in the exact language, spelled perfectly, that exists in the document.

The 2ms vs 147ms latency comparison is the kind of metric that looks great in a slide deck and means nothing in production. You cant ship a system that returns wrong answers for 38% of queries to save 145 milliseconds.

## The Architecture: Hybrid Search with Zero-Trust RBAC

When Max types "towary niebezpieczne przepisy," two things happen simultaneously. His user context (clearance level 1, department: warehouse) gets resolved into a Qdrant filter. And the query gets embedded into a 1536-dimensional vector AND tokenized into BM25 sparse terms. Both representations search Qdrant's collection at the same time, both filtered by Max's RBAC constraints, and the results get fused with Reciprocal Rank Fusion.

```python
async def hybrid_search(
    query: str,
    user: UserContext,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[str], Coroutine],
    top_k: int = 5,
    mode: SearchMode = SearchMode.HYBRID,
) -> list[SearchResult]:
    rbac_filter = build_qdrant_filter(user)
    prefetch_limit = top_k * 4

    if mode == SearchMode.HYBRID:
        query_vector = await embed_fn(query)
        sparse_vector = text_to_sparse_vector(query)

        response = await qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(query=query_vector, using="dense", limit=prefetch_limit),
                models.Prefetch(query=sparse_vector, using="bm25", limit=prefetch_limit),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=rbac_filter,
            limit=top_k,
            with_payload=True,
        )
```

The architectural choice is that `rbac_filter` is applied to the entire query — both prefetch branches and the fused result. When Max searches "CEO compensation," the Qdrant query returns zero results because the Executive Compensation Policy has clearance 4 and department executive. Max has clearance 1 and department warehouse. The LLM downstream receives zero chunks. It cant summarize, reference, or hallucinate from a document it never saw.

This is what Donella Meadows describes in "Thinking in Systems" as a system boundary. The RBAC filter is a hard boundary — not a business rule that can be bypassed, not a post-hoc filter that runs after the LLM already processed everything. Its a query constraint that excludes documents before they enter the pipeline. Information outside Max's authorization boundary literally doesnt exist from the system's perspective.

The empty department list edge case is where this thinking matters most. What happens if someone's user record has an empty department list? Qdrant's `MatchAny([])` has undefined behavior across versions — it could match everything (security breach) or nothing (silent failure). Both are wrong.

```python
def build_qdrant_filter(user: UserContext) -> Filter:
    if not user.departments:
        raise ValueError(
            f"User {user.user_id} has empty departments list. "
            "Refusing to build filter — MatchAny([]) could bypass RBAC."
        )

    return Filter(
        must=[
            FieldCondition(key="department_id", match=MatchAny(any=user.departments)),
            FieldCondition(key="clearance_level", range=Range(lte=user.clearance_level)),
        ]
    )
```

This isnt defensive programming for a theoretical scenario. An empty department list in production means a database migration error, an identity provider misconfiguration, or a newly created user without department assignment. All of these happen. The correct response is always to fail closed (zero results) rather than fail open (all results).

## The Hard Decision: Dense Alone or Dense + BM25?

The question was never "BM25 or Dense?" Anyone who frames it that way is comparing a lookup tool to a search engine. The real question is: do I need BM25 at all once I have embeddings?

I benchmarked 26 queries across 7 categories. Each category designed to stress-test a specific failure mode — not confirm what works, but find what breaks.

| Mode | Synonym (4) | Exact Code (4) | Ranking (4) | Jargon (4) | Polish (4) | Typo (4) | Negation (2) | Total |
|---|---|---|---|---|---|---|---|---|
| BM25 (free, 2ms) | 2/4 | 4/4 | 2/4 | 2/4 | 2/4 | 2/4 | 2/2 | **16/26** |
| Dense (~€0.02/1M, 147ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 1/2 | **23/26** |
| Hybrid RRF (128ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 2/2 | **24/26** |

When Max types "towary niebezpieczne," BM25 sees Polish tokens that dont exist in any English document. Zero results. Dense embeddings see the semantic concept of "hazardous goods" regardless of language and find the right document at rank 1. When Anna in logistics searches "letting go of staff," BM25 sees three English words that dont appear in the HR manual. Dense embeddings understand its a synonym for "termination" and rank the right document first.

Dense beats BM25 in every category except negation (1/2 vs 2/2). Hybrid matches dense everywhere and wins on negation by combining BM25's exact keyword match for "non-perishable" with dense's semantic understanding.

Nassim Taleb would call this a barbell strategy (from "Antifragile"): embeddings carry the weight (23/26), BM25 adds precision at the extremes (exact codes, negation keywords). The system handles query variation because it has two independent mechanisms, each covering the other's weakness.

**The decision**: hybrid as default. Switch to dense-only when your corpus has no alphanumeric codes AND BM25 indexing becomes a maintenance burden. Switch to BM25-only: never. BM25 alone fails 38% of queries from real humans.

I also benchmarked text-embedding-3-large (3072 dimensions, ~€0.13/1M tokens) against text-embedding-3-small across all 26 queries. Result: identical. 23/26 on both. Zero extra hits at 6.5x cost. At 12 documents, the extra dimensions add no discriminating power — embeddings are already spread far enough apart in 1536-dimensional space. **Recommendation**: stick with small until corpus exceeds ~1000 semantically similar documents. That boundary is an assumption, not evidence — havent tested at that scale. Documented as an explicit unknown.

## The Evidence: What the System Does and Refuses to Do

The benchmark proves outcomes, not volume.

**Unauthorized documents are structurally invisible.** Max (clearance 1, department: warehouse) searches "salary compensation termination." He sees 2 documents — both within his clearance and department. Katrin (clearance 3, HR) searches the same query — sees 1 document. Eva (clearance 4, all departments) sees 6. Verified with real Azure OpenAI embeddings, not mocks. The system doesnt refuse Max access to the CEO's compensation. The document doesnt exist in his query universe. The LLM cant reference what it never received.

**BM25 fails consistently on non-exact queries.** Not randomly — consistently. Synonyms: 2/4. Polish: 2/4. Typos: 2/4. Jargon: 2/4. Four independent failure categories, same pattern across all of them. This isnt a sample size issue, its a structural limitation of token matching.

**Embeddings absorb real-world query patterns.** Polish logistics terminology, common typos ("pharamcorp" finds PharmaCorp), industry jargon abbreviations ("GDP compliance" finds Good Distribution Practice docs) — all handled without any domain fine-tuning. text-embedding-3-small has never seen LogiCore's specific documents. It handles "towary niebezpieczne przepisy" purely from its cross-lingual training.

**Path traversal on the ingest endpoint is blocked.** Someone sending `../../etc/passwd` as the file_path gets a 403, not a file read. The ingest endpoint validates against an allowlist directory (`data/` only). Even if the FastAPI server runs with excessive filesystem permissions, the application layer rejects paths outside the data directory.

## The Cost: What It Actually Takes

| Component | Cost | Notes |
|---|---|---|
| Embeddings (text-embedding-3-small) | ~€0.02/1M tokens | 12 docs in Phase 1: effectively €0 |
| Embeddings (text-embedding-3-large) | ~€0.13/1M tokens | Benchmark only. 6.5x cost, 0 extra hits |
| Qdrant | €0 | Self-hosted via Docker |
| PostgreSQL, Redis | €0 | Self-hosted via Docker |

At production scale (1000 docs, 200 queries/day):
- Ingestion: ~1M tokens total = €0.02 one-time
- Query embeddings: 200 queries x ~100 tokens = 20K tokens/day = €0.0004/day
- **Monthly query embedding cost: ~€0.01**

The embeddings are effectively free. The expensive part is the answer generation LLM (Phase 2+). Routing 80% of queries through a cheaper model (GPT-5-mini at ~€0.25/1M tok) instead of GPT-5.2 (~€1.75/1M tok) drops average generation cost by ~7x.

Peter Drucker's "what gets measured gets managed" applies in reverse here. If you only measure latency (BM25's 2ms looks great), you optimize for speed and ship a system where Max walks down the hall for half his searches. Those walks — interrupted work, lost time, wrong decisions made without the right document — never show up in a dashboard. At ~€25/hour for a warehouse worker, if even a fraction of those failed searches results in 5-minute detours, the daily cost dwarfs the €0.01/month embedding cost that would have surfaced the right document instantly.

And the RBAC failure cost? A single data leak incident — warehouse worker sees executive compensation — costs €25,000-250,000 (GDPR fine + potential lawsuit + contract breach). The entire embedding cost for 10 years of operation at production scale is ~€1.20. Its not even a rounding error compared to one RBAC failure.

## What Breaks: The Boundaries I Found

**RAG cant reason.** "Contract with the largest annual value" fails all modes (0/3). RAG retrieves documents that mention annual values, but it cant compare numbers across documents to find the largest. Its like asking a librarian "which book has the most pages?" — she can bring you books about page counts, but she has to open each one and compare. Retrieval is not reasoning. Phase 3 adds LangGraph agents that can reason across retrieved documents.

**Negation is fragile.** "Contracts without temperature requirements" in dense mode matches documents that MENTION temperature — the opposite of what was asked. Embeddings see "temperature" and match it, regardless of the "without." Hybrid saves it because BM25 matches "non-perishable" by keyword, which happens to be what the user wanted. But this is coincidence, not understanding. Only 2 negation queries in Phase 1 — Phase 2 expands to 4+ to stress-test whether this pattern holds.

Taleb's concept of fragility fits directly: the hybrid system looks solid on 24/26, but negation is its fragile point. The negation mechanism works by accident (BM25 keyword matching a related term), not by design. A system that truly understands negation would need query-level reasoning — thats a Phase 2 and Phase 3 concern.

**Polish works but the boundary is untested.** 4/4 on simple terms ("towary niebezpieczne przepisy", "okresy wypowiedzenia"). Unknown: complex multi-word phrases like "przepisy dotyczące transportu towarów niebezpiecznych," mixed Polish-English queries, colloquial Polish. This is a bet on cross-lingual embedding quality that needs stress-testing at scale.

**No confidence threshold.** "HNSW index parameters" (completely irrelevant to a logistics corpus) still returns top_k results. The system always returns something. Without precision@k metrics, every query looks like it "worked." Phase 5 adds evaluation rigor to catch this.

## What Id Do Differently

**Start with the hard queries.** My first benchmark had 12 queries and 3 categories. The phase reviewer called it out: claims backed by insufficient evidence across too few categories. Expanding to 26 queries across 7 categories took extra time but made the findings defensible. Meadows' insight about leverage points applies here: the leverage in benchmarking isnt the number of easy queries that pass, its the number of adversarial categories that expose boundaries.

**Character-based chunking was a shortcut.** 512 characters with 50-char overlap at word boundaries. Works for Phase 1 scope. Token-based chunking (512 tokens via tiktoken) would give more consistent semantic density per chunk. Phase 2 benchmarks three chunking strategies head-to-head.

**The path traversal bug should have been caught by TDD.** I found it during development and fixed it before writing the test. Thats the wrong order. The correct sequence: write the attack test (red), watch it pass when it shouldnt (thats the scary part), then fix the code (green). Security follows the same red-green-refactor cycle as features. I got lucky. Luck isnt a security model.

**More negation test cases from day one.** Negation is the one category where hybrid demonstrably beats dense (2/2 vs 1/2). Its the most architecturally interesting finding in the benchmark. And I almost missed it with only 2 queries.

## Vendor Lock-In and Swap Costs

| Component | Lock-in Risk | Swap Cost | Alternative |
|---|---|---|---|
| Qdrant | Low | ~3 days | Weaviate, Milvus, pgvector |
| Azure OpenAI embeddings | Medium | ~1 day | OpenAI direct, Cohere, local model |
| text-embedding-3-small | Low | ~1 day | Any 1536d model |
| FastAPI | Very low | N/A | Litestar, Starlette |

The retriever accepts an `embed_fn` callable, not a specific API client. Swapping embedding providers means changing one function, not the retrieval pipeline.

Qdrant's hybrid search (prefetch + RRF fusion) is a nice API but not unique. Weaviate has hybrid search. pgvector could do it with two queries + application-side fusion. The RBAC filter pattern (metadata filtering at query time) works on any vector DB that supports payload filtering.

Migration path if Qdrant changes pricing or licensing: export vectors + payloads, create equivalent collection in alternative DB, update client initialization. The retriever interface stays the same. Budget 3 days for a senior engineer, including re-testing the RBAC boundary cases.

## Series Close

Phase 1 proved that embeddings are mandatory for human-facing search and that RBAC must happen at the database level, not after retrieval. The system finds documents in Polish, absorbs typos, handles industry jargon — and guarantees that unauthorized documents never reach the LLM.

It also found where it breaks: reasoning across documents, negation understanding, confidence thresholds. Each boundary maps to a future phase.

Phase 1/12 of LogiCore. Next: your chunks are wrong, and re-ranking matters more than you think.

---

*All code snippets in this article are from the actual codebase, not pseudocode.*
