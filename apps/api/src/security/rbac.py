"""RBAC filtering for zero-trust retrieval.

Filters are applied at the Qdrant query level — the LLM never sees
documents outside the user's authorization tier.
"""

from qdrant_client.models import FieldCondition, Filter, MatchAny, Range

from apps.api.src.domain.document import UserContext

# Phase 1 demo user store — in production, this would be a DB/IdP lookup.
DEFAULT_USER_STORE: dict[str, UserContext] = {
    "max.weber": UserContext(
        user_id="max.weber",
        clearance_level=1,
        departments=["warehouse"],
    ),
    "anna.schmidt": UserContext(
        user_id="anna.schmidt",
        clearance_level=2,
        departments=["logistics", "warehouse"],
    ),
    "katrin.fischer": UserContext(
        user_id="katrin.fischer",
        clearance_level=3,
        departments=["hr", "management"],
    ),
    "eva.richter": UserContext(
        user_id="eva.richter",
        clearance_level=4,
        departments=["hr", "management", "legal", "logistics", "warehouse", "executive"],
    ),
}


async def resolve_user_context(
    user_id: str,
    user_store: dict[str, UserContext] | None = None,
) -> UserContext:
    """Resolve a user ID to their clearance level and departments.

    In production this would hit a database or identity provider.
    For Phase 1, uses an in-memory lookup.
    """
    if user_store is None:
        user_store = DEFAULT_USER_STORE

    if user_id not in user_store:
        raise ValueError(f"Unknown user: {user_id}")

    return user_store[user_id]


def build_qdrant_filter(user: UserContext) -> Filter:
    """Build a Qdrant filter that enforces RBAC constraints.

    Every query is filtered by:
    1. department_id IN user.departments (department access)
    2. clearance_level <= user.clearance_level (clearance ceiling)

    Raises ValueError if departments is empty — MatchAny([]) behavior
    is undefined in Qdrant and could bypass RBAC entirely.
    """
    if not user.departments:
        raise ValueError(
            f"User {user.user_id} has empty departments list. "
            "Refusing to build filter — MatchAny([]) could bypass RBAC."
        )

    return Filter(
        must=[
            FieldCondition(
                key="department_id",
                match=MatchAny(any=user.departments),
            ),
            FieldCondition(
                key="clearance_level",
                range=Range(lte=user.clearance_level),
            ),
        ]
    )
