# Phase 8 Technical Recap: Regulatory Shield — EU AI Act Compliance

## What This Phase Does (Business Context)

A Polish logistics company running AI-powered invoice auditing, fleet management, and HR screening faces EU AI Act Article 12: every high-risk AI decision must be automatically recorded and reconstructable. If a regulator asks "what did the AI do on September 15th?" you need to answer in minutes, not weeks. Phase 8 builds the immutable compliance logging layer that makes that possible while simultaneously satisfying GDPR deletion rights — two regulations that directly contradict each other when your audit log contains personal data.

## Architecture Overview

```
AI Decision (RAG query, invoice audit, fleet alert)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  atomic_audit_write (same asyncpg transaction)          │
│  ┌──────────────────┐  ┌──────────────────────────────┐ │
│  │ LangGraph         │  │ AuditLogger                  │ │
│  │ Checkpointer      │  │  ├─ write_with_hash_chain()  │ │
│  │ .save(state)      │  │  ├─ entry_hash (SHA-256)     │ │
│  └──────────────────┘  │  └─ prev_entry_hash (chain)   │ │
│         ▲               └──────────────────────────────┘ │
│         │               Both succeed or both roll back    │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  PostgreSQL                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ audit_log   │  │ audit_pii_   │  │ document_      │  │
│  │ (APPEND     │  │ vault        │  │ versions       │  │
│  │  ONLY)      │  │ (GDPR soft-  │  │ chunk_versions │  │
│  │ REVOKE      │  │  delete)     │  │ (lineage)      │  │
│  │ UPDATE,     │  │ AES-256-GCM  │  │                │  │
│  │ DELETE      │  │ encrypted    │  │                │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                          │
│  Layer 1: DB REVOKE (prevents application tampering)     │
│  Layer 3: Hash chain (proves no rows were modified)      │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  Application Layer                                       │
│  ┌──────────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ AuditEntry   │  │ AuditRBAC │  │ BiasDetector     │  │
│  │ (frozen      │  │ (4 roles, │  │ (>2x threshold,  │  │
│  │  Pydantic)   │  │  least    │  │  n≥30 minimum)   │  │
│  │              │  │  privilege)│  │                  │  │
│  │ Layer 2:     │  └───────────┘  └──────────────────┘  │
│  │ Immutable in │                                        │
│  │ memory       │  ┌───────────┐  ┌──────────────────┐  │
│  └──────────────┘  │ Langfuse  │  │ Compliance       │  │
│                    │ Snapshot  │  │ Report Generator  │  │
│                    │ (SPOF     │  │ (entry_count_    │  │
│                    │  removal) │  │  hash for         │  │
│                    └───────────┘  │  completeness)    │  │
│                                   └──────────────────┘  │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│  API Layer (5 endpoints)                                 │
│  GET /audit-log (RBAC-filtered)                          │
│  GET /report (compliance_officer/admin only)             │
│  GET /lineage/{doc_id}                                   │
│  GET /hash-chain/verify                                  │
│  POST /bias-report (compliance_officer/admin only)       │
└──────────────────────────────────────────────────────────┘
```

## Components Built

### 1. Compliance Models: `apps/api/src/domains/logicore/models/compliance.py`

**What it does**: Defines 8 Pydantic models (AuditEntryCreate, AuditEntry, ComplianceReport, DocumentVersion, ChunkVersion, LineageRecord, PIIVaultEntry, LogLevel) that enforce the data contracts for the entire compliance layer.

**The pattern**: **Frozen Model (Immutability by Construction)**. AuditEntry uses `model_config = {"frozen": True}` so once created, no field can be mutated in application memory. This is Layer 2 of the three-layer immutability model.

**Key code walkthrough**:

```python
# apps/api/src/domains/logicore/models/compliance.py:73-80
class AuditEntry(BaseModel):
    """Full audit log entry -- immutable after creation.

    Frozen: fields cannot be modified after construction.
    This mirrors the database constraint (REVOKE UPDATE/DELETE).
    """
    model_config = {"frozen": True}
```

The separation of `AuditEntryCreate` (mutable input) from `AuditEntry` (frozen output) is deliberate. The caller provides content fields; the server adds `id`, `created_at`, and `entry_hash`. This prevents callers from setting server-controlled fields like the hash.

**Why it matters**: Without frozen models, a bug in the report generator or RBAC filter could accidentally mutate an entry in memory — corrupting data passed to subsequent operations in the same request. Frozen models make this class of bug impossible at the type level.

**Alternatives considered**: Could have used `@dataclass(frozen=True)` instead of Pydantic. Chose Pydantic because the rest of the codebase uses it, it gives us validation (`Field(ge=0)`, `model_validator`), and JSON serialization for free via `model_dump(mode="json")`.

### 2. Audit Logger: `apps/api/src/domains/logicore/compliance/audit_logger.py`

