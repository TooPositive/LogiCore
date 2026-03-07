---
phase: 1
title: "Embeddings Are Mandatory. BM25 Is a Lookup Tool, Not a Search Engine."
linkedin_post: docs/content/linkedin/phase-1-post.md
status: draft
date: 2026-03-07
tags: [rag, hybrid-search, rbac, enterprise-ai, qdrant, embeddings]
---

# Embeddings Are Mandatory. BM25 Is a Lookup Tool, Not a Search Engine.

*26 queries, 7 categories, 12 documents. What actually works for enterprise RAG with zero-trust RBAC.*

## The Problem

LogiCore Transport has a problem every logistics company has: mountains of unstructured documents that employees cant find. HR manuals, legal contracts, safety protocols, customs regulations, executive compensation policies. all living in various systems, unsearchable except by people who already know whats in them.

the actual CTO pain isnt "we need AI." its "our AI chatbot told a warehouse worker about the CEO's compensation package. we need zero-trust retrieval."

two problems, not one: the search has to actually work for real humans (not just keyword lookup), AND it has to enforce access control at a level where the LLM itself never sees unauthorized documents. most RAG tutorials solve neither.

## What I Tried First (and Why It Failed)

I started with BM25 because its the obvious choice. free, local, sub-millisecond latency, no API calls. Qdrant has native sparse vector support with an IDF modifier, so I didnt even need SPLADE (which would require downloading a 400MB+ transformer model).

the implementation is simple: tokenize the text, compute term frequencies, hash tokens to sparse vector indices, let Qdrant handle the IDF weighting server-side.

```python
def text_to_sparse_vector(text: str) -> SparseVector:
    tokens = tokenize(text)
    if not tokens:
        return SparseVector(indices=[], values=[])

    tf = Counter(tokens)
    indices = []
    values = []
    for token, count in tf.items():
        idx = hash(token) % _VOCAB_SIZE  # 65536
        indices.append(idx)
        values.append(float(count))

    return SparseVector(indices=indices, values=values)
```

works great for exact terms. "CTR-2024-001" finds the PharmaCorp contract instantly. "ISO-9001" finds the quality manual. rank 1, every time. this is BM25's strength: when the user types the exact string that exists in the document, nothing beats it.

then I ran 26 queries designed to break things. 7 categories: synonyms, exact codes, ranking, industry jargon, German, typos, negation.

BM25 scored 16/26.

the failure pattern was consistent across 4 categories:

- **Synonyms (2/4)**: "letting go of staff" returns zero results. the document says "termination procedures." "dangerous goods" returns nothing because the doc says "hazardous materials." real users describe what they need, they dont quote the document back at it.
- **German (2/4)**: "Gefahrgut Vorschriften" (hazmat regulations) returns garbage. the documents are in English. BM25 has no concept of cross-lingual similarity.
- **Typos (2/4)**: "pharamcorp" (typo for PharmaCorp) returns nothing. "tempature" returns nothing. BM25 needs exact character matches.
- **Jargon (2/4)**: "GDP compliance" returns nothing because the doc uses "Good Distribution Practice" without the acronym.

the pattern is clear: BM25 only works when the user already knows the exact terminology in the exact language, spelled perfectly. in a logistics company where warehouse workers search in German and managers use industry acronyms, thats maybe half the queries on a good day.

**2ms average latency though. fast results that are wrong half the time.**

## The Architecture Decision

Dense embeddings (text-embedding-3-small, 1536 dimensions, $0.02/1M tokens) scored 23/26 on the same queries.

- Synonyms: 4/4. "letting go of staff" finds termination procedures at rank 1.
- German: 4/4. "Gefahrgut Vorschriften" finds the hazmat contract at rank 1. cross-lingual embedding quality is surprisingly strong.
- Typos: 4/4. "pharamcorp" finds PharmaCorp at rank 1. embeddings absorb common misspellings.
- Jargon: 3/4. "GDP compliance" finds Good Distribution Practice docs.

the jump from 16/26 to 23/26 isnt a marginal improvement. its the difference between a system that works for humans and one that works for people who already memorized the document corpus.

so why not just use dense embeddings and skip BM25 entirely?

