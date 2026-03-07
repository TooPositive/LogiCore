# Phase 12 Tracker: Full Stack Demo — Integration Capstone

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-12-full-stack-demo.md`
**Depends on**: ALL Phases 1-11

## Implementation Tasks

- [ ] `scripts/demo_scenario.py` — orchestrates full Swiss Border scenario
- [ ] `scripts/demo_telemetry.py` — temperature spike event sequence
- [ ] `scripts/demo_injection.py` — prompt injection during demo
- [ ] `apps/web/src/app/demo/page.tsx` — live demo dashboard
- [ ] `apps/web/src/components/demo-timeline.tsx` — step-by-step timeline
- [ ] `apps/web/src/components/metrics-panel.tsx` — live metrics
- [ ] `docker-compose.demo.yml` — compose override for demo
- [ ] `docs/DEMO-RUNBOOK.md` — step-by-step guide
- [ ] `tests/e2e/test_full_scenario.py` — automated e2e test

## Success Criteria

- [ ] `docker compose --profile demo up` runs entire scenario
- [ ] Temp spike → agent response → HITL → approval in < 60 seconds
- [ ] Prompt injection blocked and logged during demo
- [ ] Circuit breaker triggers, Ollama serves seamlessly
- [ ] Langfuse shows end-to-end trace across all agents
- [ ] Compliance report generated
- [ ] Dashboard shows live timeline with metrics
- [ ] MCP tools accessible from Claude Code during demo
- [ ] Total cost of full scenario: < €0.05
- [ ] All 12 phases visible in one execution

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Demo scenario | Swiss Border Incident | | |
| Demo duration | ~45 seconds | | |
| Dashboard framework | Next.js + live updates | | |
| Compose profile | "demo" | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

_This is the final metrics table — the "money shot" for LinkedIn._

| Metric | Value | Context |
|---|---|---|
| Total response time | | seconds |
| LLM calls | | count |
| Total tokens | | count |
| Total cost | | EUR |
| Cache hits | | count |
| Cache savings | | EUR |
| Security events blocked | | count |
| Audit log entries | | count |
| Provider used | | which model served |
| Retrieval precision | | 0-1 |
| EU AI Act compliance | | pass/fail |
| Services running | | count in `docker compose ps` |
| Total project lines of code | | count |
| Total project duration | | weeks |

## Screenshots Captured

- [ ] Demo dashboard (live timeline)
- [ ] Langfuse (end-to-end trace)
- [ ] Cost breakdown (per-step)
- [ ] Security dashboard (blocked injection)
- [ ] `docker compose ps` (all services healthy)
- [ ] Terminal (demo script output)
- [ ] Final metrics table
- [ ] Architecture progress card (all 12 phases green)

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | "7 months ago I typed docker-compose up" |
| Medium article | — | | Full retrospective |
| LinkedIn hero image | — | | Final architecture card |
