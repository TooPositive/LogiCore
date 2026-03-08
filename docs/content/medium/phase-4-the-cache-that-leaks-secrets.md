---
title: "We Cut AI Costs 93% — The Dangerous Part Was the Cache"
subtitle: "How semantic caching becomes a universal access control bypass, and the partition key that prevents it"
series: "LogiCore AI System — Phase 4/12"
phase: 4
date: 2026-03-08
status: draft
tags: ["LLMOps", "semantic caching", "model routing", "FinOps", "RBAC", "Langfuse", "observability", "enterprise AI", "cost optimization"]
---

# We Cut AI Costs 93% — The Dangerous Part Was the Cache

## 1. The Bill Nobody Could Explain

Martin opens his Monday morning report and sees a line item: "Azure OpenAI — EUR 1,260/month." He knows the AI system is working — the invoice audit agents caught EUR 40,800 in overcharges last quarter (Phase 3 of this series). He knows the document search handles 800 queries per day. But he cant break down that EUR 1,260 into anything useful.

Which queries cost money? Which are expensive? How much does each agent cost per run? Is the fleet monitoring system burning tokens on simple status lookups that dont need a frontier model?

Martin is the CFO of LogiCore Transport, a Polish logistics company running AI across document search, invoice auditing, and fleet monitoring. The AI works. What Martin doesnt have is a bill he can read.

This is Phase 4 of a 12-phase AI system im building for a logistics company. Phase 1 built document search with RBAC-filtered access control — proving that embeddings are mandatory and BM25 alone breaks on 50% of real queries. Phase 2 stress-tested retrieval quality at scale: re-ranking, chunking, HyDE, and the finding that text-embedding-3-large adds zero value at 6.5x the cost. Phase 3 built multi-agent invoice auditing with LangGraph — agents that find EUR 588 overcharges and then STOP, waiting for human approval, with PostgreSQL persistence so a server crash at 2 AM doesnt lose the CFOs review queue.

Phase 4 asks: if you cant trace why your AI answered what it answered, how do you know its not costing you more than the clerks it replaced?

## 2. Why Observability Is Harder Than It Looks

Peter Drucker supposedly said "you cant manage what you cant measure." Whether he actually said it is debatable, but the point applies directly to LLM costs. Unlike traditional API calls where the cost is fixed per request, LLM costs scale with input AND output tokens, vary 350x between model tiers, and depend entirely on which model handles which query.

The naive approach is to send every query to the best model. GPT-5.2 at $1.75/$14.00 per 1M tokens handles everything well. At 2,400 queries/day, that costs EUR 42/day. EUR 1,260/month. EUR 15,120/year.

The problem is that 50% of those 2,400 queries are simple lookups: "whats the status of shipment TRK-2024-0847?" or "how many trucks are in the fleet?" These dont need multi-hop reasoning. They dont need cross-document synthesis. They need a model that can read a database row and format a sentence. GPT-5 nano does this at $0.05/$0.40 per 1M tokens — 35x cheaper on input, 35x cheaper on output.

Daniel Kahneman's "Thinking, Fast and Slow" describes two modes of thought: System 1 (fast, automatic, cheap) and System 2 (slow, deliberate, expensive). Model routing is Kahneman for LLMs. Simple lookups get System 1 (nano). Financial analysis gets System 2 (GPT-5.2). You dont need the deliberate system for automatic tasks.

The routing decision tree:

```
Incoming query
  ├── Contains financial keyword? (contract, invoice, rate, penalty...)
  │     └── COMPLEX → GPT-5.2 (always, no LLM classifier needed)
  │
  ├── LLM classifier says SIMPLE (confidence > 0.7)?
  │     └── GPT-5 nano ($0.05/$0.40 per 1M)
  │
  ├── LLM classifier says MEDIUM?
  │     └── GPT-5 mini ($0.25/$2.00 per 1M)
  │
  └── Confidence < 0.7 or unparseable response?
        └── Escalate one tier (safe fallback)
```