**What it does**: Writes, reads, and verifies immutable audit log entries using parameterized SQL. Contains the hash chain writer (`write_with_hash_chain`) and verifier (`verify_hash_chain`). Also contains the `atomic_audit_write` function that coordinates checkpoint + audit in a single transaction.

**The pattern**: **Connection Injection (not Pool Injection)**. Every method accepts an `asyncpg` connection, not a pool. This is the architectural key that enables atomic transactions — the caller `pool.acquire()`s a connection, opens a transaction, and passes that same connection to both the checkpointer and the audit logger.

**Key code walkthrough — Hash chain write (the hardest part)**:

```python
# apps/api/src/domains/logicore/compliance/audit_logger.py:302-380
async def write_with_hash_chain(self, conn, entry: AuditEntryCreate) -> AuditEntry:
    # Step 1: Acquire advisory lock to serialize concurrent writers
    await conn.execute(f"SELECT pg_advisory_xact_lock({_HASH_CHAIN_LOCK_ID})")

    # Step 2: Read the last entry's hash (None if chain is empty)
    prev_hash = await conn.fetchval(_SELECT_LAST_ENTRY_HASH_SQL)

    # Step 3: Compute chain hash
    query_hash = hashlib.sha256(entry.query_text.encode("utf-8")).hexdigest()
    response_hash_val = hashlib.sha256(entry.response_text.encode("utf-8")).hexdigest()

    # CRITICAL: Use the SAME timestamp for hash computation and DB INSERT.
    now = datetime.now(UTC)

    chain_hash = compute_chain_hash(
        prev_hash=prev_hash, created_at=now, user_id=entry.user_id,
        query_hash=query_hash, response_hash=response_hash_val,
        model_version=entry.model_version,
    )

    # Step 4: Write with chain fields + explicit created_at ($20)
    row = await conn.fetchrow(
        _INSERT_WITH_TIMESTAMP_SQL,
        entry.user_id,        # $1
        # ... $2-$19 ...
        now,                  # $20 -- explicit created_at
    )
    return _row_to_audit_entry(row)
```

**Why the `$20` parameter is critical**: The original code relied on PostgreSQL `DEFAULT NOW()` for `created_at`. But `datetime.now(UTC)` in Python and `NOW()` in PostgreSQL differ by microseconds-to-milliseconds. When `verify_hash_chain` recomputes the hash using the DB-stored `created_at`, it gets a different timestamp than what was used in `compute_chain_hash`. Result: every single entry appears tampered on real PostgreSQL. The fix passes the same Python `now` as both the hash input and the `$20` INSERT parameter. One clock, not two.

**Key code walkthrough — Atomic write**:

```python
# apps/api/src/domains/logicore/compliance/audit_logger.py:428-453
async def atomic_audit_write(conn, checkpoint_fn, audit_entry):
    logger = AuditLogger()
    async with conn.transaction():
        await checkpoint_fn(conn)
        return await logger.write(conn, audit_entry)
    # Both succeed or both roll back
```

This is 6 lines that prevent a EUR 3.5M fine. Without the shared transaction, a crash between `checkpoint_fn` and `logger.write` creates a compliance gap: the workflow resumes (checkpoint survived) but the audit entry was never written. The gap might not be discovered until a regulator asks about it months later.

**Alternatives considered**: Could have used a separate "audit worker" that reads from an event queue. Rejected because (a) it introduces eventual consistency (gap between decision and audit write), (b) adds Kafka/Redis dependency for something PostgreSQL handles natively, (c) queue can lose messages on crash. The transactional approach guarantees zero gaps.

### 3. PII Vault: `apps/api/src/domains/logicore/compliance/pii_vault.py`

**What it does**: Resolves the fundamental tension between GDPR Article 17 (right to erasure) and EU AI Act Article 12 (immutable audit trail). Stores encrypted PII in a separate table with soft-delete capability, while the audit_log keeps only a query hash.

**The pattern**: **Strategy Pattern via Injectable Callables**. Encryption is injected as `encrypt_fn: Callable[[str], bytes]` — not hardcoded. This means the same code works with a mock XOR cipher in tests, Azure Key Vault in production, and AWS KMS after a migration. Zero code changes to swap key management providers.

**Key code walkthrough**:

```python
# apps/api/src/domains/logicore/compliance/pii_vault.py:129-167
async def store(self, conn, audit_entry_id, query_text,
                encryption_key_id, encrypt_fn, retention_years=10):
    encrypted = encrypt_fn(query_text)  # Injectable: mock in test, AKV in prod
    retention_until = datetime(
        datetime.now(UTC).year + retention_years, ...)
    row = await conn.fetchrow(
        _INSERT_SQL,
        audit_entry_id,    # $1
        encrypted,         # $2 (BYTEA -- AES-256-GCM)
        encryption_key_id, # $3
        retention_until,   # $4
    )
    return dict(row)
```

