---
phase: 4
date: "2026-03-08"
selected: A
---

# Phase 4 Implementation Approaches

## Context

Phase 4 has 5 major components: (1) Langfuse observability, (2) semantic caching, (3) cost tracking/FinOps, (4) LLM-as-Judge evaluation, (5) model routing. The approaches differ primarily on the **cache strategy** and **routing strategy** — the two highest-risk, highest-value components. Langfuse integration and cost tracking are straightforward regardless of approach.

## Approach A: Semantic Vector Cache + LLM Router (Full Spec)

**Summary**: Redis Stack with RediSearch for vector similarity matching. RBAC + entity partitioning in cache keys. LLM-based model routing (GPT-5 nano classifier) with keyword overrides for financial terms. Full spec implementation.

**Pros**:
- Highest cache hit rate (~35%) — catches semantically similar but differently worded queries
- Matches the spec exactly — all success criteria met
- Model routing via LLM handles edge cases better than static rules
- Best content story ("93% cost reduction via intelligent routing + semantic caching")

**Cons**:
- Requires Redis Stack (not standard Redis) — infrastructure change
- False match risk: 0.95 cosine threshold can match cross-client queries without entity extraction
- Entity extraction adds ~EUR 0.0001/query overhead and complexity
- More failure modes to test (threshold tuning, entity extraction accuracy, cache poisoning)
- Redis Stack vector search performance at scale needs benchmarking

**Effort**: L (~5-7 days)
**Risk**: Cache false matches serving wrong client data (EUR 3,240/incident). Mitigated by entity-aware partitioning but adds complexity.

## Approach B: Deterministic Cache + Rule-Based Router (Pragmatic)

**Summary**: Normalize queries (lowercase, strip whitespace, sort tokens) → SHA-256 hash → exact match lookup. RBAC context (clearance + department) concatenated before hashing. Rule-based model routing with keyword lists (no LLM classifier). Standard Redis — no Redis Stack needed.

**Pros**:
- **Zero false match risk** — different query = different hash, full stop
- No entity extraction needed — RBAC safety is structural (different context = different hash)
- Works with standard Redis (no infrastructure change)
- Simpler to test, debug, and explain to a CTO
- Deterministic — no similarity threshold to tune
- Rule-based routing: keyword lists are auditable, no LLM classification cost

**Cons**:
- Lower hit rate (~15-20%) — only catches exact (normalized) query matches, misses paraphrases
- "What's PharmaCorp's penalty?" and "PharmaCorp delivery penalty rate?" are different hashes = cache misses
- Rule-based routing misses nuanced complexity (but keyword override catches financial terms)
- Less impressive content story (no "semantic" angle)

**Effort**: M (~3-4 days)
**Risk**: Lower cache savings (EUR 12/day vs EUR 22/day). No security risk from cache.

## Approach C: Tiered Cache — Deterministic Base + Semantic Opt-In (Recommended)

**Summary**: Two-tier cache system. Tier 1: deterministic hash cache for ALL queries (safe, always on). Tier 2: semantic vector similarity ONLY for queries tagged `cacheable: true` AND `sensitive: false` (non-RBAC, non-financial, non-personalized). Financial/compliance/RBAC queries NEVER enter the semantic tier. Rule-based routing with keyword overrides (same as B).

**Pros**:
- **Safe by default** — deterministic tier handles all sensitive queries with zero false-match risk
- Higher total hit rate than B (~25-30%) — semantic tier catches paraphrases for safe queries
- No entity extraction needed — sensitive queries never enter semantic matching
- Best architect story: "We don't just cache — we know WHAT to cache and WHAT to protect"
- Demonstrates the architect's "when NOT to do X" thinking
- Rule-based routing: auditable, deterministic, zero overhead

**Cons**:
- Two cache tiers = more code than either A or B alone
- Needs Redis Stack for the semantic tier (Tier 2)
- Query classification (`cacheable` + `sensitive` flags) needs careful design
- Testing both tiers doubles cache test surface

**Effort**: L (~5-6 days)
**Risk**: Moderate. Semantic tier only serves non-sensitive queries, so worst-case false match is a wrong general answer (not a data leak). Deterministic tier is risk-free.

## Recommendation

**Approach C** — because it demonstrates the architect's core skill: knowing when to apply which tool. A CTO doesn't want to hear "we cached everything" — they want to hear "we cached safe queries semantically for 30% hit rate, and we structurally prevented sensitive queries from EVER entering similarity matching."

The two-tier design also sets up Phase 5 (evaluation rigor) cleanly — the semantic tier's hit rate and false-match rate become measurable quality metrics.

However, Approach B is the right fallback if time is tight — it ships the full observability + cost tracking + evaluation pipeline without the semantic cache complexity, and cache can be upgraded to tiered later.

## Selected: Approach A

User selected Approach A (Full Semantic Vector Cache + LLM Router). Quality is top priority — implement full spec with Redis Stack vector cache, RBAC + entity-aware cache partitioning, LLM-based model routing with keyword overrides, Langfuse integration with PostgreSQL fallback, and comprehensive LLM-as-Judge evaluation pipeline. No shortcuts.
