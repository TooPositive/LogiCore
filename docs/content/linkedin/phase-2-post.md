# Phase 2 LinkedIn Post: Retrieval Engineering

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

we benchmarked 6 re-ranking models for our Polish logistics RAG. one was LABELED "multilingual." it made search worse.

im building a 12-phase AI system for a logistics company. each phase tackles a real business problem — what works, what doesnt, what it costs. this is phase 2: retrieval engineering. logistics is a good stress test coz you get Polish workers, English contracts, alphanumeric cargo codes, and typos from warehouse workers on mobile devices. if your retrieval pipeline handles all that, it handles anything.

phase 1 said hybrid search (dense + BM25) was the best mode. 24/26 queries. phase 2 doubled the query set to 52 across 10 categories and the conclusion REVERSED. dense-only MRR=0.885 beats hybrid MRR=0.847. BM25 adds noise when query diversity increases. the lesson: benchmark conclusions are scale-dependent. always re-validate when your test set grows.

the re-ranking story is where it gets interesting. we tested 6 cross-encoder models on 2 production-quality Polish corpora (57 docs each, 5-9K chars per doc, not the 800-char toy docs you see in tutorials).

TinyBERT (14.5M params): -25.5% MRR. ms-marco (33M): -3%. both English-only, both break on Polish queries and typos. expected.

mmarco-mMiniLM (118M params, explicitly trained on translated ms-marco data, marketed as "multilingual"): -6.6% MRR. it made search WORSE than no re-ranking at all. "multilingual" on the model card means the training data was translated. it doesnt mean the model actually understands cross-lingual semantics. if you deployed this based on the label youd have degraded search quality without knowing why.

BGE-base (278M): +0.3%. neutral. wastes 144ms of compute for nothing.

BGE-large (560M): +23.5% MRR. BGE-m3 (568M): +25.8% MRR. the difference? BGE-m3 has a dedicated m3 training objective (multi-lingual, multi-functionality, multi-granularity). its purpose-built for cross-lingual retrieval, not retrofitted.

we also tested HyDE (hypothetical document embedding) on 4 categories. it HURT across the board. vague queries: -20.9% recall@5. exact codes: -25.0% MRR. at 12-doc corpus scale the hypothetical answer is LESS specific than the original query. switching condition: probably useful above 500+ semantically similar docs where direct queries cant find the right one.

cost side: text-embedding-3-small ($0.02/1M tok) still beats text-embedding-3-large ($0.13/1M tok) at 52 queries. MRR 0.885 vs 0.856. the expensive model is 6.5x the cost and performs WORSE. not justified until your corpus has 1000+ semantically similar docs.

the pipeline breaks on negation (0.458 MRR). "contracts WITHOUT temperature requirements" still returns temperature docs coz embeddings match "temperature" semantically. they cant negate. thats not a retrieval fix, thats a Phase 3 agent reasoning problem.

329 tests, 52 queries, 10 categories, 6 re-ranking models, 2 production corpora. total embedding cost for all Phase 2 benchmarks: roughly ~€0.15. BGE-m3 runs fully local, no data leaves the infrastructure (GDPR advantage over cloud re-rankers).

post 2/12 in the LogiCore series. next up: what happens when search works but the AI cant reason across multiple documents. multi-agent orchestration with human-in-the-loop 😅

---

## Reply Ammo

### 1. "52 queries isn't enough to draw conclusions"

fair, its not a research paper. but each query targets a specific failure mode across 10 categories (Polish, typos, jargon, negation, exact codes, synonyms, vague, natural language, ranking, multi-hop). the patterns are extremely consistent — all 3 English-only models break Polish the same way, all fail typos the same way. consistency across categories matters more than raw sample size for architecture decisions.

### 2. "Why not just use Cohere Rerank? It's the standard"

we have the CohereReranker implemented and ready. didnt benchmark it yet coz BGE-m3 at +25.8% MRR runs fully local — zero data leaves the infrastructure. for a Polish logistics company with GDPR concerns thats a real advantage. Cohere is the cloud backup if latency budget is tight (BGE-m3 is ~480ms at 7K char docs). mapped to Phase R for formal comparison.

### 3. "HyDE is proven to help in papers"

on large corpora with high semantic overlap, yeah. at 12-doc scale the hypothetical answer's embedding is LESS specific than the original query. the corpus is small enough that direct queries already find the right doc. we put a switching condition at 500+ similar docs. below that, HyDE adds latency and noise for zero benefit.

### 4. "That mmarco result seems wrong — it IS multilingual"

thats exactly the point. the model card says multilingual. the training data was translated ms-marco. but translation ≠ understanding. BGE-m3's m3 objective (multi-lingual, multi-functionality, multi-granularity) explicitly trains for cross-lingual semantics. mmarco just translates English patterns into other languages. our benchmark proves the label is meaningless without the right training objective. this is why you benchmark, not trust model cards.

### 5. "Why test 6 models? Just use the best one"

coz "the best one" depends on your deployment context. TinyBERT at 14.5M params runs on CPU in 28ms — if youre air-gapped English-only (Phase 6), thats your model. BGE-m3 at 568M needs ~2GB disk and gives +25.8% MRR on multilingual. BGE-large is the backup if BGE-m3 has compatibility issues. the 6-model comparison gives you a decision framework, not just a recommendation.

### 6. "What about the 480ms latency hit from BGE-m3?"

yes its real. 480ms at 7K char avg doc length, 355ms at 1K chars. but +25.8% MRR means the right document goes from position 3-4 to position 1. for a logistics manager making a decision about a penalty clause, getting the right answer 480ms slower is infinitely better than getting a wrong answer 480ms faster. latency-vs-quality is not even close here.

### 7. "Dense-only reversing hybrid at higher query count is suspicious"

actually its the most interesting finding. at 26 queries (Phase 1), 65% were natural language where BM25 adds noise. at 52 queries with 10 categories including exact codes and ranking, BM25 helps on exact_code (1.000 MRR vs 0.760 for dense) but hurts everywhere else. the crossover is probably around 25%+ exact-code queries. below that, dense-only wins.

### 8. "Negation at 0.458 MRR — isn't that a bug?"

its a fundamental embedding limitation. "contracts WITHOUT temperature" matches on "temperature" semantically. embeddings dont negate. BM25 can handle keyword negation but it hurts overall MRR. the right fix isnt retrieval at all — its agent reasoning (Phase 3) that can filter results by logic, not similarity.

### 9. "Why not use a bigger embedding model to fix the quality issues?"

we tested text-embedding-3-large (3072d, $0.13/1M tok). its WORSE by -0.029 MRR than small (1536d, $0.02/1M tok) on 52 queries. higher dimensions dont help when your corpus is 12 docs — theres not enough semantic overlap to separate. the switching condition is probably 1000+ semantically similar docs. below that, youre paying 6.5x for lower quality.

### 10. "How do you handle reranker failures in production?"

circuit breaker pattern. 3 consecutive failures → trip → fallback to NoOp (no re-ranking). 60s recovery timeout, half-open probe. all state transitions tested (42 reranker tests). the fallback is graceful degradation — you lose the +25.8% quality boost but search still works. composable: CircuitBreakerReranker wraps any primary/fallback pair.
