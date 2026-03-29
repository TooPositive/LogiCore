# ADR-009: Graph-Level RBAC Filtering over Prompt-Based

## Status
Accepted

## Context
Multi-agent workflows (Phase 3) produce findings with varying clearance levels. Sub-agent output must be filtered before entering parent graph state, ensuring users only see findings at or below their clearance. Two fundamentally different enforcement points exist: LLM prompt instructions ("don't return data above clearance X") or Python code at the graph boundary.

## Decision
**ClearanceFilter in Python at the graph boundary.** Missing `clearance_level` defaults to 1 (most restrictive) — fail-closed.

## Rationale

| Criteria | Python Code Filter | Prompt-Based Filter |
|----------|-------------------|-------------------|
| Bypass resistance | Cannot be bypassed — runs in Python, not LLM | Vulnerable to prompt injection |
| Enforcement point | Last step before sub-agent data enters parent state | Inside the LLM context window |
| Fail-closed default | `clearance_level` missing → most restrictive (1) | LLM may infer or hallucinate clearance |
| Testability | Deterministic — unit testable | Non-deterministic — requires adversarial testing |
| Auditability | Filter decision is logged in code | Filter decision is embedded in LLM reasoning |

## Consequences
- Requires structured findings with `clearance_level` metadata — free-text sub-agent output cannot be filtered
- The filter is architecturally impossible to bypass: it's a Python `list comprehension` checking `clearance_level <= user_clearance`
- LLM prompt injection cannot escalate access — the filter runs after the LLM, not inside it
- Post-processing in the auditor node was rejected because it couples security enforcement to business logic
- Content-level filtering (partial redaction rather than full exclusion) is deferred to Phase 10 (LLM Firewall)
