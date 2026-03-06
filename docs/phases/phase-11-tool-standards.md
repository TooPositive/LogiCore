# Phase 11: "Tool Standards" — MCP Server Integration

## Business Problem

Every AI agent framework has its own way of connecting to tools. LangGraph tools. CrewAI tools. Claude tools. OpenAI function calls. When you build a Qdrant search tool for LangGraph, it only works in LangGraph. The same tool needs to be rebuilt for every framework. And when a new developer opens Cursor or Claude Code, they can't use any of your production tools.

MCP (Model Context Protocol) standardizes this. Build the tool once, use it everywhere.

**CTO pain**: "We have 15 internal tools scattered across 4 different AI frameworks. When we switch frameworks, we rewrite everything. And our developers can't access production tools from their IDE."

## Architecture

```
MCP Servers (standardized tool interfaces)
  ├── logicore-search (MCP Server)
  │     ├── Tool: hybrid_search(query, department, clearance)
  │     ├── Tool: semantic_search(query, collection, top_k)
  │     └── Resource: collection stats, index health
  ├── logicore-sql (MCP Server)
  │     ├── Tool: read_query(sql) — read-only, parameterized
  │     ├── Tool: invoice_lookup(invoice_id)
  │     └── Resource: schema, table stats
  ├── logicore-fleet (MCP Server)
  │     ├── Tool: fleet_status(truck_id)
  │     ├── Tool: publish_alert(alert)
  │     └── Resource: active alerts, fleet overview
  └── logicore-compliance (MCP Server)
        ├── Tool: log_decision(audit_entry)
        ├── Tool: query_audit_log(filters)
        └── Resource: compliance report, lineage graph

Consumers:
  ├── LangGraph Agents (via MCP client in tool nodes)
  ├── Claude Code / Cursor (via mcp server config)
  ├── CI/CD Pipeline (via MCP CLI)
  └── Future: any MCP-compatible agent framework
```

**Key design decisions**:
- Each domain = one MCP server (search, sql, fleet, compliance)
- Tools are the same ones LangGraph agents use — not wrappers, the real thing
- Security: MCP servers enforce the same RBAC as the API layer
- Developer experience: devs get production search + SQL in their IDE
- Composability: mix and match servers per use case

## Implementation Guide

### Prerequisites
- Phases 1-3 complete (search, agents, tools exist)
- Understanding of MCP protocol (resources, tools, prompts)
- Python MCP SDK (`mcp` package)

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/mcp/__init__.py` | Package init |
| `apps/api/src/mcp/search_server.py` | MCP server: Qdrant hybrid search tools |
| `apps/api/src/mcp/sql_server.py` | MCP server: read-only SQL tools |
| `apps/api/src/mcp/fleet_server.py` | MCP server: fleet status + alert tools |
| `apps/api/src/mcp/compliance_server.py` | MCP server: audit log + lineage tools |
| `apps/api/src/mcp/auth.py` | MCP auth middleware (token validation, RBAC) |
| `apps/api/src/tools/sql_query.py` | **Modify** — extract into reusable tool, shared with MCP |
| `apps/api/src/rag/retriever.py` | **Modify** — extract search as reusable tool |
| `.mcp/config.json` | MCP server configuration for IDE integration |
| `docker-compose.yml` | **Modify** — add MCP server services |
| `tests/integration/test_mcp_search.py` | MCP search server integration test |
| `tests/integration/test_mcp_security.py` | RBAC enforcement via MCP |
| `docs/adr/007-mcp-tool-standardization.md` | ADR: MCP over framework-specific tools |

### Technical Spec

**MCP Search Server**:
```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("logicore-search")

@server.tool()
async def hybrid_search(
    query: str,
    department: str | None = None,
    clearance_level: int = 1,
    top_k: int = 5,
) -> list[TextContent]:
    """Search corporate knowledge base with RBAC filtering.
    Uses hybrid search (BM25 + dense vectors) with re-ranking."""
    results = await retriever.search(
        query=query,
        rbac_filter=RBACFilter(department=department, clearance=clearance_level),
        top_k=top_k,
    )
    return [TextContent(type="text", text=r.to_json()) for r in results]

@server.tool()
async def semantic_search(
    query: str,
    collection: str = "corporate_knowledge",
    top_k: int = 10,
) -> list[TextContent]:
    """Direct vector search without RBAC (for internal/admin use)."""
    ...
```

**MCP SQL Server (security-critical)**:
```python
@server.tool()
async def read_query(sql: str) -> list[TextContent]:
    """Execute read-only SQL against the invoice database.
    SECURITY: uses parameterized execution, read-only DB role,
    query whitelist validation."""
    # Validate: no DDL, no DML, only SELECT
    if not sql_validator.is_safe_select(sql):
        raise ToolError("Only SELECT queries are allowed")

    async with db.acquire_readonly() as conn:
        rows = await conn.fetch(sql)
        return [TextContent(type="text", text=json.dumps(rows, default=str))]
```

**IDE Configuration** (`.mcp/config.json`):
```json
{
  "mcpServers": {
    "logicore-search": {
      "command": "uv",
      "args": ["run", "python", "-m", "apps.api.src.mcp.search_server"],
      "env": { "QDRANT_HOST": "localhost" }
    },
    "logicore-sql": {
      "command": "uv",
      "args": ["run", "python", "-m", "apps.api.src.mcp.sql_server"],
      "env": { "POSTGRES_HOST": "localhost" }
    }
  }
}
```

### Success Criteria
- [ ] 4 MCP servers running (search, sql, fleet, compliance)
- [ ] Same tool code used by LangGraph agents AND MCP servers (no duplication)
- [ ] Claude Code / Cursor can use `hybrid_search` tool via MCP config
- [ ] MCP SQL server rejects non-SELECT queries
- [ ] RBAC enforced: MCP search respects clearance_level
- [ ] `docker compose up` starts MCP servers alongside API
- [ ] LangGraph agents can call tools via MCP client (framework-agnostic)

## LinkedIn Post Angle
**Hook**: "We stopped building custom tool integrations. MCP changed everything."
**Medium deep dive**: "Building Production MCP Servers for Enterprise AI: Search, SQL, and Fleet Management — with Security That Actually Works" — full implementation showing how one tool definition serves LangGraph, Claude Code, and CI/CD.

## Key Metrics to Screenshot
- Same tool working in: LangGraph agent, Claude Code, Cursor IDE
- MCP server list with tool counts and health status
- Security test: RBAC rejection via MCP vs direct API (same behavior)
- Before/after: tool duplication count across frameworks
