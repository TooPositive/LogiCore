"""Shared 12-document corpus for benchmarks and evaluation.

The canonical corpus for a Polish logistics company (LogiCore Sp. z o.o.).
Each entry: (doc_id, text, department, clearance_level).

These are the ground truth anchor documents — queries in ground_truth.py
reference these by doc_id. The texts are summary-length (~500-1000 chars)
for fast embedding in tests. Full production-length docs are in
data/benchmark-corpus/ (generated separately).
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
            "management requirements for warehouse operations at LogiCore "
            "Sp. z o.o. All incoming goods must be inspected within 4 hours "
            "of receipt per internal procedure PR-WH-007. Temperature-sensitive "
            "cargo requires continuous monitoring with SensoGuard TM-400 sensors. "
            "Non-conformities must be logged in the QMS system within 24 hours. "
            "Annual internal audit schedule maintained by Quality Manager. "
            "Corrective action requests (CAR) must be closed within 30 business days. "
            "Supplier quality assessments conducted quarterly for all Tier 1 suppliers."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-003",
        text=(
            "Driver Safety Protocol. Pre-trip inspection checklist for all "
            "LogiCore drivers. EU Regulation (EC) No 561/2006 applies to all "
            "company drivers operating vehicles over 3.5 tonnes. Maximum daily "
            "driving time: 9 hours (extendable to 10 hours twice per week). "
            "Continuous driving break: 45 minutes after 4.5 hours (may be split "
            "into 15 + 30 minutes). Weekly rest: minimum 45 consecutive hours. "
            "Tachograph must be calibrated annually per Ustawa o tachografach. "
            "All violations reported to fleet manager within 24 hours. "
            "Drivers must complete annual defensive driving refresher course. "
            "Blood alcohol limit: 0.0 per mille (zero tolerance policy)."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-SAFETY-002",
        text=(
            "Warehouse Fire Safety Plan (Plan Ochrony Przeciwpozarowej). "
            "Prepared in accordance with Ustawa o ochronie przeciwpozarowej "
            "and Rozporzadzenie MSWiA w sprawie ochrony przeciwpozarowej budynkow. "
            "Evacuation routes posted at every exit with illuminated signage. "
            "Fire extinguisher inspection every 6 months by certified technician. "
            "Sprinkler system covers 100% of storage area (Zones A through F). "
            "Emergency assembly point: parking lot B (north side of building). "
            "Fire drills conducted quarterly — all shifts. Maximum evacuation "
            "time target: 4 minutes. Fire alarm system: Bosch FPA-5000 with "
            "smoke and heat detectors in all zones. Annual inspection by "
            "Panstwowa Straz Pozarna (PSP) required."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-SAFETY-003",
        text=(
            "Forklift Operation Manual (Instrukcja Obslugi Wozka Widlowego). "
            "Only operators holding valid UDT (Urzad Dozoru Technicznego) "
            "certification may operate forklifts. Maximum load capacity: "
            "2,500 kg for standard Toyota 8FBE25 units. Pre-shift inspection "
            "required (checklist WH-FK-001). Speed limit in warehouse: 10 km/h "
            "in aisles, 5 km/h in pedestrian zones. Pedestrian zones clearly "
            "marked with yellow floor tape. Horn required at every intersection. "
            "Battery charging only in designated area (Zone G) with eye wash "
            "station and spill kit. Forklift maintenance log reviewed monthly "
            "by warehouse supervisor. Annual UDT technical inspection mandatory."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-002",
        text=(
            "Executive Compensation Policy CONFIDENTIAL. CEO salary: EUR "
            "280,000 per annum (gross). Performance bonus: up to 40% of base "
            "salary tied to EBITDA targets and customer NPS score. Stock options: "
            "50,000 shares vesting over 4 years (25% annually). Car allowance: "
            "EUR 1,500/month. Private health insurance (Medicover Platinum) for "
            "executive and immediate family. Pension contribution: 15% of base "
            "salary to PPE (Pracowniczy Program Emerytalny). Non-compete clause: "
            "12 months post-employment, compensated at 50% of base salary. "
            "Annual compensation review by Supervisory Board (Rada Nadzorcza) "
            "in Q1. Benchmarked against logistics sector C-suite in CEE region."
        ),
        department="hr",
        clearance_level=4,
    ),
    CorpusDocument(
        doc_id="DOC-HR-004",
        text=(
            "Employee Termination Procedures (Procedura Rozwiazywania Umow "
            "o Prace) HR CONFIDENTIAL. Performance-based termination: two "
            "consecutive quarterly reviews below 2.0/5.0 triggers Performance "
            "Improvement Plan (PIP) for 90 days. If PIP fails, termination "
            "with notice per Kodeks Pracy Art. 36: 2 weeks (< 6 months tenure), "
            "1 month (6 months to 3 years), 3 months (> 3 years). Consultation "
            "with trade union (Zwiazki Zawodowe) required per Art. 38 KP before "
            "termination of union member. Severance formula: 0.5 months salary "
            "per year of service (company policy, exceeds statutory minimum). "
            "Exit interview conducted by HR Business Partner. IT access revoked "
            "within 2 hours of termination effective time. Company property "
            "return checklist (laptop, phone, access cards, fuel card)."
        ),
        department="hr",
        clearance_level=3,
    ),
    CorpusDocument(
        doc_id="DOC-HR-005",
        text=(
            "Employee Onboarding Handbook (Podrecznik Wdrozenia Pracownika). "
            "New hire orientation: first 3 days structured program. Day 1: "
            "HR paperwork, IT equipment provisioning within 24 hours, building "
            "access card, parking assignment. Day 2: safety training (BHP "
            "szkolenie wstepne), warehouse tour, meet the team. Day 3: role-"
            "specific training with direct supervisor. Buddy system: assigned "
            "mentor for first 90 days. Probation period: 3 months per Kodeks "
            "Pracy Art. 25. Performance check-in at 30, 60, 90 days. Mandatory "
            "e-learning modules: RODO (data protection), anti-corruption, "
            "workplace harassment prevention. Employee handbook acknowledgment "
            "form must be signed by end of Day 1."
        ),
        department="hr",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-001",
        text=(
            "PharmaCorp Polska Service Agreement CTR-2024-001. Temperature-"
            "controlled pharmaceutical logistics between LogiCore Sp. z o.o. "
            "and PharmaCorp Polska Sp. z o.o. Routes: Warszawa-Krakow-Katowice-"
            "Wroclaw distribution network, 45 pharmacy chains. GDP (Good "
            "Distribution Practice) compliance required per Prawo Farmaceutyczne. "
            "SLA: on-time delivery >= 98.5%. Penalty: EUR 500 per late shipment. "
            "Temperature excursion outside 2-8 degrees Celsius: EUR 2,000 per "
            "incident plus full batch replacement cost. Temperature data logger "
            "required in every shipment. Annual value: EUR 1,200,000. Contract "
            "duration: 3 years with automatic 1-year renewal. Quarterly business "
            "review meetings mandatory."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-002",
        text=(
            "FreshFoods Logistics Agreement CTR-2024-002. Refrigerated "
            "transport of fresh produce between LogiCore Sp. z o.o. and "
            "FreshFoods S.A. 12 fixed routes across Mazowsze, Malopolska, "
            "and Slask voivodeships, serving 180 retail locations (Biedronka, "
            "Lidl, Zabka). Penalty: EUR 200 per late store delivery. "
            "Temperature range: 2-6 degrees Celsius for fresh produce, "
            "-18 degrees Celsius for frozen goods. HACCP compliance mandatory. "
            "Delivery windows: 05:00-07:00 for morning stores, 14:00-16:00 "
            "for afternoon replenishment. Annual value: EUR 650,000. "
            "Peak season surcharge (November-December): +15% on all routes. "
            "Returns handling included at no additional cost."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-003",
        text=(
            "AutoParts Express Contract CTR-2024-003. Non-perishable "
            "auto parts distribution for AutoParts Express Sp. z o.o. "
            "8 routes across Slask voivodeship serving 120 workshops and "
            "dealerships. No temperature requirements. Same-day delivery "
            "for orders placed before 10:00. Penalty: EUR 100 per late "
            "delivery. Annual value: EUR 320,000. Packaging: reusable "
            "plastic crates (deposit system, EUR 5 per crate). Dangerous "
            "goods excluded (batteries, oils shipped separately under ADR). "
            "Insurance: EUR 50,000 per shipment. Contract duration: 2 years."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-004",
        text=(
            "ChemTrans Hazmat Agreement CTR-2024-004. ADR-certified "
            "hazardous materials transport between LogiCore Sp. z o.o. "
            "and ChemTrans S.A. Requires UN-approved packaging per ADR "
            "Chapter 6. Driver must hold valid ADR certificate (zaswiadczenie "
            "ADR) per Ustawa o przewozie towarow niebezpiecznych. Routes: "
            "Plock refinery to chemical plants in Tarnow, Police, and Pulawy. "
            "DGSA (Dangerous Goods Safety Adviser) oversight required. "
            "Penalty: EUR 5,000 per compliance violation. Emergency response "
            "plan required per ADR 1.8.3.1. Annual value: EUR 2,100,000. "
            "Vehicles must carry ADR equipment kit (2 warning triangles, "
            "2 self-standing warning signs, eye wash, wheel chock)."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-005",
        text=(
            "LogiCore Master Service Agreement template (Ogolne Warunki "
            "Umowy). General terms and conditions for all logistics contracts "
            "entered into by LogiCore Sp. z o.o. Payment terms: NET 30 "
            "from invoice date. Late payment interest: statutory rate per "
            "Ustawa o przeciwdzialaniu nadmiernym opoznieniom w transakcjach "
            "handlowych. Liability cap: 2x annual contract value. Force "
            "majeure clause includes pandemics, natural disasters, government "
            "sanctions, and border closures. Governing law: Polish law. "
            "Dispute resolution: arbitration at Sad Arbitrazowy przy KIG "
            "(Krajowa Izba Gospodarcza) in Warszawa. RODO data processing "
            "addendum attached as Annex 3. Insurance: OC przewoznika "
            "(carrier liability) minimum EUR 500,000 per event."
        ),
        department="legal",
        clearance_level=2,
    ),
]
