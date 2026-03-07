# Phase 1: "The Corporate Brain" — Advanced RAG & Data Integration

## Business Problem

Logistics enterprises sit on mountains of unstructured data — HR manuals, legal contracts, safety protocols, customs regulations. Employees waste hours searching SharePoint. When they do find answers, there's no guarantee the AI didn't hallucinate or leak data across departments.

**CTO pain**: "Our AI chatbot told a warehouse worker about the CEO's compensation package. We need zero-trust retrieval."

## Real-World Scenario: LogiCore Transport

**Feature: Document Search Portal**

Warehouse worker Max Weber (clearance 1) searches "ISO-9001 quality requirements" in the LogiCore AI assistant. He sees the ISO 9001 Quality Manual (DOC-SAFETY-001) and the Driver Safety Protocol (DOC-HR-003) — both clearance level 1, both relevant.

HR director Katrin Fischer (clearance 3) searches the same query. She sees everything Max sees, PLUS the Termination Procedures (DOC-HR-004, clearance 3) because her clearance is higher.

CEO Eva Richter (clearance 4) searches "compensation" — she sees the Executive Compensation Policy (DOC-HR-002, clearance 4). Max searches the same word — zero results. The AI didn't refuse him. It never saw the document at all.

Meanwhile, logistics manager Anna Schmidt searches "CTR-2024-001 penalty clause" — hybrid search finds the PharmaCorp contract using BM25 exact match on the contract ID, not just semantic similarity.

**The "aha" moment for the demo**: Same search bar, same AI, different results based on who's logged in. The LLM never sees unauthorized documents — they're filtered at the database level before the AI even runs.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Hybrid Search (BM25 + dense vectors) | Finds "ISO-9001" by exact code AND "quality standards" by meaning | Employees find docs whether they know the exact term or describe what they need |
| RBAC metadata filtering | Max sees 3 docs, Katrin sees 5, Eva sees all 12 | Zero risk of AI leaking confidential docs to wrong employee |
| Qdrant vector database | Sub-second search across 10K+ documents | Replaces hours of SharePoint searching |
| Alpha weighting | Search quality tuning per query type | Acronyms and part numbers always found (not lost in semantic noise) |

## Architecture

```
User Query → API Gateway (JWT auth)
  → Query Router (keyword vs semantic vs hybrid)
    → Qdrant Hybrid Search (BM25 + Dense vectors)
      → RBAC Filter (clearance_level + department_id metadata)
        → Context Assembly (ranked chunks)
          → LLM (GPT-5 mini for simple lookups / GPT-5.2 for complex reasoning)
            → Response + Source Citations
              → Langfuse Trace (full audit log)
```

**Key design decisions**:
- Hybrid search (not pure vector) — acronyms like "ISO-9001" and part numbers need exact BM25 matching
- RBAC at retrieval level, not prompt level — the LLM never sees unauthorized documents
- Alpha weighting between dense/sparse vectors tunable per query type

## Implementation Guide

### Prerequisites
- Docker Compose services running: `qdrant`, `postgres`, `redis`
- Azure OpenAI deployment configured in `.env`
- Phase 0 (this skeleton) complete

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/rag/__init__.py` | Package init |
| `apps/api/src/rag/ingestion.py` | Document chunking + embedding pipeline |
| `apps/api/src/rag/retriever.py` | Hybrid search with RBAC filtering |
| `apps/api/src/rag/embeddings.py` | Azure OpenAI embedding wrapper |
| `apps/api/src/infrastructure/qdrant/client.py` | Qdrant connection + collection setup |
| `apps/api/src/infrastructure/qdrant/collections.py` | Collection schemas (dense + sparse vectors) |
| `apps/api/src/security/rbac.py` | User clearance level + department resolution |
| `apps/api/src/api/v1/search.py` | POST /api/v1/search endpoint |
| `apps/api/src/api/v1/ingest.py` | POST /api/v1/ingest endpoint |
| `apps/api/src/domain/document.py` | Document, Chunk, SearchResult models |
| `data/mock-contracts/` | 5-10 mock PDF contracts with varying clearance levels |
| `scripts/seed_documents.py` | Ingestion script for mock data |
| `tests/unit/test_retriever.py` | RBAC filtering tests |
| `tests/integration/test_search_e2e.py` | End-to-end search with Qdrant |

### Technical Spec

**API Endpoints**:

```
POST /api/v1/ingest
  Request: { "file_path": str, "department_id": str, "clearance_level": int }
  Response: { "document_id": str, "chunks_created": int }

