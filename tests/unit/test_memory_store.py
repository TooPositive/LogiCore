"""Unit tests for 3-tier fleet agent memory.

Tier 1: Short-term (LangGraph state -- within a single workflow run)
Tier 2: Medium-term (Redis per-truck, 30-day sliding window)
Tier 3: Long-term (PostgreSQL fleet_agent_memory table)

The memory abstraction unifies all three tiers behind a single interface.
Tests use mocks for Redis and PostgreSQL -- no Docker needed.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry


def _make_pg_pool_mock(mock_conn: AsyncMock) -> MagicMock:
    """Create a mock asyncpg pool that supports `async with pool.acquire()`."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool.acquire = _acquire
    return mock_pool


# ── FleetMemoryRedis (Medium-term: per-truck Redis history) ──────────────────


class TestFleetMemoryRedis:
    """Redis-based medium-term memory: 30-day sliding window per truck."""

    async def test_write_anomaly_to_redis(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        mock_redis = AsyncMock()
        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30)

        entry = {
            "alert_type": "temperature_spike",
            "severity": "critical",
            "action_taken": "Diverted to Zurich cold storage",
            "timestamp": datetime.now(UTC).isoformat(),
        }

        await memory.record_anomaly(truck_id="truck-4721", entry=entry)

        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args
        assert call_args[0][0] == "truck:truck-4721:anomalies"

    async def test_read_truck_history(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        stored_entries = [
            json.dumps({
                "alert_type": "temperature_spike",
                "severity": "critical",
                "timestamp": (datetime.now(UTC) - timedelta(days=i)).isoformat(),
            })
            for i in range(3)
        ]

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=stored_entries)

        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30)
        history = await memory.get_truck_history(truck_id="truck-4721")

        assert len(history) == 3
        assert history[0]["alert_type"] == "temperature_spike"

    async def test_empty_history_returns_empty_list(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30)
        history = await memory.get_truck_history(truck_id="truck-new")

        assert history == []

    async def test_redis_ttl_set_on_write(self):
        """Entries should auto-expire after TTL days."""
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        mock_redis = AsyncMock()
        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30)

        await memory.record_anomaly(
            truck_id="truck-001",
            entry={"alert_type": "speed_anomaly", "timestamp": datetime.now(UTC).isoformat()},
        )

        # Should set TTL on the key
        mock_redis.expire.assert_called_once()
        call_args = mock_redis.expire.call_args
        assert call_args[0][0] == "truck:truck-001:anomalies"
        # 30 days in seconds
        assert call_args[0][1] == 30 * 86400

    async def test_list_trimmed_to_max_entries(self):
        """Keep at most 100 entries per truck (prevent unbounded growth)."""
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        mock_redis = AsyncMock()
        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30, max_entries=100)

        await memory.record_anomaly(
            truck_id="truck-001",
            entry={"alert_type": "temperature_spike", "timestamp": datetime.now(UTC).isoformat()},
        )

        mock_redis.ltrim.assert_called_once_with("truck:truck-001:anomalies", 0, 99)

    async def test_count_similar_alerts(self):
        """Count alerts of a specific type for pattern detection."""
        from apps.api.src.domains.logicore.infrastructure.fleet_memory import (
            FleetMemoryRedis,
        )

        stored_entries = [
            json.dumps({"alert_type": "temperature_spike", "timestamp": "2026-03-01"}),
            json.dumps({"alert_type": "speed_anomaly", "timestamp": "2026-03-02"}),
            json.dumps({"alert_type": "temperature_spike", "timestamp": "2026-03-05"}),
            json.dumps({"alert_type": "temperature_spike", "timestamp": "2026-03-09"}),
        ]

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=stored_entries)

        memory = FleetMemoryRedis(redis_client=mock_redis, ttl_days=30)
        count = await memory.count_similar_alerts(
            truck_id="truck-4521",
            alert_type="temperature_spike",
        )

        assert count == 3


# ── FleetAgentMemory (Long-term: PostgreSQL patterns) ────────────────────────


