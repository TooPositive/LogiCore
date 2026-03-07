# Phase 11 Tracker: Tool Standards — MCP Server Integration

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-11-tool-standards.md`
**Depends on**: Phases 1-3

## Implementation Tasks

- [ ] `apps/api/src/mcp/__init__.py`
- [ ] `apps/api/src/mcp/search_server.py` — MCP server: Qdrant hybrid search tools
- [ ] `apps/api/src/mcp/sql_server.py` — MCP server: read-only SQL tools
- [ ] `apps/api/src/mcp/fleet_server.py` — MCP server: fleet status + alert tools
- [ ] `apps/api/src/mcp/compliance_server.py` — MCP server: audit log + lineage tools
- [ ] `apps/api/src/mcp/auth.py` — MCP auth middleware (RBAC)
- [ ] `apps/api/src/tools/sql_query.py` — MODIFY: extract into reusable shared tool
- [ ] `apps/api/src/rag/retriever.py` — MODIFY: extract search as reusable tool
- [ ] `.mcp/config.json` — MCP server configuration for IDE integration
- [ ] `docker-compose.yml` — MODIFY: add MCP server services
- [ ] `tests/integration/test_mcp_search.py` — MCP search integration
- [ ] `tests/integration/test_mcp_security.py` — RBAC via MCP
- [ ] `docs/adr/007-mcp-tool-standardization.md`

### Agentic: Tool Selection Reasoning

- [ ] `apps/api/src/tools/tool_selector.py` — ToolSelector class (embedding pre-filter + LLM selection)
- [ ] `apps/api/src/tools/tool_registry.py` — tool descriptions registry with quality guidelines
- [ ] `apps/api/src/infrastructure/embeddings/tool_embeddings.py` — SentenceTransformer tool description embeddings
- [ ] `data/tool-descriptions/` — curated tool descriptions (bad vs good examples)
- [ ] `tests/unit/test_tool_selector.py` — pre-filter accuracy, LLM selection correctness
- [ ] `tests/integration/test_tool_selection_e2e.py` — query → embedding filter → LLM pick → execution
- [ ] `benchmarks/tool_selection_benchmark.py` — naive (all tools) vs pre-filter cost/accuracy comparison

## Success Criteria

- [ ] 4 MCP servers running (search, sql, fleet, compliance)
- [ ] Same tool code used by LangGraph agents AND MCP servers
- [ ] Claude Code / Cursor can use hybrid_search via MCP config
- [ ] MCP SQL server rejects non-SELECT queries
- [ ] RBAC enforced via MCP
- [ ] `docker compose up` starts MCP servers alongside API
- [ ] LangGraph agents call tools via MCP client
- [ ] Tool selector pre-filters 15+ tools to top-K via embedding similarity
- [ ] LLM selects correct tool from reduced set (>95% accuracy)
- [ ] Naive vs pre-filter cost comparison shows >50% savings

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| MCP servers per domain | 4 (search, sql, fleet, compliance) | | |
| Tool reuse strategy | shared code, not wrappers | | |
| IDE config format | .mcp/config.json | | |
| Tool selection | embedding pre-filter + LLM | | |
| Embedding model | SentenceTransformer (local) | | |
| Pre-filter K | top-5 from 15+ tools | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Tool duplication (before MCP) | | count across frameworks |
| Tool duplication (after MCP) | | should be 0 |
| MCP search latency | | vs direct API call |
| MCP SQL latency | | vs direct API call |
| RBAC rejection test (MCP vs API) | | same behavior? |
| IDE integration test | | Claude Code works? |
| Tool selection accuracy (pre-filter) | | % correct tool in top-K |
| Tool selection accuracy (LLM) | | % correct final pick |
| Tokens per selection (naive) | | all tools in prompt |
| Tokens per selection (pre-filter) | | top-K only in prompt |
| Cost savings (pre-filter vs naive) | | % reduction |
| Pre-filter latency | | ms (embedding similarity) |

## Screenshots Captured

- [ ] Same tool in: LangGraph, Claude Code, Cursor
- [ ] MCP server list with health status
- [ ] RBAC rejection via MCP
- [ ] Tool duplication before/after
- [ ] Tool selection: naive (all 15+ tools) vs pre-filter (top-5) token comparison
- [ ] Tool description quality: bad vs good examples side-by-side

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
