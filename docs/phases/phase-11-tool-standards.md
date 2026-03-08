# Phase 11: "Tool Standards" — MCP Server Integration

## Business Problem

Every AI agent framework has its own way of connecting to tools. LangGraph tools. CrewAI tools. Claude tools. OpenAI function calls. When you build a Qdrant search tool for LangGraph, it only works in LangGraph. The same tool needs to be rebuilt for every framework. And when a new developer opens Cursor or Claude Code, they can't use any of your production tools.

MCP (Model Context Protocol) standardizes this. Build the tool once, use it everywhere.

**CTO pain**: "We have 15 internal tools scattered across 4 different AI frameworks. When we switch frameworks, we rewrite everything. And our developers can't access production tools from their IDE."

## Real-World Scenario: LogiCore Transport

**Feature: Universal Tool Access (IDE + Agents + CI/CD)**

New developer joins LogiCore Transport's engineering team. Day 1, she opens Claude Code. Her `.mcp/config.json` connects her to the same production tools the AI agents use.

**Developer workflow**: She types in Claude Code: "Search for all pharmaceutical contracts with penalty clauses above 10%." The `logicore-search` MCP server runs hybrid search against Qdrant — same RBAC, same re-ranking, same results as the production RAG agent. She gets PharmaCorp (15%), ChemTrans (20%). No need to learn the internal API, write curl commands, or navigate a separate dashboard.

**Debugging a discrepancy**: The invoice audit flagged INV-2024-0923 but the report looks wrong. She uses the `logicore-sql` MCP tool: "Show me invoice INV-2024-0923 details." The MCP server validates it's a SELECT query, runs it via the read-only database role, and returns the result — same security as the AI agent. She compares against the contract via `logicore-search` and finds the auditor's rate extraction was correct.

**CI/CD pipeline**: Every PR triggers `logicore-compliance` MCP tool to verify the audit log schema hasn't changed. Same tool the compliance report generator uses. No separate test harness needed.

**The "build once" moment**: The `hybrid_search` function exists in ONE place. LangGraph agents call it via MCP client. Claude Code calls it via MCP config. Cursor IDE calls it via MCP config. CI/CD calls it via MCP CLI. Zero duplication. Update the search logic → every consumer gets the update.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| MCP (Model Context Protocol) | Same AI tools in the production system, the IDE, and CI/CD | Build once, use everywhere — no tool duplication |
| MCP server per domain | `logicore-search`, `logicore-sql`, `logicore-fleet`, `logicore-compliance` | Clean separation of concerns with consistent security |
| RBAC enforcement via MCP | Developer with clearance 2 can't access clearance 4 docs, even in the IDE | Security applies everywhere, not just in the web app |
| IDE integration | New developer productive on day 1 — AI tools work in their editor | Faster onboarding, lower friction, better developer experience |
| Framework-agnostic tools | Switch from LangGraph to another framework? Tools still work | Future-proof investment, not framework lock-in |

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
| `apps/api/src/core/mcp/__init__.py` | Package init |
| `apps/api/src/core/mcp/search_server.py` | MCP server: Qdrant hybrid search tools |
| `apps/api/src/domains/logicore/mcp/sql_server.py` | MCP server: read-only SQL tools |
| `apps/api/src/domains/logicore/mcp/fleet_server.py` | MCP server: fleet status + alert tools |
| `apps/api/src/domains/logicore/mcp/compliance_server.py` | MCP server: audit log + lineage tools |
| `apps/api/src/core/mcp/auth.py` | MCP auth middleware (token validation, RBAC) |
| `apps/api/src/domains/logicore/tools/sql_query.py` | **Modify** — extract into reusable tool, shared with MCP |
| `apps/api/src/core/rag/retriever.py` | **Modify** — extract search as reusable tool |
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

## Decision Framework: When MCP Is Worth It

**MCP overhead**: JSON-RPC serialization + stdio/SSE transport adds ~5-10ms per tool call.