**The PII detection heuristic**:

```python
# apps/api/src/domains/logicore/compliance/pii_vault.py:74-76
_UPPER = r"A-ZĄĆĘŁŃÓŚŹŻ"
_LOWER = r"a-ząćęłńóśźż"
_NAME_PATTERN = re.compile(rf"[{_UPPER}][{_LOWER}]+\s+[{_UPPER}][{_LOWER}]+")
```

The character classes include all Polish diacritical characters (ą, ć, ę, ł, ń, ó, ś, ź, ż and uppercase equivalents). The original `[A-Z][a-z]+` missed names like "Łukasz Śliwiński" — a showstopper for a Polish company where most employee names contain diacritics.

**Why it matters**: Without the vault separation, you have two bad options: (1) store raw PII in the immutable audit log and violate GDPR when erasure requests come, or (2) enable DELETE on the audit log and violate the AI Act. The vault makes both regulations satisfiable: delete from vault (GDPR), audit structure stays intact (AI Act).

**Alternatives considered**: Could have used tokenization (replace PII with tokens that map to a separate lookup). Rejected because tokenization requires a token store that itself needs GDPR compliance, and the vault approach is simpler — one table, one soft-delete, done.

### 4. SQL Migrations: `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql`

**What it does**: Creates the append-only `audit_log` table with 21 columns, 3 indexes, and `REVOKE UPDATE, DELETE ON audit_log FROM logicore` — the database-level immutability enforcement (Layer 1).

**The pattern**: **Defense in Depth (3 Layers)**. Each layer catches a different failure mode:

| Layer | Where | What it prevents | What it can't prevent |
|-------|-------|------------------|-----------------------|
| 1. DB REVOKE | `001_audit_log.sql:76` | Application-level tampering (compromised app server) | DBA with superuser access |
| 2. Frozen Pydantic | `compliance.py:80` | In-memory mutation bugs | Anything outside Python |
| 3. Hash chain | `audit_logger.py:35-70` | DBA tampering (mathematically detectable) | Nothing — if you can verify the chain, tampering is provable |

**Key code walkthrough**:

```sql
-- apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql:72-76
-- IMMUTABILITY ENFORCEMENT
-- The application role can only INSERT and SELECT.
REVOKE UPDATE, DELETE ON audit_log FROM logicore;
```

**Why three layers**: A single REVOKE is one `GRANT` statement away from being undone by a misconfigured migration. Frozen Pydantic catches bugs but only in Python. The hash chain is the one layer that's mathematically verifiable by anyone — a regulator can walk the chain and verify it independently. Each layer compensates for the others' weaknesses.

### 5. Audit RBAC: `apps/api/src/domains/logicore/compliance/audit_rbac.py`

**What it does**: Filters audit log entries based on the viewer's role. Users see only their own entries. Managers see their department. Compliance officers and admins see everything. Unknown roles default to user-level access (most restrictive).

**The pattern**: **Principle of Least Privilege with Safe Defaults**. The critical design decision is line 63: `return False`. Any role not explicitly handled gets denied.

**Key code walkthrough**:

```python
# apps/api/src/domains/logicore/compliance/audit_rbac.py:28-63
def can_view_entry(self, viewer_user_id, entry_user_id, viewer_role,
                   viewer_department=None, entry_department=None):
    # Own entries are always visible
    if viewer_user_id == entry_user_id:
        return True
    # Full access roles (compliance_officer, admin)
    if viewer_role in _FULL_ACCESS_ROLES:
        return True
    # Manager: same department
    if viewer_role == "manager":
        if viewer_department and entry_department:
            return viewer_department == entry_department
        return False  # No department info → deny (conservative)
    # Default (user, unknown): own entries only
    return False
```

**Why it matters**: A role escalation bug (e.g., injecting `viewer_role="admin"` in the query parameter) is a real risk since RBAC is currently enforced via query param, not JWT. The safe default means even if someone passes an unknown role name, they get minimum access.

**Alternatives considered**: Could have used a decorator pattern or middleware. Chose explicit method calls because (a) the RBAC logic is auditable — you can read exactly what each role gets, (b) it's testable without HTTP overhead, (c) Phase 10 will replace the query param with JWT extraction, and the RBAC class doesn't need to change.

### 6. Langfuse Snapshot: `apps/api/src/domains/logicore/compliance/langfuse_snapshot.py`

**What it does**: Extracts 5 critical fields from Langfuse trace data (prompt_tokens, completion_tokens, total_cost_eur, model_version, response_hash) and stores them in the audit entry itself. If Langfuse goes down, gets rebuilt, or loses traces during migration, the audit entry is still self-contained.

**The pattern**: **Single Point of Failure Elimination via Data Duplication**. The audit entry stores both a `langfuse_trace_id` (link to full trace) and a snapshot of the 5 fields needed for compliance reconstruction. The snapshot is the fallback; Langfuse is the nice-to-have.