The router itself runs on nano. Cost per classification: EUR 0.000025. At 2,400 queries/day, the router costs EUR 0.06/day. The savings it generates: EUR 39.13/day. Thats a 652x return on the classification cost.

## 3. The Architecture: Tracing Every Token

Every LLM call passes through a handler that records: trace ID, agent name, model, prompt tokens, completion tokens, latency in milliseconds, cost in EUR. This feeds a FinOps dashboard where Martin can finally see his cost breakdown:

```python
class LangfuseHandler:
    def on_llm_end(
        self,
        trace_id: str,
        run_id: str,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ...
    ) -> None:
        cost = self._cost_tracker.record(
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        try:
            self._langfuse.trace(
                name=agent_name,
                id=trace_id,
                input=prompt,
                output=response,
                metadata={
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "cost_eur": str(cost),
                },
            )
        except Exception:
            self._fallback.store_trace(trace)
```

That double try/except is the most important architectural decision in Phase 4. Langfuse is self-hosted (EU data residency — the prompts contain contract rates and invoice amounts, which cant leave the infrastructure under GDPR). But self-hosted means self-maintained. If Langfuse goes down, the handler writes the full trace to a fallback store. If the fallback store ALSO fails, it logs the error and continues. The LLM call result is NEVER blocked by telemetry failure.

Nassim Taleb would call this antifragile observability — the system degrades gracefully under failure instead of propagating it. The reconciliation job backfills Langfuse after recovery. You lose trace visibility during an outage, but you never lose a user query.

Why does this matter? Because Langfuse isnt just an observability tool — its a compliance dependency. Phase 8 will build immutable audit logs that reference Langfuse trace IDs. If Langfuse data is lost, those audit entries become dangling pointers. A regulator asking "show me the AI reasoning for this financial decision" gets a broken link. The fallback store prevents this gap entirely.

## 4. The Hard Decision: What the Cache Should NOT Do

With tracing in place, I could see the cost breakdown. Document search: EUR 0.0015/query. Invoice audit: EUR 0.031/run. Fleet monitoring: EUR 0.002/alert. Simple lookups: EUR 0.000065/query. Total with routing: EUR 2.87/day.

The next obvious optimization is caching. If Anna asks "whats the penalty for late delivery to PharmaCorp?" at 9 AM and Stefan asks the same question at 9:15 AM, why pay for the LLM call twice? Embed the query, check Redis for a similar cached query (0.95 cosine similarity threshold), serve the cached answer in 2ms for EUR 0.00.

Projected savings: 35% cache hit rate, EUR 18/day.

And this is where the naive implementation becomes a EUR 250,000 vulnerability.

| What I almost built | What I actually built | Why |
|---|---|---|
| Cache keyed by query similarity only | Cache partitioned by RBAC context + entity name | Similarity-only cache is a universal access control bypass |
| Single cache namespace | Partition key: `cl:{clearance}\|dept:{departments}\|ent:{entities}` | Different clearance levels are structurally separate namespaces |
| 35% hit rate | 15-25% effective hit rate | Security partitioning reduces matches but prevents data leaks |

The scenario that caught it: a clearance-3 user asks "whats PharmaCorp's penalty rate?" and the answer gets cached. A clearance-1 user asks the same question. Cosine similarity: 0.99. Without partitioning, thats a cache hit. The clearance-1 user sees confidential contract data they shouldnt have access to. EUR 25,000-250,000 GDPR exposure.

The partition key prevents this structurally, not through filtering:

```python
def _partition_key(
    clearance_level: int,
    departments: list[str],
    entity_keys: list[str] | None = None,
) -> str:
    sorted_depts = sorted(departments)
    sorted_entities = sorted(entity_keys or [])
    parts = [
        f"cl:{clearance_level}",
        f"dept:{','.join(sorted_depts)}",
        f"ent:{','.join(sorted_entities)}",
    ]
    return "|".join(parts)
```