| Scenario | MCP Worth It? | Why |
|---|---|---|
| >2 consumers share the same tool (LangGraph + Claude Code + Cursor) | **Yes** | Build once, use everywhere. The 5-10ms overhead pays for itself in zero duplication |
| Single consumer, single framework | **No** | Direct function call is faster and simpler. MCP adds indirection for no benefit |
| Latency-critical hot path (<10ms budget) | **No** | 5-10ms MCP overhead eats your entire budget |
| CI/CD needs to call production tools | **Yes** | MCP CLI gives CI pipelines tool access without custom HTTP clients |
| New devs need IDE access to production data | **Yes** | MCP config in `.mcp/config.json` = day-1 productivity |
| Simple CRUD with no shared logic | **No** | Direct DB call or REST endpoint is simpler |

**Cost comparison**:
- Direct API call: ~1ms overhead, 0 serialization, tight coupling to framework
- MCP-wrapped call: ~5-10ms overhead, JSON-RPC serialization, framework-agnostic
- The "tax" is 5-10ms per call. For LogiCore's ~50 req/sec peak, that's negligible. For a trading system at 10K req/sec with <5ms budget, it's a dealbreaker.

**LogiCore decision**: 4 MCP servers (search, sql, fleet, compliance) serve 3+ consumers each (LangGraph agents, Claude Code, Cursor, CI/CD). The 5-10ms overhead is justified.

## Technical Deep Dive: RBAC in MCP

**Problem**: Claude Code and Cursor don't send `user_id` in tool calls. How does the MCP server know the caller's clearance level?

**Solution**: MCP auth middleware extracts identity from the transport layer, not the tool call:

```python
# MCP auth middleware — runs before every tool invocation
class RBACMiddleware:
    async def authenticate(self, request: MCPRequest) -> UserContext:
        # Option 1: Bearer token in SSE transport headers
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        # Option 2: Session context from stdio (IDE passes env vars)
        if not token:
            token = os.environ.get("LOGICORE_API_TOKEN", "")

        claims = jwt.decode(token, verify=True)
        return UserContext(
            user_id=claims["sub"],
            clearance_level=claims["clearance"],
            department=claims["dept"],
        )
```

**Security model — tool-level RBAC**:

| Tool Category | Access Pattern | Rationale |
|---|---|---|
| Read-only search (`hybrid_search`, `semantic_search`) | Broader access, RBAC filters results | Users can search, but results filtered to their clearance |
| Read-only SQL (`read_query`, `invoice_lookup`) | Restricted to SELECT, read-only DB role | Can see data but can't mutate anything |
| Write tools (`publish_alert`, `log_decision`) | Restricted by role + department | Only fleet managers publish alerts; only auditors log decisions |
| Admin tools (`schema`, `collection stats`) | Admin clearance only | Infrastructure visibility limited to ops team |

**Key insight**: RBAC happens at two levels — (1) "can you call this tool at all?" (middleware) and (2) "what data does the tool return?" (result filtering). `hybrid_search` lets clearance-2 users call it, but filters out clearance-4 documents from results.

### When NOT to Use MCP

- **Single-consumer tools**: If only LangGraph calls a function, keep it as a direct LangGraph tool. Wrapping in MCP adds complexity with no reuse benefit.
- **Hot path with <10ms budget**: MCP's 5-10ms serialization overhead is too expensive. Call the function directly.
- **Simple CRUD with no shared logic**: A basic `get_user(id)` doesn't need MCP. A REST endpoint or direct DB call is simpler.
- **Prototyping / early phases**: Don't MCP-ify tools until you have a second consumer. YAGNI applies. LogiCore waited until Phase 11 (not Phase 1) to standardize on MCP — by then, we knew which tools had multiple consumers.
- **Internal-only tools with no IDE need**: If developers never need to call it from Claude Code/Cursor, the MCP wrapper provides no developer experience benefit.

## Agentic Architecture: Tool Selection Reasoning

Most agent demos hardcode tool access — the agent has 3 tools and uses all 3 every time. In production, an agent has access to 15+ tools and must **decide which 2-3 are relevant** to the current query. Getting this wrong wastes tokens and money; getting it right is the difference between a chatbot and an agent.

### The Problem

