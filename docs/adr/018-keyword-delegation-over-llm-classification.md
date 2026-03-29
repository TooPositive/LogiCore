# ADR-018: Keyword-Based Delegation over LLM Classification

## Status
Accepted

## Context
Phase 3's customs agent needs to detect when an invoice discrepancy might involve a contract amendment, triggering delegation to a sub-agent for contract lookup. The trigger decision has extreme cost asymmetry: false positive = 500ms + 1 RAG query (cheap), false negative = EUR 136-588 per missed invoice (expensive). Phase 4 extends this pattern with financial keyword overrides that bypass the LLM model router entirely.

## Decision
**Regex keyword matching** (11 keywords in Phase 3, 10 financial keywords in Phase 4) for high-stakes delegation triggers. LLM classification handles the remaining queries where misclassification cost is near-zero.

## Rationale

| Criteria | Keyword Matching (chosen) | LLM Classifier | NER / Semantic Similarity |
|----------|--------------------------|----------------|--------------------------|
| Cost per check | EUR 0.00 (string match) | ~EUR 0.005 (GPT-5-mini) | EUR 0.00-0.005 |
| Recall | ~100% on known terms | ~95% (non-deterministic) | ~90% (embedding similarity) |
| False positive rate | ~10% | ~5% | ~8% |
| False positive cost | 500ms + 1 RAG query | 500ms + 1 RAG query | 500ms + 1 RAG query |
| False negative cost | EUR 136-588 per invoice | EUR 136-588 per invoice | EUR 136-588 per invoice |
| Determinism | Fully auditable | Temperature-dependent | Embedding-dependent |

**Cost asymmetry: 270-1176x.** At this ratio, optimizing for 100% recall with ~10% false positives is the correct strategy.

## Consequences
- English-only in Phase 3 — Polish contract terms ("aneks do umowy", "faktura", "stawka") are missed (~5-10% of Polish-only contracts)
- Phase 4's financial keywords ("rate", "invoice", "penalty", "contract") force COMPLEX model routing, bypassing the cheaper LLM classifier
- Overclassification waste: ~EUR 0.017/query for false positives. Misclassification damage: EUR 486-3,240/query in Phase 4
- When to revisit: (1) false positive rate exceeds 30% and 500ms penalty hits latency SLA, (2) Polish-language keyword coverage is added, or (3) a production analysis shows keyword-only catches <90% of real triggers
