# Phase 5 Tracker: Assessment Rigor — Judge Bias, Drift Detection & Prompt Caching

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-5-evaluation-rigor.md`
**Depends on**: Phase 4

## Implementation Tasks

- [ ] `apps/api/src/telemetry/quality_pipeline.py` — pairwise scoring, position-randomized
- [ ] `apps/api/src/telemetry/judge_config.py` — judge model selection, bias settings
- [ ] `apps/api/src/telemetry/drift_detector.py` — automated regression + alerting
- [ ] `apps/api/src/telemetry/model_registry.py` — track model versions + baselines
- [ ] `apps/api/src/telemetry/prompt_optimizer.py` — static-first prompt restructuring
- [ ] `apps/api/src/infrastructure/llm/cache.py` — MODIFY: prompt-level caching metrics
- [ ] `scripts/calibrate_judge.py` — human vs LLM judge correlation
- [ ] `scripts/run_drift_check.py` — weekly regression suite
- [ ] `tests/quality/test_judge_bias.py` — position + verbosity bias detection
- [ ] `tests/quality/test_drift_detection.py` — model version change simulation

## Success Criteria

- [ ] Pairwise scoring detects and eliminates position bias
- [ ] Judge model != generator model (configurable)
- [ ] Human calibration: Spearman correlation > 0.85
- [ ] Drift detector catches simulated model version change within 1 hour
- [ ] Regression suite alerts on >5% score drop
- [ ] Prompt restructuring achieves >60% cache hit rate
- [ ] Cost reduction from caching measured and dashboarded

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Judge model | different from generator | | |
| Position bias mitigation | run twice, swap order | | |
| Drift threshold | 5% score drop | | |
| Prompt cache strategy | static-first ordering | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Position bias detection rate | | % of tests showing bias |
| Human-judge Spearman correlation | | 0-1 |
| Drift detection latency | | time to alert after model change |
| Prompt cache hit rate (before) | | % |
| Prompt cache hit rate (after) | | % |
| Cost savings from prompt caching | | EUR/day |
| Regression suite pass rate | | % |
| False positive rate (drift alerts) | | % |

## Screenshots Captured

- [ ] Position bias test results (swapped order scores)
- [ ] Human vs judge correlation scatter plot
- [ ] Drift detection alert
- [ ] Prompt cache hit rate dashboard
- [ ] Cost savings chart

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
