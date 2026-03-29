# ADR-008: Pure-Function Auditor (No LLM for Rate Comparison)

## Status
Accepted

## Context
The invoice audit workflow (Phase 3) compares contract rates against invoice rates to detect overcharges. The auditor node must determine whether `invoice_rate > contract_rate` and classify the discrepancy band (ACCEPTABLE/WARNING/CRITICAL). This node runs after LLM-powered reader and SQL agents, and before a human-in-the-loop gate. It must be idempotent for crash recovery via LangGraph's checkpointer.

## Decision
**AuditorAgent is pure deterministic math — no LLM call.**

## Rationale

| Criteria | Pure Function | LLM-Based Comparison | Hybrid (Math + LLM Explanation) |
|----------|--------------|---------------------|-------------------------------|
| Correctness | `0.52 > 0.45` is always true | Temperature > 0 introduces non-determinism | Math correct, explanation may vary |
| Cost per call | EUR 0.00 | ~EUR 0.02 (GPT-5-mini) | ~EUR 0.02 |
| Latency | <1ms | ~2,000ms | ~2,000ms |
| Idempotency | Guaranteed — same input, same output | Not guaranteed at temperature > 0 | Not guaranteed |
| Crash recovery | Checkpoint resumes with identical result | Checkpoint resumes with potentially different result | Mixed |
| Auditability | Deterministic — result is provable | Probabilistic — result depends on model version | Mixed |

## Consequences
- Cannot do "soft" comparisons (market rate analysis, historical trend detection) — those require LLM reasoning
- Every discrepancy band classification is reproducible and auditable
- Crash recovery via LangGraph checkpointer produces identical results on replay
- Zero marginal cost per audit, regardless of volume
- When the auditor needs external context (Phase 8 market intelligence), a separate LLM node handles that — the rate comparison itself stays deterministic

## When to Revisit
If the audit requires qualitative judgment ("is this rate reasonable given market conditions?"), add a separate LLM node for context — don't replace the deterministic comparison.
