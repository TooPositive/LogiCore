"""3-tier memory abstraction for fleet guardian agent.

Coordinates Redis (medium-term, 30-day window) and PostgreSQL (long-term,
indefinite) memory behind a single interface. Short-term memory lives in
LangGraph state (not managed here).

Memory tiers:
  Short-term  -> LangGraph TypedDict state (within single workflow run)
  Medium-term -> Redis per-truck history (30-day sliding window)
  Long-term   -> PostgreSQL fleet_agent_memory (indefinite, learned patterns)
"""

import logging
from datetime import UTC, datetime
from typing import Any

from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

logger = logging.getLogger(__name__)


class MemoryStore:
    """Unified 3-tier memory for fleet guardian agent.

    Args:
        redis_memory: FleetMemoryRedis instance (medium-term).
        pg_memory: FleetAgentMemoryPostgres instance (long-term).
        recurring_threshold: Number of similar alerts to flag as recurring.
    """

    def __init__(
        self,
        redis_memory: Any,
        pg_memory: Any,
        recurring_threshold: int = 3,
    ) -> None:
        self._redis = redis_memory
        self._pg = pg_memory
        self._recurring_threshold = recurring_threshold

    async def lookup(self, truck_id: str) -> dict[str, Any]:
        """Retrieve all memory context for a truck.

        Returns both medium-term history (Redis) and long-term patterns (PostgreSQL).
        """
        truck_history = await self._redis.get_truck_history(truck_id)
        known_patterns = await self._pg.get_patterns(truck_id)

        return {
            "truck_history": truck_history,
            "known_patterns": known_patterns,
        }

    async def write_back(
        self,
        truck_id: str,
        alert_type: str,
        severity: str,
        action_taken: str,
        pattern_detected: str | None = None,
        occurrence_count: int = 1,
    ) -> None:
        """Write anomaly resolution back to memory.

        Always writes to Redis (medium-term).
        If a pattern was detected, also writes to PostgreSQL (long-term).
        """
        # Medium-term: always record in Redis
        await self._redis.record_anomaly(
            truck_id=truck_id,
            entry={
                "alert_type": alert_type,
                "severity": severity,
                "action_taken": action_taken,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # Long-term: only persist if pattern detected
        if pattern_detected:
            entry = FleetMemoryEntry(
                truck_id=truck_id,
                pattern=pattern_detected,
                alert_type=alert_type,
                action_taken=action_taken,
                outcome="pending_verification",
                learned_at=datetime.now(UTC),
                occurrence_count=occurrence_count,
            )
            await self._pg.store_pattern(entry)

    async def is_recurring_pattern(
        self, truck_id: str, alert_type: str
    ) -> bool:
        """Check if a truck has a recurring pattern for a given alert type.

        Returns True if the number of similar alerts exceeds the threshold.
        """
        count = await self._redis.count_similar_alerts(truck_id, alert_type)
        return count >= self._recurring_threshold
