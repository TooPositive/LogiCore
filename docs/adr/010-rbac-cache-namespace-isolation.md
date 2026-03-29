# ADR-010: RBAC Cache Namespace Isolation over Post-Retrieval Filtering

## Status
Accepted

## Context
Phase 4's semantic cache stores LLM responses to avoid repeated inference. The cache must respect RBAC — a clearance-1 user's cached response must never be served to a clearance-3 query (or vice versa). Two enforcement models: filter cached entries by RBAC metadata on read, or physically separate cache entries into RBAC-partitioned namespaces.

## Decision
**Physical namespace isolation via partition key `cl:N|dept:X|ent:Y`.** Cache entries in different RBAC contexts are in different data structures — code that queries one partition cannot reach another.

## Rationale

| Criteria | Namespace Isolation (chosen) | Post-Retrieval Filter | Hash-Based Exact Match |
|----------|----------------------------|----------------------|----------------------|
| Cross-clearance leakage | Structurally impossible | Possible if filter has bugs | Impossible (no similarity) |
| Enforcement model | Same as OS process isolation | Same as application-level ACL | Exact match only — no semantic cache |
| Cache hit rate | 15-25% (multi-tenant) | ~35% (unpartitioned) | <5% (exact match) |
| Cost of one wrong response | EUR 3,240 (compliance breach) | EUR 3,240 | N/A |

## Consequences
- Hit rate drops from ~35% (unpartitioned) to 15-25% (partitioned), costing EUR 5-10/day in cache savings
- One wrong cached response costs EUR 3,240 — the hit rate penalty is a bargain
- The partition boundary is structural, not logical — no access control check to get wrong
- If hit rate drops below 10% (partitions too granular), coarsen entity grouping (e.g., partition by client tier, not individual client)
- RBAC cache honesty is validated in Phase 5's prompt caching metrics, which report partition-adjusted hit rates (not single-tenant numbers)
