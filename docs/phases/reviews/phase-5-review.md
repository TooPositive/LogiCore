---
phase: 5
phase_name: "Assessment Rigor -- Judge Bias, Drift Detection & Prompt Caching"
date: "2026-03-08"
score: 29/30
verdict: "PROCEED"
---

# Phase 5 Architect Review: Assessment Rigor -- Judge Bias, Drift Detection & Prompt Caching

## Score: 29/30

| Category | Score | Weight |
|---|---|---|
| Framing Quality | 10/10 | 33% |
| Evidence Depth | 9/10 | 33% |
| Architect Rigor | 5/5 | 17% |
| Spec Compliance | 5/5 | 17% |

## Re-Review: Gap Closure Verification

This is a re-review after 5 gaps were identified in the first review (27/30). Each gap is verified below.

| Gap | Status | Evidence |
|---|---|---|
| 1. Verbosity bias threshold configurable | CLOSED | `verbosity_length_ratio` parameter on `BiasDetector.__init__()`. 5 dedicated tests in `TestVerbosityThresholdConfigurability`: default 1.5x, lower 1.2x for legal domains, higher 2.0x for strict filtering, legal domain scenario, verbose-but-correct not flagged. Implementation on line 159 of quality_pipeline.py. |
| 2. Fine-tuned model family support | CLOSED | `register_model_family()` + `clear_family_overrides()` + `_EXACT_FAMILY_OVERRIDES` dict in judge_config.py. Resolution order: exact-match first, then prefix, then UNKNOWN. 11 dedicated tests in `TestFineTunedModelFamily`: ft:gpt, Azure deployment, Ollama, registration, independence pass/fail, case insensitive, exact-override priority, clear restores default. |
| 3. Golden set data artifact | CLOSED | `data/golden_set.json` exists: 50 entries, 10 categories, scores 2-5, schema header with maintenance instructions. 6 validation tests in `TestGoldenSetArtifact`: exists, 50 entries, schema, score range, category coverage (all 10), score variance (at least 3 unique scores). Scorer notes explain reasoning per entry. |
| 4. Mixed-signal judge tests | CLOSED | `TestMixedSignalJudge` class with 5 scenarios: factual-unbiased/subjective-biased, complex-only verbosity bias, 70% partial self-preference, full mixed-signal report, query-type-specific detection rate. Tests prove detection works with non-uniform bias (the realistic case). |
| 5. Large-scale 100+ metric regression tests | CLOSED | `TestLargeScaleRegressionSuite` class with 5 scenarios: 100 metrics mixed drift (5 RED, 10 YELLOW, 85 GREEN = exactly 15 alerts), 100 all improved (0 alerts), 100 all red (100 alerts), cancelling-out metrics still fire individual alerts, per-metric alert naming. Plus `TestSpearmanHeavilyTied` with 4 scenarios: heavily tied, all tied (returns 0.0), binary clusters, realistic golden set distribution. |

All 5 gaps are verifiably closed with implementation code and dedicated tests.

## Framing Audit

### A. "So What?" Test

| Conclusion | Passes? | Notes |
|---|---|---|
| "Position bias detection rate 100%" | PASS | Framed as: "the pairwise scorer catches EVERY position-biased judge. Running twice with swap costs 2x per eval but eliminates the most common LLM judge failure mode. At EUR 0.022/eval vs EUR 0.011/eval, the 2x cost buys trustworthy scores." Actionable: tells CTO the cost of the mitigation and the cost of not doing it. |
| "Family-level check is critical" | PASS | Framed as: "GPT-5-mini judging GPT-5.2 = same OpenAI family = 10-15% score inflation. The check costs EUR 0.00 (just a string prefix match) but changes which model you use as judge." Zero-cost decision with high impact. |
| "Three-tier severity enables graduated response" | PASS | Framed as graduated ops playbook: "green=ignore, yellow=investigate, red=halt." Tells ops team exactly what to do at each level. Includes blast radius math (weekly=7-day, daily=1-day). |
| "RBAC partitioning is the honest limiter on cache hit rate" | PASS | Directly contradicts the spec's 60% claim with honest numbers: single-tenant 55-65%, multi-tenant 15-25%. Recommendation: "optimize within-partition hit rate, accept that cross-partition sharing is structurally impossible without RBAC bypass." CTO knows exactly what to expect. |
| "Bootstrap CI exposes whether your eval dataset is large enough" | PASS | Framed as: "A score of 0.89 +/- 0.04 is trustworthy. A score of 0.83 +/- 0.09 might be below the 0.80 gate." Directly actionable: if CI is wide, add more examples. |