**Key code walkthrough**:

```python
# apps/api/src/domains/logicore/compliance/langfuse_snapshot.py:27-50
def create_langfuse_snapshot(trace_data: dict) -> dict:
    usage = trace_data.get("usage", {}) or {}
    cost = trace_data.get("cost")
    model = trace_data.get("model")
    output = trace_data.get("output")
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "total_cost_eur": Decimal(str(cost)) if cost else Decimal("0"),
        "model_version": model,
        "response_hash": _compute_response_hash(output),
    }
```

The `or 0` and `or {}` defaults handle missing/None fields gracefully. `verify_snapshot_against_trace` returns all mismatches (not just the first), so a compliance officer can see every field that drifted between the audit entry and the live Langfuse data.

### 7. Data Lineage Tracker: `apps/api/src/domains/logicore/compliance/data_lineage.py`

**What it does**: Tracks the full chain: source document → document version → chunk version → embedding model → Qdrant point ID. Every re-ingestion creates a new version; old versions are preserved so audit entries can reference the exact document state at decision time.

**The pattern**: **Immutable Version Chain**. Instead of updating a document row, every change creates a new `document_versions` row with an incremented version number. Chunks are linked via FK. The `source_hash` (SHA-256 of the file) enables tamper detection: re-hash the source file and compare.

```python
# apps/api/src/domains/logicore/compliance/data_lineage.py:221-252
async def verify_source_hash(self, conn, document_id, version, expected_hash):
    stored_hash = await conn.fetchval(
        _SELECT_SOURCE_HASH_SQL, document_id, version)
    if stored_hash is None:
        return False
    return stored_hash == expected_hash
```

### 8. Bias Detector: `apps/api/src/domains/logicore/compliance/bias_detector.py`

**What it does**: Statistical fairness checks for AI decision bias. Flags if any department receives >2x its expected share of decisions (routing bias), if queries are consistently routed to specific models (model preference), or if degraded-mode decisions correlate with specific departments.

**The pattern**: **Proportion-Based Threshold with Minimum Sample Guard**.

```python
# apps/api/src/domains/logicore/compliance/bias_detector.py:63-99
_MIN_SAMPLE_SIZE = 30

def _detect_proportion_bias(rows, total, group_key):
    if total == 0 or len(rows) == 0:
        return False, [], False
    if total < _MIN_SAMPLE_SIZE:
        return False, [], True  # insufficient_data flag
    num_groups = len(rows)
    expected_rate = 1.0 / num_groups
    flagged = []
    for row in rows:
        actual_rate = row["count"] / total
        if actual_rate > expected_rate * _BIAS_THRESHOLD:
            flagged.append(row[group_key])
    return len(flagged) > 0, flagged, False
```

The `insufficient_data` flag (third return value) is critical for compliance reporting. A regulator reads "no bias detected" very differently from "not enough data to tell." The n≥30 threshold is the standard Central Limit Theorem minimum for proportion tests.

**Known limitation**: With exactly 2 groups, the threshold can't trigger (2x of 50% = 100%, mathematically impossible). This is documented and the recommendation is chi-squared testing for production with large datasets (Phase 12).

### 9. Compliance Report Generator: `apps/api/src/domains/logicore/compliance/report_generator.py`

**What it does**: Generates Article 12 compliance reports for a date range — total entries, models used, unique users, HITL approvals, cost, degraded decisions, hash chain verification, and an `entry_count_hash` for completeness.

**The pattern**: **Completeness Verification via Hash**. The `entry_count_hash = SHA-256(f"{count}:{start_iso}:{end_iso}")` lets a verifier re-query the count and recompute the hash. If they diverge, entries were silently excluded from the report.

### 10. API Layer: `apps/api/src/domains/logicore/api/compliance.py`

**What it does**: 5 FastAPI endpoints exposed via a factory function. Two are gated behind `compliance_officer`/`admin` role checks. Factory pattern enables dependency injection of the database pool.

**The pattern**: **Router Factory with Injected Dependencies**. `create_compliance_router(db_pool)` returns an `APIRouter` with all endpoints pre-configured. This matches the analytics router pattern from earlier phases.

```python
# apps/api/src/domains/logicore/api/compliance.py:34-42
def create_compliance_router(db_pool: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])
    # ... endpoints use db_pool via closure ...
    return router
```

## Key Decisions Explained

### Decision 1: Hash Chain Over Blockchain

