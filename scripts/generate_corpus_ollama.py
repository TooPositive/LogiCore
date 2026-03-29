"""Generate production-quality diverse corpus via Ollama (qwen3:32b).

Creates realistic logistics company documents for the re-ranking benchmark.
Each batch generates 5-7 unique documents via a single Ollama call.

Usage:
    python scripts/generate_corpus_ollama.py
    python scripts/generate_corpus_ollama.py --model qwen3:32b --validate

Output: data/benchmark-corpus/diverse_docs.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "benchmark-corpus" / "diverse_docs.json"

# Each batch: (category, count, specific_instructions)
BATCHES = [
    (
        "safety_manual",
        7,
        """Generate 7 safety manual documents for a German logistics company (EuroLogistics GmbH).
Each must be COMPLETELY different — different topic, different writing style, different structure.

Topics (one document per topic):
1. HAZMAT chemical spill response procedure for warehouse — include specific chemicals (sulfuric acid, acetone), containment steps, PPE levels, notification chain. Reference ADR regulations. 800-1200 chars.
2. Warehouse racking inspection policy — inspection frequency, load limits per shelf (kg), damage classification (Green/Amber/Red), who can authorize continued use. 500-900 chars.
3. Cold storage safety — hypothermia risk assessment, maximum exposure times by temperature zone (-18C, -25C, -30C), buddy system rules, emergency warming procedures. 700-1100 chars.
4. Loading dock operations manual — vehicle approach speed, wheel chocking procedure, dock leveler operation, trailer inspection before loading, signal person hand signals. 600-1000 chars.
5. PPE requirements matrix by warehouse zone — general warehouse, cold storage, chemical storage, battery charging area. Include specific PPE items (steel-toe boots, hi-vis class, gloves type). 500-800 chars.
6. Night shift safety protocols — minimum staffing levels, lone worker check-in procedure (every 30 min), emergency lighting test schedule, restricted areas after 22:00. 500-900 chars.
7. Summer heat stress prevention — temperature action triggers (28C/32C/35C), hydration stations, modified break schedule, heat illness symptoms to watch for. Reference Arbeitsstättenverordnung. 500-800 chars.

IMPORTANT: Write each as a real document a safety manager would create. Use section numbers, bold headers (indicated by CAPS), specific measurements, and reference real regulations where appropriate. Each should feel like it was written by a different person at a different time.""",
    ),
    (
        "hr_policy",
        7,
        """Generate 7 HR policy documents for EuroLogistics GmbH (German logistics company).
Each completely different in topic, tone, and format.

Topics:
1. Annual leave policy — entitlement by tenure (24/26/28/30 days), request procedure, blackout periods (peak season Nov-Dec), carry-over rules (max 5 days to Q1), reference Bundesurlaubsgesetz. 700-1000 chars.
2. Overtime and working time policy — Arbeitszeitgesetz limits (8h/day, 10h max), overtime approval process, comp time vs payout options, Sunday/holiday premium rates (50%/100%), driver-specific rules. 600-1000 chars.
3. Workplace harassment and discrimination policy (Allgemeines Gleichbehandlungsgesetz / AGG) — reporting channels, investigation timeline (5 business days), confidentiality, consequences, external ombudsperson contact. 700-1100 chars.
4. Performance review process — quarterly check-ins, annual formal review, 5-point rating scale with descriptions, PIP (Performance Improvement Plan) trigger and duration, link to compensation adjustments. 600-900 chars.
5. Employee data privacy notice (DSGVO/GDPR) — what personal data is processed, legal basis, retention periods, employee rights (access, deletion, portability), DPO contact. 600-1000 chars.
6. Works council (Betriebsrat) consultation procedures — when consultation is mandatory (hiring, termination, schedule changes per BetrVG §99/§102), timeline requirements, escalation to Einigungsstelle. 500-900 chars.
7. Company vehicle and fuel card policy — eligibility, private use rules, driver obligation (report damage within 24h, maintain service schedule), fuel card limits (EUR 400/month), accident procedure. 500-800 chars.

Write as real HR documents. Some should be formal policy language, others more accessible employee-facing. Include effective dates, version numbers, or "Last updated" dates where natural.""",
    ),
    (
        "technical_spec",
        6,
        """Generate 6 technical specification/IT documents for EuroLogistics GmbH.
