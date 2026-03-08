---
phase: 7
phase_name: "Resilience Engineering"
date: "2026-03-08"
score: 28/30
verdict: "PROCEED"
---

# Phase 7 Architect Review: Resilience Engineering

## Score: 28/30

| Category | Score | Weight |
|---|---|---|
| Framing Quality | 9/10 | 33% -- are conclusions useful to a CTO? |
| Evidence Depth | 9/10 | 33% -- do benchmarks have enough cases, categories, and boundaries to back the claims? |
| Architect Rigor | 5/5 | 17% -- security model sound, negative tests, benchmarks designed to break things? |
| Spec Compliance | 5/5 | 17% -- was the promise kept? |

## Framing Failures Found

| Where | Junior Framing (current) | Architect Reframe (fix) | Impact |
|---|---|---|---|
| PROGRESS.md quality gate row | "The gate strips whitespace before checking length, preventing padding bypass. Failed quality checks count as provider failures in the circuit breaker." | "The gate strips whitespace AND 6 Unicode invisible characters (U+200B, U+FEFF, U+200C, U+200D, U+00AD, U+2060) before checking length. Python's str.strip() does NOT handle these -- a provider returning zero-width spaces passes the naive length check. Discovered and fixed during review gap analysis." | MEDIUM -- PROGRESS.md still reflects the pre-fix state. The quality gate section claims `content.strip()` handles Unicode zero-width characters, which was the exact bug found in the first review. The tracker is correct; PROGRESS.md is stale. |
| PROGRESS.md red team section | "17 Tests, 6 Attack Categories" (header) / "Whitespace stripping before length check" (quality gate bypass row) | Should read "24 Tests, 7 Attack Categories" and the quality gate bypass row should mention explicit Unicode invisible char stripping, not just whitespace stripping. | LOW -- PROGRESS.md was not updated after gap fixes added 7 Unicode bypass tests and the degraded governance tests. Tracker is correct but PROGRESS.md still describes the pre-review state. |
| PROGRESS.md test counts | "148 new tests, 1165 total" | Should be "167 new tests, 1199 total" after gap fixes (20 new tests added). | LOW -- stale count, tracker is correct. |

## Evidence Depth Failures Found

| Claim | Cases (n) | Credible? | Missing Categories | Boundary Found? | Phase Teaser |
|---|---|---|---|---|---|
| Circuit breaker state machine works | 44 | YES | -- | YES: concurrent HALF_OPEN transitions tested (50 concurrent). Edge cases: threshold=1, success_threshold=1, rapid open/close cycles. | -- |
| Retry backoff with jitter prevents thundering herd | 21 + 2 red team | YES | -- | YES: 100 draws produce >20 unique values. Bounds proven [0, calculated_delay]. Monotonic backoff without jitter proven. | -- |
| ProviderChain failover works | 18 | YES | -- | YES: 3-provider cascade, cache miss + raise, cache error + raise. | -- |
| Quality gate catches 200-OK-garbage | 11 + 12 red team | YES | -- | YES: exact boundary (min_length-1 fails, min_length passes). 6 Unicode invisible chars. Mixed invisible + whitespace. Real content with embedded ZWSP passes. | -- |
| Cost model: 83.5% savings at 70/20/10 | 8 sensitivity tests | YES | Could test non-uniform distributions where simple/medium split varies (e.g., 60/30/10 vs 70/20/10 both have 10% complex but different savings) | YES: crossover at ~90% complex. Monotonicity proven across 11 distribution points. | Phase 12: validate assumed 70/20/10 against real query distribution from production logs. |
| Degraded mode blocks financial auto-approve | 5 governance tests | YES (barely) | No test for PARTIAL degradation (e.g., fallback works but with degraded quality, not fully down). Governance function is defined inline in the test, not in production code -- proves the CONTRACT but not the integration. | PARTIAL: proves the flag contract works, but the actual governance function lives in the test, not in Phase 3's HITL gateway. | Phase 8/12: wire is_degraded into Phase 3's actual HITL gateway and Phase 8's compliance engine. |
| Failover time <100ms | 3 outage simulation tests | YES (conceptual) | This is an architectural claim, not a measured latency. The tests prove the breaker trips and chain falls back, but don't measure actual failover latency under realistic conditions. | NO: no latency measurement. The <100ms claim is logical (skip a tripped breaker = no network call) but not empirically proven. | Phase 12: measure actual failover latency with real Azure + Ollama under simulated outage. |
| Per-provider isolation prevents cascade | 2 red team tests | YES (minimal) | Two tests is thin for a cascade isolation claim. Could add: 3+ providers where middle provider fails, N providers with interleaved failures, shared-vs-independent breaker comparison. | YES: Azure failure leaves Ollama untouched. | -- |
| Concurrent safety (50 concurrent requests) | 2 tests | YES | -- | YES: 50 concurrent requests during HALF_OPEN, all succeed or get CircuitOpenError. | Phase 10: load testing under sustained concurrent traffic. |
| Unicode invisible char bypass blocked | 7 red team tests | YES | Could test additional Unicode categories: RTL override (U+202E), Hangul filler (U+3164), Mongolian vowel separator (U+180E). | PARTIAL: 6 specific chars covered. Not exhaustive of all Unicode invisible categories. | Phase 10 (LLM Firewall): comprehensive Unicode normalization across all invisible character categories. |