- **The choice**: SHA-256 hash chain where each entry stores `prev_entry_hash` + `entry_hash`
- **The alternatives**: Private blockchain (Hyperledger Fabric), managed audit platform (Splunk), REVOKE-only
- **The reasoning**: A private blockchain with one writer has the same trust model as a hash chain — both use SHA-256, both produce tamper evidence. The blockchain adds distributed consensus (unnecessary for single-writer) at EUR 8,000-15,000/year for a managed node. The hash chain does it at EUR 0.
- **The trade-off**: No multi-writer consensus. If LogiCore ever needs multiple independent audit log writers, blockchain becomes justified.
- **When to revisit**: When the system has 5+ independent writers that can't share a PostgreSQL transaction
- **Interview version**: "We chose a SHA-256 hash chain over blockchain because with a single writer, both have the same trust model — both use SHA-256 for tamper evidence. The blockchain adds distributed consensus we don't need at EUR 8-15K/year. Same math, zero extra infrastructure."

### Decision 2: PII Vault Separation (GDPR/AI Act Resolution)

- **The choice**: Two tables — `audit_log` (immutable, stores query hash) and `audit_pii_vault` (encrypted, supports soft-delete)
- **The alternatives**: (a) Log everything in one table and handle GDPR by exemption, (b) Tokenization service, (c) Don't log PII-containing queries
- **The reasoning**: Option (a) is legally indefensible — GDPR has no AI Act exemption. Option (c) creates compliance gaps for exactly the queries regulators care most about (employee data queries). Option (b) adds complexity without benefit since the vault is simpler.
- **The trade-off**: Two write paths. Every PII-containing query writes to both tables. Higher write latency for ~5% of queries (those containing PII).
- **When to revisit**: When PII detection needs to be more sophisticated than regex (Phase 10 LLM-based semantic detection)
- **Interview version**: "GDPR says delete personal data on request. The AI Act says your audit trail must be immutable. They directly conflict. We resolved it architecturally: the audit log stores a hash of the query (immutable), the raw PII goes to a separate encrypted vault with soft-delete. GDPR request comes in — delete from vault. The audit entry stays intact for regulators."

### Decision 3: Atomic Checkpoint + Audit Write

- **The choice**: Both operations in the same asyncpg transaction
- **The alternatives**: (a) Write audit entry after checkpoint (separate writes), (b) Audit worker consuming from an event queue, (c) Two-phase commit with external coordination
- **The reasoning**: Option (a) has a crash window between the two writes — the workflow resumes but the audit entry is gone. Option (b) introduces eventual consistency (gap between decision and audit record). Option (c) adds complexity for something PostgreSQL transactions already guarantee.
- **The trade-off**: Both systems must use the same PostgreSQL database. Can't move the audit log to an external SaaS service without losing this guarantee.
- **When to revisit**: If the checkpointer moves to a different database, or if you add a second audit destination (e.g., S3 for archival)
- **Interview version**: "The audit write and the LangGraph checkpoint must be in the same database transaction. If they're separate, a crash between them creates a compliance gap — the workflow resumes but the audit entry was never written. Same connection, same transaction, both succeed or both roll back. It's 6 lines of code that prevent a EUR 3.5M fine."

### Decision 4: Advisory Lock for Hash Chain Concurrency

- **The choice**: `pg_advisory_xact_lock(8_000_000_001)` — a transaction-scoped PostgreSQL advisory lock
- **The alternatives**: (a) Application-level mutex, (b) `SELECT ... FOR UPDATE` on a sentinel row, (c) Serialize at the application level (single writer)
- **The reasoning**: Two concurrent `write_with_hash_chain` calls could both read the same `prev_hash`, compute their chain hashes, and write — forking the chain. Advisory lock serializes the read-compute-write sequence within the transaction.
- **The trade-off**: All hash chain writes are serialized (no concurrent chain writes). At 10K decisions/day this is ~0.1 writes/second — serialization overhead is negligible.
- **When to revisit**: When write throughput exceeds what serialized hash chain writes can handle (~1000 writes/second on PostgreSQL). At that point, batch writes with a single chain computation per batch.
- **Interview version**: "Without the advisory lock, two concurrent writes could both read the same previous hash and fork the chain. We use `pg_advisory_xact_lock` — it's transaction-scoped, so it's released on commit or rollback, and it serializes the read-hash-write sequence. At 10K decisions/day, the serialization overhead is negligible."

### Decision 5: Injectable Encryption (Not Hardcoded)

- **The choice**: `encrypt_fn: Callable[[str], bytes]` passed to `PIIVault.store()`
- **The alternatives**: (a) Hardcode AES-256-GCM with env var key, (b) Use pg_crypto extension, (c) Use a specific KMS SDK
- **The reasoning**: Key management is deployment-specific. Tests use a mock XOR cipher. Production uses Azure Key Vault. If you migrate to AWS, swap to KMS. No code change — just swap the callable.
- **The trade-off**: Caller must provide the encrypt/decrypt functions. More boilerplate at the call site.
- **When to revisit**: If encryption logic becomes complex enough to warrant its own abstraction (key rotation, multiple algorithms)
- **Interview version**: "Encryption is injected as a callable, not hardcoded. Tests use a mock cipher, production uses Azure Key Vault, and if you migrate to AWS you swap to KMS — no code change. The vault doesn't know or care what's encrypting the data."

