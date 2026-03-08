"""Compliance sub-agent -- retrieves legal context for unknown clauses.

Spawned dynamically by the auditor when it encounters an amendment
or surcharge clause it can't resolve. Gets temporary elevated clearance
scoped to the run. Findings are filtered by ClearanceFilter before
returning to the parent state.

Delegation trigger: keyword-based, NOT LLM-based. This is a deliberate
recall-over-precision tradeoff. False positive (unnecessary compliance
check) costs ~500ms + 1 RAG query. False negative (missed contract
amendment) costs EUR 136-588 per invoice in undetected overcharges.
At this 270-1176x cost asymmetry, we accept 100% recall at the cost
of ~10% false positive rate. Switch to LLM-based trigger only when
false positive rate exceeds 30% and the 500ms penalty becomes a
latency SLA issue.

Keywords (11): amendment, surcharge, unknown clause, addendum,
supplement, revision, penalty, annex, rider, modification, protocol.
"""

import re
from typing import Any

from apps.api.src.graphs.clearance_filter import ClearanceFilter

# Keywords that indicate the discrepancy may involve a contract amendment
# or clause that requires legal context.
#
# Deliberately broad: false positive = 500ms wasted, false negative = EUR 136-588 lost.
# The cost asymmetry (270-1176x) justifies high recall over precision.
_DELEGATION_KEYWORDS = re.compile(
    r"amendment|surcharge|unknown\s+clause|addendum|supplement|revision"
    r"|penalty|annex|rider|modification|protocol",
    re.IGNORECASE,
)


def needs_legal_context(discrepancies: list[dict[str, Any]]) -> bool:
    """Determine if any discrepancy requires legal context lookup.

    Returns True if any discrepancy description contains keywords
    suggesting a contract amendment or unknown clause.
    """
    for d in discrepancies:
        desc = d.get("description", "")
        if _DELEGATION_KEYWORDS.search(desc):
            return True
    return False


async def run_compliance_check(
    contract_id: str,
    query: str,
    retriever,
    elevated_clearance: int = 3,
    parent_clearance: int | None = None,
) -> list[dict[str, Any]]:
    """Run a compliance check for contract amendments.

    Uses elevated clearance for the search, then filters results
    to parent_clearance before returning.

    Args:
        contract_id: The contract to search for amendments.
        query: Search query for relevant amendments.
        retriever: RAG retriever (injected).
        elevated_clearance: Temporary clearance for this search.
        parent_clearance: Parent's clearance level for filtering.
            If None, no filtering is applied (caller is at max clearance).

    Returns:
        List of findings filtered to parent_clearance.
    """
    search_query = f"contract {contract_id} {query}"
    results = await retriever.search(search_query)

    if not results:
        return []

    # Build findings with clearance metadata
    findings: list[dict[str, Any]] = []
    for r in results:
        # In a real system, the clearance_level would come from the
        # document metadata in Qdrant. For now, we assign based on
        # the content source.
        clearance = getattr(r, "clearance_level", 1)
        if not clearance:
            clearance = 1

        findings.append({
            "content": r.content,
            "source": getattr(r, "source", "unknown"),
            "score": getattr(r, "score", 0.0),
            "clearance_level": clearance,
            "contract_id": contract_id,
        })

    # Apply clearance filter before returning to parent
    if parent_clearance is not None:
        findings = ClearanceFilter.filter(findings, parent_clearance)

    return findings