### B. "Real Users" Test

Phase 5 users: operations teams monitoring quality, DevOps running drift checks, architects choosing judge models. The framing addresses all three: ops teams get graduated severity, DevOps gets cron-compatible scripts with exit codes, architects get decision frameworks for judge model selection and pairwise vs single-pass tradeoffs.

### C. "Wrong Decision" Test

No conclusions lead to wrong decisions. The RBAC-cache honesty is particularly strong -- a CTO following the spec's 60% claim would over-promise savings. The tracker explicitly corrects this. The family-level separation recommendation prevents the most common judge configuration mistake (same-provider judging).

### D. "Irrelevant Metric" Test

No irrelevant metrics found. Every metric maps to a specific decision:
- Position bias rate -> whether to use pairwise (2x cost)
- Self-preference rate -> which model family to use as judge
- Cache hit rate -> expected savings by deployment type
- Drift severity thresholds -> ops response playbook
- Bootstrap CI width -> whether to trust the quality gate

### E. "Missing Recommendation" Test

Every comparison ends with a recommendation + condition for when it changes:
- Pairwise: "Yes for CI gates, No for daily monitoring"
- Judge model: "Claude Sonnet for standard evals, Opus for compliance-critical"
- Drift frequency: "Daily for production, weekly for development"
- Cache optimization: "Do it regardless -- the optimization is free even if hit rates are lower than expected"

### F. "Cost of the Wrong Choice" Test

Quantified throughout:
- Wrong judge model: "every quality metric in the system is inflated by 10-15%"
- No drift detection: "EUR 5,600 blast radius per undetected regression (800 queries/day x 14 days x EUR 0.50)"
- Position bias undetected: "10-30% of quality scores are unreliable (published research)"
- Skipping pairwise: "EUR 0.011/eval saved, but one bad PR shipping to production costs more"

## Framing Failures Found

| Where | Junior Framing (current) | Architect Reframe (fix) | Impact |
|---|---|---|---|
| None found | -- | -- | -- |