### Decision 6: Explicit `created_at` Parameter ($20)

- **The choice**: Pass `datetime.now(UTC)` as the `$20` parameter to the INSERT, not rely on PostgreSQL `DEFAULT NOW()`
- **The alternatives**: Use `DEFAULT NOW()` and accept the clock mismatch
- **The reasoning**: This was a critical bug caught during review. `datetime.now(UTC)` in Python and `NOW()` in PostgreSQL differ by microseconds. The hash chain uses `created_at` in its computation. If the hash was computed with Python's timestamp but the DB stores PostgreSQL's timestamp, every entry appears tampered during verification. One clock source eliminates the bug entirely.
- **The trade-off**: Slightly more complex INSERT (20 params instead of 19). Worth it.
- **When to revisit**: Never. Using two independent clocks for a hash chain is always wrong.
- **Interview version**: "The hash chain computes its hash using `created_at`. If we used `DEFAULT NOW()`, the DB's timestamp would differ from Python's by microseconds. The verification step would recompute using the DB-stored timestamp and get a different hash — every entry appears tampered. We pass the same Python `now` to both the hash function and the INSERT. One clock, not two."

## Patterns & Principles Used

### 1. Defense in Depth (3-Layer Immutability)
- **What**: Multiple independent protections against the same threat
- **Where**: Layer 1: `001_audit_log.sql:76` (REVOKE), Layer 2: `compliance.py:80` (frozen model), Layer 3: `audit_logger.py:35-70` (hash chain)
- **Why**: Each layer has a failure mode the others cover. REVOKE can be undone by a migration. Frozen models only work in Python. The hash chain is mathematically verifiable.
- **When NOT to use**: When the cost of a breach is low. Defense in depth adds complexity — don't use it for non-critical data.

### 2. Strategy Pattern via Callable Injection
- **What**: Pass behavior as a function parameter instead of hardcoding it
- **Where**: `pii_vault.py:135` (`encrypt_fn: Callable[[str], bytes]`)
- **Why**: Key management varies by environment. Tests need deterministic encryption. Production needs Azure Key Vault. Migration target needs AWS KMS.
- **When NOT to use**: When there's only one implementation and no foreseeable need to swap. Unnecessary abstraction.

### 3. Factory Pattern for Router Creation
- **What**: Function that creates and returns a configured object
- **Where**: `compliance.py:34` (`create_compliance_router(db_pool)`)
- **Why**: Endpoints need a database pool, but FastAPI routers are created at import time (before the pool exists). Factory defers construction until the pool is ready.
- **When NOT to use**: When dependencies are available at import time (no deferred construction needed).

### 4. Connection Injection (Not Pool Injection)
- **What**: Methods accept an asyncpg connection, not a pool
- **Where**: Every method in `AuditLogger`, `PIIVault`, `DataLineageTracker`, `ComplianceReportGenerator`, `BiasDetector`
- **Why**: Enables atomic transactions — the caller controls the transaction boundary. If methods took a pool, they'd each create their own connection and couldn't share a transaction.
- **When NOT to use**: When each operation is independent and doesn't need to participate in a shared transaction.