Each about a different system, with realistic technical detail.

Topics:
1. Temperature monitoring system specification — Sensor model (SensoGuard TM-400), accuracy ±0.3°C, alarm thresholds by zone (pharma: 2-8°C, frozen: -20±2°C, ambient: 15-25°C), data logging interval (5 min), battery life, calibration schedule (every 6 months), MQTT integration with WMS. 800-1200 chars.
2. Fleet GPS tracking system — Device: TeltonikFMC130, update interval (30s moving/5min stationary), geofencing rules (customer sites, rest areas, borders), data retention (2 years per GDPR), driver privacy mode (personal use button), integration API endpoint. 600-1000 chars.
3. WMS barcode scanning workflow — Scanner model (Zebra TC52), supported formats (GS1-128, EAN-13, QR), scan-to-verify receiving process, pick confirmation workflow, error handling (unknown barcode → manual entry + supervisor alert), label printer integration. 600-900 chars.
4. Warehouse network infrastructure — WiFi coverage (802.11ax, 99.8% coverage target), VLAN segmentation (OT-VLAN-10 for scanners, IT-VLAN-20 for office, IoT-VLAN-30 for sensors), redundant uplinks, failover procedure, vendor support contract. 500-800 chars.
5. Transport order lifecycle — SAP SD → WMS pick order → driver app assignment → loading confirmation → departure scan → GPS tracking → delivery POD → SAP billing. Include message types (IDoc DESADV, RFC calls), retry logic, error states. 700-1100 chars.
6. Disaster recovery and backup plan — RPO/RTO targets (WMS: 1h/4h, ERP: 4h/8h, email: 24h/48h), backup schedule, offsite replication (Azure Germany West Central), annual DR test procedure, escalation contacts. 600-900 chars.

Write as technical documents an IT architect would create. Include version numbers, system names, specific config values. Not marketing — real engineering docs.""",
    ),
    (
        "incident_report",
        5,
        """Generate 5 incident reports for EuroLogistics GmbH. Each must feel like a real investigation report filled out after an actual event.

Required format for each: Date/Time, Location, Personnel involved (use realistic German names), Description, Root cause, Immediate actions taken, Corrective actions (with deadlines and responsible person).

Topics:
1. Forklift near-miss in Warehouse A — forklift (Unit FK-012) rounded blind corner at excessive speed, narrowly missed pedestrian (warehouse worker). No injury. Root cause: mirror at intersection removed during renovation, not reinstalled. Severity: Near-miss (Level 2). Date: 2025-08-14. 700-1000 chars.
2. Temperature excursion in cold storage unit 3 — compressor failure caused temperature rise from -18°C to -8°C over 6 hours overnight. Product affected: 3 pallets FreshFoods yogurt (240 cases). Loss: EUR 12,400. Root cause: compressor bearing failure, last maintenance overdue by 2 weeks. Date: 2025-09-22. 700-1100 chars.
3. Driver fatigue incident on A8 motorway — driver (11h on duty, 8.5h driving) drifted onto hard shoulder near km 147.3. Dashcam triggered lane departure alert. No collision. Root cause: dispatcher assigned run exceeding planned schedule due to late loading. Date: 2025-07-03. 600-900 chars.
4. Slip and fall in loading bay 6 — worker slipped on wet surface during heavy rain, fell from dock edge (height ~1.2m). Injury: sprained ankle. Lost time: 3 working days. Root cause: drainage channel blocked by shrink wrap debris. Rain mat not deployed. Date: 2025-10-11. 600-900 chars.
5. Minor chemical leak during unloading — 20L drum of industrial degreaser developed crack during unloading from trailer. Approx 2L leaked onto dock floor. Contained with spill kit within 8 minutes. No environmental release. Root cause: drum stacked 3-high without edge protection, shifted during transport. Date: 2025-06-28. 600-1000 chars.

Make each report feel authentic — written by different people (safety officer, shift supervisor, fleet manager). Include incident reference numbers (e.g., INC-2025-031).""",
    ),
    (
        "meeting_minutes",
        6,
        """Generate 6 sets of meeting minutes for EuroLogistics GmbH. Different meeting types, attendees, and tones.

