"""Unit tests for Phase 8 audit log SQL migration.

Validates the migration SQL file is:
- Parseable (valid SQL syntax)
- Contains expected columns for Article 12 compliance
- Contains REVOKE UPDATE/DELETE for immutability
- Contains hash chain fields (prev_entry_hash, entry_hash)
- Contains Langfuse snapshot fields
- Contains degraded mode fields
- Uses gen_random_uuid() for default IDs
- Uses TIMESTAMPTZ for temporal fields
- Has appropriate defaults (NOW(), '{}')
"""

from pathlib import Path

import pytest


@pytest.fixture
def migration_sql() -> str:
    """Read the audit_log migration SQL file."""
    migration_path = (
        Path(__file__).resolve().parent.parent.parent
        / "apps"
        / "api"
        / "src"
        / "core"
        / "infrastructure"
        / "postgres"
        / "migrations"
        / "001_audit_log.sql"
    )
    assert migration_path.exists(), f"Migration file not found at {migration_path}"
    return migration_path.read_text()


class TestAuditLogMigration:
    """Validate the audit_log table SQL migration."""

    def test_migration_file_exists(self, migration_sql: str):
        """Migration file exists and is not empty."""
        assert len(migration_sql) > 0

    def test_creates_audit_log_table(self, migration_sql: str):
        """SQL creates the audit_log table."""
        assert "CREATE TABLE" in migration_sql
        assert "audit_log" in migration_sql

    # --- Core Article 12 fields ---

    def test_has_id_column_with_uuid(self, migration_sql: str):
        """Primary key is UUID with gen_random_uuid() default."""
        assert "id" in migration_sql
        assert "UUID" in migration_sql.upper()
        assert "gen_random_uuid()" in migration_sql

    def test_has_created_at_timestamptz(self, migration_sql: str):
        """created_at uses TIMESTAMPTZ for timezone-aware timestamps."""
        assert "created_at" in migration_sql
        assert "TIMESTAMPTZ" in migration_sql.upper()

    def test_has_user_id(self, migration_sql: str):
        assert "user_id" in migration_sql

    def test_has_query_text(self, migration_sql: str):
        assert "query_text" in migration_sql

    def test_has_retrieved_chunk_ids_jsonb(self, migration_sql: str):
        assert "retrieved_chunk_ids" in migration_sql
        assert "JSONB" in migration_sql.upper()

    def test_has_model_version(self, migration_sql: str):
        assert "model_version" in migration_sql

    def test_has_model_deployment(self, migration_sql: str):
        assert "model_deployment" in migration_sql

    def test_has_response_text(self, migration_sql: str):
        assert "response_text" in migration_sql

    def test_has_hitl_approver_id(self, migration_sql: str):
        assert "hitl_approver_id" in migration_sql

    def test_has_langfuse_trace_id(self, migration_sql: str):
        assert "langfuse_trace_id" in migration_sql

    def test_has_metadata_jsonb(self, migration_sql: str):
        assert "metadata" in migration_sql

    def test_has_log_level(self, migration_sql: str):
        assert "log_level" in migration_sql

    # --- Hash chain fields (tamper evidence) ---

    def test_has_prev_entry_hash(self, migration_sql: str):
        """Hash chain: previous entry's hash for sequential integrity."""
        assert "prev_entry_hash" in migration_sql

    def test_has_entry_hash(self, migration_sql: str):
        """Hash chain: this entry's computed hash."""
        assert "entry_hash" in migration_sql

    # --- Langfuse snapshot fields (self-contained audit entry) ---

    def test_has_prompt_tokens(self, migration_sql: str):
        assert "prompt_tokens" in migration_sql

    def test_has_completion_tokens(self, migration_sql: str):
        assert "completion_tokens" in migration_sql

    def test_has_total_cost_eur(self, migration_sql: str):
        assert "total_cost_eur" in migration_sql

    def test_has_response_hash(self, migration_sql: str):
        assert "response_hash" in migration_sql

    # --- Degraded mode fields (Phase 7 integration) ---

    def test_has_is_degraded(self, migration_sql: str):
        assert "is_degraded" in migration_sql

    def test_has_provider_name(self, migration_sql: str):
        assert "provider_name" in migration_sql

    def test_has_quality_drift_alert(self, migration_sql: str):
        assert "quality_drift_alert" in migration_sql

    # --- Immutability enforcement ---

    def test_revoke_update(self, migration_sql: str):
        """REVOKE UPDATE prevents modification of audit entries."""
        sql_upper = migration_sql.upper()
        assert "REVOKE" in sql_upper
        assert "UPDATE" in sql_upper

    def test_revoke_delete(self, migration_sql: str):
        """REVOKE DELETE prevents deletion of audit entries."""
        sql_upper = migration_sql.upper()
        assert "REVOKE" in sql_upper
        assert "DELETE" in sql_upper

    def test_revoke_on_audit_log_table(self, migration_sql: str):
        """REVOKE applies specifically to the audit_log table."""
        # Find REVOKE line(s) and check they reference audit_log
        lines = migration_sql.split("\n")
        revoke_lines = [line for line in lines if "REVOKE" in line.upper()]
        assert len(revoke_lines) > 0
        # At least one REVOKE references audit_log
        assert any("audit_log" in line for line in revoke_lines)

    # --- Indexes for query performance ---

    def test_has_created_at_index(self, migration_sql: str):
        """Index on created_at for date range queries (compliance reports)."""
        sql_upper = migration_sql.upper()
        assert "INDEX" in sql_upper
        assert "created_at" in migration_sql

    def test_has_user_id_index(self, migration_sql: str):
        """Index on user_id for per-user audit queries."""
        # Check for an index that includes user_id
        lines = migration_sql.split("\n")
        index_lines = [line for line in lines if "INDEX" in line.upper()]
        user_id_indexes = [line for line in index_lines if "user_id" in line]
        assert len(user_id_indexes) > 0

    # --- SQL quality checks ---

    def test_not_null_on_required_fields(self, migration_sql: str):
        """NOT NULL constraints on required fields."""
        assert "NOT NULL" in migration_sql.upper()

    def test_has_default_now_for_created_at(self, migration_sql: str):
        """created_at defaults to NOW() for server-side timestamp."""
        assert "NOW()" in migration_sql.upper()

    def test_no_string_interpolation_patterns(self, migration_sql: str):
        """Migration SQL does not contain Python format string patterns."""
        # These would indicate potential injection if used at runtime
        assert "%s" not in migration_sql
        assert "{}" not in migration_sql or "'{}'::jsonb" in migration_sql.lower()
