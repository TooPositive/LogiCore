# Architect Notes: Migration & Integration Strategy

> How to plug AI into an existing enterprise stack without rewriting everything.

## The Problem

LogiCore starts from scratch with docker-compose — great for learning, but real enterprises have SAP, Oracle, legacy .NET monoliths, mainframes. The architect question: how do you introduce AI into a brownfield environment?

## The .NET Answer: Microsoft.Extensions.AI (MAF)

For .NET enterprises (which is a massive chunk of the enterprise world), **MAF is the migration strategy**. You don't build a separate AI service and call it via HTTP. You add AI directly into the existing application and turn existing services into AI-callable tools.

This is the strongest architect insight in the entire series: **you don't need a rewrite. You need 3 NuGet packages and 50 lines of glue code.**

### What MAF Actually Does

MAF (`Microsoft.Extensions.AI`) is the .NET abstraction layer for AI. It gives you:
- `IChatClient` — universal interface for any LLM provider (Azure OpenAI, Ollama, Anthropic, anything)
- `AIFunction` / `AIFunctionFactory` — turn any C# method into an AI-callable tool
- Middleware pipeline — caching, rate limiting, logging, token tracking as composable layers
- `FunctionInvokingChatClient` — automatic tool calling loop (LLM calls tool → gets result → calls next tool → etc.)
- DI-native — works with standard ASP.NET dependency injection, no framework lock-in

### The Migration Pattern: Existing Services → AI Tools

This is the key insight. Every existing .NET service in a legacy app is already a potential AI tool:

```csharp
// BEFORE: Existing .NET service in your legacy monolith
// This already exists. You don't change it.
public class InvoiceService
{
    public async Task<Invoice> GetInvoice(string invoiceId) { ... }
    public async Task<List<Invoice>> GetOverdueInvoices() { ... }
    public async Task<decimal> CalculateDiscount(string contractId, decimal amount) { ... }
}

// AFTER: 10 lines to make it AI-callable
// Add [Description] attributes so the LLM knows what each method does
public class InvoiceService
{
    [Description("Retrieve invoice details by ID")]
    public async Task<Invoice> GetInvoice(
        [Description("The invoice ID, e.g. INV-2024-0847")] string invoiceId) { ... }

    [Description("List all invoices past their due date")]
    public async Task<List<Invoice>> GetOverdueInvoices() { ... }

    [Description("Calculate applicable discount based on contract terms")]
    public async Task<decimal> CalculateDiscount(
        [Description("Contract ID")] string contractId,
        [Description("Invoice amount in EUR")] decimal amount) { ... }
}

// Register as AI tools — that's it
var tools = AIFunctionFactory.Create(invoiceService);
// Now the LLM can call GetInvoice, GetOverdueInvoices, CalculateDiscount
```

### Full Integration in an Existing ASP.NET App

```csharp
// Program.cs of your existing .NET monolith — add ~20 lines

// 1. Register the LLM provider
builder.Services.AddChatClient(new AzureOpenAIClient(
    new Uri(config["AzureOpenAI:Endpoint"]),
    new ApiKeyCredential(config["AzureOpenAI:Key"])
).GetChatClient("gpt-4o").AsIChatClient())
    .UseFunctionInvocation(fi => fi.MaximumIterationsPerRequest = 8)  // cap tool loops
    .UseOpenTelemetry()   // observability for free
    .Build();

// 2. Your existing services are already in DI. Just resolve and wrap:
app.MapPost("/api/ai/query", async (
    IChatClient chat,
    InvoiceService invoices,
    ContractService contracts,
    WarehouseService warehouses,
    string query) =>
{
    var tools = new List<AITool>();
    tools.AddRange(AIFunctionFactory.Create(invoices));    // existing service → AI tool
    tools.AddRange(AIFunctionFactory.Create(contracts));   // existing service → AI tool
    tools.AddRange(AIFunctionFactory.Create(warehouses));  // existing service → AI tool

    var response = await chat.GetResponseAsync(
        query,
        new ChatOptions { Tools = tools }
    );
    return response.Text;
});
```

**That's the entire migration.** The existing `InvoiceService`, `ContractService`, `WarehouseService` — they keep working exactly as before. Existing UI, existing API endpoints, existing business logic. Unchanged. You just added one new endpoint that lets AI call them.

### Why This Is Better Than the API Gateway Pattern

| Approach | What You Build | Latency | Complexity | Existing Code Changes |
|---|---|---|---|---|
| API Gateway (separate Python service) | New service + HTTP calls | 50-200ms per hop | High (2 services, 2 deploys, auth between them) | None, but adds infra |
| MAF (in-process) | 20 lines in existing app | 0ms (same process) | Low (one deploy, shared DI) | Add `[Description]` attributes |

**For .NET shops, API gateway is the wrong answer.** It's the Python/microservices answer. The .NET answer is MAF — same process, same DI container, same auth, zero network hops.

### The Middleware Pipeline (production hardening)

MAF's middleware is composable. You add production concerns without touching business logic:

```csharp
builder.Services.AddChatClient(innerClient)
    .UseDistributedCache(redis)           // semantic caching (Phase 4)
    .UseFunctionInvocation(fi =>
    {
        fi.MaximumIterationsPerRequest = 8;  // prevent runaway tool loops
        fi.AllowConcurrentInvocation = true;  // parallel tool calls
    })
    .UseOpenTelemetry()                    // observability (Langfuse/OTEL)
    .UseRateLimiting(limiter)              // rate limiting
    .Build();
```

Each middleware wraps the next. Request flows outside→in, response flows inside→out. Same pattern as ASP.NET middleware — .NET devs already know it.

### Real AgentHub Pattern: Plugin Adapter

AgentHub already does this with `MafPluginAdapter` — converts Semantic Kernel plugins to MAF tools:

```csharp
// From AgentHub.Core — bridge SK plugins to MAF
public static AIFunction[] ToAIFunctions(object plugin, string? pluginPrefix = null)
{
    var methods = plugin.GetType()
        .GetMethods(BindingFlags.Public | BindingFlags.Instance)
        .Where(m => m.GetCustomAttribute<KernelFunctionAttribute>() is not null);

    return methods.Select(m =>
    {
        var attr = m.GetCustomAttribute<KernelFunctionAttribute>()!;
        var desc = m.GetCustomAttribute<DescriptionAttribute>()?.Description;
        var name = attr.Name ?? m.Name;

        return AIFunctionFactory.Create(m, plugin, new AIFunctionFactoryOptions
        {
            Name = name,
            Description = desc
        });
    }).ToArray();
}
```

The point: any C# object with methods → AI tools. No framework coupling. Just reflection + attributes.

### What This Means for LogiCore as a Portfolio Piece

LogiCore is built in Python (FastAPI + LangGraph). That's the right choice for demonstrating RAG/agent concepts. But the **architect perspective** is:

> "If your enterprise runs .NET, you don't need to rewrite anything in Python. Add Microsoft.Extensions.AI to your existing app. Your existing services become AI tools. Same DI, same auth, same deployment. 20 lines of glue code."

This is the kind of thing a CTO hires a €1,200/day architect to say — not "rewrite everything in Python." The architect answer is always the smallest change that delivers the most value.

### Decision Framework: When to Use Which

| Enterprise Stack | Migration Pattern | Why |
|---|---|---|
| **.NET (ASP.NET, WCF, Azure)** | MAF in-process | Zero infra change, services become tools directly |
| **Java (Spring Boot)** | Spring AI (similar concept) | Java equivalent of MAF, same in-process pattern |
| **Python (Django, Flask)** | LangChain/LangGraph directly | Already in the right ecosystem |
| **SAP / Oracle / Legacy** | API Gateway or Kafka Event Bridge | No AI SDK available, HTTP/events are the only option |
| **Mainframe (COBOL)** | API Gateway + screen scraping or MQ | Wrap in REST, then connect |

## Integration Patterns (non-.NET systems)

### 1. API Gateway Pattern (for SAP, Oracle, mainframes)

When MAF isn't an option (non-.NET stack), LogiCore runs as a sidecar service:

```
[Existing ERP/SAP] → HTTP → [LogiCore API] → [RAG / Agents / Fleet]
                                   ↓
                            [Response back to ERP]
```

**What to build in LogiCore:**
- `apps/api/src/api/v1/integration/` — dedicated integration endpoints
- `POST /api/v1/integration/query` — universal query endpoint
- `POST /api/v1/integration/audit` — invoice audit trigger

**Why this pattern**: Zero changes to the legacy system. IT team adds one HTTP call.

### 2. Event Bridge Pattern (Kafka)

```
[SAP] → Kafka: erp.invoices.new → [LogiCore Consumer] → Audit → Kafka: logicore.audit.results → [SAP reads]
```

**Why**: Decoupled. If LogiCore is down, messages queue. No data loss.

### 3. Database View Pattern (BI tools)

```sql
CREATE VIEW v_audit_results AS
SELECT a.created_at, a.invoice_id, a.discrepancy_amount, a.status
FROM audit_log a WHERE a.status = 'completed';
```

Existing BI tools (Tableau, Power BI) query the view directly.

### 4. MCP Bridge Pattern (developer tools)

Phase 11 MCP servers. Same tools in LangGraph agents, Claude Code, Cursor IDE, and CI/CD.

## What NOT To Build

- **Don't build a full ERP connector** — that's a product, not a feature
- **Don't try to replace SAP/Oracle** — position AI as an augmentation layer
- **Don't build custom auth per integration** — standard JWT or API keys
- **Don't sync data bidirectionally** — AI reads from external systems, writes results back

## Files to Create

| File | Purpose |
|---|---|
| `apps/api/src/api/v1/integration/__init__.py` | Package init |
| `apps/api/src/api/v1/integration/query.py` | Universal query endpoint |
| `apps/api/src/api/v1/integration/audit.py` | External audit trigger |
| `apps/api/src/api/v1/integration/webhooks.py` | Callback endpoints for async workflows |
| `docs/adr/008-integration-patterns.md` | ADR: MAF in-process vs API gateway vs event bridge |

## When to Build This

After Phase 3 (agents working) and Phase 10 (security hardened). Integration endpoints are external-facing — they need full security stack before exposure.

The MAF section is documentation / positioning material — it demonstrates architect-level thinking about the .NET enterprise world without requiring actual .NET code in LogiCore.