Topics:
1. Monthly safety committee meeting (Oct 2025) — Attendees: 6-8 people including safety officer, Betriebsrat rep, dept heads. Agenda: review of September incidents (2 near-misses, 1 LTI), external audit prep for ISO 45001, winter safety campaign launch, PPE budget Q4. Include action items with owners and deadlines. 800-1200 chars.
2. Q3 2025 operations review — Attendees: COO, logistics heads, fleet manager. KPIs presented: on-time delivery 96.2% (target 98%), fleet utilization 84%, fuel cost EUR 0.38/km (+5% YoY), customer complaints down 12%. Action items: investigate 3 SLA breaches with FreshFoods, approve 2 new routes for ChemTrans expansion. 700-1100 chars.
3. Board meeting excerpt — fleet electrification investment — EUR 2.4M CapEx for 12 electric trucks (MAN eTGM), EU subsidy application (up to 40%), TCO analysis vs diesel (break-even at year 5), charging infrastructure at 3 depots, timeline: first deliveries Q2 2026. Board approved 8-2 with conditions. 700-1000 chars.
4. Weekly logistics huddle (Monday 2025-11-03) — 15-minute standup format. Topics: driver availability this week (3 on leave, 1 sick), peak season volume forecast (+35% vs normal), temporary staff onboarding (4 agency drivers starting Wednesday), route R-017 closure due to bridge works (detour adds 45min). Informal tone. 500-800 chars.
5. IT steering committee — WMS upgrade from v4.2 to v5.0 — Timeline: pilot in Warehouse B (Jan 2026), full rollout (Mar 2026), parallel run period (2 weeks). Budget: EUR 180K (license + implementation). Risks: scanner firmware compatibility, staff retraining (est. 8h per user). Go/no-go decision deferred to December meeting. 600-900 chars.
6. Works council negotiation update (confidential) — New collective agreement for warehouse staff. Key points: 3.2% wage increase (union demanded 5.5%), one additional leave day, night shift premium increase from 25% to 30%, agreement on flexible scheduling with 2-week advance notice. Valid 2026-2027. Clearance: 3. 500-800 chars.

Make minutes feel real — some structured with numbered agenda items, others more informal notes. Include dates, room numbers, "minutes prepared by" attribution.""",
    ),
    (
        "sop",
        6,
        """Generate 6 Standard Operating Procedures (SOPs) for EuroLogistics GmbH. Each must be a step-by-step operational procedure with numbered steps.

Topics:
1. Inbound goods receiving and quality inspection — Steps from truck arrival to goods putaway. Include: dock assignment, seal verification, document check (CMR, delivery note), quantity count, quality sampling (1 in 20 for standard, 100% for pharma), damage documentation, WMS booking, putaway assignment. Reference ISO 9001 Section 7.4. 800-1200 chars.
2. ADR dangerous goods loading procedure — Pre-loading checks (vehicle certification, driver ADR card, placarding), loading sequence (heavy items bottom, incompatibility segregation per ADR 7.5.2), securing requirements, documentation (transport document per ADR 5.4.1, emergency instructions), departure checks. 800-1200 chars.
3. Cold chain verification — temperature check at pickup (reject if >2°C deviation), continuous monitoring during transport, delivery checkpoint (customer sign-off on temperature log), exception handling (temperature breach → quarantine + notify quality), documentation retention (3 years). 600-1000 chars.
4. Customer returns processing — Receipt of return, condition assessment (A=resellable, B=repackage, C=dispose), WMS booking (return reason code), quality hold, credit note trigger, restocking or disposal workflow, monthly returns analysis report. 500-800 chars.
5. Cross-docking for time-critical shipments — Pre-arrival notification (min 2h), dock reservation, direct transfer (no putaway), sorting by destination, outbound trailer assignment, priority loading, maximum dwell time 4 hours, escalation if delayed. 500-800 chars.
6. Driver departure checklist — Vehicle walk-around (tires, lights, load securing), document verification (CMR, ADR if applicable, delivery schedule), tachograph check, fuel level, route review in driver app, departure scan at gate, estimated arrival confirmation. 500-800 chars.