class TestFleetAgentMemoryPostgres:
    """PostgreSQL-based long-term memory for learned fleet patterns."""

    async def test_store_pattern(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        memory = FleetAgentMemoryPostgres(pool=mock_pool)

        entry = FleetMemoryEntry(
            truck_id="truck-4521",
            pattern="recurring_refrigeration_failure",
            alert_type="temperature_spike",
            action_taken="Diverted to cold storage 3 times",
            outcome="pending_verification",
            learned_at=datetime.now(UTC),
            occurrence_count=3,
        )

        await memory.store_pattern(entry)

        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        # Verify parameterized query (no string interpolation)
        query = call_args[0][0]
        assert "$1" in query
        assert "INSERT" in query.upper()

    async def test_get_patterns_for_truck(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "memory_id": "mem-001",
                    "truck_id": "truck-4521",
                    "pattern": "recurring_refrigeration_failure",
                    "alert_type": "temperature_spike",
                    "action_taken": "Diverted 3 times",
                    "outcome": "verified_fixed",
                    "learned_at": datetime.now(UTC),
                    "occurrence_count": 3,
                }
            ]
        )

        memory = FleetAgentMemoryPostgres(pool=mock_pool)
        patterns = await memory.get_patterns(truck_id="truck-4521")

        assert len(patterns) == 1
        assert patterns[0].pattern == "recurring_refrigeration_failure"
        assert patterns[0].occurrence_count == 3

    async def test_get_patterns_empty(self):
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)
        mock_conn.fetch = AsyncMock(return_value=[])

        memory = FleetAgentMemoryPostgres(pool=mock_pool)
        patterns = await memory.get_patterns(truck_id="truck-new")

        assert patterns == []

    async def test_query_uses_parameterized_sql(self):
        """Security: all SQL must use $N parameters, never string interpolation."""
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)
        mock_conn.fetch = AsyncMock(return_value=[])

        memory = FleetAgentMemoryPostgres(pool=mock_pool)

        # Attempt SQL injection via truck_id
        malicious_id = "'; DROP TABLE fleet_agent_memory; --"
        await memory.get_patterns(truck_id=malicious_id)

        # The malicious string should be passed as a parameter, not interpolated
        call_args = mock_conn.fetch.call_args
        query = call_args[0][0]
        assert "DROP" not in query
        assert "$1" in query
        # The malicious string is the parameter
        assert call_args[0][1] == malicious_id

    async def test_sql_injection_via_alert_type_in_store_pattern(self):
        """SQL injection via alert_type field — must be parameterized ($3)."""
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        memory = FleetAgentMemoryPostgres(pool=mock_pool)

        malicious_entry = FleetMemoryEntry(
            truck_id="truck-001",
            pattern="normal_pattern",
            alert_type="temperature_spike'); DROP TABLE fleet_agent_memory; --",
            action_taken="Diverted",
            outcome="pending_verification",
            learned_at=datetime.now(UTC),
            occurrence_count=1,
        )

        await memory.store_pattern(malicious_entry)

        call_args = mock_conn.execute.call_args
        query = call_args[0][0]
        # Query must NOT contain the injection payload
        assert "DROP" not in query
        # alert_type is $3 parameter
        assert "$3" in query
        # The malicious string goes as a parameter value, not in the query
        assert call_args[0][3] == malicious_entry.alert_type

    async def test_sql_injection_via_pattern_field_in_store_pattern(self):
        """SQL injection via pattern field — must be parameterized ($2)."""
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        memory = FleetAgentMemoryPostgres(pool=mock_pool)

        malicious_entry = FleetMemoryEntry(
            truck_id="truck-001",
            pattern="recurring'); DELETE FROM fleet_agent_memory WHERE '1'='1",
            alert_type="temperature_spike",
            action_taken="Diverted",
            outcome="pending_verification",
            learned_at=datetime.now(UTC),
            occurrence_count=1,
        )

        await memory.store_pattern(malicious_entry)

        call_args = mock_conn.execute.call_args
        query = call_args[0][0]
        assert "DELETE" not in query
        assert "$2" in query
        assert call_args[0][2] == malicious_entry.pattern

    async def test_sql_injection_via_action_taken_in_store_pattern(self):
        """SQL injection via action_taken field — must be parameterized ($4)."""
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        memory = FleetAgentMemoryPostgres(pool=mock_pool)

        malicious_entry = FleetMemoryEntry(
            truck_id="truck-001",
            pattern="test_pattern",
            alert_type="temperature_spike",
            action_taken="Diverted'; UPDATE fleet_agent_memory SET outcome='hacked' WHERE '1'='1",
            outcome="pending_verification",
            learned_at=datetime.now(UTC),
            occurrence_count=1,
        )

        await memory.store_pattern(malicious_entry)

        call_args = mock_conn.execute.call_args
        query = call_args[0][0]
        assert "UPDATE" not in query.split("INSERT")[0]  # UPDATE only appears in injected string
        assert "$4" in query
        assert call_args[0][4] == malicious_entry.action_taken

    async def test_second_order_injection_via_stored_pattern(self):
        """Stored malicious data should not execute when retrieved.

        Scenario: attacker stores SQL in pattern field via legitimate write.
        When the pattern is later retrieved (get_patterns), the stored SQL
        must be returned as data, not executed.
        """
        from apps.api.src.domains.logicore.infrastructure.fleet_agent_memory import (
            FleetAgentMemoryPostgres,
        )

        mock_conn = AsyncMock()
        mock_pool = _make_pg_pool_mock(mock_conn)

        # Simulate database returning a row with malicious data in pattern field
        malicious_pattern = "recurring'; DROP TABLE users; --"
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "memory_id": "1",
                    "truck_id": "truck-001",
                    "pattern": malicious_pattern,
                    "alert_type": "temperature_spike",
                    "action_taken": "Diverted",
                    "outcome": "pending_verification",
                    "learned_at": datetime.now(UTC),
                    "occurrence_count": 1,
                }
            ]
        )

        memory = FleetAgentMemoryPostgres(pool=mock_pool)
        patterns = await memory.get_patterns(truck_id="truck-001")

        # Pattern is returned as data, not executed
        assert len(patterns) == 1
        assert patterns[0].pattern == malicious_pattern
        # The retrieval query uses $1 parameter for truck_id
        call_args = mock_conn.fetch.call_args
        query = call_args[0][0]
        assert "$1" in query
        assert "DROP" not in query


