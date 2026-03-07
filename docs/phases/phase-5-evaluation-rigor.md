# Phase 5: "Assessment Rigor" — Judge Bias, Drift Detection & Prompt Caching

## Business Problem

Phase 4 gave us observability — we can see what the AI is doing. But can we trust our own quality scoring? LLM-as-Judge has known biases (verbosity bias, position bias, self-preference). Meanwhile, Azure silently updates model versions and nobody notices until retrieval quality drops. And we're paying full price for identical prompt prefixes on every single request.

**CTO pain**: "Our quality score says 0.92. But is the scoring itself reliable? And why did costs spike 30% last Tuesday?"

## Real-World Scenario: LogiCore Transport

**Feature: Quality Scoring Validation & Cost Optimization**

The quality dashboard from Phase 4 says "Context Precision: 0.92." But can we trust that number?

**Position bias test**: Show the LLM judge two answers to "What's PharmaCorp's delivery penalty?" Answer A is correct (15%), Answer B is wrong (10%). When A is shown first, judge picks A. Swap the order — judge STILL picks whichever is shown first. That's position bias inflating our scores. Fix: run every comparison twice with swapped order, require agreement.

**Drift detection scenario**: Tuesday morning, Azure silently updates GPT-5.2 from version 2026-0301 to 2026-0415. Nobody notices. Wednesday, the invoice audit workflow starts miscalculating discrepancy amounts — the new model rounds differently. Thursday, the drift detector runs its weekly regression suite: 100+ test cases against the baseline. Precision dropped from 0.92 to 0.84. Alert fires to Slack: "Model version change detected: gpt-5.2-2026-0301 → gpt-5.2-2026-0415. Regression: context_precision -8.7%."

**Prompt caching savings**: Every RAG query starts with the same 2,000-token system prompt (role definition, tool descriptions, few-shot examples). Before optimization, this prefix is recomputed on every request. After restructuring prompts (static content first, dynamic content last), Azure's prompt cache kicks in: 60% cache hit rate, saving €22/day.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| LLM-as-Judge bias mitigation | Quality scores you can actually trust | "0.92 precision" means 0.92, not inflated by scoring bugs |
| Pairwise comparison | Two answers scored head-to-head, not on absolute scale | More reliable than asking "rate this 1-10" |
| Drift detection | Alert: "Model changed, quality dropped 8.7%" | Catch silent provider changes before they hit production users |
| Model version registry | Dashboard showing which model version is serving | Know exactly what's running — no "it worked yesterday" mysteries |
| Prompt caching (static-first structure) | 60% reduction in prompt processing costs | Same answers, lower bill — pure efficiency |

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

## Cost of Getting It Wrong

The evaluation pipeline is the system's immune system. When it's wrong, EVERYTHING is wrong.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Position bias inflates quality** | Judge consistently prefers first option. CI gate passes at 0.92. Real score: 0.88. Below threshold. Degraded code ships. | EUR 2,000-20,000 in accumulated wrong decisions over 2 weeks | 1-2/year |
| **7 days of wrong audits** | Azure silently updates GPT-5.2. Drift detector runs weekly. System runs degraded Mon→Sun. 50 audits/day × 7 days = 350 potentially wrong audits. | EUR 1,000-5,000/week | 2-4/year (model updates ~quarterly) |
| **Judge evaluates with wrong ruler** | Model update changes the JUDGE too. Comparing old baseline (scored by old judge) vs new results (scored by new judge) = apples-to-oranges. Drift appears worse or better than reality. | Unreliable quality metrics across entire system | On every model update |
| **Ground truth drifts** | 10% of evaluation dataset answers are outdated (contracts amended). Quality gate approves bad PRs, blocks good ones. | EUR 5,000-20,000/year in wrong gate decisions | Continuous without maintenance |

**The CTO line**: "Our quality score says 0.92. If that number is wrong, every decision we've made about model choice, caching thresholds, and deployment gates is wrong too. The evaluation pipeline is the most important code in the system — it validates everything else."

### Who Watches the Watchmen?

Phase 5 validates Phases 1-4. If the judge is biased:
- Phase 4's dashboard numbers are wrong → CTO sees false metrics
- Phase 2's retrieval benchmarks are inflated → wrong model/threshold choices
- Phase 3's audit accuracy claims are unverified → false confidence in financial decisions

**Mitigation**: Store a human-scored "golden set" (50 query-answer pairs scored by domain expert). This never changes regardless of model versions. Compare against this as the ultimate ground truth. If judge-golden correlation drops below 0.85, halt all automated quality gates until recalibrated.

### Blast Radius Calculation

When a bad PR passes the quality gate, how much damage before detection?

```
Queries/day × days-to-detect × cost-per-wrong-answer = blast radius

800 queries/day × 14 days (next weekly eval) × EUR 0.50/wrong-answer = EUR 5,600
```

Reducing drift detection from weekly to daily cuts blast radius by 7x. Continuous sampling (5% of production queries) cuts it to hours.

## Decision Framework: Judge Model Selection

Not all evaluations need the most expensive judge. Match the judge model to the evaluation complexity.

### Decision Tree