The LogiCore system has 15+ MCP tools across 4 servers. When the invoice auditor receives a query like "Check if truck-4521's cargo insurance covers temperature damage," it shouldn't call `fleet_status` + `hybrid_search` + `read_query` + `invoice_lookup` + `query_audit_log`. It should call exactly 2: `hybrid_search` (find insurance policy) and `fleet_status` (get current cargo details).

### Tool Selection Architecture

```
Query arrives
  ├─ Tool Description Matching (embedding similarity)
  │   Input: query embedding vs tool description embeddings
  │   Output: ranked list of tools by relevance score
  │   Cost: ~€0.00001 (embedding only, no LLM)
  │
  ├─ Top-K Selection (K = 3-5)
  │   Only the top K tool descriptions are included in the LLM context
  │   Reduces prompt tokens: 15 tools × ~100 tokens each = 1,500 tokens saved
  │
  └─ LLM Tool Selection (GPT-5 nano, ~€0.00003)
      Sees: query + top 5 tool descriptions
      Decides: which 1-3 tools to actually call
      Returns: tool calls with arguments
```

### Implementation

```python
from sentence_transformers import SentenceTransformer

class ToolSelector:
    def __init__(self, tools: list[MCPTool]):
        self.tools = tools
        self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
        # Pre-compute tool description embeddings at startup
        self.tool_embeddings = self.encoder.encode(
            [t.description for t in tools]
        )

    def select_relevant(self, query: str, top_k: int = 5) -> list[MCPTool]:
        query_embedding = self.encoder.encode(query)
        similarities = cosine_similarity([query_embedding], self.tool_embeddings)[0]

        top_indices = similarities.argsort()[-top_k:][::-1]
        return [self.tools[i] for i in top_indices if similarities[i] > 0.3]
```

**Why embedding-based pre-filter + LLM selection (not just LLM)**:
- Sending all 15 tool descriptions to the LLM = ~1,500 extra input tokens per call = ~€0.0001 wasted per query at GPT-5 mini rates
- At 10K queries/day = €1/day wasted on irrelevant tool descriptions
- Pre-filter to top 5 → LLM sees only relevant tools → faster, cheaper, more accurate

### Tool Description Quality Matters

Bad tool descriptions = bad selection. The agent can only reason about tools based on what you tell it.

```python
# BAD — vague, overlapping
@server.tool()
async def search(query: str): """Search the database."""

# GOOD — specific, with examples and constraints
@server.tool()
async def hybrid_search(
    query: str,
    department: str | None = None,
    clearance_level: int = 1,
) -> list[TextContent]:
    """Search corporate knowledge base (contracts, policies, regulations)
    using hybrid BM25 + vector search with RBAC filtering.

    Use for: finding contract terms, policy clauses, regulatory requirements.
    Do NOT use for: invoice amounts (use read_query), truck locations (use fleet_status),
    or audit history (use query_audit_log).

    Examples:
    - "PharmaCorp penalty clause" → returns contract sections
    - "temperature requirements for pharmaceutical transport" → returns compliance docs
    """
```

### Measuring Tool Selection Accuracy

```python
# Evaluation: does the agent pick the right tools?
TOOL_SELECTION_TESTS = [
    {
        "query": "What's truck-4521's current temperature?",
        "expected_tools": ["fleet_status"],
        "should_not_call": ["hybrid_search", "read_query"],
    },
    {
        "query": "Find the penalty clause in PharmaCorp's contract",
        "expected_tools": ["hybrid_search"],
        "should_not_call": ["fleet_status", "read_query"],
    },
    {
        "query": "Compare invoice INV-2024-0847 against contract rate",
        "expected_tools": ["read_query", "hybrid_search"],
        "should_not_call": ["fleet_status", "publish_alert"],
    },
]

# Run as part of Phase 5 evaluation suite
# Track: tool_selection_precision, tool_selection_recall, unnecessary_tool_calls
```

### Cost Impact of Good Tool Selection

| Scenario | Tools Called | Tokens Used | Cost/Query | Monthly (10K/day) |
|---|---|---|---|---|
| No selection (call all 4 relevant) | 4 | ~3,000 | €0.008 | €2,400 |
| LLM selects from all 15 | 2-3 | ~2,500 (includes 15 descriptions) | €0.006 | €1,800 |
| Pre-filter + LLM selects from top 5 | 2 | ~1,200 | €0.003 | €900 |
| Savings vs naive | | | **62% less** | **€1,500/mo saved** |

