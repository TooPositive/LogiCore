"""Phase 8: EU AI Act Compliance -- regulatory shield for LogiCore.

Modules:
- audit_logger: Immutable audit log writer (append-only, parameterized SQL,
  SHA-256 hash chain with advisory lock concurrency)
- pii_vault: GDPR-safe encrypted PII storage with soft delete
- langfuse_snapshot: Self-contained audit entry snapshot extraction/verification
- audit_rbac: Role-based access control for audit log entries
- data_lineage: Document -> chunk -> embedding version tracking
- report_generator: EU AI Act Article 12 compliance report builder
- bias_detector: Statistical fairness checks (routing, model preference, degraded correlation)
"""
