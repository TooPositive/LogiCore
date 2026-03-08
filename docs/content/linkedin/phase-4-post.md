# Phase 4 LinkedIn Post: Trust Layer — LLMOps, Observability & Evaluation

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

Martin is the CFO of a Polish logistics company. Monday morning he opens his report and sees a line item: "Azure OpenAI — EUR 1,260/month." He knows the AI works. The invoice audit agents caught EUR 40,800 in overcharges last quarter. But he cant break down that EUR 1,260 into anything useful. Which queries cost money? Which agents are expensive? Is the fleet monitoring system burning tokens on lookups that dont need a frontier model?

"How much does each AI query cost?" Nobody can answer. The system is a black box with a monthly bill attached.

This is Phase 4 of a 12-phase AI system im building for a logistics company. Phase 1 built document search with access control. Phase 2 proved which embedding models actually work for Polish text. Phase 3 built autonomous invoice auditing agents that stop and wait for human approval. Phase 4 asks: if you cant trace why your AI answered what it answered, how do you know its not costing you more than the clerks it replaced?

So I built cost tracking. Every LLM call gets traced: which model, how many tokens, exact cost in EUR. Turns out 50% of queries are simple lookups ("whats the status of shipment X?") being sent to GPT-5.2 at EUR 0.018 per query. GPT-5 nano handles those for EUR 0.000065. Thats a 277x price difference for identical quality on simple lookups.

With model routing (nano for lookups, mini for search, 5.2 for financial analysis): EUR 2.87/day. Without routing (everything on 5.2): EUR 42/day. 93% reduction. At 10x scale thats EUR 144K/year saved by not being lazy about which model handles which query.

The router itself runs on GPT-5 nano. Cost per classification: EUR 0.000025. Basically free. But I added a keyword override list (contract, invoice, rate, penalty, amendment, surcharge, audit, compliance, discrepancy, annex) that forces complex queries to GPT-5.2 without even asking the LLM classifier. Coz if someone asks "whats the penalty rate for PharmaCorp?" and the router sends that to nano, you get a partial answer that misses the Q4 amendment surcharge. Wrong financial answer = EUR 486-3,240 per incident.

Then I built semantic caching. Same question twice = cached answer in 2ms instead of 800ms, EUR 0.00 instead of EUR 0.012.

And this is where it gets dangerous.

A clearance-3 user asks "whats PharmaCorp's penalty rate?" and the answer gets cached. Then a clearance-1 user asks the exact same question. 0.99 cosine similarity. Cache hit. Except clearance-1 doesnt have access to PharmaCorp contract data. The cache just became a universal RBAC bypass. EUR 25,000-250,000 GDPR exposure.

So the cache isnt keyed by query similarity alone. Every entry is partitioned by clearance level + department + entity name. The partition key looks like `cl:3|dept:finance,logistics|ent:PharmaCorp`. A clearance-1 warehouse user asking the same question hits a completely different partition. Cache miss. Fresh retrieval with proper RBAC filtering.

And "PharmaCorp penalty rate?" and "FreshFoods penalty rate?" score 0.96 cosine similarity (almost identical semantically) but theyre in different entity partitions. Different rates, different answers, structurally impossible to mix them up.

The effective cache hit rate drops from 35% (unpartitioned) to 15-25% with RBAC+entity partitioning. You lose EUR 5-10/day in cache savings. One wrong cached response costs EUR 3,240. The math is not complicated.

What breaks: the keyword override list is English-only. This is a Polish logistics company. Someone asking "jaka jest kara za opoznienie?" (whats the penalty for delay) doesnt trigger the financial keyword override and might route to nano. Known gap, mapped to a future phase for multilingual keywords.

Also the LLM-as-Judge eval pipeline scores (0.89 precision, 0.83 faithfulness) are pipeline validation metrics, not production quality measurements. The mock judge proves the evaluation mechanics work end-to-end. Real LLM scoring comes next phase coz position bias inflates scores by ~4 points and I want to quantify that before trusting any CI quality gates in production.

