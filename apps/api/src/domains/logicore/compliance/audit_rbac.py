"""Audit-specific RBAC for compliance log access control.

Roles:
  - "user": sees only own audit entries
  - "manager": sees own entries + team entries (same department)
  - "compliance_officer": sees all entries (regulatory access)
  - "admin": sees all entries (system administration)
  - unknown role: defaults to "user" (principle of least privilege)

Department matching for managers uses the entry's metadata.department
field. If no department metadata exists, the entry is excluded from
manager view (conservative default -- better to hide than expose).
"""

from apps.api.src.domains.logicore.models.compliance import AuditEntry

# Roles with unrestricted access to all audit entries
_FULL_ACCESS_ROLES = frozenset({"compliance_officer", "admin"})


class AuditRBAC:
    """Audit log access control based on user roles and departments.

    Implements the principle of least privilege: unknown roles default
    to user-level access (own entries only).
    """

    def can_view_entry(
        self,
        viewer_user_id: str,
        entry_user_id: str,
        viewer_role: str,
        viewer_department: str | None = None,
        entry_department: str | None = None,
    ) -> bool:
        """Check if a viewer can access a specific audit entry.

        Args:
            viewer_user_id: ID of the user requesting access
            entry_user_id: ID of the user who created the entry
            viewer_role: Role of the viewer
            viewer_department: Department of the viewer (for manager role)
            entry_department: Department of the entry creator

        Returns:
            True if the viewer can see this entry.
        """
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
            return False

        # Default (user, unknown): own entries only
        return False

    def filter_entries_for_user(
        self,
        entries: list[AuditEntry],
        viewer_user_id: str,
        viewer_role: str,
        viewer_department: str | None = None,
    ) -> list[AuditEntry]:
        """Filter a list of audit entries based on viewer's access.

        Args:
            entries: list of audit entries to filter
            viewer_user_id: ID of the user requesting access
            viewer_role: Role of the viewer
            viewer_department: Department of the viewer (for manager role)

        Returns:
            Filtered list containing only entries the viewer can access.
        """
        if not entries:
            return []

        # Fast path: full access roles get everything
        if viewer_role in _FULL_ACCESS_ROLES:
            return list(entries)

        return [
            entry
            for entry in entries
            if self.can_view_entry(
                viewer_user_id=viewer_user_id,
                entry_user_id=entry.user_id,
                viewer_role=viewer_role,
                viewer_department=viewer_department,
                entry_department=entry.metadata.get("department"),
            )
        ]