### Connection to MCP

Tool selection reasoning and MCP are natural complements:
- MCP gives you a **standardized tool registry** with consistent descriptions
- Tool selection gives you **intelligent routing** to the right tools
- Together: agents discover available tools via MCP, pre-filter by relevance, and call only what's needed

Without MCP, each framework has its own tool format, and the selection logic must be reimplemented per framework. With MCP, the tool descriptions are the same everywhere — the selection logic is write-once.

### Success Criteria
- [ ] 4 MCP servers running (search, sql, fleet, compliance)
- [ ] Same tool code used by LangGraph agents AND MCP servers (no duplication)
- [ ] Claude Code / Cursor can use `hybrid_search` tool via MCP config
- [ ] MCP SQL server rejects non-SELECT queries
- [ ] RBAC enforced: MCP search respects clearance_level
- [ ] `docker compose up` starts MCP servers alongside API
- [ ] LangGraph agents can call tools via MCP client (framework-agnostic)

## Cost of Getting It Wrong

MCP adds 5-10ms per tool call. The security value is worth far more than the latency cost.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **RBAC bypass via stale MCP token** | Developer's .env has stale JWT with old (higher) clearance level. Token not revoked. Developer accesses clearance-3 docs from Claude Code. | EUR 25,000-250,000 (RBAC breach) | 1 incident |
| **MCP server crash = shared failure** | `logicore-search` crashes. Both LangGraph agents AND developer IDE lose search simultaneously. Single point of failure. | EUR 135/hour (manual fallback) + degraded fleet monitoring | 2-4 hours/month |
| **Tool selection error** | Agent calls `fleet_status` instead of `hybrid_search` for a contract question. Returns GPS data instead of clause. | EUR 100-500/incident | 10-20/month at 90% tool selection accuracy |
| **Cross-consumer interference** | Developer runs bulk re-indexing via Claude Code MCP. Saturates Qdrant. Production fleet alert RAG lookup times out. | EUR 5,000-180,000 (fleet SLA broken during business hours) | 1-2/year |
| **Stale tool descriptions** | Tool description not updated after logic change. Agent selects wrong tool based on outdated description. | EUR 100-500/incident | 5-10/month |

**The CTO line**: "MCP's real value isn't 'build once, use everywhere.' It's 'one RBAC implementation, one place to audit, one place to fix.' Without MCP, four different RBAC implementations means four different ways to leak data."

### Single Enforcement Point (The Architect Case for MCP)

| Without MCP | With MCP |
|---|---|
| RBAC in LangGraph agents | One `logicore-search` server |
| RBAC in Claude Code integration | Same server, same RBAC |
| RBAC in CI quality gates | Same server, same RBAC |
| RBAC in Cursor integration | Same server, same RBAC |
| **4 implementations to audit** | **1 implementation to audit** |
| Bug in one = data leak in one consumer | Bug in one = fix everywhere at once |

### MCP Token Lifecycle (Missing from Spec)

| Token Type | Max TTL | Rotation | Revocation |
|---|---|---|---|
| Production agent tokens | 24 hours | Auto-rotate daily | Immediate via token blocklist |
| Developer IDE tokens | 8 hours | New token each session | Expire on session end |
| CI/CD tokens | 1 hour | Per-pipeline-run | Expire on pipeline completion |

**Rule**: No MCP token should live longer than 24 hours. Developer tokens should be session-scoped, not stored in .env files.

## LinkedIn Post Angle
**Hook**: "We stopped building custom tool integrations. MCP changed everything."
**Medium deep dive**: "Building Production MCP Servers for Enterprise AI: Search, SQL, and Fleet Management — with Security That Actually Works" — full implementation showing how one tool definition serves LangGraph, Claude Code, and CI/CD.

## Key Metrics to Screenshot
- Same tool working in: LangGraph agent, Claude Code, Cursor IDE
- MCP server list with tool counts and health status
- Security test: RBAC rejection via MCP vs direct API (same behavior)
- Before/after: tool duplication count across frameworks
