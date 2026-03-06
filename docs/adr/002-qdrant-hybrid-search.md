# ADR-002: Qdrant with Hybrid Search

## Status
Accepted

## Context
Enterprise document retrieval for HR manuals, legal contracts, customs regulations. Must handle exact keyword matching (ISO codes, part numbers, legal article references) AND semantic similarity.

## Decision
**Qdrant** with hybrid search (dense vectors + sparse BM25 via SPLADE).

## Rationale

| Criteria | Qdrant | Pinecone | Milvus |
|----------|--------|----------|--------|
| Hybrid search | Native (dense + sparse) | Sparse via metadata | Supported |
| Self-hosted | Yes (Docker) | Cloud only | Yes |
| RBAC filtering | Payload-based filtering | Namespace-based | Expression filters |
| Cost | Free (self-hosted) | Per-query pricing | Free (self-hosted) |
| Maturity | Production-ready, v1.13 | Production-ready | Complex setup |

## Consequences
- Must manage infrastructure (mitigated by Docker Compose)
- Sparse vectors (SPLADE) require separate embedding model
- Alpha weighting between dense/sparse needs tuning per corpus
- Payload filtering enables per-document RBAC without index duplication