### 5. Safe Default (Principle of Least Privilege)
- **What**: Unknown inputs get the most restrictive behavior
- **Where**: `audit_rbac.py:63` (`return False` for unknown roles)
- **Why**: A role escalation bug should fail closed (deny access), not open (grant access).
- **When NOT to use**: When failing closed would break critical operations (e.g., don't default to "deny" for health check endpoints).

### 6. Deterministic Test Doubles
- **What**: Test mocks produce predictable, verifiable output
- **Where**: `test_pii_vault.py:58-69` — XOR-based mock encrypt/decrypt that's fully round-trippable
- **Why**: Tests need to verify that encryption happened and that decryption recovers the original. A random mock wouldn't let you assert on the output.
- **When NOT to use**: When testing that the real implementation handles edge cases (use the real thing in integration tests).

## Benchmark Results & What They Mean

| Metric | Value | What it means |
|--------|-------|---------------|
| SQL parameters per INSERT | 19-20 ($1-$20) | Zero string interpolation anywhere. SQL injection is structurally impossible, not just "tested against." |
| Fields per audit entry | 21 | Covers Article 12 requirements + hash chain + snapshot + degraded mode. More than spec'd because analysis revealed gaps (Langfuse SPOF, Phase 7 integration). |
| RBAC roles tested | 5 (user, manager, compliance_officer, admin, unknown) | Unknown defaulting to user proves the safe-default principle. Role escalation via unknown role name fails closed. |
| PII detection patterns | 12 (8 original + 4 fix) | Covers name+keyword, email, phone, PESEL, Polish diacritics. Missing: obfuscated PII ("J. K-ski"), Unicode normalization (NFC vs NFD). Phase 10 adds LLM-based semantic detection. |
| Hash chain tests | 18 (15 + 3 timestamp fix) | Covers empty chain, single entry, multi-entry, tampered data, broken links, advisory lock, timestamp consistency, determinism. Missing: real PostgreSQL concurrent writes. Phase 12. |
| Bias detection threshold | >2x expected proportion, n≥30 minimum | Works for 3+ groups. Breaks with exactly 2 groups (2x of 50% = 100% is impossible). This is a math limitation, not a bug — documented and deferred to chi-squared for Phase 12. |

**The boundary found**: The `$20` timestamp bug. On mocked connections, hash chain verification always passes because the mock returns whatever timestamp you give it. On real PostgreSQL, `DEFAULT NOW()` would return a different timestamp than `datetime.now(UTC)`, and the chain would appear broken on the very first entry. This is why integration tests on real PostgreSQL (Phase 12) are non-negotiable before production.

## Test Strategy

### Organization

All 196 tests are unit tests with mocked asyncpg connections. No Docker dependencies.

| Test File | Tests | What it proves |
|-----------|-------|----------------|
| `test_compliance_models.py` | 25 | Pydantic validation works, AuditEntry is truly frozen (mutation raises), serialization round-trips correctly |
| `test_audit_schema.py` | 31 | SQL migration contains all expected columns, types, indexes, REVOKE statement, defaults, and comments |
| `test_audit_logger.py` | 16 | Write/read/filter operations use parameterized SQL, SQL injection in metadata is blocked, all 21 fields round-trip |
| `test_atomic_audit.py` | 7 | Checkpoint + audit both succeed or both roll back, checkpoint runs before audit, same connection shared |
| `test_hash_chain.py` | 15+3 | Chain builds correctly (None → hash1 → hash2), advisory lock acquired, tampered entry detected at correct index, timestamp matches between hash and DB |
| `test_pii_vault.py` | 20+4 | Encrypt/decrypt round-trips, GDPR soft-delete returns None, SQL injection blocked, PII detection catches Polish names+diacritics, non-PII correctly excluded |
| `test_langfuse_snapshot.py` | 13 | Snapshot extraction from trace data, safe defaults for missing fields, mismatch detection returns all drifted fields |
| `test_audit_rbac.py` | 15 | Each role sees exactly what it should, unknown role defaults to user, department isolation for managers, empty list handled |
| `test_data_lineage.py` | 13 | Multi-version documents, chunk versioning, full lineage assembly, source hash tamper detection, SQL injection blocked |
| `test_compliance_report_generator.py` | 11 | Date range filtering, all entries included, model aggregation, degraded count, hash chain verification, entry_count_hash |
| `test_bias_detector.py` | 8+4 | Even distribution not flagged, disproportionate flagged, insufficient data (n<30) returns flag, model preference works independently |
| `test_compliance_api.py` | 11 | RBAC enforcement (403 for non-privileged), date filtering, report generation, lineage, hash chain, bias report, input validation |

### Key test patterns

**Mocking strategy**: Every test uses `AsyncMock` for asyncpg connections. The mock returns pre-built dicts that match the DB schema. This avoids Docker dependency but means the tests prove logic correctness, not PostgreSQL compatibility.

**What ISN'T tested and why**:
- **Real PostgreSQL**: No integration tests. The REVOKE statement, advisory lock, hash chain on real timestamps — all verified against SQL text or mocked behavior, not against a live database. Deferred to Phase 12.
- **Concurrent hash chain writes on real PG**: The advisory lock is tested by checking it's called, but actual serialization behavior requires real PostgreSQL advisory locks.
- **PII detection with obfuscated names**: "J. K-ski's salary" would not be detected. Phase 10 adds LLM-based semantic PII detection.
- **Report generation at scale**: No performance test with 10K+ entries. Phase 12.
- **JWT-based RBAC**: Currently `viewer_role` is a query parameter. Phase 10 replaces with JWT extraction middleware.

## File Map

| File | Purpose | Key patterns | Lines |
|------|---------|-------------|-------|
| `apps/api/src/domains/logicore/models/compliance.py` | 8 Pydantic models + LogLevel enum | Frozen model, field validation, model_validator | ~197 |
| `apps/api/src/domains/logicore/compliance/audit_logger.py` | Audit log writer + hash chain + atomic write | Connection injection, advisory lock, dual-clock fix | ~453 |
| `apps/api/src/domains/logicore/compliance/pii_vault.py` | Encrypted PII storage + detection heuristic | Injectable encryption, soft delete, regex PII detection | ~210 |
| `apps/api/src/domains/logicore/compliance/audit_rbac.py` | Role-based audit log filtering | Safe defaults, least privilege | ~100 |
| `apps/api/src/domains/logicore/compliance/langfuse_snapshot.py` | Self-contained audit entry snapshots | SPOF elimination via data duplication | ~100 |
| `apps/api/src/domains/logicore/compliance/data_lineage.py` | Document version → chunk → embedding tracking | Immutable version chain, source hash verification | ~252 |
| `apps/api/src/domains/logicore/compliance/report_generator.py` | Article 12 compliance reports | Completeness hash, aggregation | ~222 |
| `apps/api/src/domains/logicore/compliance/bias_detector.py` | Fairness checks on routing/model decisions | Proportion threshold, minimum sample guard | ~264 |
| `apps/api/src/domains/logicore/api/compliance.py` | 5 REST endpoints | Router factory, RBAC gating | ~181 |
| `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` | Audit log table + REVOKE | Defense in depth, JSONB for flexibility | ~76 |
| `apps/api/src/core/infrastructure/postgres/migrations/002_data_lineage.sql` | Lineage tables | FK constraints, version ordering | ~36 |
| `apps/api/src/core/infrastructure/postgres/migrations/003_pii_vault.sql` | PII vault table | Soft delete, BYTEA encryption, REVOKE DELETE | ~37 |
| `apps/api/src/domains/logicore/compliance/__init__.py` | Package init | Module documentation | ~12 |

**Test files**: 12 test files, 196 tests total, all in `tests/unit/`.

## Interview Talking Points

1. **GDPR vs AI Act resolution**: "GDPR says delete personal data on request. The AI Act says your audit trail must be immutable. We resolved the contradiction architecturally — the audit log stores a hash (immutable), the raw PII goes to a separate encrypted vault with soft-delete. Two tables, two retention lifecycles, both regulations satisfied."

2. **Three-layer immutability**: "We use defense in depth: database REVOKE prevents application tampering, frozen Pydantic models prevent in-memory mutation, and a SHA-256 hash chain provides mathematical tamper evidence. Each layer catches what the others miss — REVOKE can be undone by a migration, models only work in Python, but the hash chain is verifiable by anyone."

3. **Atomic audit writes**: "The checkpoint and audit log entry must be in the same database transaction. Without it, a crash between the two creates a compliance gap — the workflow resumes but the audit entry was never written. It's 6 lines of code that prevent what could be a EUR 3.5M fine."

4. **Hash chain over blockchain**: "A private blockchain with one writer has the same trust model as a hash chain — same SHA-256, same tamper evidence. The blockchain adds distributed consensus we don't need at EUR 8-15K/year. Same math, zero infrastructure cost."

5. **The dual-clock bug**: "Our hash chain computes a hash using `created_at`. The original code used `datetime.now()` in Python but let PostgreSQL set `DEFAULT NOW()`. Those two clocks differ by microseconds. On real PostgreSQL, every entry would appear tampered because the verification step uses the DB-stored timestamp, not the Python one. We fixed it by passing the same Python timestamp to both the hash function and the INSERT."

6. **Injectable encryption**: "PII encryption uses dependency injection via a callable. Tests use a mock cipher, production uses Azure Key Vault, and migration to AWS KMS requires zero code changes. The vault doesn't know what's encrypting the data."

7. **Bias detection minimum sample guard**: "We return `insufficient_data: true` when n < 30, not `no_bias: true`. A regulator reads 'no bias' very differently from 'not enough data to tell.' The n≥30 threshold is the standard Central Limit Theorem minimum for proportion tests."

8. **Cost framing**: "Full compliance logging costs EUR 5,400/year. A single unlogged high-risk AI decision carries a fine of up to EUR 3.5M (7% of EUR 50M turnover). The ratio is 648:1. The question is never 'can we afford compliance logging' — it's 'can we afford one unlogged decision?'"

## What I'd Explain Differently Next Time

**The $20 timestamp fix is the most instructive bug in the whole phase.** It's invisible in unit tests (mocks return whatever you give them) and would break catastrophically on real PostgreSQL (every entry appears tampered). If I were explaining this phase to someone, I'd lead with this bug — it perfectly illustrates why integration tests matter and why having two independent sources of truth for the same value is always a mistake.

**The GDPR/AI Act tension should be presented as a binary architectural choice, not a problem to "solve."** Either you separate PII from the audit structure upfront (2 days of work) or you retrofit it after a GDPR complaint forces you to explain why personal data is stored in a table where DELETE is revoked. There's no third option. Framing it as a binary choice makes the decision obvious.

**The atomic write pattern is easier to understand backward.** Start with the failure mode (crash between checkpoint and audit write creates a compliance gap), then show the fix (same transaction). Don't start with "we need atomic writes" — start with "what happens if these two writes aren't atomic?"

**Defense in depth is only convincing when you explain what each layer CAN'T do.** Saying "we have 3 layers of immutability" sounds like over-engineering. Saying "REVOKE is bypassable by a DBA, frozen models only work in Python, but the hash chain is mathematically verifiable by anyone" explains why each layer exists.
