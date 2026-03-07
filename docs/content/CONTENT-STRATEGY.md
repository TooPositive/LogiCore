# LogiCore Content Strategy: AI Solution Architect Positioning

## The Positioning

**AI Solution Architect** = the person who translates between "the CTO who says we need AI" and "the engineering team that needs to build it." The content must consistently show the layer ABOVE the code: business problems, trade-off reasoning, cost modeling, and "why NOT" decisions.

Every post answers: **"What should the business DO, and why this over the alternatives?"**

| Junior framing (NEVER) | Architect framing (ALWAYS) |
|---|---|
| "I built a RAG system with hybrid search" | "A logistics manager searches 'dangerous goods' and gets zero results. Here's the architecture decision that fixes this." |
| "BM25 is fine if users know exact terms" | "BM25 alone is NOT viable. Users never use document terminology. Period." |
| "Dense is better than BM25" | "Embeddings are mandatory. BM25's only role: supplementing dense search with code/ID precision." |
| "Latency is 3ms vs 151ms" | "The 50x latency gap is irrelevant — you cant ship a mode that returns garbage for half your queries to save 148ms." |
| "We tested 3 search modes" | "We proved that skipping embeddings saves ~0.02/1M tok but breaks 50% of real queries. That 'savings' makes the system unusable." |

## The LogiCore Series (12 Phases)

A 12-phase AI system for a logistics company (LogiCore Transport). Each phase tackles a real business problem. The series documents what works, what doesnt, and what it costs.

**Why logistics?** Overlapping complexity that stress-tests architecture: multilingual docs (Polish workers, English contracts, EU customs), strict access control, real-time fleet data, regulatory compliance (EU AI Act, GDPR), and cost pressure. Every architecture decision has immediate business consequences.

