# LogiCore Content Strategy: AI Solution Architect Positioning

**Cosmos source**: `logicore-architect-positioning-2026-03` (knowledge-nodes, partition: content-strategy)

## The Shift

From "I built cool AI stuff" → "I design AI systems at the architecture level."

Every post answers: **"What would I advise a CTO to do and why?"**

## 5 Framing Rules

1. **Lead with business problem, not tech** — "A truck is stuck at the Swiss border" not "I implemented hybrid search"
2. **Show what you chose NOT to build** — ADRs are gold. "Why I rejected CrewAI" > "How I built with LangGraph"
3. **Cost modeling in every phase** — EUR per query, monthly infra, cost comparison. CTOs think in euros.
4. **Decision frameworks** — "When to use RAG vs fine-tuning" = pure architect content
5. **Non-happy-path** — What breaks, degradation strategy, SLAs. Planning for failure = architect thinking.

## Content Modes

| Mode | Ratio | Description |
|---|---|---|
| Builder Update | 4/5 posts | What you're building, what broke, what it costs |
| Business Bridge | 1/5 posts | For CTOs to share with their non-technical stakeholders |
| Architect Perspective | Standalone | Decision frameworks, migration, vendor lock-in, capacity |

## Architect Topics (all embedded in build docs)

| Topic | Where It Lives | CTO Question | What To Build |
|---|---|---|---|
| FinOps Deep Dive | `phase-4-trust-layer.md` → "Architect Perspective" section | "What's the total cost?" | Token budgets, model routing economics, break-even tables, CTO spreadsheet |
| Multi-Tenancy | `phase-1-corporate-brain.md` → "Architect Perspective" section | "Can this serve 50 clients?" | Qdrant tenant strategies, LangGraph state isolation, cost attribution |
| Capacity Planning | `phase-12-full-stack-demo.md` → "Architect Perspective" section | "What at 10x?" | Per-component scaling triggers, "don't scale yet" guide |
| Vendor Lock-In | `phase-12-full-stack-demo.md` → "Architect Perspective" section + `docs/architect-notes/vendor-lock-in-strategy.md` | "What if Qdrant doubles price?" | Abstraction layers, exit time per vendor, risk scenarios |
| Migration / Integration | `docs/architect-notes/migration-integration-strategy.md` | "How plug into SAP/Oracle?" | API gateway, Kafka event bridge, DB views, MCP bridge patterns |

## Claude Code Agents

| Agent | File | Use When |
|---|---|---|
| `linkedin-architect` | `.claude/agents/linkedin-architect.md` | Writing LinkedIn posts |
| `medium-architect` | `.claude/agents/medium-architect.md` | Writing Medium deep dives |
| `content-reviewer` | `.claude/agents/content-reviewer.md` | Reviewing any draft before publishing |

### Workflow

```
1. Pick a phase or topic
2. Spawn linkedin-architect → generates LinkedIn post + reply ammo
3. Spawn medium-architect → generates companion Medium article
4. Spawn content-reviewer → scores both drafts, flags issues
5. Fix issues → publish
```

## Brand

- Handle: @barski_io
- Headline: "AI Solution Architect | Building production AI systems for logistics & enterprise"
- Series: "LogiCore" (12 phases, each = LinkedIn post + Medium deep dive)
- Voice: See `docs/BARTEK-VOICE.md` in AgentHub or voice sections in agents

## Phase → Content Map

| Phase | LinkedIn Hook Direction | Medium Deep Dive |
|---|---|---|
| 1 | RBAC demo: same query, two users, different results | Hybrid Search + RBAC implementation guide |
| 2 | "Vector similarity is lying to you" | Chunking/re-ranking benchmark with real data |
| 3 | "Autonomous AI agents are a compliance nightmare" | LangGraph HITL implementation |
| 4 | "If you can't trace WHY your LLM answered, it's a liability" | LLMOps + semantic caching + FinOps |
| 5 | "Your LLM-as-Judge is biased" | Judge bias mitigation + drift detection |
| 6 | "Swiss banks can't use OpenAI" | Air-gapped deployment guide |
| 7 | "Our AI survived a 4-hour Azure outage" | Circuit breakers + model routing |
| 8 | "Article 12 compliance today" | Immutable audit logs + data lineage |
| 9 | "Batch processing is dead" | Event-driven AI with Kafka |
| 10 | "Your SQL Agent is a ticking time bomb" | 5-layer LLM firewall implementation |
| 11 | "We stopped building custom tool integrations" | MCP server implementation |
| 12 | "7 months ago I typed docker-compose up" | Full retrospective with real metrics |
| ADR | "Why I rejected CrewAI for enterprise agents" | Decision framework article |
| Standalone | "How to introduce RAG into a legacy enterprise stack" | Migration/integration guide |
| Standalone | "How I designed this so we can swap any component" | Vendor lock-in strategy |

## Mini-Series: "The Agent Reality Check" (4 posts)

Cross-cutting series pulling from multiple phases. Positioned as the **anti-hype take** on AI agents — not anti-agent, anti-naive-agent.

| # | Hook | Phases Used | Architect Take |
|---|---|---|---|
| 1 | "Everyone's building AI agents. Nobody's building them safely." | Phase 3 (HITL) + Phase 10 (firewall) | 5-layer defense around an agent with database access. Contrarian: agents are dangerous without architecture. |
| 2 | "The €3,000/day mistake: why your agent doesn't need an LLM." | Phase 9 (fleet guardian) | Two-tier: 99% rules, 1% LLM. Knowing when NOT to use an agent > knowing how to build one. |
| 3 | "Your agent crashed at 2 AM. Now what?" | Phase 3 (checkpointer) + Phase 7 (resilience) | State persistence, crash recovery, graceful degradation. Demo agents never handle this. |
| 4 | "Single agents are demos. Multi-agent orchestration is production." | Phase 3 (dynamic delegation) + Phase 9 (cross-session memory) | Fixed pipelines vs dynamic delegation, stateless vs memory-aware. LangGraph state machines vs "let agents chat." |

**Why this series works**: Everyone posting "I built an agent" has L1-L2 agency (single agent + tool loop). LogiCore has the patterns most people aren't building: crash-safe state machines, event-driven activation, cross-session memory, dynamic delegation, and cost-tiered processing. The series reframes what we already have rather than adding agents as a buzzword.