# ── MemoryStore (3-tier abstraction) ─────────────────────────────────────────


class TestMemoryStore:
    """Unified 3-tier memory store that coordinates Redis + PostgreSQL."""

    async def test_lookup_returns_combined_history_and_patterns(self):
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.get_truck_history = AsyncMock(
            return_value=[
                {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-05"},
            ]
        )

        mock_pg_mem = AsyncMock()
        mock_pg_mem.get_patterns = AsyncMock(
            return_value=[
                FleetMemoryEntry(
                    truck_id="truck-4521",
                    pattern="recurring_refrigeration_failure",
                    alert_type="temperature_spike",
                    action_taken="Diverted 2 times",
                    outcome="pending",
                    learned_at=datetime.now(UTC),
                    occurrence_count=2,
                )
            ]
        )

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)
        result = await store.lookup(truck_id="truck-4521")

        assert len(result["truck_history"]) == 2
        assert len(result["known_patterns"]) == 1
        assert result["known_patterns"][0].pattern == "recurring_refrigeration_failure"

    async def test_write_back_records_to_redis(self):
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_pg_mem = AsyncMock()

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)

        await store.write_back(
            truck_id="truck-4721",
            alert_type="temperature_spike",
            severity="critical",
            action_taken="Diverted to Zurich cold storage",
        )

        mock_redis_mem.record_anomaly.assert_called_once()

    async def test_write_back_with_pattern_stores_to_postgres(self):
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_pg_mem = AsyncMock()

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)

        await store.write_back(
            truck_id="truck-4521",
            alert_type="temperature_spike",
            severity="critical",
            action_taken="Maintenance alert",
            pattern_detected="recurring_refrigeration_failure",
            occurrence_count=3,
        )

        # Should write to BOTH Redis and PostgreSQL
        mock_redis_mem.record_anomaly.assert_called_once()
        mock_pg_mem.store_pattern.assert_called_once()

    async def test_write_back_without_pattern_skips_postgres(self):
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_pg_mem = AsyncMock()

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)

        await store.write_back(
            truck_id="truck-001",
            alert_type="speed_anomaly",
            severity="medium",
            action_taken="Driver notified",
        )

        mock_redis_mem.record_anomaly.assert_called_once()
        mock_pg_mem.store_pattern.assert_not_called()

    async def test_detect_recurring_pattern(self):
        """If same alert type occurs 3+ times, flag as recurring pattern."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.count_similar_alerts = AsyncMock(return_value=3)

        mock_pg_mem = AsyncMock()

        store = MemoryStore(
            redis_memory=mock_redis_mem,
            pg_memory=mock_pg_mem,
            recurring_threshold=3,
        )

        is_recurring = await store.is_recurring_pattern(
            truck_id="truck-4521",
            alert_type="temperature_spike",
        )

        assert is_recurring is True

    async def test_not_recurring_below_threshold(self):
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.count_similar_alerts = AsyncMock(return_value=1)

        mock_pg_mem = AsyncMock()

        store = MemoryStore(
            redis_memory=mock_redis_mem,
            pg_memory=mock_pg_mem,
            recurring_threshold=3,
        )

        is_recurring = await store.is_recurring_pattern(
            truck_id="truck-001",
            alert_type="temperature_spike",
        )

        assert is_recurring is False


# ── Graceful Degradation (memory tier failure) ────────────────────────────


class TestMemoryGracefulDegradation:
    """A broken memory tier must never prevent anomaly response.

    When Redis is down, the agent falls back to stateless investigation
    (no history = treat as new truck). When PostgreSQL is down, the agent
    completes notification but skips long-term persistence.

    ARCHITECT DECISION: Silent memory failure is acceptable because:
    - The anomaly response still happens (driver still gets alerted)
    - Memory is supplementary context, not a correctness requirement
    - The alternative (crashing on Redis timeout) means cargo spoils
      while ops restarts Redis — EUR 207,000 per incident
    """

    async def test_redis_down_during_lookup_returns_empty_history(self):
        """Redis connection refused -> empty history -> agent investigates from scratch."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.get_truck_history = AsyncMock(
            side_effect=ConnectionError("Redis connection refused")
        )

        mock_pg_mem = AsyncMock()
        mock_pg_mem.get_patterns = AsyncMock(return_value=[])

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)
        result = await store.lookup(truck_id="truck-4721")

        assert result["truck_history"] == []
        assert result["known_patterns"] == []

    async def test_postgres_down_during_lookup_returns_empty_patterns(self):
        """PostgreSQL timeout -> empty patterns -> agent investigates normally."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.get_truck_history = AsyncMock(
            return_value=[{"alert_type": "temperature_spike", "timestamp": "2026-03-01"}]
        )

        mock_pg_mem = AsyncMock()
        mock_pg_mem.get_patterns = AsyncMock(
            side_effect=TimeoutError("PostgreSQL connection timed out")
        )

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)
        result = await store.lookup(truck_id="truck-4721")

        assert len(result["truck_history"]) == 1
        assert result["known_patterns"] == []

    async def test_both_tiers_down_returns_empty_everything(self):
        """Redis + PostgreSQL both down -> full stateless fallback."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.get_truck_history = AsyncMock(
            side_effect=ConnectionError("Redis down")
        )

        mock_pg_mem = AsyncMock()
        mock_pg_mem.get_patterns = AsyncMock(
            side_effect=ConnectionError("PostgreSQL down")
        )

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)
        result = await store.lookup(truck_id="truck-4721")

        assert result["truck_history"] == []
        assert result["known_patterns"] == []

    async def test_redis_down_during_write_back_does_not_crash(self):
        """Redis write failure -> agent still completes (notification not blocked)."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.record_anomaly = AsyncMock(
            side_effect=ConnectionError("Redis write failed")
        )

        mock_pg_mem = AsyncMock()

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)

        # Should not raise — graceful degradation
        await store.write_back(
            truck_id="truck-4721",
            alert_type="temperature_spike",
            severity="critical",
            action_taken="Diverted to cold storage",
        )

        # Redis was called (and failed), but no exception propagated
        mock_redis_mem.record_anomaly.assert_called_once()

    async def test_postgres_down_during_write_back_does_not_crash(self):
        """PostgreSQL write failure -> pattern not persisted, but agent completes."""
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )

        mock_redis_mem = AsyncMock()
        mock_pg_mem = AsyncMock()
        mock_pg_mem.store_pattern = AsyncMock(
            side_effect=ConnectionError("PostgreSQL write failed")
        )

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)

        # Should not raise even with pattern (triggers PG write)
        await store.write_back(
            truck_id="truck-4521",
            alert_type="temperature_spike",
            severity="critical",
            action_taken="Maintenance alert",
            pattern_detected="recurring_refrigeration_failure",
            occurrence_count=3,
        )

        # Redis succeeded, PG was called (and failed)
        mock_redis_mem.record_anomaly.assert_called_once()
        mock_pg_mem.store_pattern.assert_called_once()

    async def test_degraded_lookup_routes_to_investigate_not_escalate(self):
        """With Redis down, no history -> route_by_memory -> 'investigate' (not escalate).

        This is correct behavior: without memory, the agent can't know about
        recurring patterns, so it does a full investigation. Better to over-investigate
        than to miss a critical anomaly.
        """
        from apps.api.src.domains.logicore.agents.guardian.memory_store import (
            MemoryStore,
        )
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            route_by_memory,
        )

        mock_redis_mem = AsyncMock()
        mock_redis_mem.get_truck_history = AsyncMock(
            side_effect=ConnectionError("Redis down")
        )

        mock_pg_mem = AsyncMock()
        mock_pg_mem.get_patterns = AsyncMock(
            side_effect=ConnectionError("PostgreSQL down")
        )

        store = MemoryStore(redis_memory=mock_redis_mem, pg_memory=mock_pg_mem)
        memory_context = await store.lookup(truck_id="truck-4521")

        state = {
            "alert": {"truck_id": "truck-4521", "alert_type": "temperature_spike"},
            "truck_history": memory_context["truck_history"],
            "known_patterns": memory_context["known_patterns"],
            "pattern_detected": None,
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
        }

        route = route_by_memory(state)
        assert route == "investigate", (
            "With memory tiers down, agent must fall back to full investigation. "
            "Never skip investigation just because memory is unavailable."
        )