```
Evaluation task
  │
  ├── Simple correctness check (is the answer factually right?)
  │     └── GPT-5 mini ($0.25/$2.00 per 1M) — sufficient for binary right/wrong
  │
  ├── Standard evaluation (faithfulness, relevancy, precision scoring)
  │     └── GPT-5.2 ($1.75/$14.00 per 1M) — good reasoning, cost-effective for most evals
  │
  ├── High-stakes evaluation (compliance, legal, audit-grade scoring)
  │     └── Claude Opus 4.6 ($5.00/$25.00 per 1M) — highest quality, strongest reasoning
  │
  └── Pairwise comparison (A vs B head-to-head)
        └── 2x the cost of single-pass (run twice with swapped positions)
        └── Use GPT-5.2 for standard, Claude Opus 4.6 for compliance-critical
```

### Cost of Evaluation Strategies

| Strategy | Judge Model | Calls per Eval | Cost per Eval (avg 2K input + 500 output tokens) | Monthly (100 evals/day) |
|---|---|---|---|---|
| Single-pass scoring | GPT-5 mini | 1 | €0.0015 | €4.50 |
| Single-pass scoring | GPT-5.2 | 1 | €0.011 | €33 |
| Pairwise comparison | GPT-5.2 | 2 | €0.022 | €66 |
| Single-pass scoring | Claude Opus 4.6 | 1 | €0.023 | €69 |
| Pairwise comparison | Claude Opus 4.6 | 2 | €0.046 | €138 |

### Decision: Is Pairwise Worth the 2x Cost?

**Yes** when:
- Position bias has been measured at >10% disagreement rate in your domain
- Evaluation results feed into CI gates (false pass = bad code ships)
- Compliance/audit requirements demand defensible scoring methodology

**No** when:
- Simple correctness checks (binary right/wrong — no position to bias)
- Internal development iteration (speed matters more than precision)
- Budget-constrained environments where 2x eval cost is material

**Recommendation**: Run pairwise for CI gate evaluations (high stakes), single-pass for daily monitoring dashboards (lower stakes).

### Rule: Judge != Generator

Never use the same model family to judge its own output. Self-preference bias is well-documented.

| Generator | Acceptable Judge | Avoid as Judge |
|---|---|---|
| GPT-5 mini | Claude Sonnet 4.6, GPT-5.2 | GPT-5 mini |
| GPT-5.2 | Claude Opus 4.6, Claude Sonnet 4.6 | GPT-5.2, GPT-5 mini |
| Llama 4 Scout (local) | GPT-5.2 (cloud eval), Claude Sonnet 4.6 | Llama 4 Scout |

## Technical Deep Dive: Judge Bias Calibration

LLM judges drift over time — model updates, prompt sensitivity, domain shift. Periodic calibration against human judgments keeps scores meaningful.

### Calibration Process

1. **Collect human judgments**: 10 domain experts score 10 query-answer pairs each = 100 labeled examples
2. **Run LLM judge** on the same 100 examples
3. **Compute Spearman correlation** between human and LLM scores
4. **Threshold**: correlation > 0.85 = judge is calibrated. Below 0.85 = recalibrate (adjust prompts, switch judge model)

### Calibration Cost

| Item | Cost |
|---|---|
| 10 human judgments × €5 per judgment | €50 per calibration cycle |
| 100 LLM judge calls (GPT-5.2) | ~€1.10 per cycle |
| **Total per calibration cycle** | **~€51** |

### How Often to Recalibrate: Decision Tree

```
Monitor judge–human correlation weekly
  │
  ├── Correlation stable (>0.85, drift <2% week-over-week)
  │     └── Recalibrate monthly — €51/month
  │
  ├── Moderate drift (correlation 0.80–0.85 or drift 2-5%)
  │     └── Recalibrate weekly — €204/month
  │
  └── Significant drift (correlation <0.80 or drift >5%)
        └── Recalibrate immediately + investigate root cause
        └── Likely cause: model version change, domain shift, prompt regression
```

### Drift Detection Thresholds

| Metric | Green | Yellow | Red |
|---|---|---|---|
| Judge–human Spearman correlation | >0.85 | 0.80–0.85 | <0.80 |
| Week-over-week score drift | <2% | 2–5% | >5% |
| Position bias disagreement rate | <5% | 5–10% | >10% |

### When NOT to Evaluate

Not every response needs to go through the evaluation pipeline. Over-evaluating wastes compute.

- **Cached responses**: already evaluated when first generated — don't re-evaluate on cache hit
- **Low-stakes queries**: simple status lookups ("What's the tracking number for shipment X?") — correctness is obvious from the data, no need for LLM judge
- **Cost-constrained environments**: if evaluation cost exceeds 10% of generation cost, you're over-spending on quality assurance relative to the value of the output
- **High-volume identical patterns**: if 500 queries/day follow the same template with different entity IDs, evaluate a sample (5%), not all of them
- **Development/staging**: use lightweight spot-checks, save full evaluation pipeline for CI gates and production monitoring

**Rule of thumb**: evaluate ~10-20% of production queries continuously, 100% on CI/CD gate runs.

## LinkedIn Post Angle
**Hook**: "Your LLM-as-Judge is biased. Here's how we proved it — and fixed it."
**Medium deep dive**: "We Found 3 Hidden Biases in Our AI Quality Pipeline. Position bias, verbosity bias, and self-preference were silently inflating our scores."

## Key Metrics to Screenshot
- Position bias test: same test with swapped order showing different scores
- Human vs LLM judge correlation scatter plot
- Drift detection alert: model version change triggers automatic regression
- Prompt cache hit rate dashboard (before/after restructuring)
- Cost savings chart from prompt caching
