"""ClearanceFilter -- architectural guard against clearance leaks.

The compliance sub-agent receives elevated clearance to access
confidential contract amendments. Its return value MUST be filtered
to the parent's clearance level before state merge.

This is enforced by the graph structure, not by agent prompts.
The filter is the LAST step before data enters the parent state.
"""

from typing import Any


class ClearanceFilter:
    """Filters findings to a maximum clearance level.

    Prevents clearance-3 data from leaking into clearance-2 parent state.
    Applied architecturally (in graph code), not procedurally (in prompts).
    """

    @staticmethod
    def filter(
        findings: list[dict[str, Any]],
        parent_clearance: int,
    ) -> list[dict[str, Any]]:
        """Strip findings above the parent's clearance level.

        Args:
            findings: List of dicts with 'clearance_level' field.
            parent_clearance: Maximum allowed clearance in parent state.

        Returns:
            Filtered list with only findings at or below parent clearance.
        """
        return [
            f for f in findings
            if f.get("clearance_level", 1) <= parent_clearance
        ]