The clearance-1 user doesnt "fail" a filter check on the cached entry. Their query goes to a completely different partition. The cached entry for clearance-3 is structurally unreachable. Its not access control — its namespace isolation.

And "PharmaCorp penalty rate?" and "FreshFoods penalty rate?" score 0.96 cosine similarity (the embeddings treat them as nearly identical since the semantic structure is the same). Without entity partitioning, thats a cache hit serving PharmaCorp's 15% penalty rate when someone asked about FreshFoods' 10% rate. Finance applies the wrong rate. EUR 3,240 per incident, estimated 2-3 per month at 0.95 threshold.

With entity partitioning, theyre in separate namespaces. Cache miss. Fresh retrieval with the correct contract data.

Donella Meadows would recognize this as a leverage point — the partition key is a small structural change that prevents an entire category of failure. The cache doesnt know about RBAC. It doesnt check permissions. It just puts things in separate boxes, and the box labels include who the answer is for.

The cost: effective hit rate drops from 35% to 15-25%. Daily savings drop from EUR 18 to EUR 8-13. One wrong cached response costs EUR 3,240. The math is not complicated — you take the security tax and sleep at night.

## 5. The Evidence: What It Actually Costs

After building routing + caching + tracing, Martin gets his Monday report:

| Use Case | Queries/Day | Model | Cost/Query | Daily Cost |
|---|---|---|---|---|
| Simple lookups | 900 | GPT-5 nano | EUR 0.000065 | EUR 0.06 |
| Document search | 800 | GPT-5 mini | EUR 0.0015 | EUR 1.20 |
| Invoice audit | 50 | GPT-5.2 | EUR 0.031 | EUR 1.55 |
| Fleet monitoring | 30 | GPT-5 mini | EUR 0.002 | EUR 0.06 |
| Cache hits | ~620 | none | EUR 0.00 | EUR 0.00 |
| **Total** | **~2,400** | | | **EUR 2.87/day** |

Previous cost (everything on GPT-5.2, no caching): EUR 42.00/day. Thats a 93% reduction. EUR 14,448/year savings at current volume. At 10x scale (24,000 queries/day), the savings reach EUR 144K/year.

The model routing accounts for most of the savings. The 10 financial keywords (contract, invoice, rate, penalty, amendment, surcharge, annex, audit, compliance, discrepancy) force COMPLEX routing without even asking the LLM classifier. This is a deterministic, free (no LLM call) override that catches exactly the queries where misclassification hurts most.

The router has three safety mechanisms for queries it cant classify cleanly:

The keyword override catches financial queries by keyword match. If the LLM classifier returns garbage (unparseable response), it defaults to COMPLEX. If the confidence is below 0.7, it escalates one tier (SIMPLE becomes MEDIUM, MEDIUM becomes COMPLEX). All three mechanisms push toward the expensive-but-safe model. The system can waste money on overclaassification but can never save money by misclassifying a complex query as simple.

## 6. The Cost of Getting It Wrong

| Error | Cost | Frequency | Mitigation |
|---|---|---|---|
| Cache serves wrong client data | EUR 3,240 per incident | 2-3/month without entity partitioning | Entity-aware partition keys |
| Cache bypasses RBAC | EUR 25,000-250,000 per incident | HIGH without clearance in key | Clearance + department in partition |
| Financial query routed to nano | EUR 486-3,240 per misrouted query | Variable | 10 keyword overrides force COMPLEX |
| Stale cache after contract update | EUR 500-3,240 per incident | 1-2/month | Staleness detection + doc invalidation |
| Langfuse outage during audit | EUR 10,000-100,000 regulatory | 2-4 days/year | PostgreSQL fallback store + reconciliation |

The staleness detection was one of those "how did we almost miss this" moments. A contract gets updated (new rate), but the cache still holds the old answer. Finance asks the same question, gets the cached old rate, applies it to an invoice. The staleness check compares each cached entry's creation time against its source documents' last-updated time. If ANY source document was updated after the cache entry was created, its treated as a miss. Fresh retrieval.