because CTR-2024-001 (a specific contract ID) ranks at position 2 in dense-only mode. embeddings blur similar alphanumeric codes. BM25 puts it at rank 1 because its an exact string match. when a logistics manager needs a specific contract by its code, "close enough" is wrong.

and negation: "contracts without temperature requirements" in dense mode matches documents that MENTION temperature (wrong docs). BM25 matches "non-perishable" by exact keyword, which is actually what the user wanted. dense: 1/2 on negation. hybrid: 2/2.

hybrid RRF (Reciprocal Rank Fusion) scored 24/26. best of both.

the actual decision was never "BM25 or dense." it was "dense alone or dense + BM25." and the answer is: dense + BM25, with BM25 as the precision booster for exact codes and negation keyword matching.

**Switch condition**: use hybrid as default. switch to dense-only when your corpus has no alphanumeric codes AND BM25 indexing becomes a maintenance burden. switch to BM25-only: never.

### What About the Expensive Embedding Model?

I benchmarked text-embedding-3-large (3072 dimensions, $0.13/1M tokens) against text-embedding-3-small across all 26 queries.

Result: 23/26 on both. identical. 0 extra hits at 6.5x cost.

at 12 documents, the extra dimensions add zero discriminating power. the embeddings from the small model are already spread far enough apart in 1536-dimensional space that nothing is getting confused.

**recommendation**: stick with small. upgrade to large only when your corpus grows past ~1000 semantically similar documents where close embeddings start overlapping. that boundary is an assumption, not evidence (I havent tested at that scale yet). documented as an explicit unknown for Phase 2.

## Implementation

the retriever supports three modes: dense_only, sparse_only, and hybrid. hybrid uses Qdrant's native prefetch + RRF fusion, so the ranking happens server-side.

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
    prefetch_limit = top_k * 4  # Over-fetch for better fusion quality

    if mode == SearchMode.HYBRID:
        query_vector = await embed_fn(query)
        sparse_vector = text_to_sparse_vector(query)

        response = await qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=query_vector,
                    using="dense",
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using="bm25",
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=rbac_filter,
            limit=top_k,
            with_payload=True,
        )
```

key design choice: the `rbac_filter` is applied at the Qdrant query level. both prefetch branches AND the fused result are filtered. the LLM downstream never sees a document the user isnt authorized for.

the collection schema configures both vector types with RBAC payload indexes:

```python
await client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config={
        "dense": models.VectorParams(
            size=dense_size,  # 1536 for small, 3072 for large
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(
            modifier=models.Modifier.IDF,  # Qdrant applies IDF server-side
        ),
    },
)

# Payload indexes for RBAC filtering
await client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="department_id",
    field_schema=models.PayloadSchemaType.KEYWORD,
)
await client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="clearance_level",
    field_schema=models.PayloadSchemaType.INTEGER,
)
```

## RBAC: The Other Half of Enterprise RAG

most RAG tutorials skip access control entirely or add it as a post-retrieval filter. thats fundamentally broken. if you filter after retrieval, the LLM has already processed unauthorized documents. theyre in the context window. a prompt injection in one of those docs could leak the content even if your app hides it from the response.

the security model here is zero-trust at the database level:

```python
def build_qdrant_filter(user: UserContext) -> Filter:
    if not user.departments:
        raise ValueError(
            f"User {user.user_id} has empty departments list. "
            "Refusing to build filter -- MatchAny([]) could bypass RBAC."
        )

    return Filter(
        must=[
            FieldCondition(
                key="department_id",
                match=MatchAny(any=user.departments),
            ),
            FieldCondition(
                key="clearance_level",
                range=Range(lte=user.clearance_level),
            ),
        ]
    )