**Series structure**: Each post = one phase, framed as business problem + architecture decision. Posts reference each other (Phase 3 picks up where Phase 1's RAG reasoning boundary was found). LinkedIn post + companion Medium deep-dive for each phase.

## Six Architect Signals

EVERY piece of content must hit at least 3 (LinkedIn) or all 6 (Medium):

1. **Lead with business problem, not tech.** The hook makes a CTO nod. "A truck is stuck at the Swiss border because nobody can find the customs form" > "I built a RAG system."

2. **Show what you chose NOT to build and why.** Architects are defined by "no" decisions. Every ADR is a content hook.

3. **Cost modeling in EUR.** Per query, per agent run, monthly infra, comparison. CTOs hire architects who think in euros, not tokens.

4. **Decision frameworks with switch conditions.** "When to use hybrid vs dense-only — and the switch condition." This is what a consultant provides that a senior engineer doesnt.

5. **Failure modes and boundaries.** What breaks? When? Degradation strategy? "RAG cant reason — 0/3 on cross-doc queries. Thats not a bug, its a category boundary."

6. **Trade-off reasoning with data.** Not "hybrid is best" but the specific evidence with the specific business consequence.

## The Architect Story Arc

Each phase tells a STORY, not a report:

1. **BUSINESS CRISIS**: Specific LogiCore Transport scenario where someone cant do their job
2. **WHY THIS IS HARD**: Technical constraint that makes naive solutions fail
3. **WHAT WE TRIED FIRST**: And why it didnt work (with numbers)
4. **THE ARCHITECTURE DECISION**: What we chose, what we rejected, the decision framework
5. **THE EVIDENCE**: Benchmarks framed as proof the decision was right
6. **THE COST**: EUR modeling, comparison with alternatives, cost of wrong decision
7. **WHAT BREAKS**: Boundaries found, failure modes, degradation strategy
8. **THE SWITCH CONDITION**: When should someone revisit this decision?
9. **WHATS NEXT**: Teaser for next phase, framed as business problem

## Zero Hallucination Protocol

**"NOT KNOWING > LYING."** Better to write "untested" or "boundary unknown" than invent a result.

### Auto-Stop Triggers

1. **Is this number from the tracker?** Cant point to exact file -> DONT WRITE IT
2. **Is this code from the codebase?** Pseudocode -> DONT WRITE IT
3. **Am I inventing a scenario?** -> STOP. Only from phase docs or test cases.
4. **Am I extrapolating?** Flag as assumption, dont state as fact.
5. **Am I inflating?** "Groundbreaking" -> STOP.

| Allowed | NOT Allowed |
|---------|-------------|
| Number from tracker benchmarks | "Probably around X" |
| Code from `apps/api/src/` | Pseudocode or simplified version |
| Test result from actual run | "Should work" or "would likely" |
| Cost calculated with shown math | Rounded costs without math |
| Scenario from phase spec docs | Made-up business story |
| Boundary found during testing | Assumed boundary from theory |

## Judge Verification

Score each dimension 1-5 BEFORE publishing. Fix anything below 4.

1. **FACT ACCURACY** (35%): Every number from tracker? Code from codebase? Cost with math?
2. **VOICE AUTHENTICITY** (25%): Sounds like Bartek? 3+ markers? Zero banned patterns?
3. **ARCHITECT POSITIONING** (25%): Business-first? Rejection reasoning? EUR cost? Failure modes? Decision framework?
4. **HALLUCINATION RISK** (15%): Zero invented claims? Assumptions flagged?

- ALL >= 4: Publish
- Any 3: Fix and re-score
- Any <= 2: Rewrite from scratch

## Banned Patterns

### AI sentence patterns (INSTANT KILL)
- "Here's the thing:", "Let me explain:", "Not only X, but also Y"
- "What's more/interesting/important," as openers
- "It's worth noting that...", "In today's world..."
- "...highlighting the importance of...", "...showcasing the power of..."
- Rule of three: "speed, quality, and reliability"
- Em dashes for dramatic effect
- "It's not just about X, it's about Y"
- "In this article we will explore..." / "In conclusion,"
- Thread-bait: "I spent 6 months building X. Here's what I learned:"
- Numbered lists in LinkedIn body

### AI vocabulary (NEVER use)
- "delve", "landscape", "leverage", "foster", "crucial", "pivotal", "paradigm"
- "groundbreaking", "game-changing", "revolutionary", "cutting-edge"
- "harness", "synergy", "holistic", "transformative", "utilize"
- "robust", "seamless", "comprehensive" (as filler)
- "exciting times ahead", "stay tuned", "watch this space"

### Inflated framing
- "Nobody else is doing this" (say "less common")
- Any superlative without data
- Promotional language

## Content Modes

| Mode | Ratio | Description |
|---|---|---|
| Builder Update | 4/5 posts | What youre building, what broke, what it costs |
| Business Bridge | 1/5 posts | For CTOs to share with non-technical stakeholders |
| Architect Perspective | Standalone | Decision frameworks, migration, vendor lock-in |

## Accuracy Modes

| Mode | Truth | Best for |
|---|---|---|
| Full spicy | 80% | Reach. Nuance in replies. |
| Accurate-but-exciting | 95% | DEFAULT. Credibility + engagement. |
| Pure accurate | 100% | Niche/technical audience. |

## LinkedIn Post Rules

- Hook (<210 chars): business problem or counterintuitive finding, NEVER "I built X"
- After hook: brief series intro (1-2 sentences about 12-phase series + why logistics)
- No headers, no bold, no bullets. Flows like a message.
- Voice: casual dev-to-dev. "coz", parenthetical asides, honest hedging, 1-2 emoji max
- Must include at least ONE EUR cost figure
- Must include at least ONE "we chose NOT to do X because Y"
- Must include at least ONE boundary/failure mode
- Close with series position + next phase teaser (casual, not salesy)
- Reply ammo: 8-10 predicted objections with architect-level responses

## Medium Article Rules

- Title: specific claim, not description. "Embeddings Are Mandatory" not "Building a RAG System"
- 2,000-4,000 words
- Real code from codebase (max 4-5 blocks, each with architectural reasoning)
- Must include ALL 6 architect signals
- Must include comparison table (chose X vs rejected Y vs why)
- Must include vendor lock-in awareness with swap costs
- Must include "What Id Do Differently" with architect reflections
- Series context in intro + series close

## Claude Code Agents

| Agent | File | Use When |
|---|---|---|
| `linkedin-architect` | `.claude/agents/linkedin-architect.md` | Writing LinkedIn posts |
| `medium-architect` | `.claude/agents/medium-architect.md` | Writing Medium deep dives |
| `content-reviewer` | `.claude/agents/content-reviewer.md` | Reviewing any draft before publishing |

### Workflow

```
1. /write-phase-post {N}  (or manually: pick phase, read sources, write both)
2. Self-score with Judge Verification
3. Fix anything below 4/5
4. Optional: spawn content-reviewer for independent quality gate
5. Publish
```

## Brand

- Handle: @barski_io
- Headline: "AI Solution Architect | Building production AI systems for logistics & enterprise"
- Series: "LogiCore" (12 phases, each = LinkedIn post + Medium deep dive)
- Voice: `docs/BARTEK-VOICE.md`

## Phase-to-Content Map

| Phase | LinkedIn Hook Direction | Medium Deep Dive | Series Close Teaser |
|---|---|---|---|
| 1 | Business pain: search that fails real humans (Polish, typos, synonyms) | Hybrid Search + RBAC: embeddings mandatory, BM25 is lookup | Phase 2: "your chunks are wrong and re-ranking matters more than you think" |
| 2 | "Vector similarity is lying to you" | Chunking/re-ranking benchmark | Phase 3: "what happens when search works but the AI cant reason across docs" |
| 3 | "Autonomous AI agents are a compliance nightmare" | LangGraph HITL | Phase 4: "you cant trace why your AI answered. thats a liability." |
| 4 | "If you cant trace WHY your LLM answered, its a liability" | LLMOps + semantic caching + FinOps | Phase 5: "your LLM-as-Judge is biased. heres the data." |
| 5 | "Your LLM-as-Judge is biased" | Judge bias mitigation + drift detection | Phase 6: "Swiss banks cant use OpenAI. now what?" |
| 6 | "Swiss banks cant use OpenAI" | Air-gapped deployment guide | Phase 7: "what happens when Azure goes down for 4 hours?" |
| 7 | "Our AI survived a 4-hour Azure outage" | Circuit breakers + model routing | Phase 8: "Article 12 compliance isnt optional anymore" |
| 8 | "Article 12 compliance today" | Immutable audit logs + data lineage | Phase 9: "batch processing is dead for fleet monitoring" |
| 9 | "Batch processing is dead" | Event-driven AI with Kafka | Phase 10: "your SQL agent is a ticking time bomb" |
| 10 | "Your SQL Agent is a ticking time bomb" | 5-layer LLM firewall | Phase 11: "we stopped building custom tool integrations" |
| 11 | "We stopped building custom tool integrations" | MCP server implementation | Phase 12: "the full retrospective with real numbers" |
| 12 | "7 months ago I typed docker-compose up" | Full retrospective with metrics | Series complete |
| ADR | "Why I rejected CrewAI for enterprise agents" | Decision framework article | — |
| Standalone | "How to introduce RAG into a legacy stack" | Migration/integration guide | — |
| Standalone | "I designed this so we can swap any component" | Vendor lock-in strategy | — |

## Mini-Series: "The Agent Reality Check" (4 posts)

Cross-cutting series pulling from multiple phases. Anti-hype take on AI agents.

| # | Hook | Phases | Architect Take |
|---|---|---|---|
| 1 | "Everyone's building AI agents. Nobody's building them safely." | 3 + 10 | 5-layer defense. Agents are dangerous without architecture. |
| 2 | "The 3,000/day mistake: your agent doesnt need an LLM." | 9 | Two-tier: 99% rules, 1% LLM. |
| 3 | "Your agent crashed at 2 AM. Now what?" | 3 + 7 | State persistence, crash recovery. |
| 4 | "Single agents are demos. Multi-agent is production." | 3 + 9 | Dynamic delegation, cross-session memory. |

## The Content Chain

Tracker conclusions -> `/phase-review` catches junior framing -> fixed tracker -> content agents read tracker -> LinkedIn/Medium posts. If the tracker says "BM25 is viable," the post will too — and every CTO reading it will think "this person doesnt understand enterprise search." Fix framing at the source.