We tested 7 staleness scenarios: single-doc stale, fresh entry, multi-source-doc where only 1 of 3 was updated (still stale), no update timestamps provided (treat as fresh), unrelated document updated (not stale), nonexistent document invalidation (returns 0, no error), and explicit doc-ID invalidation.

## 7. What Breaks

The keyword override list is English-only. LogiCore is a Polish company. "Jaka jest kara za opoznienie?" (whats the penalty for delay) contains "kara" (penalty) in Polish, not "penalty" in English. The override misses it. The query routes to nano. Nano produces a shallow answer on a question where the Q4 amendment surcharge changes the rate by EUR 486.

This is a known gap. The fix is straightforward (add Polish and German keywords: "faktura", "umowa", "kara", "stawka", "Rechnung", "Vertrag", "Strafe") but it belongs in a future phase where multilingual support is the focus.

The LLM-as-Judge evaluation pipeline produces scores: context precision 0.89, faithfulness 0.83, answer relevancy 0.89. These are pipeline validation metrics — they prove the evaluation mechanics work end-to-end (dataset loads, judge scores, quality gate blocks/passes, CLI returns correct exit code). Theyre NOT production quality measurements. The mock judge uses word-overlap heuristics. Real LLM scoring with GPT-5-mini doing claim-by-claim analysis is Phase 5, along with quantifying position bias which inflates scores by ~4 points.

The CI quality gate threshold is 0.8. If faithfulness is actually 0.79 after position bias correction, the gate would correctly fail. But we wont know the real number until Phase 5 calibrates the judge. Phase 4 builds the pipeline. Phase 5 makes the numbers trustworthy.

## 8. What Id Do Differently

If I were advising a team building this, Id insist on cache partitioning from the architecture phase, before any code is written. Its dangerously natural to build a cache without thinking about access control. Every caching tutorial shows `get(query) -> response`. None of them show `get(query, clearance_level, departments, entity_keys) -> response`. That default mental model is what creates EUR 250,000 GDPR exposures in enterprise systems.

W. Edwards Deming's point about quality being designed in, not inspected in, applies directly. If the cache architecture doesnt include RBAC partitioning from the start, you end up bolting on a filter after the fact, which is a weaker defense than structural namespace isolation. The partition key is a design decision, not an afterthought.

I also wouldve built the keyword override list collaboratively with the operations team from day one. An engineer picks "contract, invoice, penalty." An operations manager would immediately add "annex, rider, amendment, surcharge" — the terms that actually appear in the documents. Domain knowledge isnt something you can skip with LLM classification.

## 9. Vendor Lock-in and Swap Costs

| Component | Current | Alternative | Swap Cost |
|---|---|---|---|
| Langfuse (observability) | Self-hosted Docker | LangSmith, Phoenix, custom | Medium — handler interface wraps client; swap the client, keep the interface |
| Redis (cache) | Redis Stack with RediSearch | Memcached + pgvector, DragonflyDB | Medium — SemanticCache class abstracts backend; swap the storage, keep the partitioning logic |
| Model routing | GPT-5 nano classifier | Static rules, local classifier, Claude Haiku | Low — ModelRouter accepts any LLM; swap the classifier, keep the keyword override and escalation |
| Cost tracking | In-memory CostTracker | PostgreSQL-backed, Prometheus | Low — CostTracker is a simple aggregator; swap the storage, keep the pricing table |
| LLM-as-Judge | Mock (word overlap) → GPT-5-mini (Phase 5) | Claude, Gemini, open-source judge | Low — judge interface is score(question, answer, context) → float |

The RBAC partition logic is the most portable part. It doesnt depend on Redis, Langfuse, or any specific model. Its pure Python operating on clearance levels, department lists, and entity keys. You could move the entire cache to PostgreSQL with pgvector and the partition key logic wouldnt change by a single line.

Phase 4/12 of LogiCore. Next: your LLM-as-Judge is biased. The quality dashboard says 0.92. The real number is 0.88. And that 4-point gap is big enough to ship bad code through your CI gate.
