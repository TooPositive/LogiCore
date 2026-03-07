# Phase 10 Tracker: LLM Firewall — Security & Red Teaming

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-10-llm-firewall.md`
**Depends on**: Phases 1-6

## Implementation Tasks

- [ ] `apps/api/src/security/__init__.py`
- [ ] `apps/api/src/security/input_sanitizer.py` — pattern-based input cleaning
- [ ] `apps/api/src/security/guardrail.py` — Llama Guard / NeMo integration
- [ ] `apps/api/src/security/output_filter.py` — response PII/harmful check
- [ ] `apps/api/src/security/sql_sandbox.py` — query parameterization + whitelist
- [ ] `apps/api/src/security/middleware.py` — FastAPI middleware wiring all layers
- [ ] `apps/api/src/api/v1/security.py` — GET /report, /blocked-attempts
- [ ] `apps/api/src/domain/security.py` — SecurityEvent, ThreatReport models
- [ ] `tests/red-team/promptfoo.yaml` — OWASP LLM Top 10 config
- [ ] `tests/red-team/attacks/` — attack payloads per category
- [ ] `tests/red-team/run_red_team.py` — red team execution
- [ ] `tests/unit/test_input_sanitizer.py` — bypass attempt tests
- [ ] `tests/unit/test_sql_sandbox.py` — SQL injection prevention
- [ ] `scripts/security_report.py` — security posture report

## Success Criteria

- [ ] Direct prompt injection blocked at Layer 1
- [ ] Llama Guard catches sophisticated jailbreaks
- [ ] SQL injection fails (parameterized + read-only)
- [ ] Output filter catches PII leakage
- [ ] Red team runs all OWASP LLM Top 10 categories
- [ ] Pass rate > 95% on automated attacks
- [ ] Every blocked attempt logged
- [ ] Security report shows trends
- [ ] CI blocks deployment if pass rate drops

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Guardrail model | Llama Guard 3 8B | | |
| Red team tool | Promptfoo | | |
| Layer count | 5 layers | | |
| Latency budget | <50ms total overhead | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Layer 1 (sanitizer) latency | | ms |
| Layer 2 (Llama Guard) latency | | ms |
| Total security overhead | | ms per request |
| Red team pass rate | | % |
| Attacks blocked per layer | | count per layer |
| False positive rate | | % legitimate queries blocked |
| OWASP categories covered | | /10 |
| PII leak detection rate | | % |
| SQL injection block rate | | % |

## Screenshots Captured

- [ ] Red team dashboard (OWASP categories)
- [ ] Blocked attempts timeline
- [ ] Defense layer effectiveness chart
- [ ] Security report (pass rate trend)
- [ ] Latency overhead measurement

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
