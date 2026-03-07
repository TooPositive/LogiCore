# Phase 1 LinkedIn Post: Corporate Brain (RAG + RBAC)

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-07 | **Status**: draft

---

I ran 26 queries against my RAG system. half of them designed to fail.

BM25 alone scored 16/26. fails synonyms (2/4), Polish queries (2/4), typos (2/4), jargon (2/4). a warehouse worker types "dangerous goods" and gets zero results coz the document says "hazardous materials." types "towary niebezpieczne przepisy" (Polish for hazmat regulations) and gets garbage. types "pharamcorp" with a typo and gets nothing.

real humans dont search in exact english document terminology, spelled perfectly. BM25 expects them to.

dense embeddings (text-embedding-3-small, $0.02/1M tokens) scored 23/26. synonyms 4/4, Polish 4/4, typos 4/4. "letting go of staff" finds the termination procedures doc. "towary niebezpieczne przepisy" finds the hazmat contract. thats what enterprise search should do.

so why not just dense? coz CTR-2024-001 (a contract ID) ranks position 2 in dense mode. BM25 puts it rank 1. when a logistics manager needs a specific contract by its code, position 2 is wrong. hybrid RRF fusion: 24/26, best of both.

the expensive embedding model (text-embedding-3-large, 3072d, $0.13/1M tok)? tested it across all 26 queries. same 23/26 as small. 0 extra hits at 6.5x cost. not justified until you have thousands of semantically similar docs where higher dimensions actually separate them.

security side: warehouse worker Max searches "CEO compensation." zero results. not an error, not a refusal. zero. the LLM never sees the document. RBAC filters at the Qdrant query level before retrieval even happens. same query, three users: Max sees 2 docs, Katrin sees 1, Eva sees 6. verified with real embeddings, not mocks.

what it cant do: reasoning. "contract with the largest annual value" fails ALL modes (0/3). RAG retrieves docs, it doesnt compare numbers across them. thats a multi-agent problem.

80 tests, 12 docs, 26 queries, 7 categories. phase 1 of a 12-phase AI system for logistics. probably wrote more test code than actual code at this point 😅

---

## Reply Ammo

### 1. "BM25 is fine for most use cases"

yeah if your users are developers who know the exact terms in the codebase. for enterprise docs where a Polish warehouse worker types "towary niebezpieczne" and the doc says "hazardous materials" in English? 2/4 on our Polish queries. thats not "fine", thats a coin flip.

### 2. "What about the latency difference? BM25 is way faster"

2ms vs 147ms. sounds impressive until you realize BM25 returns garbage for half the queries. saving 145ms on a wrong result isnt a win. (and hybrid was actually 128ms, faster than dense-only coz of the prefetch + fusion pipeline)

### 3. "26 queries isn't statistically significant"

agreed its not a research paper. but each query was picked to stress a specific failure mode: synonyms, exact codes, ranking, jargon, Polish, typos, negation. 7 categories, each with 4 cases (except negation at 2). its a diagnostic, not a p-value exercise. and the patterns were extremely consistent across categories.

### 4. "Why not SPLADE instead of basic BM25?"

considered it. SPLADE needs a 400MB+ transformer model download and inference step. for Phase 1, BM25 with Qdrant's native IDF modifier does the job: exact keyword matching for codes like ISO-9001. SPLADE would be a Phase 2 upgrade for learned term expansion. dont over-engineer the sparse side when embeddings carry 90% of the weight.

### 5. "What about Cohere reranker or cross-encoder reranking?"

thats Phase 2 territory. Phase 1 proves retrieval works (or doesnt) at the base layer. re-ranking on top of bad retrieval is like applying a filter to a blurry photo. need the foundation right first.

### 6. "The RBAC model seems too simple for production"

its the Phase 1 demo model. 4 users, in-memory dict. production would hit an IdP (Entra ID, Okta). but the security model itself is sound: filters at the Qdrant query level, not post-retrieval. empty department lists throw a ValueError coz MatchAny([]) behavior in Qdrant is undefined and could bypass RBAC entirely. thats the kind of edge case that matters.

### 7. "Why Qdrant over Pinecone/Weaviate?"

native hybrid search (dense + sparse in same collection with RRF fusion server-side), self-hosted (no vendor lock-in for air-gapped deployments in Phase 6), and the RBAC metadata filtering works at query time. wrote an ADR about it. the swap cost to another vector DB is ~3 days if needed.

### 8. "Doesn't every RAG system do RBAC?"

most RAG tutorials filter AFTER retrieval. the LLM sees all docs, then the app hides some from the response. thats fundamentally broken: the LLM has already processed unauthorized content, its in the context window, and a prompt injection could leak it. filtering at the DB level means unauthorized docs never enter the pipeline at all.

### 9. "What about fine-tuning embeddings for your domain?"

not yet. text-embedding-3-small already handles Polish queries, logistics jargon, and typos at 4/4 across those categories. fine-tuning makes sense when you have thousands of domain-specific terms that off-the-shelf models confuse. at 12 docs, the model is already overpowered for the task.

### 10. "How does this scale to 100K+ documents?"

thats the honest unknown. 12 docs, 26 queries is diagnostic, not load test. the architecture scales (Qdrant handles millions of vectors, RBAC filters use payload indexes), but i havent proven it yet. Phase 2 will grow the corpus. the embedding model comparison (small vs large finds 0 extra at 12 docs) will probably change at 100K. thats documented as an explicit boundary.