## What a CTO Would Respect

The cost model sensitivity analysis is genuinely impressive. Rather than presenting a single headline number (83.5% savings), the team stress-tested across 6 distributions, found the exact crossover point (~90% complex), and proved monotonicity. A CTO can look at their actual query mix and immediately know their savings. The quality gate fix for Unicode zero-width characters shows the review process works -- a gap was found, code was fixed, tests were added, and the fix is structurally sound (explicit character stripping, not regex or heuristics).

## What a CTO Would Question

The <100ms failover claim is architectural reasoning, not measured latency. A CTO running a logistics company where the spec estimates EUR 180,000 per undetected temperature spike would want to see actual timing data from a simulated outage, not just "we skip a tripped breaker so it must be fast." The degraded mode governance tests prove the contract (is_degraded flag exists and works) but the governance function is defined inline in the test file, not wired into Phase 3's actual HITL gateway -- a CTO would ask "yes, but does your invoice auditor actually check this flag?" The answer is "Phase 8/12 wires it" which is honest, but it means the claim is about the API contract, not the end-to-end behavior.

## Architect Rigor Checklist

| Check | Status | Note |
|---|---|---|
| Security/trust model sound | PASS | Per-provider circuit breakers prevent cascade. Cache is read-only callback (no write injection). Excluded exceptions prevent breaker manipulation via 4xx. Quality gate catches invisible char bypass. Bounded O(1) state prevents resource exhaustion. |
| Negative tests | PASS | 24 red team tests across 7 attack categories. Tests prove what the system REFUSES to do: breaker manipulation, thundering herd, cache RBAC bypass, provider exhaustion, quality gate bypass (whitespace + Unicode), retry abuse, cascading failure. |
| Benchmarks designed to break | PASS | Cost model sensitivity finds the crossover point. Quality gate boundary tests (min_length-1 fails). Concurrent HALF_OPEN races. Rapid open/close cycles. Unicode invisible chars. |
| Test pyramid | PASS | 167 unit tests, 0 integration (deferred to Phase 12 with reasoning), 0 e2e. All unit tests are fast (~6s). Integration test deferral is documented: requires both Azure and Ollama running simultaneously. |
| Spec criteria met | PASS | All success criteria checked. Circuit breaker transitions, failover, cache fallback, model routing, cost reduction (83.5% > spec's 50%), jitter, response metadata. Langfuse tracing deferred to Phase 12 (documented). |
| Deviations documented | PASS | 3 deviations documented with reasoning: no separate model_router.py (reuses Phase 4), no integration test (requires dual providers), ProviderChainResponse as frozen dataclass (consistency). |

## Benchmark Expansion Needed

1. **Failover latency measurement** -- Add timing instrumentation to the outage simulation. Measure wall-clock time from "primary fails" to "fallback response received." Expected: <100ms for breaker skip, <5s including retry exhaustion. Mapped to Phase 12 (full stack demo with real providers).

2. **Degraded mode integration** -- Test is_degraded flag through Phase 3's actual HITL gateway, not a governance function defined in the test. Expected: invoice audit with is_degraded=True routes to human review. Mapped to Phase 8/12 (compliance engine wiring).

3. **Unicode normalization completeness** -- Test additional Unicode invisible categories: RTL override (U+202E), interlinear annotation (U+FFF9-FFFB), Hangul filler (U+3164), variation selectors (U+FE00-FE0F). Expected: all stripped before length check. Mapped to Phase 10 (LLM Firewall -- comprehensive input sanitization).

4. **Real query distribution validation** -- The cost model assumes 70/20/10. Measure actual distribution from production query logs to validate the assumption. If reality is 40/30/30, savings drop to ~55%. Mapped to Phase 12 (full stack demo with production-like corpus).

## Gaps to Close

1. **PROGRESS.md is stale after gap fixes (LOW).** The sprint summary still says "148 new tests, 1165 total" and describes the quality gate as using `content.strip()` for Unicode. Update to reflect 167 tests, 1199 total, and the explicit Unicode char stripping fix. Update red team section from "17 tests, 6 categories" to "24 tests, 7 categories." This is a doc update, not a code change.

2. **Tracker test count discrepancy (COSMETIC).** Tracker lists individual file counts summing to 168, but actual collected tests are 167. One test was likely renamed or merged. Update the tracker table to match reality.

3. **Degraded governance function lives in test, not production code (NOTED -- Phase 8/12).** The `should_auto_approve()` and `is_safe_for_financial_decision()` functions are defined inline in `test_degraded_mode.py`. They prove the is_degraded contract works, but the actual integration with Phase 3's HITL gateway is deferred. This is honest and correctly scoped -- Phase 7 builds the resilience infrastructure, downstream phases consume it.

## Architect Recommendation: PROCEED

The gap fixes from the first review are substantive and well-executed:

**Cost model sensitivity (was HIGH):** 8 parameterized tests across 6 distributions with proven crossover point and monotonicity. This transforms the 83.5% headline from a single-scenario anecdote into a validated model a CTO can trust with their actual query distribution. The crossover finding (~90% complex) is content gold: "Routing saves money in every realistic scenario. The only distribution where it doesn't help is 90%+ complex queries -- and if 90% of your queries require GPT-5.2, your problem isn't routing, it's prompt engineering."

**Unicode zero-width bypass (was MEDIUM):** Code fix is clean -- explicit character stripping in `_INVISIBLE_CHARS`, not a regex or Unicode category check. 7 tests cover the 6 specific chars plus mixed combinations plus the critical false-positive check (real content with embedded ZWSP passes). The docstring explicitly calls out that `str.strip()` does NOT handle these characters, which is the kind of knowledge that distinguishes architects from developers.

**Degraded mode downstream (was LOW):** 5 governance tests prove the contract pattern. The decision to test the contract (is_degraded flag) rather than the full integration (Phase 3's HITL gateway) is correctly scoped. Phase 7 builds resilience infrastructure; Phase 8/12 wires it into compliance and financial decision flows.

**Tracker framing (was LOW):** Metrics are now reframed with architect context. "100% detection" replaced with explanation of WHY 200-OK-garbage is the silent killer. Failover time explained against manual MTTR. Concurrent safety explained against split-brain risk.

The two remaining gaps (stale PROGRESS.md, off-by-1 test count) are documentation synchronization issues that do not affect architect credibility or the technical story. The phase is solid and ready for content.
