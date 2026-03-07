"""Compare chunking strategies on the LogiCore corpus.

Measures: chunk count, avg chunk size, size variance, clause integrity
(does a full clause stay in one chunk?).

Two corpus modes:
  --expanded   Use expanded (realistic-length) documents built from inline
               corpus. Each doc is padded with realistic filler to ~2000 chars
               so chunking strategies actually differentiate. DEFAULT.
  --inline     Use the inline 12-doc corpus as-is (~200-300 chars per doc).
               Too short for meaningful chunking comparison — included only
               as a baseline sanity check.
  --live       Use real Azure OpenAI embeddings for semantic chunker instead
               of hash-based mock. Requires AZURE_OPENAI_* env vars.

Usage:
    python scripts/benchmark_chunking.py                  # expanded + mock
    python scripts/benchmark_chunking.py --live            # expanded + real embeddings
    python scripts/benchmark_chunking.py --inline          # short docs (baseline)

No external services required (unless --live).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.rag.chunking import (
    FixedSizeChunker,
    ParentChildChunker,
    SemanticChunker,
)
from apps.api.src.rag.embeddings import MockEmbedder
from tests.evaluation.corpus import CORPUS, CorpusDocument


# ---------------------------------------------------------------------------
# Expanded corpus: realistic-length documents (~2000-3000 chars each)
# ---------------------------------------------------------------------------

EXPANDED_CORPUS: list[CorpusDocument] = [
    CorpusDocument(
        doc_id="DOC-LEGAL-001",
        text=(
            "SERVICE AGREEMENT CTR-2024-001\n"
            "Between: PharmaCorp AG (Client) and LogiCore Transport GmbH (Provider)\n"
            "Effective: 2024-03-01 — 2026-02-28\n\n"
            "1. Scope of Services\n"
            "LogiCore Transport GmbH shall provide temperature-controlled "
            "pharmaceutical logistics services for PharmaCorp AG, including "
            "collection from manufacturing facilities, warehousing at certified "
            "GDP-compliant facilities, and last-mile delivery to pharmacies and "
            "hospitals across Germany, Austria, and Switzerland.\n\n"
            "2. Service Level Agreement\n"
            "SLA: on-time delivery >= 98.5%. On-time is defined as delivery "
            "within the agreed 4-hour window. Measurement period: calendar month. "
            "Reports delivered by the 5th business day of the following month.\n\n"
            "3. Penalty Clauses\n"
            "3.1 Penalty: EUR 500 per late shipment. Late is defined as arrival "
            "more than 30 minutes after the agreed delivery window.\n"
            "3.2 Temperature excursion: EUR 2,000 per incident. An excursion is "
            "any reading outside 2-8°C for more than 15 consecutive minutes.\n"
            "3.3 Documentation failure: EUR 200 per missing or incomplete delivery "
            "record.\n"
            "3.4 Maximum annual penalty cap: EUR 500,000.\n\n"
            "4. Financial Terms\n"
            "Annual value: EUR 1,200,000. Payment terms: NET 30 from invoice date. "
            "Late payment interest: 3% above ECB base rate. Annual price review "
            "in Q4, linked to transport cost index.\n\n"
            "5. Compliance Requirements\n"
            "All vehicles must maintain GDP certification. Drivers must complete "
            "annual cold-chain handling training. Temperature loggers calibrated "
            "quarterly. Deviation reports within 24 hours of incident.\n\n"
            "6. Termination\n"
            "Either party may terminate with 6 months written notice. Immediate "
            "termination for material breach (defined as 3+ SLA failures in "
            "any rolling 3-month period)."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-LEGAL-004",
        text=(
            "HAZARDOUS MATERIALS TRANSPORT AGREEMENT CTR-2024-004\n"
            "Between: ChemTrans GmbH (Client) and LogiCore Transport GmbH (Provider)\n"
            "Effective: 2024-01-15 — 2025-12-31\n\n"
            "1. Scope of Services\n"
            "LogiCore Transport GmbH shall provide ADR-certified hazardous "
            "materials transport services for ChemTrans GmbH. Cargo classes: "
            "UN Class 3 (flammable liquids), Class 6.1 (toxic substances), "
            "and Class 8 (corrosives). Routes: Ludwigshafen to 14 chemical "
            "processing plants across Bavaria, Baden-Württemberg, and Hessen.\n\n"
            "2. Safety and Compliance\n"
            "All shipments require UN-approved packaging verified by shipper. "
            "Every driver must hold a valid ADR certificate (renewed every 5 years). "
            "Vehicles equipped with ADR-compliant placarding, fire extinguishers, "
            "spill containment kits, and emergency shower equipment.\n\n"
            "3. Penalty Clauses\n"
            "Penalty: EUR 5,000 per compliance violation. A violation includes: "
            "expired ADR certificate, missing or incorrect placarding, unsealed "
            "containment, or failure to report spill within 1 hour.\n"
            "3.2 Regulatory fine passthrough: LogiCore bears 100% of fines "
            "imposed by Gefahrgutbeauftragter (dangerous goods safety advisor) "
            "inspection.\n"
            "3.3 Insurance premium surcharge: 15% increase for any quarter with "
            "2+ compliance incidents.\n\n"
            "4. Financial Terms\n"
            "Annual value: EUR 2,100,000. Payment terms: NET 15 (accelerated "
            "due to hazmat insurance requirements). Fuel surcharge adjusted "
            "monthly per ADAC diesel index.\n\n"
            "5. Emergency Procedures\n"
            "24/7 emergency hotline staffed by ADR-certified coordinator. "
            "Spill response within 30 minutes for routes within 50km of depot. "
            "Joint emergency drill with client quarterly.\n\n"
            "6. Termination\n"
            "90 days written notice. Immediate termination for any incident "
            "resulting in environmental contamination or regulatory shutdown."
        ),
        department="legal",
        clearance_level=2,
    ),
    CorpusDocument(
        doc_id="DOC-HR-003",
        text=(
            "DRIVER SAFETY PROTOCOL\n"
            "LogiCore Transport GmbH — Operations Department\n"
            "Version 4.1 — Effective 2024-06-01\n\n"
            "1. Pre-Trip Inspection\n"
            "Every driver must complete the 15-point pre-trip inspection "
            "checklist before departing. This includes tire pressure (minimum "
            "7.5 bar for trailer axles), brake check (visual + functional), "
            "lights (all 14 light positions), mirrors (adjustment and cleanliness), "
            "load securing (tension straps minimum 2,500 daN), and refrigeration "
            "unit verification for temperature-controlled shipments.\n\n"
            "2. Driving Hours Compliance\n"
            "EU Regulation (EC) No 561/2006 applies to all LogiCore drivers. "
            "Maximum daily driving: 9 hours. Can be extended to 10 hours twice "
            "per week. Continuous driving break: 45 minutes after 4.5 hours "
            "(may be split into 15+30 minutes). Maximum weekly driving: 56 hours. "
            "Maximum fortnightly driving: 90 hours. Digital tachograph must be "
            "used at all times — analogue charts are not accepted.\n\n"
            "3. Speed Limits\n"
            "Motorway: 80 km/h (trucks >3.5t). Urban areas: 30 km/h within "
            "warehouse and depot zones. Loading bays: 5 km/h maximum. "
            "Violation of speed limits results in written warning (first offense) "
            "or suspension pending review (second offense within 12 months).\n\n"
            "4. Incident Reporting\n"
            "All incidents (collision, near-miss, mechanical failure) must be "
            "reported within 2 hours using the LogiCore Incident App. Photos "
            "required for any vehicle damage. Police report mandatory for "
            "collisions involving third parties.\n\n"
            "5. Fatigue Management\n"
            "Drivers must self-assess fatigue using the Stanford Sleepiness "
            "Scale before each shift. Score >= 5 requires supervisor review "
            "before departure. Night shift drivers (22:00-06:00) limited to "
            "8 hours maximum.\n\n"
            "6. Training Requirements\n"
            "Annual defensive driving refresher (8 hours). Cold-chain handling "
            "certification (for temperature-controlled routes). ADR certificate "
            "renewal every 5 years (for hazmat routes)."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-004",
        text=(
            "EMPLOYEE TERMINATION PROCEDURES — HR CONFIDENTIAL\n"
            "LogiCore Transport GmbH — HR Department\n"
            "Version 2.3 — Last Updated 2024-09-15\n\n"
            "1. Grounds for Termination\n"
            "1.1 Performance-based: Two consecutive quarterly reviews below "
            "2.0/5.0 after documented improvement plan (minimum 90 days). "
            "The improvement plan must include specific, measurable targets "
            "agreed by employee and manager.\n"
            "1.2 Conduct-based: Gross misconduct (theft, violence, intoxication "
            "on duty) permits immediate termination. Standard misconduct "
            "(repeated lateness, policy violations) requires progressive "
            "discipline: verbal warning → written warning → final warning → "
            "termination.\n"
            "1.3 Redundancy: Role elimination due to restructuring. Selection "
            "criteria per social selection (Sozialauswahl) under German labor law.\n\n"
            "2. Notice Periods\n"
            "Per German labor law (§622 BGB): 4 weeks during probation, "
            "1 month after 2 years, 2 months after 5 years, 3 months after "
            "8 years, 7 months after 20 years. Works Council (Betriebsrat) "
            "must be consulted before any termination — BetrVG Section 102.\n\n"
            "3. Severance Calculations\n"
            "Severance formula: 0.5 months salary per year of service. Calculated "
            "on gross monthly salary including regular bonuses. Pro-rated for "
            "partial years (>6 months = full year). Minimum severance: EUR 5,000 "
            "(for employees with 2+ years). Maximum severance: 18 months salary "
            "(capped by social plan agreement with Works Council).\n\n"
            "4. Exit Process\n"
            "IT access revoked within 4 hours of notification. Company vehicle "
            "returned within 5 business days. Final paycheck including accrued "
            "vacation within 30 days. Exit interview conducted by HR (optional "
            "for employee, mandatory for HR to offer). Reference letter "
            "(Arbeitszeugnis) issued within 14 days of last working day.\n\n"
            "5. Documentation Requirements\n"
            "All termination decisions must be documented in HR system with: "
            "grounds, supporting evidence, consultation records, employee "
            "acknowledgment. Records retained for 10 years per German data "
            "retention requirements."
        ),
        department="hr",
        clearance_level=3,
    ),
    CorpusDocument(
        doc_id="DOC-SAFETY-002",
        text=(
            "WAREHOUSE FIRE SAFETY PLAN\n"
            "LogiCore Transport GmbH — Warehouse Schwechat\n"
            "Version 3.0 — Approved by Feuerwehr Schwechat 2024-04-20\n\n"
            "1. Fire Detection Systems\n"
            "Aspirating smoke detection (VESDA) in all storage halls. Point-type "
            "heat detectors in loading bays (where smoke detection is unreliable "
            "due to exhaust fumes). Manual call points at every exit and at "
            "25-meter intervals along main corridors. Central fire alarm panel "
            "in security office, monitored 24/7.\n\n"
            "2. Fire Suppression\n"
            "Sprinkler system covers 100% of storage area. Wet-pipe sprinklers "
            "in ambient zones, pre-action dry-pipe in cold storage (to prevent "
            "freezing). Fire extinguisher inspection every 6 months. Types: "
            "CO2 for electrical rooms, foam for liquid storage, powder for "
            "general areas. Hydrant connections at 4 locations for fire brigade.\n\n"
            "3. Evacuation Procedures\n"
            "Evacuation routes posted at every exit and at each workstation. "
            "Maximum evacuation time target: 4 minutes to assembly point. "
            "Emergency assembly point: parking lot B (north side, away from "
            "loading bays). Roll call by shift supervisor using digital roster. "
            "Disabled evacuation: designated evacuation chairs at each stairwell.\n\n"
            "4. Fire Warden Organization\n"
            "Minimum 2 trained fire wardens per shift. Fire warden training: "
            "4-hour course annually, covering extinguisher use, evacuation "
            "leadership, and first aid basics. Fire drill: minimum 2 per year, "
            "at least 1 unannounced. Results documented and shared with local "
            "fire brigade.\n\n"
            "5. Hazardous Materials Storage\n"
            "Separate fire compartment for flammable goods (F+). Maximum 500 kg "
            "per compartment. MSDS sheets posted at compartment entrance. "
            "Spill containment: bunded floor with 110% capacity. No ignition "
            "sources within 10 meters (ATEX zone 2 classification).\n\n"
            "6. Emergency Contacts\n"
            "Fire brigade: 122. Internal emergency: ext. 9999. Facility manager "
            "on-call: +43 (0) 664 XXX XXXX. Insurance hotline: documented in "
            "emergency folder at reception."
        ),
        department="warehouse",
        clearance_level=1,
    ),
    CorpusDocument(
        doc_id="DOC-HR-005",
        text=(
            "EMPLOYEE ONBOARDING HANDBOOK\n"
            "LogiCore Transport GmbH — HR Department\n"
            "Version 5.1 — Updated 2024-08-01\n\n"
            "1. First Week Schedule\n"
            "New hire orientation: first 3 days. Day 1: HR paperwork, IT setup, "
            "office tour, team introduction. Day 2: Company history, values, "
            "organizational structure, safety briefing. Day 3: Role-specific "
            "training, system access, first task assignment.\n\n"
            "2. IT Equipment\n"
            "IT equipment provisioning within 24 hours of start date. Standard "
            "kit: laptop (Dell Latitude 5540), 2 monitors, headset, VPN token. "
            "Software: Microsoft 365, SAP access, LogiCore internal apps. "
            "Admin access requires manager approval + IT security review.\n\n"
            "3. Buddy System\n"
            "Buddy system: assigned mentor for first 90 days. Buddy must be "
            "from the same department, minimum 1 year tenure. Weekly 30-minute "
            "check-ins for first month, then bi-weekly. Buddy receives 2 hours "
            "per week allocated time for mentoring activities.\n\n"
            "4. Probation Period\n"
            "Probation period: 6 months. Performance review at 3 months "
            "(mid-probation) and 6 months (end-probation). Probation extension "
            "possible for up to 3 additional months with documented justification. "
            "During probation: 2-week notice period (both directions), per §622 BGB.\n\n"
            "5. Training Plan\n"
            "Mandatory training within first 30 days: data protection (GDPR), "
            "workplace safety (§12 ArbSchG), anti-corruption compliance, "
            "information security awareness. Role-specific certifications "
            "must be completed within 90 days.\n\n"
            "6. Documentation\n"
            "All onboarding steps tracked in HR system. Manager signs off "
            "completion of each phase. New hire feedback survey at 30 and "
            "90 days. Results shared with HR for process improvement."
        ),
        department="hr",
        clearance_level=1,
    ),
]


# ---------------------------------------------------------------------------
# Clause integrity check
# ---------------------------------------------------------------------------


# Key clauses that should stay intact in chunks
KEY_CLAUSES = [
    "Penalty: EUR 500 per late shipment",
    "Maximum daily driving: 9 hours",
    "Severance formula: 0.5 months salary per year of service",
    "SLA: on-time delivery >= 98.5%",
    "Penalty: EUR 5,000 per compliance violation",
    "Annual value: EUR 2,100,000",
    "Probation period: 6 months",
    "Fire extinguisher inspection every 6 months",
]


def check_clause_integrity(
    chunks: list[str],
    clauses: list[str],
    corpus: list[CorpusDocument],
) -> dict:
    """Check what fraction of key clauses stay within a single chunk.

    Checks clause existence against the actual corpus being chunked,
    not a hardcoded reference.
    """
    total = 0
    intact = 0
    details: list[dict] = []

    for clause in clauses:
        # Check if this clause exists in the corpus being chunked
        found_in_corpus = False
        for doc in corpus:
            if clause in doc.text:
                found_in_corpus = True
                break
        if not found_in_corpus:
            continue

        total += 1
        # Check if any single chunk contains the entire clause
        found_in_chunk = False
        for chunk in chunks:
            if clause in chunk:
                found_in_chunk = True
                intact += 1
                break

        details.append({
            "clause": clause,
            "intact": found_in_chunk,
        })

    return {
        "total_clauses": total,
        "intact_clauses": intact,
        "integrity_rate": intact / total if total > 0 else 0.0,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Run benchmarks
# ---------------------------------------------------------------------------


def benchmark_strategy(
    strategy_name: str,
    chunker,
    corpus: list[CorpusDocument],
) -> dict:
    """Run a single chunking strategy and collect metrics."""
    all_chunks: list[str] = []
    chunk_counts: list[int] = []
    chunk_sizes: list[int] = []

    for doc in corpus:
        results = chunker.chunk(doc.text)
        chunks = [r.content for r in results]
        all_chunks.extend(chunks)
        chunk_counts.append(len(chunks))
        chunk_sizes.extend(len(c) for c in chunks)

    integrity = check_clause_integrity(all_chunks, KEY_CLAUSES, corpus)

    return {
        "strategy": strategy_name,
        "total_chunks": len(all_chunks),
        "avg_chunks_per_doc": statistics.mean(chunk_counts) if chunk_counts else 0,
        "avg_chunk_size": statistics.mean(chunk_sizes) if chunk_sizes else 0,
        "min_chunk_size": min(chunk_sizes) if chunk_sizes else 0,
        "max_chunk_size": max(chunk_sizes) if chunk_sizes else 0,
        "size_stddev": statistics.stdev(chunk_sizes) if len(chunk_sizes) > 1 else 0,
        "clause_integrity": integrity["integrity_rate"],
        "clauses_intact": f"{integrity['intact_clauses']}/{integrity['total_clauses']}",
        "clause_details": integrity["details"],
    }


def main():
    parser = argparse.ArgumentParser(description="Compare chunking strategies")
    parser.add_argument(
        "--inline", action="store_true",
        help="Use short inline corpus (~200 chars/doc) — baseline only",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Use real Azure OpenAI embeddings for semantic chunker",
    )
    parser.add_argument(
        "--output-json", type=Path, default=None,
        help="Save results to JSON file",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("CHUNKING STRATEGY COMPARISON")
    print("=" * 78)

    if args.inline:
        corpus = CORPUS
        corpus_label = "inline (short docs, ~200-300 chars — baseline only)"
    else:
        corpus = EXPANDED_CORPUS
        corpus_label = "expanded (realistic-length, ~2000-3000 chars)"

    print(f"  Corpus: {corpus_label}")
    print(f"  Documents: {len(corpus)}")
    total_chars = sum(len(d.text) for d in corpus)
    avg_chars = total_chars // len(corpus)
    print(f"  Total chars: {total_chars:,} (avg {avg_chars:,}/doc)")
    print()

    # Embedding function for semantic chunker
    if args.live:
        import asyncio
        from apps.api.src.rag.embeddings import get_embeddings
        embeddings = get_embeddings()

        def sync_embed(texts: list[str]) -> list[list[float]]:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                embeddings.aembed_documents(texts)
            )
            loop.close()
            return result

        embed_label = "live (Azure OpenAI text-embedding-3-small)"
    else:
        embedder = MockEmbedder(dimensions=128)

        def sync_embed(texts: list[str]) -> list[list[float]]:
            return [embedder._hash_to_vector(t) for t in texts]

        embed_label = "mock (SHA-256 hash — no semantic understanding)"

    print(f"  Semantic embeddings: {embed_label}")
    print()

    # Configure strategies — include small chunk sizes to find breaking point
    strategies = [
        ("Fixed-size (512, ov=50)", FixedSizeChunker(chunk_size=512, overlap=50)),
        ("Fixed-size (256, ov=25)", FixedSizeChunker(chunk_size=256, overlap=25)),
        ("Fixed-size (128, ov=15)", FixedSizeChunker(chunk_size=128, overlap=15)),
        ("Fixed-size (80, ov=10)", FixedSizeChunker(chunk_size=80, overlap=10)),
        (
            "Semantic (t=0.5, min=50)",
            SemanticChunker(
                similarity_threshold=0.5,
                min_chunk_size=50,
                max_chunk_size=2000,
                embed_fn=sync_embed,
            ),
        ),
        (
            "Semantic (t=0.3, min=50)",
            SemanticChunker(
                similarity_threshold=0.3,
                min_chunk_size=50,
                max_chunk_size=2000,
                embed_fn=sync_embed,
            ),
        ),
        ("Parent-Child (default)", ParentChildChunker()),
        (
            "Parent-Child (min=30)",
            ParentChildChunker(min_child_size=30),
        ),
    ]

    results = []
    for name, chunker in strategies:
        result = benchmark_strategy(name, chunker, corpus)
        results.append(result)

    # Print table
    headers = [
        "Strategy", "Chunks", "Avg/Doc",
        "Avg Size", "Min", "Max", "StdDev", "Clause",
    ]
    widths = [30, 8, 8, 10, 6, 6, 8, 12]

    header_line = ""
    for h, w in zip(headers, widths):
        header_line += f"  {h:<{w}}"
    print(header_line)
    print("  " + "-" * (sum(widths) + len(widths) * 2))

    for r in results:
        line = (
            f"  {r['strategy']:<30}"
            f"  {r['total_chunks']:<8}"
            f"  {r['avg_chunks_per_doc']:<8.1f}"
            f"  {r['avg_chunk_size']:<10.0f}"
            f"  {r['min_chunk_size']:<6}"
            f"  {r['max_chunk_size']:<6}"
            f"  {r['size_stddev']:<8.0f}"
            f"  {r['clauses_intact']:<12}"
        )
        print(line)

    # Clause detail breakdown — show best AND worst if they differ
    print()
    print("  CLAUSE INTEGRITY DETAILS:")
    print("  " + "-" * 70)
    best = max(results, key=lambda r: r["clause_integrity"])
    worst = min(results, key=lambda r: r["clause_integrity"])

    if best["clause_integrity"] != worst["clause_integrity"]:
        print(f"  Best ({best['strategy']}):")
        for detail in best.get("clause_details", []):
            status = "INTACT" if detail["intact"] else "SPLIT"
            clause_short = detail["clause"][:55]
            print(f"    [{status:>5}] {clause_short}")
        print()
        print(f"  Worst ({worst['strategy']}):")
        for detail in worst.get("clause_details", []):
            status = "INTACT" if detail["intact"] else "SPLIT"
            clause_short = detail["clause"][:55]
            print(f"    [{status:>5}] {clause_short}")
    else:
        print(f"  ({best['strategy']}):")
        for detail in best.get("clause_details", []):
            status = "INTACT" if detail["intact"] else "SPLIT"
            clause_short = detail["clause"][:55]
            print(f"    [{status:>5}] {clause_short}")

    # Architect verdict
    print()
    print("  ARCHITECT ANALYSIS:")
    print("  " + "-" * 60)

    best_integrity = max(results, key=lambda r: r["clause_integrity"])
    worst_integrity = min(results, key=lambda r: r["clause_integrity"])

    print(f"  Best clause integrity:  {best_integrity['strategy']}")
    print(f"    -> {best_integrity['clauses_intact']} key clauses preserved")
    print(f"  Worst clause integrity: {worst_integrity['strategy']}")
    print(f"    -> {worst_integrity['clauses_intact']} key clauses preserved")

    delta = best_integrity["clause_integrity"] - worst_integrity["clause_integrity"]
    if delta > 0:
        pct = delta * 100
        print()
        print(
            f"  DECISION: {best_integrity['strategy']} preserves "
            f"{pct:.0f}% more key clauses than {worst_integrity['strategy']}."
        )
        print(
            "  A split clause means the LLM gets partial context — "
            "'Penalty: EUR' in one chunk, '500 per late shipment' in another."
        )
        print(
            "  The user's question about penalties gets a wrong or incomplete "
            "answer."
        )
    else:
        print()
        print("  NOTE: All strategies show identical clause integrity.")
        if args.inline:
            print(
                "  This is expected — inline docs are ~200-300 chars, "
                "shorter than any chunk size."
            )
            print("  Run without --inline (expanded corpus) for meaningful comparison.")
        elif not args.live:
            print(
                "  Mock embeddings (hash-based) don't provide semantic "
                "understanding."
            )
            print("  Run with --live for real semantic chunking comparison.")

    print()
    print("  RECOMMENDATION: Use the strategy with highest clause integrity")
    print("  for contract/legal documents. Switch to smaller fixed-size chunks")
    print("  only when documents are >10 pages and retrieval latency matters.")
    print("=" * 78)

    if args.output_json:
        # Remove non-serializable details for JSON output
        for r in results:
            r.pop("clause_details", None)
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Results saved to {args.output_json}")


if __name__ == "__main__":
    main()
