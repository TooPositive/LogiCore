"""Phase 8: EU AI Act Compliance -- regulatory shield for LogiCore.

Modules:
- audit_logger: Immutable audit log writer (append-only, parameterized SQL,
  SHA-256 hash chain with advisory lock concurrency)
- pii_vault: GDPR-safe encrypted PII storage with soft delete
- langfuse_snapshot: Self-contained audit entry snapshot extraction/verification
- audit_rbac: Role-based access control for audit log entries
"""
