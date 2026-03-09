"""Bias detection for EU AI Act fairness compliance.

Statistical checks for routing and model preference bias:
  - Routing bias: are decisions unfairly distributed across departments?
  - Model preference: do certain queries consistently get routed to specific models?
  - Degraded correlation: do degraded-mode decisions correlate with specific departments?

Bias thresholds:
  - Department routing: flagged if any department has >2x the expected rate
  - Model preference: flagged if any model handles >2x the expected share
  - Degraded correlation: flagged if any department has >2x expected degraded rate

Security model:
  1. Parameterized queries only ($1, $2, ...) -- no string interpolation
  2. All methods accept an asyncpg connection for transaction sharing
"""

from datetime import datetime

# --- SQL (parameterized) ---

_DECISIONS_BY_DEPARTMENT_SQL = """
SELECT
    COALESCE(metadata->>'department', 'unknown') AS department,
    COUNT(*) AS count
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
GROUP BY COALESCE(metadata->>'department', 'unknown')
ORDER BY count DESC
"""

_TOTAL_DECISIONS_SQL = """
SELECT COUNT(*) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
"""

_DECISIONS_BY_MODEL_SQL = """
SELECT model_version, COUNT(*) AS count
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
GROUP BY model_version
ORDER BY count DESC
"""

_DEGRADED_BY_DEPARTMENT_SQL = """
SELECT
    COALESCE(metadata->>'department', 'unknown') AS department,
    COUNT(*) AS count
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2 AND is_degraded = TRUE
GROUP BY COALESCE(metadata->>'department', 'unknown')
ORDER BY count DESC
"""

_TOTAL_DEGRADED_SQL = """
SELECT COUNT(*) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2 AND is_degraded = TRUE
"""

# Bias threshold: >2x expected proportion
_BIAS_THRESHOLD = 2.0


def _detect_proportion_bias(
    rows: list[dict],
    total: int,
    group_key: str,
) -> tuple[bool, list[str]]:
    """Check if any group has >2x its expected proportion.

    Args:
        rows: list of dicts with group_key and 'count' fields
        total: total number of decisions
        group_key: key name for the group label (e.g., 'department', 'model_version')

    Returns:
        (bias_detected, list of flagged group names)
    """
    if total == 0 or len(rows) == 0:
        return False, []

    num_groups = len(rows)
    expected_rate = 1.0 / num_groups
    flagged = []

    for row in rows:
        actual_rate = row["count"] / total
        if actual_rate > expected_rate * _BIAS_THRESHOLD:
            flagged.append(row[group_key])

    return len(flagged) > 0, flagged


class BiasDetector:
    """Statistical fairness checks for AI decision bias.

    All methods accept an asyncpg connection (not pool) for
    transaction sharing with other compliance operations.
    """

    async def detect_routing_bias(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Check if decisions are unfairly distributed across departments.

        Flags any department with >2x the expected decision rate.

        Args:
            conn: asyncpg connection
            period_start: start of period
            period_end: end of period

        Returns:
            Dict with bias_detected (bool) and flagged_departments (list).
        """
        dept_rows = await conn.fetch(
            _DECISIONS_BY_DEPARTMENT_SQL, period_start, period_end
        )
        total = await conn.fetchval(
            _TOTAL_DECISIONS_SQL, period_start, period_end
        )

        bias_detected, flagged = _detect_proportion_bias(
            dept_rows, total, "department"
        )

        return {
            "bias_detected": bias_detected,
            "flagged_departments": flagged,
            "total_decisions": total,
            "department_counts": {
                row["department"]: row["count"] for row in dept_rows
            },
        }

    async def detect_model_preference_bias(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Check if queries consistently get routed to specific models.

        Flags any model handling >2x the expected share.

        Args:
            conn: asyncpg connection
            period_start: start of period
            period_end: end of period

        Returns:
            Dict with bias_detected (bool) and flagged_models (list).
        """
        model_rows = await conn.fetch(
            _DECISIONS_BY_MODEL_SQL, period_start, period_end
        )
        total = await conn.fetchval(
            _TOTAL_DECISIONS_SQL, period_start, period_end
        )

        bias_detected, flagged = _detect_proportion_bias(
            model_rows, total, "model_version"
        )

        return {
            "bias_detected": bias_detected,
            "flagged_models": flagged,
            "total_decisions": total,
            "model_counts": {
                row["model_version"]: row["count"] for row in model_rows
            },
        }

    async def generate_fairness_report(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Generate comprehensive fairness assessment.

        Combines routing bias, model preference bias, and degraded
        mode correlation checks into a single report.

        Args:
            conn: asyncpg connection
            period_start: start of period
            period_end: end of period

        Returns:
            Dict with routing_bias, model_preference_bias, and
            degraded_correlation sections.
        """
        routing_result = await self.detect_routing_bias(
            conn, period_start, period_end
        )
        model_result = await self.detect_model_preference_bias(
            conn, period_start, period_end
        )
        degraded_result = await self._detect_degraded_correlation(
            conn, period_start, period_end
        )

        return {
            "routing_bias": routing_result,
            "model_preference_bias": model_result,
            "degraded_correlation": degraded_result,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    async def _detect_degraded_correlation(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Check if degraded-mode decisions correlate with specific departments.

        Flags if any department receives >2x the expected share of
        degraded decisions. This could indicate infrastructure bias
        (e.g., one department's requests always hit an overloaded server).

        Args:
            conn: asyncpg connection
            period_start: start of period
            period_end: end of period

        Returns:
            Dict with bias_detected (bool) and flagged_departments (list).
        """
        dept_rows = await conn.fetch(
            _DEGRADED_BY_DEPARTMENT_SQL, period_start, period_end
        )
        total = await conn.fetchval(
            _TOTAL_DEGRADED_SQL, period_start, period_end
        )

        bias_detected, flagged = _detect_proportion_bias(
            dept_rows, total, "department"
        )

        return {
            "bias_detected": bias_detected,
            "flagged_departments": flagged,
            "total_degraded": total,
            "department_counts": {
                row["department"]: row["count"] for row in dept_rows
            },
        }
