"""Shared 12-document corpus for benchmarks and evaluation.

The canonical corpus matches the Phase 1 benchmark DOCS array.
Each entry: (doc_id, text, department, clearance_level).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CorpusDocument:
    """A document in the evaluation corpus."""

    doc_id: str
    text: str
    department: str
    clearance_level: int


CORPUS: list[CorpusDocument] = [
    CorpusDocument(
        doc_id="DOC-SAFETY-001",
        text=(
            "ISO 9001 Quality Management Manual. Section 4.2: Quality "
            "management requirements for warehouse operations. All "
            "incoming goods must be inspected within 4 hours of receipt. "
            "Temperature-sensitive cargo requires continuous monitoring."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-003",
        text=(
            "Driver Safety Protocol. Pre-trip inspection checklist. EU "
            "Regulation (EC) No 561/2006 applies to all LogiCore drivers. "
            "Maximum daily driving: 9 hours. Continuous driving break: "
            "45 minutes after 4.5 hours."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-SAFETY-002",
        text=(
            "Warehouse Fire Safety Plan. Evacuation routes posted at "
            "every exit. Fire extinguisher inspection every 6 months. "
            "Sprinkler system covers 100% of storage area. Emergency "
            "assembly point: parking lot B."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-SAFETY-003",
        text=(
            "Forklift Operation Manual. Only certified operators may use "
            "forklifts. Maximum load capacity: 2,500 kg. Pre-shift "
            "inspection required. Speed limit in warehouse: 10 km/h. "
            "Pedestrian zones clearly marked."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-002",
        text=(
            "Executive Compensation Policy CONFIDENTIAL. CEO salary EUR "
            "280,000 per annum. Performance bonus up to 40% of base "
            "salary. Stock options 50,000 shares vesting over 4 years."
        ),
        department="hr",
        clearance_level=4,
    ),
    CorpusDocument(
        doc_id="DOC-HR-004",
        text=(
            "Employee Termination Procedures HR CONFIDENTIAL. "
            "Performance-based termination: two consecutive quarterly "
            "reviews below 2.0/5.0. Notice periods per German labor law. "
            "Severance formula: 0.5 months salary per year of service."
        ),
        department="hr",
        clearance_level=3,
    ),
    CorpusDocument(
        doc_id="DOC-HR-005",
        text=(
            "Employee Onboarding Handbook. New hire orientation: first "
            "3 days. IT equipment provisioning within 24 hours. Buddy "
            "system: assigned mentor for first 90 days. Probation "
            "period: 6 months."
        ),
        department="hr",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-001",
        text=(
            "PharmaCorp Service Agreement CTR-2024-001. Temperature-"
            "controlled pharmaceutical logistics. SLA: on-time delivery "
            ">= 98.5%. Penalty: EUR 500 per late shipment. Temperature "
            "excursion: EUR 2,000 per incident. Annual value: "
            "EUR 1,200,000."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-002",
        text=(
            "FreshFoods Logistics Agreement CTR-2024-002. Refrigerated "
            "transport of fresh produce. 12 fixed routes, 180 retail "
            "locations. Penalty: EUR 200 per late store delivery. "
            "Temperature range: 2-6 degrees fresh, -18 degrees frozen. "
            "Annual value: EUR 650,000."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-003",
        text=(
            "AutoParts Express Contract CTR-2024-003. Non-perishable "
            "auto parts distribution. 8 routes across Bavaria. No "
            "temperature requirements. Penalty: EUR 100 per late "
            "delivery. Annual value: EUR 320,000."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-004",
        text=(
            "ChemTrans Hazmat Agreement CTR-2024-004. ADR-certified "
            "hazardous materials transport. Requires UN-approved "
            "packaging. Driver must hold ADR certificate. Penalty: "
            "EUR 5,000 per compliance violation. Annual value: "
            "EUR 2,100,000."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-005",
        text=(
            "LogiCore Master Service Agreement template. General terms "
            "and conditions for all logistics contracts. Payment terms: "
            "NET 30. Liability cap: 2x annual contract value. Force "
            "majeure clause includes pandemics and natural disasters."
        ),
        department="legal",
        clearance_level=2,
    ),
]