Post 4/12 in the LogiCore series. Next up: your LLM-as-Judge is biased, and the numbers might surprise you 😅

---

## Reply Ammo

### 1. "93% cost reduction sounds like marketing"

its literally just not sending simple lookups to the expensive model. 50% of queries are "whats the status of X" which nano handles at $0.05/1M input tokens instead of $1.75/1M. the math: 900 simple queries/day x EUR 0.018 on 5.2 = EUR 16.20. same queries on nano = EUR 0.06. multiply across 4 complexity tiers and caching on top. the only way you DONT get this saving is if every single query genuinely requires frontier-model reasoning, which... no.

### 2. "Why not just cache everything with a high threshold?"

coz at 0.95 cosine similarity, "PharmaCorp penalty rate" and "FreshFoods penalty rate" match. different clients, different rates, same cache hit. entity-aware partitioning is mandatory. without it the cache is a data leak, not a performance optimization. we tested this specifically — the red team test creates both queries and verifies theyre in separate partitions.

### 3. "RBAC in the cache key seems overengineered"

the alternative is a cache that serves clearance-3 data to clearance-1 users. thats not a bug, thats a GDPR violation. the partition key adds maybe 50 bytes per entry and zero lookup overhead (its a hash prefix). the "overengineering" costs nothing, the alternative costs EUR 25,000-250,000 per incident.

### 4. "15-25% hit rate is pretty low for a cache"

yeah. thats the security tax. unpartitioned cache gets 35% but leaks data. 15-25% is what you get when every user-entity-clearance combination is a separate partition. at scale (10x volume, 24K queries/day) even 15% saves EUR 90/day = EUR 33K/year. and you sleep at night.

### 5. "Langfuse seems like a single point of failure"

it would be if we let it. the handler has a double try/except: Langfuse fails -> write to fallback store. fallback store also fails -> log error, continue. the LLM call result is NEVER blocked by telemetry failure. reconciliation job backfills Langfuse after recovery. coz losing a trace is annoying but blocking a user query coz your observability tool is down is unacceptable.

### 6. "Why keyword override instead of just trusting the LLM router?"

coz the router classification is probabilistic and financial misrouting costs EUR 486-3,240 per incident. keyword check is deterministic, free (no LLM call), and catches the exact queries where misclassification hurts most. its insurance. the LLM router handles the other 60% of queries where misclassification cost is near-zero (a slightly worse status lookup answer costs nothing).

### 7. "Mock judge scores aren't real quality metrics"

correct, and thats the point. the mock judge validates that the evaluation pipeline works: dataset loads, judge scores, quality gate blocks/passes, CLI returns correct exit code. production scoring needs a real LLM judge (gpt-5-mini doing claim-by-claim analysis). that comes in phase 5, along with quantifying position bias which inflates scores by ~4 points. building the pipeline mechanics first was deliberate.

### 8. "What about model routing latency overhead?"

the classification call runs on nano (~50ms) and happens before the actual query. for queries that hit keyword override theres no LLM call at all — just a string contains check. net overhead: 0-50ms. the savings: 200-500ms on queries routed to nano instead of 5.2 (nano is faster). routing is actually net-negative latency for simple queries.

### 9. "EUR 42/day for 2,400 queries seems high"

thats what happens when you route everything to GPT-5.2 at $1.75/$14.00 per 1M tokens. average query is 2800 input + 400 output. at those rates: (2800 * 1.75 / 1M) + (400 * 14.00 / 1M) = $0.0105 per query. multiply by 2,400 queries = ~$25/day base, plus the 50 audit queries at 4 LLM calls each on 5.2. it adds up fast when you dont route.

### 10. "Why self-hosted Langfuse instead of Langfuse Cloud?"

EU data residency. the prompts contain contract rates, penalty clauses, invoice amounts. sending that to a US-hosted SaaS violates GDPR for a Polish company handling EU logistics data. self-hosted Langfuse in Docker = EUR 0/month, full control, no data leaves the infrastructure. Langfuse Cloud is EUR 59/month and requires a DPA analysis.