POST /api/v1/search
  Request: { "query": str, "user_id": str, "top_k": int }
  Response: { "results": [{ "content": str, "score": float, "source": str }] }
```

**Qdrant Collection Schema**:
```python
{
    "collection_name": "corporate_knowledge",
    "vectors": {
        "dense": { "size": 1536, "distance": "Cosine" },  # text-embedding-3-small
    },
    "sparse_vectors": {
        "bm25": {}  # SPLADE sparse embeddings
    },
    "payload_schema": {
        "department_id": "keyword",
        "clearance_level": "integer",
        "document_id": "keyword",
        "source_file": "keyword",
        "chunk_index": "integer"
    }
}
```

**RBAC Filter Logic**:
```python
# Applied at Qdrant query time — LLM never sees filtered-out docs
filter = models.Filter(
    must=[
        models.FieldCondition(key="department_id", match=models.MatchAny(any=user.departments)),
        models.FieldCondition(key="clearance_level", range=models.Range(lte=user.clearance_level)),
    ]
)
```

## Decision Framework: Model Selection for RAG

### Which model generates the RAG answer?

| Query Type | Model | Cost/query | When |
|---|---|---|---|
| Simple lookup ("What's our Zurich office address?") | GPT-5 nano ($0.05/$0.40 per 1M tok) | ~€0.00004 | Answer is directly in the retrieved chunk, no reasoning needed |
| Standard RAG ("What are PharmaCorp delivery penalties?") | GPT-5 mini ($0.25/$2.00 per 1M tok) | ~€0.003 | Summarize/synthesize 3-5 chunks, moderate reasoning |
| Complex multi-hop ("Compare penalty clauses across all Q4 contracts and flag outliers") | GPT-5.2 ($1.75/$14.00 per 1M tok) | ~€0.02 | Cross-document reasoning, comparison, inference |
| Compliance-critical / judge ("Does this clause violate EU regulation X?") | Claude Opus 4.6 ($5.00/$25.00 per 1M tok) | ~€0.06 | Highest accuracy required, legal/financial stakes |

**Cost impact**: A naive "use GPT-5.2 for everything" approach costs ~€0.02/query. Routing 80% of queries through GPT-5 nano/mini drops average cost to ~€0.002/query — a 10x reduction at scale.

**Implementation**: The Query Router (line 2 of the architecture) classifies query complexity using GPT-5 nano ($0.00002/classification) and routes to the appropriate generation model.

### Alpha Weighting: BM25 vs Dense — How to Choose

The `alpha` parameter controls the blend: `alpha=1.0` = pure dense (semantic), `alpha=0.0` = pure BM25 (keyword).

| Query Pattern | Alpha | Reasoning |
|---|---|---|
| Exact codes/IDs ("ISO-9001", "CTR-2024-001") | 0.2 | BM25 dominates — exact string match is critical |
| Natural language ("what are our delivery obligations?") | 0.8 | Dense dominates — semantic similarity matters |
| Mixed ("PharmaCorp penalty clause") | 0.5-0.6 | Both matter — entity name (BM25) + concept (dense) |

**How to tune**: Start at `alpha=0.6` (the literature default). Run your benchmark queries. If exact-match queries fail, lower alpha. If semantic queries fail, raise it. Log alpha per query type in Langfuse and A/B test.

**Don't over-tune**: The difference between 0.55 and 0.65 is negligible. The difference between 0.2 and 0.8 is massive. Pick a lane per query category, not per query.

### When NOT to Use RAG

RAG adds latency (~200-500ms for retrieval) and cost (embedding + search + generation). Sometimes simpler is better.

| Situation | Better Alternative | Why |
|---|---|---|
| Structured data ("How many invoices this month?") | SQL query (direct or via SQL Agent) | Data is already structured — vectorizing it loses precision |
| Real-time data ("Current warehouse temperature") | API call / sensor feed | RAG indexes are stale by definition (minutes to hours) |
| Simple key-value lookup ("What's driver ID for Jan Kowalski?") | Cache / database lookup | Sub-millisecond vs 300ms RAG round-trip |
| Repetitive identical queries | Response cache (Redis) | Same question → same answer, no need to re-retrieve |
| Data already in the prompt / session | Just use context window | Don't retrieve what you already have |

**Rule of thumb**: If the answer lives in a database column, use SQL. If it lives in a document paragraph, use RAG. If it lives in both, use RAG with SQL tool access.

### Success Criteria
- [ ] `curl POST /api/v1/ingest` — ingests mock contract, returns chunk count
- [ ] `curl POST /api/v1/search` as warehouse worker — does NOT return CEO-level docs
- [ ] `curl POST /api/v1/search` as HR director — returns all HR docs
- [ ] Hybrid search returns exact matches for "ISO-9001" (BM25) AND semantic matches for "quality standards" (dense)
- [ ] Langfuse trace shows full retrieval pipeline with timing
- [ ] Unit tests pass for RBAC filtering edge cases

## Cost of Getting It Wrong

Operating cost is EUR 0.003/query. Error cost is 10,000x-100,000x higher.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **RBAC leak** | Bug passes empty department list → Qdrant interprets as "no filter" → clearance-1 user sees CEO compensation | EUR 25,000-250,000 (GDPR fine + lawsuit + contract breach) | 1 incident = career-ending |
| **Wrong alpha weight** | Alpha too high on safety query → semantic match beats exact clause → worker follows wrong safety procedure | EUR 0-500,000 (physical safety incident) | Depends on query mix |
| **Hallucinated rate** | LLM invents penalty rate "10%" when clause says "15%" → manager uses in negotiation → PharmaCorp notices | EUR 486/shipment + relationship damage | 2-3/month without re-ranking |
| **Stale document** | Contract amended but old version in Qdrant → AI cites superseded clause → finance disputes wrong terms | EUR 500-2,000 per dispute + vendor trust | 1-2/month |

**The CTO line**: "A single RBAC failure that leaks executive compensation to the warehouse floor costs more in lawsuits and GDPR fines than 10 years of operating the entire AI system."

### Defense-in-Depth RBAC (not just retrieval filtering)

Phase 1's RBAC filter at Qdrant is the primary defense. But a single filter is a single point of failure. Add a secondary check:

```python
# Context assembly — verify BEFORE sending to LLM
def assemble_context(chunks: list[Chunk], user: User) -> list[Chunk]:
    """Defense-in-depth: verify clearance AGAIN at assembly time."""
    safe_chunks = [c for c in chunks if c.clearance_level <= user.clearance_level]
    if len(safe_chunks) < len(chunks):
        logger.warning(f"RBAC assertion caught {len(chunks) - len(safe_chunks)} unauthorized chunks for user {user.id}")
    return safe_chunks