Format as real SOPs with: SOP number, version, effective date, responsible department, numbered procedural steps, and quality checkpoints (marked with ✓ or QC).""",
    ),
    (
        "compliance_audit",
        4,
        """Generate 4 compliance/audit documents for EuroLogistics GmbH.

Topics:
1. ISO 9001:2015 internal audit summary (Sep 2025) — Scope: warehouse operations and transport quality. Auditor: Sabine Fischer (Lead Auditor). 3 minor non-conformities: (1) calibration records incomplete for 2 of 8 temperature sensors, (2) corrective action log not updated since July, (3) customer complaint response exceeded 48h target in 2 cases. 0 major non-conformities. Next audit: March 2026. 800-1200 chars.
2. ADR compliance self-assessment — Annual review per ADR 1.8.3. Areas checked: vehicle certification (12/12 valid), driver training currency (28/30 drivers current — 2 renewals overdue), dangerous goods safety advisor (DGSA) appointed ✓, placarding compliance, emergency equipment inspection. Overall status: SUBSTANTIALLY COMPLIANT, 2 actions required. 700-1000 chars.
3. GDPR/DSGVO data processing impact assessment for fleet telematics — System: GPS tracking + driver behavior monitoring. Legal basis: legitimate interest (fleet management). Data subjects: 94 drivers. Data collected: location (30s intervals), speed, harsh braking, idling. Retention: 90 days (reduced from 1 year after Betriebsrat consultation). Risk assessment: medium (continuous location monitoring). Mitigations: privacy mode button, data minimization, access controls. 800-1200 chars.
4. Annual fire safety inspection by TÜV Rheinland — Inspector: Dipl.-Ing. Markus Bauer. Facilities: Warehouse A, Warehouse B, office building. Findings: fire extinguisher in Zone C-14 expired (replaced same day), emergency exit 3 partially blocked by pallets (cleared), sprinkler test satisfactory, fire alarm response time 2.3 minutes (target <3 min). Overall: PASSED with 2 observations. Next inspection: October 2026. 700-1000 chars.

Write as formal audit/compliance documents with finding reference numbers, severity classifications, and corrective action deadlines.""",
    ),
    (
        "vendor_agreement",
        4,
        """Generate 4 vendor/supplier agreements for EuroLogistics GmbH. These are contracts WHERE EUROLOGISTICS IS THE CUSTOMER (buying services), not providing logistics.

Topics:
1. Fuel supply agreement with PetroFlex GmbH — Contract PF-2025-001. Diesel and AdBlue supply to 3 depots (Munich, Stuttgart, Frankfurt). Pricing: index-linked to Platts NWE diesel, with EUR 0.03/L handling fee. Delivery: weekly, minimum 8,000L per depot. Quality: EN 590 diesel standard. Payment: 14 days from delivery. Term: 2 years with auto-renewal. Penalty for short delivery: EUR 0.10/L shortfall. 700-1100 chars.
2. Fleet maintenance contract with AutoService24 GmbH — Preventive and corrective maintenance for 45 vehicles. Response time: 4h for roadside assistance, 24h for scheduled service. Scope includes: oil changes, brake service, tire management, annual TÜV preparation. Excluded: body damage, tachograph calibration. Parts warranty: 12 months. Monthly retainer: EUR 185/vehicle + parts at cost +15%. Term: 3 years. KPIs: vehicle availability >96%, first-time fix rate >90%. 800-1200 chars.
3. Warehouse cleaning and pest control — CleanPro Facility Services. Weekly deep clean (all warehouse zones), daily office cleaning, monthly pest inspection (rodent monitoring stations, insect light traps). Pest response SLA: 4h for critical (rodent sighting), 24h for non-critical. Compliance with HACCP requirements for food storage areas. Monthly fee: EUR 4,200. Penalty for failed audit: EUR 2,000 per instance. 600-900 chars.
4. Cyber insurance policy summary — Insurer: Allianz Cyber Protection. Policy CYB-2025-ELG-001. Coverage: EUR 5M per incident. Covers: ransomware, data breach notification costs, business interruption (72h waiting period), regulatory fines defense. Excludes: nation-state attacks, prior known vulnerabilities, social engineering over EUR 50K. Premium: EUR 28,000/year. Deductible: EUR 15,000. Requirement: annual penetration test, MFA on all external access. 700-1000 chars.

