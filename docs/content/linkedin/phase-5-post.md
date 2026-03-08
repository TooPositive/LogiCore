# Phase 5 LinkedIn Post: Assessment Rigor — Judge Bias, Drift Detection & Prompt Caching

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

Martin presents the quarterly AI metrics to the CTO. Slide 12: Context Precision 0.92. Budget approved for the next phase. Three weeks later someone switches the judge model from GPT-5-mini to Claude Sonnet. Same test data. Score: 0.80.

Every deployment decision since the last quarter was based on an inflated number.

This is Phase 5 of a 12-phase AI system im building for a logistics company. Phase 1 proved embeddings are mandatory for search (BM25 fails 50% of real queries). Phase 2 benchmarked re-ranking across 6 models for Polish text. Phase 3 built invoice audit agents that stop for human approval. Phase 4 added cost tracking and cut AI spend by 93%. Phase 5 asks: what if the quality scores weve been reporting are wrong?

The problem is self-preference bias. GPT-5-mini judging GPT-5.2 output = same OpenAI family. Published benchmarks consistently show 10-15% score inflation when judge and generator share a model family. The judge subtly prefers outputs that look like what its own family would produce. Your 0.92 might actually be 0.80.

The fix costs EUR 0.00. Literally a string prefix comparison on model names. Claude Sonnet 4.6 judging GPT-5.2 costs the same per eval (EUR 0.011) and eliminates family-level bias entirely. But most tutorials say "use a different model as judge" without specifying that "different model from the same provider" still carries the bias.

Position bias is the other one. Show the LLM two answers, A first and B second. It picks A. Swap order. It picks whichever is first again. So every pairwise comparison runs twice with swapped positions. Both rounds must agree on the SAME answer for the result to count. Disagreement = position bias detected = result thrown out, not averaged. Averaging masks the bias. Discarding exposes it. Doubles eval cost (EUR 0.022 vs EUR 0.011) but for CI gates where a false pass ships bad code, thats cheap insurance. For daily monitoring dashboards, single-pass is fine coz the volume averages out across hundreds of evals.

Then theres the silent failure. Azure updates model versions without notification. Tuesday: GPT-5.2 version 2026-0301. Wednesday: silently becomes 2026-0415. Invoice audit agents start rounding differently. Weekly regression check? Thats 7 days x 800 queries/day x EUR 0.50/wrong answer = EUR 2,800 blast radius before anyone notices. Three-tier severity (green <2%, yellow 2-5%, red >5%) gives ops a graduated playbook instead of alert fatigue.

Honesty check: the spec promised 60% cache hit rates from prompt restructuring. Then I looked at what RBAC does to cache prefixes. Each clearance-department-entity combination creates a separate partition. 5 tenants = 5 cold misses per burst. Real multi-tenant hit rate: 15-25%, not 60%. The optimization is still free (reorder static content first) but the savings are smaller than spec'd. Correcting your own spec earns more trust than confirming it.

What breaks: all bias detection runs against mock judges, not real LLMs. The detection logic works across mixed-signal judges, heavily tied scores, and catastrophic 100-metric regression scenarios. Whether actual LLM judges exhibit these biases at the exact rates assumed — thats Phase 12 live validation. Build the detector first. Validate with real judges later.

Post 5/12 in the LogiCore series. Next up: Swiss banks cant use OpenAI. When your deployment bans cloud APIs, the architecture changes completely 😅

---

## Reply Ammo

### 1. "10-15% score inflation sounds made up"

published research (Zheng et al., "Judging LLM-as-a-Judge") found consistent self-preference across model families. the range depends on task type — lower for factual QA, higher for creative/subjective tasks. the exact number matters less than the existence of the bias. and detecting it costs EUR 0.00, its just a string prefix check on model names. no reason not to check.

### 2. "Running every comparison twice is wasteful"

single-pass with randomized position averages out bias across many evaluations but doesnt tell you WHICH evaluations were affected. if 20% of your evals are position-biased and you average them in, the aggregate score is still contaminated. running twice and discarding disagreements gives you a clean signal per comparison. for CI gates you need per-comparison reliability, not statistical-average reliability.

### 3. "What about fine-tuned models that don't match prefix patterns?"

fine-tuned models (like "ft:gpt-5.2:logicore:2026" or "logicore-gpt52-deployment") default to UNKNOWN family. UNKNOWN fails the independence check — which is the safe default. blocks judging rather than allowing potentially biased judging. theres a register_model_family() function for explicit assignment at deploy time if you need it.

### 4. "50 golden set entries isn't enough"

depends what you're measuring. for Spearman rank correlation, 50 paired scores gives meaningful signal. the bootstrap CI tells you how much to trust it. correlation of 0.89 +/- 0.04 on 50 samples = reliable. correlation of 0.83 +/- 0.09 = need more data. the CI width IS the honest answer to "is 50 enough?"

### 5. "Weekly regression checks are fine"

7-day blast radius at 800 queries/day at EUR 0.50/wrong answer = EUR 2,800. daily cuts that to EUR 400. the regression check itself costs maybe EUR 2 (100 eval queries). annual cost of daily: EUR 730. annual savings vs weekly: ~EUR 9,600 across ~4 model update incidents/year. if your volume is 50 queries/day not 800, weekly is probably fine — blast radius scales linearly.

### 6. "Why not open-source models as judge?"

you can. llama judging GPT is cross-family. the tradeoff is judge quality — smaller OSS models have weaker reasoning which increases scoring noise. decision framework: if budget allows EUR 0.011-0.023/eval, use Claude Sonnet or Opus. if air-gapped (Phase 6) or budget-constrained, use llama with higher n to compensate for noise. the bias detection framework works regardless of which judge you plug in.

### 7. "15-25% cache hit rate doesn't seem worth it"

the optimization is free. literally reorder your prompt template sections, no code changes needed. even 15% saves EUR 0.19/day at 800 queries. single-tenant deployments get 55-65% which starts mattering at scale. the tracking exists so you know which number youre getting, not to justify doing the optimization.

### 8. "The spec said 60%, you delivered 15-25%. That's a miss."

the spec assumed single-tenant. multi-tenant with RBAC partitioning makes 60% structurally impossible without bypassing access controls. I couldve tested single-tenant only and claimed 60%. instead I tracked partition fragmentation and reported the honest number for multi-tenant. "we spec'd 60%, achieved 15-25%, heres the structural reason, and the optimization is still free" is more trustworthy than "we hit 60%! (asterisk: only in the test that doesnt represent production)."

### 9. "How do you catch drift in the judge model itself?"

the golden set. 50 human-scored entries that never change regardless of model versions. if judge-golden Spearman correlation drops below 0.85, the quality gate returns HALT. the judge is the watchman. the golden set watches the watchman. 50 entries isnt many but the bootstrap CI tells you whether to trust the number. when it widens past +/- 0.08 you need more data.

### 10. "Verbosity bias — longer answers ARE often better"

sometimes. thats why the verbosity threshold is configurable. default is 1.5x length ratio (the "wrong" answer has to be 50% longer for the test to apply). for legal/compliance domains where thorough = better, lower to 1.2x. for concise operational answers where brevity = better, raise to 2.0x. the detector flags when the judge prefers length over correctness. you set the threshold for your domain.
