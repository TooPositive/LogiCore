"""PostgreSQL-based long-term fleet agent memory.

Stores confirmed patterns and learned behaviors that persist indefinitely.
Used for fleet-wide learnings: recurring failures, false positive history,
maintenance escalation patterns.

Table: fleet_agent_memory (see scripts/create_fleet_agent_memory_table.sql).
All queries use parameterized SQL -- no string interpolation.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

logger = logging.getLogger(__name__)


class FleetAgentMemoryPostgres:
    """Long-term pattern memory backed by PostgreSQL.

    Args:
        pool: asyncpg connection pool.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def store_pattern(self, entry: FleetMemoryEntry) -> None:
        """Store a learned pattern to long-term memory.

        Uses parameterized query -- truck_id and all fields are $N parameters.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO fleet_agent_memory
                    (truck_id, pattern, alert_type, action_taken,
                     outcome, learned_at, occurrence_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                entry.truck_id,
                entry.pattern,
                entry.alert_type,
                entry.action_taken,
                entry.outcome,
                entry.learned_at,
                entry.occurrence_count,
            )

    async def get_patterns(
        self, truck_id: str, limit: int = 5
    ) -> list[FleetMemoryEntry]:
        """Get known patterns for a truck, most recent first.

        Uses parameterized query -- truck_id is never interpolated.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT memory_id, truck_id, pattern, alert_type,
                       action_taken, outcome, learned_at, occurrence_count
                FROM fleet_agent_memory
                WHERE truck_id = $1
                ORDER BY learned_at DESC
                LIMIT $2
                """,
                truck_id,
                limit,
            )

        return [
            FleetMemoryEntry(
                memory_id=str(row["memory_id"]) if row.get("memory_id") else None,
                truck_id=row["truck_id"],
                pattern=row["pattern"],
                alert_type=row["alert_type"],
                action_taken=row["action_taken"],
                outcome=row["outcome"],
                learned_at=row["learned_at"],
                occurrence_count=row.get("occurrence_count", 1),
            )
            for row in rows
        ]