Write as contract summaries/abstracts (not full legal text). Include contract reference numbers, key commercial terms, and penalty/SLA provisions.""",
    ),
]


def generate_batch(
    client: httpx.Client,
    model: str,
    category: str,
    count: int,
    instructions: str,
) -> list[dict]:
    """Generate a batch of documents via Ollama."""
    prompt = f"""{instructions}

Output ONLY a valid JSON array of {count} objects. Each object must have these exact fields:
- "doc_id": unique string ID (format: category abbreviation + number, e.g., "SAFETY-MAN-001")
- "title": document title string
- "doc_type": "{category}"
- "department": one of "warehouse", "hr", "logistics", "management", "legal", "it"
- "clearance_level": integer 1-4 (1=public, 2=internal, 3=confidential, 4=restricted)
- "text": the full document text (400-2000 chars)

IMPORTANT: Output ONLY valid JSON. No markdown, no code fences, no explanation. Just the JSON array. /no_think"""

    print(f"  Generating {count} {category} docs...", end=" ", flush=True)
    start = time.time()

    resp = client.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.8,
                "num_predict": 8192,
                "num_ctx": 16384,
            },
        },
        timeout=300.0,
    )
    resp.raise_for_status()

    elapsed = time.time() - start
    raw_text = resp.json()["response"].strip()

    # Try to extract JSON from response (handle markdown code fences)
    if "```json" in raw_text:
        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_text:
        raw_text = raw_text.split("```")[1].split("```")[0].strip()

    # Find the JSON array
    start_idx = raw_text.find("[")
    end_idx = raw_text.rfind("]")
    if start_idx == -1 or end_idx == -1:
        print(f"FAILED (no JSON array found, {elapsed:.0f}s)")
        print(f"    Raw response (first 200 chars): {raw_text[:200]}")
        return []

    json_text = raw_text[start_idx : end_idx + 1]

    try:
        docs = json.loads(json_text)
        print(f"OK ({len(docs)} docs, {elapsed:.0f}s)")
        return docs
    except json.JSONDecodeError as e:
        print(f"FAILED (JSON parse error: {e}, {elapsed:.0f}s)")
        # Try to salvage partial JSON
        print(f"    First 300 chars: {json_text[:300]}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark corpus via Ollama")
    parser.add_argument("--model", default="qwen3:32b", help="Ollama model name")
    parser.add_argument("--validate", action="store_true", help="Validate after generation")
    parser.add_argument("--retry-failed", action="store_true", help="Only retry failed batches")
    args = parser.parse_args()

    # Check Ollama connectivity
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:11434/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            if not any(args.model in m for m in models):
                print(f"Model '{args.model}' not found. Available: {', '.join(models)}")
                sys.exit(1)
    except Exception as e:
        print(f"Cannot connect to Ollama: {e}")
        sys.exit(1)

    # Load existing if retrying
    existing_docs = []
    existing_types = set()
    if args.retry_failed and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            existing_docs = json.load(f)
        existing_types = {d["doc_type"] for d in existing_docs}
        print(f"Loaded {len(existing_docs)} existing docs, types: {existing_types}")

    all_docs = list(existing_docs)

    print(f"Generating corpus with {args.model}")
    print(f"Output: {OUTPUT_PATH}")
    print()

    with httpx.Client() as client:
        for category, count, instructions in BATCHES:
            if args.retry_failed and category in existing_types:
                print(f"  Skipping {category} (already generated)")
                continue

            docs = generate_batch(client, args.model, category, count, instructions)

            if not docs:
                print(f"    WARNING: No docs generated for {category}. Run with --retry-failed to retry.")
                continue

            # Ensure doc_type is set correctly
            for d in docs:
                d["doc_type"] = category

            all_docs.extend(docs)

            # Save incrementally
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_PATH, "w") as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)

    print(f"\nTotal: {len(all_docs)} documents saved to {OUTPUT_PATH}")

    if args.validate:
        print("\nValidating...")
        from scripts.load_benchmark_corpus import validate_corpus
        validate_corpus(OUTPUT_PATH)


if __name__ == "__main__":
    main()
