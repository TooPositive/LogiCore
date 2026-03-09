"""Unit tests for audit-specific RBAC.

Roles:
  - "user": sees only own audit entries
  - "manager": sees own + team entries (same department)
  - "compliance_officer": sees all entries
  - "admin": sees all entries
  - unknown role: defaults to "user" (own entries only)

Tests cover:
  - Regular user sees only own entries
  - Compliance officer sees all entries
  - Manager sees team entries (same department)
  - Manager cannot see entries from other departments
  - Admin sees all entries
  - Unknown role defaults to "user" (own entries only)
  - Empty entries list returns empty
  - can_view_entry for each role
  - Manager with department metadata matching
"""

from datetime import UTC, datetime
from uuid import uuid4

from apps.api.src.domains.logicore.models.compliance import AuditEntry


def _make_audit_entry(**overrides) -> AuditEntry:
    """Factory for AuditEntry."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "entry_hash": "sha256:abc123",
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
        "metadata": {},
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


class TestCanViewEntry:
    """AuditRBAC.can_view_entry: per-entry access control."""

    def test_user_can_view_own_entry(self):
        """User can see their own audit entry."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="user-01",
            entry_user_id="user-01",
            viewer_role="user",
        ) is True

    def test_user_cannot_view_other_entry(self):
        """User cannot see another user's audit entry."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="user-01",
            entry_user_id="user-02",
            viewer_role="user",
        ) is False

    def test_compliance_officer_can_view_any_entry(self):
        """Compliance officer can see any user's audit entry."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="officer-01",
            entry_user_id="user-99",
            viewer_role="compliance_officer",
        ) is True

    def test_admin_can_view_any_entry(self):
        """Admin can see any user's audit entry."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="admin-01",
            entry_user_id="user-99",
            viewer_role="admin",
        ) is True

    def test_manager_can_view_same_department_entry(self):
        """Manager can see entries from users in same department."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="mgr-01",
            entry_user_id="user-02",
            viewer_role="manager",
            viewer_department="logistics",
            entry_department="logistics",
        ) is True

    def test_manager_cannot_view_other_department_entry(self):
        """Manager cannot see entries from users in different department."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="mgr-01",
            entry_user_id="user-02",
            viewer_role="manager",
            viewer_department="logistics",
            entry_department="finance",
        ) is False

    def test_manager_can_view_own_entry(self):
        """Manager can always see their own entries."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        assert rbac.can_view_entry(
            viewer_user_id="mgr-01",
            entry_user_id="mgr-01",
            viewer_role="manager",
            viewer_department="logistics",
            entry_department="finance",  # different dept but own entry
        ) is True

    def test_unknown_role_defaults_to_user(self):
        """Unknown role only sees own entries (default to user)."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()
        # Can see own
        assert rbac.can_view_entry(
            viewer_user_id="user-01",
            entry_user_id="user-01",
            viewer_role="mysterious_role",
        ) is True
        # Cannot see other's
        assert rbac.can_view_entry(
            viewer_user_id="user-01",
            entry_user_id="user-02",
            viewer_role="mysterious_role",
        ) is False


class TestFilterEntries:
    """AuditRBAC.filter_entries_for_user: bulk filtering."""

    def test_user_sees_only_own_entries(self):
        """Regular user gets back only entries they created."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-02"),
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-03"),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="user-01",
            viewer_role="user",
        )

        assert len(filtered) == 2
        assert all(e.user_id == "user-01" for e in filtered)

    def test_compliance_officer_sees_all_entries(self):
        """Compliance officer gets back all entries."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-02"),
            _make_audit_entry(user_id="user-03"),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="officer-01",
            viewer_role="compliance_officer",
        )

        assert len(filtered) == 3

    def test_admin_sees_all_entries(self):
        """Admin gets back all entries."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-02"),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="admin-01",
            viewer_role="admin",
        )

        assert len(filtered) == 2

    def test_manager_sees_team_entries(self):
        """Manager sees entries from their department."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(
                user_id="user-01",
                metadata={"department": "logistics"},
            ),
            _make_audit_entry(
                user_id="user-02",
                metadata={"department": "logistics"},
            ),
            _make_audit_entry(
                user_id="user-03",
                metadata={"department": "finance"},
            ),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="mgr-01",
            viewer_role="manager",
            viewer_department="logistics",
        )

        assert len(filtered) == 2
        assert all(
            e.metadata.get("department") == "logistics" for e in filtered
        )

    def test_manager_cannot_see_other_department(self):
        """Manager doesn't see entries from other departments."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(
                user_id="user-01",
                metadata={"department": "finance"},
            ),
            _make_audit_entry(
                user_id="user-02",
                metadata={"department": "finance"},
            ),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="mgr-01",
            viewer_role="manager",
            viewer_department="logistics",
        )

        assert len(filtered) == 0

    def test_empty_entries_returns_empty(self):
        """Empty input list returns empty output for any role."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        rbac = AuditRBAC()

        for role in ["user", "manager", "compliance_officer", "admin"]:
            filtered = rbac.filter_entries_for_user(
                entries=[],
                viewer_user_id="anyone",
                viewer_role=role,
            )
            assert filtered == [], f"Empty input should return empty for {role}"

    def test_unknown_role_sees_only_own_entries(self):
        """Unknown role defaults to user behavior."""
        from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC

        entries = [
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-02"),
        ]

        rbac = AuditRBAC()
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id="user-01",
            viewer_role="mysterious_role",
        )

        assert len(filtered) == 1
        assert filtered[0].user_id == "user-01"
