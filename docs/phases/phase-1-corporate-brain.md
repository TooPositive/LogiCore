# Phase 1: "The Corporate Brain" — Advanced RAG & Data Integration

## Business Problem

Logistics enterprises sit on mountains of unstructured data — HR manuals, legal contracts, safety protocols, customs regulations. Employees waste hours searching SharePoint. When they do find answers, there's no guarantee the AI didn't hallucinate or leak data across departments.

**CTO pain**: "Our AI chatbot told a warehouse worker about the CEO's compensation package. We need zero-trust retrieval."

## Architecture

```
User Query → API Gateway (JWT auth)
  → Query Router (keyword vs semantic vs hybrid)
    → Qdrant Hybrid Search (BM25 + Dense vectors)
      → RBAC Filter (clearance_level + department_id metadata)
        → Context Assembly (ranked chunks)
          → Azure OpenAI (GPT-4o)
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

### Success Criteria
- [ ] `curl POST /api/v1/ingest` — ingests mock contract, returns chunk count
- [ ] `curl POST /api/v1/search` as warehouse worker — does NOT return CEO-level docs
- [ ] `curl POST /api/v1/search` as HR director — returns all HR docs
- [ ] Hybrid search returns exact matches for "ISO-9001" (BM25) AND semantic matches for "quality standards" (dense)
- [ ] Langfuse trace shows full retrieval pipeline with timing
- [ ] Unit tests pass for RBAC filtering edge cases

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

## Key Metrics to Screenshot
- Qdrant dashboard showing hybrid search collection stats
- Langfuse trace showing retrieval pipeline with per-step latency
- Before/after: pure vector search vs hybrid search precision on keyword queries
- RBAC demo: same query, two users, different results
