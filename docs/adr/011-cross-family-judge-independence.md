# ADR-011: Cross-Family Judge Independence for Evaluation Pipeline

## Status
Accepted

## Context
Phase 5's quality pipeline uses LLM-as-judge to score retrieval and generation quality. Published benchmarks show 10-15% self-preference inflation when a model judges output from the same model family. GPT-5-mini judging GPT-5.2 output looks like "different model" but is same-family — shared training data, RLHF preferences, and output style produce systematic bias.

## Decision
**Family-level separation enforced via prefix matching + exact-match override registry.** Judge and generator must be from different model families (e.g., OpenAI vs Anthropic). Unknown model families fail-closed — blocked from judging until explicitly registered.

## Rationale

| Criteria | Family-Level (chosen) | Model-Level Only | No Check |
|----------|----------------------|-----------------|----------|
| GPT-5-mini judging GPT-5.2 | BLOCKED (same family) | ALLOWED (different name) | ALLOWED |
| Self-preference risk | Eliminated across known families | 10-15% inflation within families | Full bias |
| Cost | EUR 0.00 (string comparison) | EUR 0.00 | EUR 0.00 |
| Claude Sonnet as judge | ALLOWED (different family, same price EUR 0.011/eval) | ALLOWED | ALLOWED |

**Detection layers:**
1. Exact-match overrides (runtime registry) — for fine-tuned/deployment-specific names
2. Prefix matching against static pattern dict — for standard model names
3. Unknown → `ModelFamily.UNKNOWN` → fail-closed on independence check

## Consequences
- Fine-tuned models (`ft:gpt-5.2:logicore:2026`) and Azure deployment names need explicit registration via `register_model_family()`
- Unknown family always fails independence check — safe default that blocks potentially biased judging
- Pairwise scoring with position-swap (same phase) catches position bias; family separation catches self-preference bias — two independent safeguards
- When to revisit: if a provider demonstrates no within-family self-preference via independent benchmarks, model-level could suffice
