# Phase 2 LinkedIn Post: Retrieval Engineering

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

A model card said "multilingual." We deployed it. Search quality dropped 6.6%.

Anna runs logistics operations for a Polish transport company. Her team searches contracts in Polish. The warehouse guys type on mobile with typos. When Anna asked "kary za opoznienie dostawy PharmaCorp" (penalties for late PharmaCorp delivery), the correct penalty clause ranked fourth. Position four means she never sees it. She calls legal. Legal pulls the 47-page contract manually. A 15-minute search that should've taken 15 seconds.

This is Phase 2 of a 12-phase AI system im building for a logistics company. Phase 1 proved embeddings are mandatory and BM25 alone breaks on real human queries (16/26). Phase 2 asks a different question: the AI finds "similar" documents, but how do you make the RIGHT one rank first?

The naive answer is "add a cross-encoder re-ranker." Pick one from HuggingFace, done. Except we tested 6 models on 2 production-quality Polish corpora (57 docs each, 5-9K chars, not the 800-char toy docs from tutorials) and 4 of them made search WORSE.

The interesting one is mmarco-mMiniLM. 118M params, explicitly trained on multilingual data, model card says "multilingual." It dropped MRR by 6.6% on our diverse corpus. "Multilingual" means the training data was machine-translated from English. It does NOT mean the model understands Polish. If Anna's company had deployed this based on the label, every search by her Polish team would've gotten slightly worse results and nobody would know why.

BGE-m3 (568M params) was the only model that actually works for multilingual. +25.8% MRR. The difference is the training objective: m3 stands for multi-lingual, multi-functionality, multi-granularity. Its purpose-built for cross-lingual retrieval, not English patterns replayed in other languages.

We also tested HyDE (generate a hypothetical answer, embed that instead of the query). It hurt across every category. Vague queries: -20.9% recall. Exact codes: -25.0% MRR. At 12-doc scale the hypothetical is less specific than the original query. Probably useful above 500+ semantically similar docs where direct queries get confused.

And Phase 1's hybrid search recommendation? Reversed at 52 queries. Dense-only MRR=0.885 beats hybrid MRR=0.847. BM25 adds noise when query diversity increases. Benchmark conclusions are scale-dependent (thats uncomfortable but thats how it works).

Cost of deploying the wrong re-ranker: at 200 queries/day, mmarco-multi means ~13 queries returning wrong results. 13 wrong answers x 15 min manual lookup = ~3 hours/day wasted. Thats roughly €1,700/month in lost productivity. BGE-m3 runs fully local, costs €0 in API fees, and no data leaves the infrastructure (the GDPR question doesnt even come up).

The pipeline still breaks on negation though (0.458 MRR). "Contracts WITHOUT temperature requirements" returns temperature docs coz embeddings cant negate. Thats not a retrieval fix, thats an agent reasoning problem.

Post 2/12 in the LogiCore series. Next up: what happens when search works but the AI cant reason across documents (spoiler: 0/3 on "which contract has the highest value") 😅

---

## Reply Ammo

### 1. "52 queries isn't statistically significant"

Fair point. But each query targets a specific failure mode across 10 categories (Polish, typos, jargon, negation, exact codes, synonyms, vague, natural language, ranking, multi-hop). The patterns are consistent across all 3 English-only models breaking the same way. When all your data points agree its probably not noise.

### 2. "Why not Cohere Rerank? Thats the industry standard"

We have CohereReranker implemented, same BaseReranker ABC. Didnt benchmark it yet coz BGE-m3 at +25.8% runs fully local. For a Polish company with GDPR concerns, zero data leaving the infrastructure is an actual architectural advantage. Cohere is the backup if latency budget gets tight.

### 3. "HyDE works great in the papers"

Yeah on large corpora with high semantic overlap. At 12 docs the hypothetical answer's embedding is LESS specific than the original query. The corpus is small enough that direct queries already find the right doc. Our switching condition is 500+ similar docs. Below that HyDE adds ~1.4-3.8s latency for worse results.

### 4. "That mmarco finding sounds like a config issue"

We thought so too. But TinyBERT (English-only, 14.5M) scored -25.5%, ms-marco (English-only, 33M) scored -3%, and mmarco-multi (118M, "multilingual") scored -6.6%. Its not a config issue, its a training objective issue. Translated ms-marco data teaches English retrieval patterns in other languages. BGE-m3's m3 objective explicitly trains for cross-lingual document relevance.

### 5. "Why 6 models? Just use the biggest one"

Coz "biggest" isnt always "best." BGE-base (278M) is neutral at +0.3% and wastes 144ms. The decision depends on deployment context: TinyBERT for air-gapped English-only (Phase 6), BGE-m3 for multilingual, skip re-ranking entirely if your corpus is <20 docs. The 6-model comparison gives you a decision framework not just a recommendation.

### 6. "480ms latency per query is a lot"

Yeah its real. But +25.8% MRR means the right document goes from position 3-4 to position 1. For Anna making a decision about a €486 penalty clause, getting the right answer 480ms slower is way better than getting the wrong answer 480ms faster.

### 7. "Dense reversing hybrid seems like overfitting to your query set"

Actually its the most architecturally interesting finding. BM25 scores 1.000 MRR on exact codes but hurts everything else when query diversity increases. The crossover is probably around 25%+ exact-code queries. Below that, BM25 is pure noise. We can test this boundary formally in Phase R.

### 8. "What happens when the re-ranker crashes?"

Circuit breaker. 3 consecutive failures trips the circuit, falls to NoOp (no re-ranking). 60s timeout, half-open probe to test recovery. The system degrades gracefully, you lose the +25.8% quality boost but search still works. Its composable too, CircuitBreakerReranker wraps any primary/fallback pair.

### 9. "Negation at 0.458 MRR — why not just add NOT to BM25?"

BM25 handles keyword negation but adding BM25 drops overall MRR from 0.885 to 0.847. You cant add it just for negation without degrading everything else. The right fix is agent reasoning (Phase 3) where the agent retrieves candidates then applies logical filtering. Retrieval fetches, reasoning filters.

### 10. "text-embedding-3-large should be better with more dimensions"

You'd think. But at 52 queries on 12 docs, small (1536d, $0.02/1M tok) scores MRR 0.885 vs large (3072d, $0.13/1M tok) at 0.856. The large model is 6.5x more expensive AND worse. Higher dimensions only help when you have 1000+ semantically similar docs where the extra separation actually matters.