The framing across tracker, PROGRESS.md, and implementation docstrings is consistently architect-level. Every claim answers "so what?" with a business decision, quantified cost, and condition for change. The RBAC-cache honesty (contradicting the spec's 60% claim) is particularly strong architect behavior -- juniors copy spec claims, architects validate them.

## Evidence Depth Audit

### Test Count Summary

| Area | Tests | Cases per Claim |
|---|---|---|
| Position bias detection | 7 (5 scenarios + 2 mixed-signal) | n=7 |
| Verbosity bias detection | 5 + 5 (threshold config) | n=10 |
| Self-preference detection | 5 + 1 (mixed-signal) | n=6 |
| Drift severity classification | 10 boundary cases | n=10 |
| Regression detection | 7 + 5 (large-scale) | n=12 |
| Version change detection | 3 | n=3 (but these are state transitions, not statistical) |
| Prompt restructuring | 6 | n=6 |
| Cache-friendliness scoring | 6 | n=6 |
| RBAC partition interaction | 6 | n=6 |
| Cost savings calculation | 5 | n=5 |
| Golden set validation | 6 | n=6 (validating 50-entry artifact) |
| Fine-tuned model support | 11 | n=11 |
| Spearman correlation | 9 + 4 (heavily tied) | n=13 |
| Bootstrap CI | 7 | n=7 |
| Mixed-signal judge | 5 | n=5 |
| Large-scale regression (100+) | 5 | n=5 (testing at 100 metric scale) |

### Evidence Depth Failures Found

| Claim | Cases (n) | Credible? | Missing Categories | Boundary Found? | Phase Teaser |
|---|---|---|---|---|---|
| "Position bias detection rate 100%" | n=7 (5 pure + 2 mixed-signal) | YES | Real LLM judges (not mock functions) | Mock-only boundary documented | "Phase 12 live benchmark validates against actual LLM judges" |
| "Verbosity bias detection rate 100%" | n=10 (5 pure + 5 threshold config) | YES | Legitimately verbose correct answers at domain boundaries | Threshold configurability proves awareness | "Phase 8 legal domain will use 1.2x threshold" |
| "Self-preference 0.0-1.0 scaled" | n=6 | YES | Actual LLM cross-provider comparison | Only mock judges tested | "Phase 12 live comparison: Claude judging GPT vs GPT judging GPT" |
| "Three-tier severity correct" | n=10 boundary cases | YES | None -- boundaries thoroughly tested | Exact boundary behavior tested (-0.02, -0.049, -0.05) | N/A |
| "Regression detection multi-metric" | n=12 (7 + 5 at 100-metric scale) | YES | None -- includes aggregation masking test | Cancelling-out test proves per-metric isolation | N/A |
| "Version change immediate" | n=3 | YES* | These are state transitions not statistical claims | N/A -- deterministic | N/A |
| "Cache hit rate: single-tenant 55-65%" | n=6 (partition tests) | YES | Production Redis integration | Structural limitation (RBAC) documented honestly | "Phase 12 Redis Stack integration for production CacheMetrics" |
| "Spearman handles tied scores" | n=13 (9 base + 4 heavily-tied) | YES | Real golden set with actual LLM judge scores | Zero-variance edge case handled (returns 0.0) | "Phase 12 golden set with real human and LLM judge scores" |
| "Bootstrap CI narrow for consistent, wide for variable" | n=7 | YES | Production-scale eval sets (100+ scores) | Minimum sample check (3) tested | N/A |
| "Fine-tuned models fail closed" | n=11 | YES | None | UNKNOWN default = independence check fails = safe | "Phase 6 extends FAMILY_PATTERNS for local models" |
| "Golden set covers 10 categories" | n=50 entries | YES | Judge scores not yet populated (human-only) | Staleness lifecycle documented | "Phase 8 staleness detection, Phase 12 full judge calibration" |
| "100+ metric regression suite" | n=5 scenarios at 100-metric scale | YES | None | Per-metric isolation vs aggregation masking explicitly tested | N/A |

**Key observation**: Zero claims are backed by fewer than 5 cases. The weakest area (version change at n=3) is a deterministic state machine, not a statistical claim -- 3 cases covering all states (same version, different version, unregistered) is sufficient.

**Mock-only limitation**: All bias detection uses synthetic mock judge functions. This is correctly documented as a known limitation with Phase 12 live validation as the fix. The LOGIC is proven at n>=5 per scenario. What remains unproven is whether real LLM judges exhibit the biases at the rates assumed. This is the correct split for Phase 5 (build the detection framework) vs Phase 12 (validate against real judges).

## What a CTO Would Respect

The RBAC-cache honesty is the strongest signal in this phase. The spec claims 60% cache hit rate. The implementation proves that RBAC partitioning structurally limits this to 55-65% single-tenant, 15-25% multi-tenant, and tracks `unique_partitions` as the real fragmentation metric. An architect who corrects their own spec -- with numbers -- earns more trust than one who confirms it. The family-level judge separation (not just model-level) shows the architect understands published self-preference research and translates it into a zero-cost configuration decision.

## What a CTO Would Question

"All your bias detection is tested against mock judges that you wrote to be biased. How do you know a real LLM judge exhibits these biases at the rates you assume?" This is valid and honestly documented -- Phase 12 live benchmark is the answer. The golden set has human scores but no judge scores yet (judge_score fields are not populated in the JSON). Until real judge scores are compared against the 50 human scores, the Spearman correlation claim is a framework, not a measurement. A CTO who asks "show me the actual correlation number" will get "the framework is built and tested, the measurement happens in Phase 12" -- which is defensible for a phased architecture project but would not be defensible for a production deployment claim.

## Architect Rigor Checklist

| Check | Status | Note |
|---|---|---|
| Security/trust model sound | PASS | RBAC partition key MUST be in cache key (tested). Cross-partition sharing structurally impossible. Family-level separation prevents self-preference. Golden set is immutable ground truth. |
| Negative tests | PASS | Same-family judging rejected. Unknown family fails closed. Unregistered model returns empty baseline. Missing metrics ignored (not alerted). Equal-length answers skip verbosity test. All-tied Spearman returns 0.0. |
| Benchmarks designed to break | PASS | Cancelling-out metrics test proves aggregation masking is prevented. Mixed-signal judges prove detection works with non-uniform bias. 100-metric catastrophic regression (all RED) proves no ceiling. Heavily tied Spearman proves robustness under realistic score distributions. |
| Test pyramid | PASS | 198 unit tests, 0 integration (correct -- no external deps needed), 0 E2E (correct -- Phase 5 modules are internal libraries, not API endpoints). Scripts are CLI tools with documented exit codes. |
| Spec criteria met | PASS | All 7 success criteria checked. 1 deviation (cache.py deferred to Phase 12) is documented with reasoning. Cache hit rate claim honestly revised downward. |
| Deviations documented | PASS | 4 deviations documented in tracker: test location, cache.py deferral, cache hit rate revision, verbosity single-pass design. Each has clear reasoning. |

## Benchmark Expansion Needed

These are Phase 12 items. Phase 5's scope (build the detection framework) is complete.

| Category | Example | Expected Outcome | Future Phase |
|---|---|---|---|
| Real LLM judge bias measurement | Run PairwiseScorer with Claude judging GPT-5.2 on 50 golden set entries, swap positions | Measure actual position bias rate (literature suggests 10-30%) | Phase 12 |
| Cross-provider self-preference | GPT-5-mini judging GPT-5.2 output vs Claude judging GPT-5.2 output on same 50 entries | Quantify actual self-preference inflation at family level | Phase 12 |
| Golden set judge calibration | Run calibrate_judge.py against data/golden_set.json with real LLM judge scores populated | Actual Spearman correlation number (target >0.85) | Phase 12 |
| Production drift simulation | Deploy run_drift_check.py on cron, simulate Azure model version change | End-to-end detection latency and alert delivery | Phase 12 |
| Prompt cache hit rate measurement | Track CacheMetrics in production with real RBAC partitions across 5 clients | Actual multi-tenant hit rate (hypothesis: 15-25%) | Phase 12 |

## Gaps to Close

1. **Golden set judge_score population** -- The 50-entry golden set has human scores but no judge scores. The calibrate_judge.py script expects a `judge_score` field per entry. This is correct for Phase 5 (human scores are the ground truth), but the Phase 12 live benchmark should populate judge scores and run actual calibration. Not a blocker -- it is a Phase 12 deliverable explicitly.

2. **Tracker test count mismatch** -- The tracker says "162 tests" but the actual count is 198 (36 new tests added for gap closure). The tracker should be updated to reflect the current count. Minor documentation issue.

## Architect Recommendation: PROCEED

Phase 5 delivers a complete evaluation reliability framework across all three pillars:

**Pillar 1 (Judge Bias)**: Position, verbosity, and self-preference detection with injectable judge functions, configurable thresholds, and pairwise position-swap agreement. Family-level separation (not just model-level) costs EUR 0.00 and eliminates the most common judge configuration mistake. Mixed-signal detection proves the framework handles realistic non-uniform bias. Golden set artifact (50 entries, 10 categories, scores 2-5) provides immutable ground truth.

**Pillar 2 (Drift Detection)**: Three-tier severity with per-metric alerting prevents both alert fatigue (single-threshold) and aggregation masking (average-based). 100+ metric regression tests prove the system scales. Version change detection is O(1). Extensible AlertHandler protocol supports Slack/email/PagerDuty without changing detection logic.

**Pillar 3 (Prompt Caching)**: Static-first restructuring is the right optimization and it is free. The honest RBAC-partition analysis (contradicting the spec's 60% claim) is the strongest architect signal in the phase. CacheMetrics tracks `unique_partitions` as the real fragmentation metric, not just global hit rate.

The mock-only limitation on bias detection is correctly scoped: Phase 5 proves the detection logic works (n>=5 per scenario, mixed-signal tests, heavily-tied Spearman). Phase 12 validates against real LLM judges. This is the correct phasing for a 12-phase architecture project.

198 tests. 867 total project tests. 0 failures. 0 regressions. All 5 gaps from the first review are verifiably closed with both implementation and dedicated tests.
