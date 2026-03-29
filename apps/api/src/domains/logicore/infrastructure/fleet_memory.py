"""Redis-based medium-term fleet memory.

Per-truck anomaly history with a configurable sliding window (default 30 days).
Enables pattern detection across recent workflow runs without hitting PostgreSQL.

Key format: truck:{truck_id}:anomalies
Value: JSON list of anomaly event dicts, most recent first.
TTL: configurable (default 30 days), refreshed on each write.
Max entries: configurable (default 100), trimmed on each write.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FleetMemoryRedis:
    """Medium-term per-truck anomaly memory backed by Redis.

    Args:
        redis_client: Async Redis client instance.
        ttl_days: How long to keep truck history (default 30 days).
        max_entries: Max entries per truck (default 100).
    """

    def __init__(
        self,
        redis_client: Any,
        ttl_days: int = 30,
        max_entries: int = 100,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_days * 86400
        self._max_entries = max_entries

    def _key(self, truck_id: str) -> str:
        return f"truck:{truck_id}:anomalies"

    async def record_anomaly(self, truck_id: str, entry: dict[str, Any]) -> None:
        """Append an anomaly event to the truck's history.

        Trims list to max_entries and refreshes TTL.
        """
        key = self._key(truck_id)
        await self._redis.lpush(key, json.dumps(entry, default=str))
        await self._redis.ltrim(key, 0, self._max_entries - 1)
        await self._redis.expire(key, self._ttl_seconds)

    async def get_truck_history(self, truck_id: str) -> list[dict[str, Any]]:
        """Get the recent anomaly history for a truck.

        Returns list of dicts, most recent first.
        """
        key = self._key(truck_id)
        raw_entries = await self._redis.lrange(key, 0, -1)
        return [json.loads(entry) for entry in raw_entries]

    async def count_similar_alerts(
        self, truck_id: str, alert_type: str
    ) -> int:
        """Count alerts of a specific type in the truck's history.

        Used for recurring pattern detection.
        """
        history = await self.get_truck_history(truck_id)
        return sum(1 for entry in history if entry.get("alert_type") == alert_type)