```

two things worth noting:

1. **Empty department list is a ValueError, not "no filter."** MatchAny with an empty list has undefined behavior in Qdrant. depending on the version, it could match everything or nothing. both are security failures: matching everything leaks data, matching nothing silently breaks search. the only correct response is to refuse to build the filter.

2. **Unauthorized documents never enter the pipeline.** warehouse worker Max (clearance 1, department: warehouse) searches "CEO compensation." the Qdrant query returns zero results because the Executive Compensation Policy is clearance 4, department: executive. the LLM receives zero chunks. it cant hallucinate from something it never saw.

verified this with real Azure OpenAI embeddings (not mocks): same query "salary compensation termination," three users. Max sees 2 docs. Katrin (HR, clearance 3) sees 1 doc. Eva (CEO, clearance 4) sees 6 docs. the test checks exact counts.

the ingest endpoint also validates file paths against an allowlist directory. someone sending `../../etc/passwd` as the file_path gets a 403, not a file read. (I found this vulnerability during development and fixed it before writing tests, which is the wrong order, but at least it got caught.)

## Results & Benchmarks

26 queries across 7 categories, 12 documents. queries designed to break specific modes.

| Mode | Synonym (4) | Exact Code (4) | Ranking (4) | Jargon (4) | German (4) | Typo (4) | Negation (2) | Total |
|---|---|---|---|---|---|---|---|---|
| BM25 (free, 2ms) | 2/4 | 4/4 | 2/4 | 2/4 | 2/4 | 2/4 | 2/2 | **16/26** |
| Dense ($0.02/1M, 147ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 1/2 | **23/26** |
| Hybrid RRF (128ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 2/2 | **24/26** |

a few things jump out:

**BM25's only advantage is exact codes and negation.** 4/4 on exact codes (vs dense 4/4 at top_k=5, but only 3/4 at top_k=1 where ranking matters). 2/2 on negation (vs dense 1/2). everything else, dense matches or beats it.

**hybrid is faster than dense-only.** 128ms vs 147ms. counterintuitive, but the prefetch + fusion pipeline parallelizes the two retrievals. smaller result sets to rank.

**the 2ms BM25 latency is noise.** saving 126ms doesnt matter when BM25 returns wrong results for 10/26 queries. optimizing the speed of wrong answers is a waste of engineering time.

**dense and hybrid tie on 5 out of 7 categories.** hybrid wins on negation (2/2 vs 1/2). the entire value of BM25 in the hybrid pipeline is that one extra correct query on negation + better exact code ranking at top_k=1.

### Embedding model comparison

| Model | Dimensions | Cost/1M tokens | Score (26 queries) |
|---|---|---|---|
| text-embedding-3-small | 1536 | $0.02 | 23/26 |
| text-embedding-3-large | 3072 | $0.13 | 23/26 |

0 extra hits. 6.5x cost. the higher dimensions add discriminating power when embeddings are close together in vector space. at 12 documents, nothing is close together. this result will probably change at 1000+ docs with high semantic overlap (10 contracts that all discuss temperature requirements, penalty clauses, and delivery schedules). thats a Phase 2 benchmark.

### RBAC verification

| Check | Result |
|---|---|
| Unknown user | 403 (ValueError) |
| Empty departments | ValueError (refused, not "no filter") |
| Clearance boundary (0, -1, 5) | Rejected |
| Path traversal on ingest | 403 |
| Warehouse worker sees CEO docs | 0 results (verified with real embeddings) |
| Same query, different users | Max: 2, Katrin: 1, Eva: 6 (verified live) |
| Total RBAC tests | 80/80 passing |

## What I'd Do Differently

**Character-based chunking was a shortcut.** I used 512 characters with 50-char overlap at word boundaries. works fine for Phase 1, but token-based chunking (512 tokens, tiktoken) would give more consistent semantic density per chunk. Phase 2 will benchmark chunk sizes and strategies.

**Start with the hard queries, not the easy ones.** my first benchmark had 12 queries and 3 categories. the phase reviewer rightfully called it out: "71% of claims backed by less than 5 cases." expanding to 26 queries across 7 categories took extra time but made the findings credible. should have started there.

**More negation test cases.** negation is the one category where hybrid demonstrably beats dense (2/2 vs 1/2). but n=2 is thin for the most interesting finding. Phase 2 should have 4+ negation queries to really stress-test whether this pattern holds.

**The path traversal bug.** the ingest endpoint originally accepted any file_path from the request body. I caught it before writing tests, which means I got lucky. the correct order is: write the attack test, watch it pass (bad), then fix the code. red-green-refactor includes security.

## Cost Breakdown

| Component | Cost | Notes |
|---|---|---|
| Embeddings (text-embedding-3-small) | $0.02/1M tokens | ~12 docs embedded in Phase 1. cost: effectively $0 |
| Embeddings (text-embedding-3-large) | $0.13/1M tokens | benchmark only. 6.5x cost, 0 extra hits |
| Qdrant | $0 | self-hosted via Docker Compose |
| PostgreSQL | $0 | self-hosted via Docker Compose |
| Redis | $0 | self-hosted via Docker Compose |
| Azure OpenAI (embedding endpoint) | ~$0 at this scale | swedencentral deployment. sub-cent costs at 12 docs |
| **Phase 1 total infra** | **~$0** | all local Docker. production would add hosting costs |

at production scale (1000 docs, 200 queries/day), the embedding cost would be:
- ingestion: ~1M tokens total = $0.02 one-time
- queries: ~200 queries x ~100 tokens each = 20K tokens/day = $0.0004/day
- monthly query embedding cost: ~$0.01

the answer generation LLM is the expensive part (Phase 2+), not the embeddings. routing 80% of queries through a cheaper model (gpt-5-mini at $0.25/1M tok vs gpt-5.2 at $1.75/1M tok) drops average generation cost by ~7x.

## What Breaks Next

these are boundaries I found during Phase 1. each one maps to a future phase.

**RAG cant reason.** "contract with the largest annual value" fails ALL modes (0/3). RAG retrieves documents about annual values, but it cant compare numbers across them to find the largest. thats not a retrieval problem, its a reasoning problem. Phase 3 adds LangGraph agents that can reason across retrieved documents.

**Negation is fragile.** "contracts without temperature requirements" in dense mode matches documents that mention temperature (wrong). hybrid saves it because BM25 matches "non-perishable" by keyword, which is what the user actually wanted. but this is a coincidence, not robust negation understanding. Phase 2 adds query understanding and re-ranking.

**German works but untested at depth.** 4/4 on simple German terms ("Gefahrgut Vorschriften", "Kuendigungsfristen"). unknown: compound nouns like Gefahrguttransportvorschriften, mixed German-English queries, Swiss German dialect. Phase 2 needs multilingual evaluation at scale.

**No confidence threshold.** "HNSW index parameters" (completely irrelevant to the logistics corpus) still returns top_k results. all modes scored 0/1 on false positive detection. the system never returns empty. without precision@k metrics, every query looks like it "worked." Phase 5 adds evaluation rigor.

**The large embedding model boundary is assumed, not proven.** "not justified until corpus >> 1000 semantically similar docs" is my hypothesis based on how embedding spaces work. I havent actually tested it at that scale. could be 500 docs. could be 5000. Phase 2 will grow the corpus and re-benchmark.

## Vendor Lock-In Awareness

| Component | Lock-in risk | Swap cost | Alternative |
|---|---|---|---|
| Qdrant | Low | ~3 days | Weaviate, Milvus, pgvector |
| Azure OpenAI embeddings | Medium | ~1 day (change API endpoint) | OpenAI direct, Cohere, local model |
| text-embedding-3-small | Low | ~1 day | Any 1536d embedding model |
| FastAPI | Very low | N/A (standard Python) | Litestar, Starlette |

the retriever accepts an `embed_fn` callable, not a specific API client. swapping embedding providers means changing one function, not the retrieval pipeline.

Qdrant's hybrid search (prefetch + RRF fusion) is a nice API but not unique. Weaviate has hybrid search. pgvector could do it with two queries + application-side fusion. the RBAC filter pattern (metadata filtering at query time) works on any vector DB that supports payload filtering.

if Qdrant doubles their pricing or stops maintaining the open-source version, the migration path is: export vectors + payloads, create equivalent collection in alternative DB, update the client initialization code. the retriever interface stays the same.

---

*Phase 1 of LogiCore, a 12-phase AI OS for logistics. 80 tests passing, 26 benchmark queries across 7 categories, zero-trust RBAC verified with real embeddings. next up: chunking strategies, re-ranking, and the queries where RAG gave up.*

*Code: all snippets in this article are from the actual codebase, not pseudocode.*