```

If this assertion EVER fires in production, you have a Qdrant filter bug. Log it as a P0 security incident.

## Cross-Phase Risk: Retrieval Quality → Financial Accuracy

Phase 1 retrieval quality is the foundation for Phase 3 (invoice audit). The cascade:

```
Wrong hybrid search result (Phase 1)
  → Wrong contract clause retrieved
    → Reader Agent extracts wrong rate (Phase 3)
      → Auditor calculates wrong discrepancy
        → Auto-approved at <1% band (false negative)
          → EUR 136-588 per invoice walks out the door silently
```

At 1,000 invoices/month with a 2.5% false negative rate from retrieval errors, that's EUR 40,800/year in unrecovered overcharges — 7,350x the EUR 5.56/month operating cost of Phase 3.

## LinkedIn Post Template

### Hook
"90% of enterprise RAG prototypes never make it to production. Here's why your vector database is lying to you."

### Body
Most teams build RAG with pure semantic search. Works great in demos. Fails catastrophically when a warehouse worker asks about "ISO-9001 Section 4.2" and gets hallucinated answers because vector similarity can't do exact keyword matching.

The fix: Hybrid Search. BM25 for exact terms (part numbers, legal article refs, acronyms) + dense vectors for semantic meaning. Alpha-weighted at query time.

But that's only half the problem. The other half? Your intern just queried the CEO's compensation package through your "helpful AI assistant."

Zero-trust RBAC at the vector database level. Every chunk tagged with `clearance_level` and `department_id`. The LLM never sees documents outside the user's authorization tier. Not filtered after retrieval — filtered BEFORE retrieval.

### Visual
Architecture diagram: "Basic RAG" (single vector path) vs "Enterprise RAG" (hybrid search + RBAC filter layer + audit log)

### CTA
"Building enterprise RAG and hitting retrieval quality issues? Drop 'RAG' in the comments — I'll share the hybrid search configuration that fixed ours."

## Architect Perspective: Multi-Tenancy Extension

Phase 1 serves one company (LogiCore Transport). Real enterprise/SaaS deployments serve multiple clients. Here's how this architecture extends to multi-tenancy.

### The Problem

A logistics platform serving 50 clients. Each client has:
- Their own contracts, invoices, documents (data isolation)
- Different clearance level structures (RBAC per tenant)
- Different model budgets (PharmaCorp pays for GPT-5.2, small clients get GPT-5 nano)
- Different compliance requirements (Swiss client = air-gapped, Polish client = cloud OK)

### Qdrant Multi-Tenancy Strategy

**Option A: Collection-per-tenant** (strong isolation, higher overhead)
```python
# Each tenant gets their own Qdrant collection
collection_name = f"knowledge_{tenant_id}"  # knowledge_pharma, knowledge_fresh
# Pro: complete data isolation, per-tenant index tuning
# Con: 50 collections = 50x memory overhead for HNSW indexes
# When: regulated industries (banking, pharma) where data must be physically separated
```

**Option B: Shared collection + tenant metadata filter** (efficient, logical isolation)
```python
# Single collection, tenant_id as payload field
filter = models.Filter(must=[
    models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
    models.FieldCondition(key="clearance_level", range=models.Range(lte=user.clearance)),
])
# Pro: efficient memory usage, simpler management
# Con: logical isolation only — bugs could leak data across tenants
# When: most SaaS deployments where tenants accept shared infrastructure
```

**Option C: Hybrid** (recommended for enterprise)
```python
# Tier 1 clients (regulated): dedicated collection
# Tier 2 clients (standard): shared collection with tenant filter
# Best of both worlds — premium clients get isolation, standard clients get efficiency
```

### LangGraph State Isolation

```python
# Thread ID includes tenant for state isolation
thread_id = f"{tenant_id}:{workflow_id}"
# PostgreSQL checkpointer uses tenant_id in partition key
# Each tenant's workflow state is physically separated
```

### Cost Attribution Per Tenant

```python
# Every Langfuse trace tagged with tenant_id
trace = langfuse.trace(name="search", metadata={"tenant_id": tenant_id})
# Monthly cost report per tenant:
# PharmaCorp: 1,200 queries × €0.016 = €19.20/mo (GPT-5.2 reasoning)
# FreshFoods:   800 queries × €0.0005 = €0.40/mo (GPT-5 nano, simple lookups)
# ChemTrans:    300 queries × €0.003 = €0.90/mo (GPT-5 mini, summaries)
```

### When to Build This

**Don't build multi-tenancy until you have 2+ paying clients.** Premature multi-tenancy adds 3-4 weeks of engineering for a problem that doesn't exist yet. The architecture supports it (metadata filters, tenant-tagged traces) but the implementation should wait.

## Key Metrics to Screenshot
- Qdrant dashboard showing hybrid search collection stats
- Langfuse trace showing retrieval pipeline with per-step latency
- Before/after: pure vector search vs hybrid search precision on keyword queries
- RBAC demo: same query, two users, different results
