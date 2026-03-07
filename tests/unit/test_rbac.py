"""Tests for RBAC filtering — the zero-trust retrieval core."""

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny, Range

from apps.api.src.domain.document import UserContext
from apps.api.src.security.rbac import build_qdrant_filter, resolve_user_context

# --- Mock user database ---
MOCK_USERS = {
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


class TestResolveUserContext:
    async def test_known_user(self):
        user = await resolve_user_context("max.weber", user_store=MOCK_USERS)
        assert user.clearance_level == 1
        assert user.departments == ["warehouse"]

    async def test_unknown_user_raises(self):
        with pytest.raises(ValueError, match="Unknown user"):
            await resolve_user_context("unknown.person", user_store=MOCK_USERS)

    async def test_ceo_has_all_departments(self):
        user = await resolve_user_context("eva.richter", user_store=MOCK_USERS)
        assert user.clearance_level == 4
        assert "executive" in user.departments


class TestBuildQdrantFilter:
    def test_warehouse_worker_filter(self):
        user = MOCK_USERS["max.weber"]
        f = build_qdrant_filter(user)

        assert isinstance(f, Filter)
        assert len(f.must) == 2

        # Department filter
        dept_cond = f.must[0]
        assert isinstance(dept_cond, FieldCondition)
        assert dept_cond.key == "department_id"
        assert isinstance(dept_cond.match, MatchAny)
        assert dept_cond.match.any == ["warehouse"]

        # Clearance filter
        cl_cond = f.must[1]
        assert isinstance(cl_cond, FieldCondition)
        assert cl_cond.key == "clearance_level"
        assert isinstance(cl_cond.range, Range)
        assert cl_cond.range.lte == 1

    def test_hr_director_sees_more(self):
        user = MOCK_USERS["katrin.fischer"]
        f = build_qdrant_filter(user)

        dept_cond = f.must[0]
        assert set(dept_cond.match.any) == {"hr", "management"}

        cl_cond = f.must[1]
        assert cl_cond.range.lte == 3

    def test_ceo_sees_everything_up_to_level_4(self):
        user = MOCK_USERS["eva.richter"]
        f = build_qdrant_filter(user)

        cl_cond = f.must[1]
        assert cl_cond.range.lte == 4

    def test_multi_department_user(self):
        user = MOCK_USERS["anna.schmidt"]
        f = build_qdrant_filter(user)

        dept_cond = f.must[0]
        assert set(dept_cond.match.any) == {"logistics", "warehouse"}

    def test_filter_always_has_two_conditions(self):
        """Every filter must have both department AND clearance constraints."""
        for user in MOCK_USERS.values():
            f = build_qdrant_filter(user)
            assert len(f.must) == 2

    def test_empty_departments_raises(self):
        """Empty department list MUST raise — MatchAny([]) behavior is undefined.

        If Qdrant interprets empty list as 'match all', that's a full RBAC bypass.
        A user with no departments sees nothing, not everything.
        """
        user = UserContext(user_id="no.dept", clearance_level=1, departments=[])
        with pytest.raises(ValueError, match="departments"):
            build_qdrant_filter(user)


class TestClearanceValidation:
    """Pydantic must reject invalid clearance levels at the boundary."""

    def test_clearance_zero_rejected(self):
        with pytest.raises(Exception):
            UserContext(user_id="x", clearance_level=0, departments=["hr"])

    def test_clearance_negative_rejected(self):
        with pytest.raises(Exception):
            UserContext(user_id="x", clearance_level=-1, departments=["hr"])

    def test_clearance_five_rejected(self):
        with pytest.raises(Exception):
            UserContext(user_id="x", clearance_level=5, departments=["hr"])

    def test_clearance_boundaries_accepted(self):
        """1 and 4 are valid — the edges of the range."""
        u1 = UserContext(user_id="x", clearance_level=1, departments=["hr"])
        u4 = UserContext(user_id="x", clearance_level=4, departments=["hr"])
        assert u1.clearance_level == 1
        assert u4.clearance_level == 4
