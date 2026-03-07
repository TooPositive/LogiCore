"""Ground truth dataset for retrieval quality evaluation.

50+ test queries across 10 categories, with expected document IDs.
Built from the 12-document LogiCore corpus (Phase 1 benchmark).

Each query represents a realistic logistics worker search — the kind
of thing a warehouse operator, HR director, or CEO would actually type.

Document IDs in the corpus:
- DOC-SAFETY-001: ISO 9001 Quality Management Manual (warehouse, clearance 1)
- DOC-HR-003:     Driver Safety Protocol (warehouse, clearance 1)
- DOC-SAFETY-002: Warehouse Fire Safety Plan (warehouse, clearance 1)
- DOC-SAFETY-003: Forklift Operation Manual (warehouse, clearance 1)
- DOC-HR-002:     Executive Compensation Policy (hr, clearance 4)
- DOC-HR-004:     Employee Termination Procedures (hr, clearance 3)
- DOC-HR-005:     Employee Onboarding Handbook (hr, clearance 1)
- DOC-LEGAL-001:  PharmaCorp Service Agreement CTR-2024-001 (legal, clearance 2)
- DOC-LEGAL-002:  FreshFoods Logistics Agreement CTR-2024-002 (legal, clearance 2)
- DOC-LEGAL-003:  AutoParts Express Contract CTR-2024-003 (legal, clearance 2)
- DOC-LEGAL-004:  ChemTrans Hazmat Agreement CTR-2024-004 (legal, clearance 2)
- DOC-LEGAL-005:  LogiCore Master Service Agreement template (legal, clearance 2)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GroundTruthQuery:
    """A test query with ground truth annotations for evaluation."""

    query: str
    category: str  # see categories list below
    relevant_doc_ids: list[str]  # document IDs that SHOULD appear in results
    description: str = ""  # what this query tests


# ---------------------------------------------------------------------------
# Categories explained:
#
# exact_code    — alphanumeric codes, contract numbers, regulation references
# natural_language — clear factual question in plain language
# vague         — broad, exploratory, underspecified
# negation      — "without", "non-", "excluding"
# german        — German language queries (LogiCore is a German company)
# synonym       — no keyword overlap with target document
# typo          — common misspellings
# jargon        — industry abbreviations, acronyms
# ranking       — multiple docs match, correct one must rank highest
# multi_hop     — requires combining info from multiple documents
# ---------------------------------------------------------------------------

GROUND_TRUTH: list[GroundTruthQuery] = [
    # =========================================================================
    # EXACT_CODE (8 queries)
    # =========================================================================
    GroundTruthQuery(
        query="CTR-2024-001",
        category="exact_code",
        relevant_doc_ids=["DOC-LEGAL-001"],
        description="PharmaCorp contract by exact contract number",
    ),
    GroundTruthQuery(
        query="CTR-2024-004",
        category="exact_code",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="ChemTrans contract by exact contract number",
    ),
    GroundTruthQuery(
        query="EU Regulation 561/2006",
        category="exact_code",
        relevant_doc_ids=["DOC-HR-003"],
        description="EU driving hours regulation by number",
    ),
    GroundTruthQuery(
        query="ISO-9001 Section 4.2",
        category="exact_code",
        relevant_doc_ids=["DOC-SAFETY-001"],
        description="ISO standard section reference",
    ),
    GroundTruthQuery(
        query="CTR-2024-002",
        category="exact_code",
        relevant_doc_ids=["DOC-LEGAL-002"],
        description="FreshFoods contract by exact number",
    ),
    GroundTruthQuery(
        query="CTR-2024-003",
        category="exact_code",
        relevant_doc_ids=["DOC-LEGAL-003"],
        description="AutoParts contract by exact number",
    ),
    GroundTruthQuery(
        query="ISO 9001",
        category="exact_code",
        relevant_doc_ids=["DOC-SAFETY-001"],
        description="ISO standard by code only (no section)",
    ),
    GroundTruthQuery(
        query="EC No 561/2006 driving hours",
        category="exact_code",
        relevant_doc_ids=["DOC-HR-003"],
        description="EU regulation with additional context words",
    ),
    # =========================================================================
    # NATURAL_LANGUAGE (8 queries)
    # =========================================================================
    GroundTruthQuery(
        query="what are the penalty fees for late deliveries",
        category="natural_language",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003"],
        description="Multiple contracts have penalty clauses",
    ),
    GroundTruthQuery(
        query="how long is the probation period for new employees",
        category="natural_language",
        relevant_doc_ids=["DOC-HR-005"],
        description="Onboarding handbook mentions 6-month probation",
    ),
    GroundTruthQuery(
        query="what is the maximum driving time per day",
        category="natural_language",
        relevant_doc_ids=["DOC-HR-003"],
        description="Driver safety protocol specifies 9 hours max",
    ),
    GroundTruthQuery(
        query="where is the emergency assembly point",
        category="natural_language",
        relevant_doc_ids=["DOC-SAFETY-002"],
        description="Fire safety plan specifies parking lot B",
    ),
    GroundTruthQuery(
        query="what is the forklift speed limit in the warehouse",
        category="natural_language",
        relevant_doc_ids=["DOC-SAFETY-003"],
        description="Forklift manual specifies 10 km/h",
    ),
    GroundTruthQuery(
        query="how much severance do employees get",
        category="natural_language",
        relevant_doc_ids=["DOC-HR-004"],
        description="Termination procedures: 0.5 months per year",
    ),
    GroundTruthQuery(
        query="what is the CEO salary",
        category="natural_language",
        relevant_doc_ids=["DOC-HR-002"],
        description="Executive compensation: EUR 280,000",
    ),
    GroundTruthQuery(
        query="when should fire extinguishers be inspected",
        category="natural_language",
        relevant_doc_ids=["DOC-SAFETY-002"],
        description="Fire safety: every 6 months",
    ),
    # =========================================================================
    # VAGUE (6 queries)
    # =========================================================================
    GroundTruthQuery(
        query="safety",
        category="vague",
        relevant_doc_ids=["DOC-HR-003", "DOC-SAFETY-001", "DOC-SAFETY-002", "DOC-SAFETY-003"],
        description="Broad term matching multiple safety documents",
    ),
    GroundTruthQuery(
        query="contracts",
        category="vague",
        relevant_doc_ids=[
            "DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003",
            "DOC-LEGAL-004", "DOC-LEGAL-005",
        ],
        description="Should return multiple legal documents",
    ),
    GroundTruthQuery(
        query="rules and procedures",
        category="vague",
        relevant_doc_ids=[
            "DOC-HR-003", "DOC-HR-004", "DOC-SAFETY-001",
            "DOC-SAFETY-002", "DOC-SAFETY-003",
        ],
        description="Very vague - many docs have rules/procedures",
    ),
    GroundTruthQuery(
        query="employee information",
        category="vague",
        relevant_doc_ids=["DOC-HR-002", "DOC-HR-004", "DOC-HR-005"],
        description="General HR query",
    ),
    GroundTruthQuery(
        query="transport logistics",
        category="vague",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003", "DOC-LEGAL-004"],
        description="Core business term - most docs relevant",
    ),
    GroundTruthQuery(
        query="warehouse operations",
        category="vague",
        relevant_doc_ids=["DOC-SAFETY-001", "DOC-SAFETY-002", "DOC-SAFETY-003"],
        description="Should match warehouse-specific docs",
    ),
    # =========================================================================
    # NEGATION (6 queries)
    # =========================================================================
    GroundTruthQuery(
        query="contracts without temperature requirements",
        category="negation",
        relevant_doc_ids=["DOC-LEGAL-003"],
        description="AutoParts has 'No temperature requirements' - negation understanding",
    ),
    GroundTruthQuery(
        query="non-perishable transport agreements",
        category="negation",
        relevant_doc_ids=["DOC-LEGAL-003"],
        description="AutoParts is non-perishable. Must understand 'non-' prefix",
    ),
    GroundTruthQuery(
        query="contracts that are not for food",
        category="negation",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-003", "DOC-LEGAL-004"],
        description="Excludes FreshFoods (DOC-LEGAL-002)",
    ),
    GroundTruthQuery(
        query="employees without stock options",
        category="negation",
        relevant_doc_ids=["DOC-HR-004", "DOC-HR-005"],
        description="Stock options only in exec comp (DOC-HR-002)",
    ),
    GroundTruthQuery(
        query="transport without hazmat certification",
        category="negation",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003"],
        description="Excludes ChemTrans which requires ADR",
    ),
    GroundTruthQuery(
        query="non-confidential employee documents",
        category="negation",
        relevant_doc_ids=["DOC-HR-005"],
        description="Only onboarding handbook is non-confidential HR doc",
    ),
    # =========================================================================
    # GERMAN (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="Gefahrgut Vorschriften",
        category="german",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="German for 'dangerous goods regulations' -> ChemTrans hazmat",
    ),
    GroundTruthQuery(
        query="Arbeitszeit Regelung LKW Fahrer",
        category="german",
        relevant_doc_ids=["DOC-HR-003"],
        description="German for 'working hours regulation truck driver'",
    ),
    GroundTruthQuery(
        query="Kuendigungsfristen",
        category="german",
        relevant_doc_ids=["DOC-HR-004"],
        description="German for 'notice periods' -> termination procedures",
    ),
    GroundTruthQuery(
        query="Qualitaetskontrolle Lager",
        category="german",
        relevant_doc_ids=["DOC-SAFETY-001"],
        description="German for 'quality control warehouse'",
    ),
    # =========================================================================
    # SYNONYM (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="letting go of underperforming staff",
        category="synonym",
        relevant_doc_ids=["DOC-HR-004"],
        description="No keyword overlap with 'termination' or 'firing'",
    ),
    GroundTruthQuery(
        query="new employee first day process",
        category="synonym",
        relevant_doc_ids=["DOC-HR-005"],
        description="'first day' has no keyword match with 'onboarding'",
    ),
    GroundTruthQuery(
        query="executive pay packages",
        category="synonym",
        relevant_doc_ids=["DOC-HR-002"],
        description="'pay packages' != 'compensation' or 'salary'",
    ),
    GroundTruthQuery(
        query="dangerous goods shipping rules",
        category="synonym",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="'dangerous goods' = 'hazardous materials' synonym",
    ),
    # =========================================================================
    # TYPO (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="pharamcorp contract",
        category="typo",
        relevant_doc_ids=["DOC-LEGAL-001"],
        description="Transposed letters in 'PharmaCorp'",
    ),
    GroundTruthQuery(
        query="tempature requirements",
        category="typo",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002"],
        description="Common misspelling of 'temperature'",
    ),
    GroundTruthQuery(
        query="saftey protocol",
        category="typo",
        relevant_doc_ids=["DOC-HR-003", "DOC-SAFETY-002"],
        description="Common misspelling of 'safety'",
    ),
    GroundTruthQuery(
        query="terminaton procedures",
        category="typo",
        relevant_doc_ids=["DOC-HR-004"],
        description="Missing letter in 'termination'",
    ),
    # =========================================================================
    # JARGON (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="ADR certified transport",
        category="jargon",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="ADR = European Agreement for transport of dangerous goods",
    ),
    GroundTruthQuery(
        query="SLA breach consequences",
        category="jargon",
        relevant_doc_ids=["DOC-LEGAL-001"],
        description="SLA mentioned in PharmaCorp contract",
    ),
    GroundTruthQuery(
        query="NET 30 payment terms",
        category="jargon",
        relevant_doc_ids=["DOC-LEGAL-005"],
        description="Standard payment term in MSA template",
    ),
    GroundTruthQuery(
        query="force majeure clause",
        category="jargon",
        relevant_doc_ids=["DOC-LEGAL-005"],
        description="Legal term in MSA template",
    ),
    # =========================================================================
    # RANKING (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="temperature requirements for pharmaceutical transport",
        category="ranking",
        relevant_doc_ids=["DOC-LEGAL-001"],
        description="Both LEGAL-001 and LEGAL-002 mention temp, but pharma = LEGAL-001",
    ),
    GroundTruthQuery(
        query="highest penalty per incident across all contracts",
        category="ranking",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="ChemTrans EUR 5,000 is highest. Needs cross-doc comparison.",
    ),
    GroundTruthQuery(
        query="workplace safety equipment inspection",
        category="ranking",
        relevant_doc_ids=["DOC-SAFETY-002"],
        description="Fire safety has extinguisher inspection. Multiple safety docs.",
    ),
    GroundTruthQuery(
        query="contract with the largest annual value",
        category="ranking",
        relevant_doc_ids=["DOC-LEGAL-004"],
        description="ChemTrans EUR 2.1M. Requires numerical reasoning.",
    ),
    # =========================================================================
    # MULTI_HOP (4 queries)
    # =========================================================================
    GroundTruthQuery(
        query="which contracts require special driver certifications",
        category="multi_hop",
        relevant_doc_ids=["DOC-LEGAL-004", "DOC-HR-003"],
        description="ChemTrans needs ADR cert + driver safety mentions certifications",
    ),
    GroundTruthQuery(
        query="total annual value of all temperature-controlled contracts",
        category="multi_hop",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002"],
        description="PharmaCorp + FreshFoods both have temp requirements and values",
    ),
    GroundTruthQuery(
        query="what happens if a driver exceeds maximum hours and causes a late delivery",
        category="multi_hop",
        relevant_doc_ids=["DOC-HR-003", "DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003"],
        description="Driver safety hours + penalty clauses across contracts",
    ),
    GroundTruthQuery(
        query="compare penalty structures across all service agreements",
        category="multi_hop",
        relevant_doc_ids=["DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003", "DOC-LEGAL-004"],
        description="Needs all 4 contracts to compare penalties",
    ),
]


def get_queries_by_category(category: str) -> list[GroundTruthQuery]:
    """Filter ground truth queries by category."""
    return [q for q in GROUND_TRUTH if q.category == category]


def get_all_categories() -> list[str]:
    """Return sorted list of unique categories."""
    return sorted({q.category for q in GROUND_TRUTH})


# Quick validation
assert len(GROUND_TRUTH) >= 50, f"Expected 50+ queries, got {len(GROUND_TRUTH)}"
assert len(get_all_categories()) == 10, f"Expected 10 categories, got {len(get_all_categories())}"
