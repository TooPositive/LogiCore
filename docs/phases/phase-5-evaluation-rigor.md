# Phase 5: "Assessment Rigor" — Judge Bias, Drift Detection & Prompt Caching

## Business Problem

Phase 4 gave us observability — we can see what the AI is doing. But can we trust our own quality scoring? LLM-as-Judge has known biases (verbosity bias, position bias, self-preference). Meanwhile, Azure silently updates model versions and nobody notices until retrieval quality drops. And we're paying full price for identical prompt prefixes on every single request.

**CTO pain**: "Our quality score says 0.92. But is the scoring itself reliable? And why did costs spike 30% last Tuesday?"

## Architecture

```
Quality Pipeline (enhanced)
  ├── Pairwise Comparison (A vs B, randomized position)
  │     └── Judge Model != Generator Model (eliminates self-preference)
  ├── Position Bias Mitigation
  │     └── Run each test twice with swapped order, average scores
  ├── Human Calibration Baseline
  │     └── 50 examples scored by human, correlation check against judge
  └── Confidence Intervals
        └── Bootstrap sampling on scores, report CI not just mean

Drift Detection
  ├── Baseline Registry (model version -> quality scores)
  ├── Weekly Regression Suite (automated, 100+ test cases)
  ├── Alerting: score drop > 5% -> Slack/email alert
  └── Model Version Tracker (detect silent updates)

Prompt Caching
  ├── Static-First Prompt Structure
  │     └── System prompt + tool defs + few-shot (static, cached)
  │     └── Retrieved chunks + user query (dynamic, last)
  ├── Anthropic/OpenAI prompt cache tracking
  └── Cost dashboard: cache hit rate, savings per day
```

**Key design decisions**:
- Never use the same model as judge and generator — eliminates self-preference bias
- Pairwise comparison is more reliable than absolute scoring for LLM judges
- Drift detection is automated and continuous — not a quarterly review
- Prompt structure follows cache-friendly ordering (static prefix first)

## Implementation Guide

### Prerequisites
- Phase 4 complete (Langfuse tracing, semantic caching, basic quality checks)
- 50+ human-scored examples for calibration
- Test dataset with known-good answers

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/telemetry/quality_pipeline.py` | Enhanced scoring: pairwise, position-randomized |
| `apps/api/src/telemetry/judge_config.py` | Judge model selection, bias mitigation settings |
| `apps/api/src/telemetry/drift_detector.py` | Automated regression testing + alerting |
| `apps/api/src/telemetry/model_registry.py` | Track model versions + baseline scores |
| `apps/api/src/telemetry/prompt_optimizer.py` | Static-first prompt restructuring + cache tracking |
| `apps/api/src/infrastructure/llm/cache.py` | **Modify** — add prompt-level caching metrics |
| `scripts/calibrate_judge.py` | Compute correlation between LLM judge and human scores |
| `scripts/run_drift_check.py` | Weekly regression suite (cron-able) |
| `tests/quality/test_judge_bias.py` | Position bias and verbosity bias detection tests |
| `tests/quality/test_drift_detection.py` | Model version change simulation tests |

### Technical Spec

**Pairwise Scoring (bias-mitigated)**:
```python
async def pairwise_score(query: str, answer_a: str, answer_b: str) -> str:
    """Run twice with A/B swapped, requires agreement for valid result."""
    # Round 1: A first, B second
    result_1 = await judge.compare(query, first=answer_a, second=answer_b)
    # Round 2: B first, A second (detects position bias)
    result_2 = await judge.compare(query, first=answer_b, second=answer_a)

    if result_1.winner != opposite(result_2.winner):
        return "inconclusive"  # position bias detected
    return result_1.winner
```

**Drift Detection**:
```python
class DriftDetector:
    async def check_regression(self):
        """Run 100+ test cases, compare against baseline."""
        current_scores = await self.run_test_suite()
        baseline = await self.registry.get_baseline(self.current_model_version)

        for metric, score in current_scores.items():
            delta = score - baseline[metric]
            if delta < -0.05:  # 5% drop threshold
                await self.alert(metric, baseline[metric], score, delta)

    async def detect_version_change(self):
        """Check if model deployment version changed since last run."""
        current = await self.get_model_version()  # API header inspection
        if current != self.registry.last_known_version:
            await self.alert_version_change(current)
            await self.check_regression()  # auto-trigger regression
```

**Prompt Cache Optimization**:
```python
# WRONG: dynamic content first (breaks cache prefix)
prompt = f"""Context: {retrieved_chunks}
User question: {query}
You are a logistics AI assistant..."""

# RIGHT: static content first (maximizes cache hits)
prompt = f"""You are a logistics AI assistant...
[tool definitions - static]
[few-shot examples - static]
[RBAC rules - session-stable]
---
Context: {retrieved_chunks}
User question: {query}"""
```

### Success Criteria
- [ ] Pairwise scoring detects and eliminates position bias
- [ ] Judge model != generator model (configurable)
- [ ] Human calibration: Spearman correlation > 0.85 between judge and human scores
- [ ] Drift detector catches simulated model version change within 1 hour
- [ ] Regression suite runs automatically, alerts on >5% score drop
- [ ] Prompt restructuring achieves >60% cache hit rate
- [ ] Cost reduction from prompt caching measured and dashboarded

## LinkedIn Post Angle
**Hook**: "Your LLM-as-Judge is biased. Here's how we proved it — and fixed it."
**Medium deep dive**: "We Found 3 Hidden Biases in Our AI Quality Pipeline. Position bias, verbosity bias, and self-preference were silently inflating our scores."

## Key Metrics to Screenshot
- Position bias test: same test with swapped order showing different scores
- Human vs LLM judge correlation scatter plot
- Drift detection alert: model version change triggers automatic regression
- Prompt cache hit rate dashboard (before/after restructuring)
- Cost savings chart from prompt caching
