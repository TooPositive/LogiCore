"""Generate production-quality diverse corpus for re-ranking benchmark.

Polish logistics company (LogiCore Sp. z o.o.) context.
Documents are realistic length: 5,000-20,000 chars (3-12 pages) per document.
Each generated individually for quality.

Usage:
    python scripts/generate_corpus.py                        # Generate diverse
    python scripts/generate_corpus.py --type homogeneous     # Generate contracts only
    python scripts/generate_corpus.py --retry-failed         # Retry failed batches

Output:
    data/benchmark-corpus/diverse_docs.json
    data/benchmark-corpus/homogeneous_docs.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmark-corpus"

SYSTEM_PROMPT = (
    "You generate realistic internal company documents for a POLISH logistics "
    "company called LogiCore Sp. z o.o., headquartered in Warszawa with depots "
    "in Katowice, Gdansk, Wroclaw, and Poznan. The company operates across Poland "
    "and Central Europe. Documents reference Polish law (Kodeks Pracy, RODO, "
    "Prawo Farmaceutyczne, Ustawa o transporcie drogowym, etc.), Polish regulatory "
    "bodies (UDT, PIP, PSP, GIF), and Polish cities/voivodeships. Currency: EUR "
    "for contracts (EU operations), PLN for internal costs where natural. "
    "Use Polish terms and abbreviations where a real Polish company would "
    "(e.g., Sp. z o.o., BHP, RODO, Kodeks Pracy, Betriebsrat→Zwiazki Zawodowe). "
    "Write as native Polish business professionals would write — mixing Polish "
    "terminology into English documents naturally. Output ONLY valid JSON."
)

# ---------------------------------------------------------------------------
# Document specs: (doc_id, doc_type, department, clearance, title_hint, prompt)
# Each generates ONE long document via a separate API call.
# ---------------------------------------------------------------------------

DIVERSE_DOCS = [
    # SAFETY MANUALS (7 docs)
    ("SAFETY-MAN-001", "safety_manual", "warehouse", 1, "HAZMAT Spill Response",
     """Write a complete HAZMAT Chemical Spill Response Procedure for a warehouse.
This is a 8-10 page safety manual. Include:
- Document header (procedure number, version, effective date, responsible person)
- Purpose and scope
- Regulatory references (ADR, Polish environmental law, Rozporządzenie w sprawie substancji niebezpiecznych)
- Hazard identification for common warehouse chemicals (sulfuric acid, acetone, diesel, AdBlue)
- PPE requirements by chemical class (Level A/B/C/D protection)
- Step-by-step spill response for small (<20L), medium (20-200L), and large (>200L) spills
- Containment procedures (absorbent booms, drain blocking, dike construction)
- Decontamination procedures
- Notification chain (shift supervisor → safety officer → Wojewódzki Inspektorat Ochrony Środowiska → fire brigade if needed)
- Incident reporting requirements and forms
- Post-incident investigation procedure
- Training requirements and drill schedule
- Appendices: emergency contact numbers, spill kit locations map, chemical compatibility chart
Write 6,000-10,000 characters of real content."""),

    ("SAFETY-MAN-002", "safety_manual", "warehouse", 1, "Warehouse Racking Inspection",
     """Write a complete Warehouse Racking Inspection and Load Safety Policy.
6-8 page document. Include:
- Document control info (policy number, version, owner)
- Legal basis (PN-EN 15512 standard, BHP regulations)
- Racking types in use (selective, drive-in, push-back, cantilever) with load ratings
- Inspection regime: daily visual (shift lead), monthly detailed (warehouse manager), annual structural (certified engineer from UDT-approved company)
- Damage classification system: GREEN (cosmetic, monitor), AMBER (deformed, reduce load by 50%, repair within 30 days), RED (critical, evacuate bay immediately, barrier tape, repair before reuse)
- Load limit signage requirements per PN-EN 15635
- Overloading prevention procedures
- Forklift collision reporting and assessment
- Repair and replacement standards
- Record keeping requirements (inspection logs, repair certificates, load calculations)
- Roles and responsibilities matrix
- Training requirements for warehouse staff
Write 5,000-8,000 characters."""),

    ("SAFETY-MAN-003", "safety_manual", "warehouse", 1, "Cold Storage Safety",
     """Write a Cold Storage Safety Manual covering hypothermia and frostbite prevention.
6-8 pages. Include:
- Scope: applies to all personnel entering cold storage zones (-18°C to -30°C)
- Risk assessment per temperature zone: chilled (2-8°C), frozen (-18°C), deep freeze (-25°C), blast freeze (-30°C)
- Maximum continuous exposure times by zone (with table)
- Mandatory PPE: insulated coveralls, thermal gloves (EN 511 rated), safety boots with thermal insoles, balaclava for deep freeze
- Buddy system rules — no lone working in zones below -18°C
- Check-in procedure (every 30 minutes via radio or dead-man switch)
- Warming break schedule (15 min warm-up per 45 min cold exposure)
- Emergency warming procedures (hypothermia stages I/II/III recognition, first aid, when to call 112)
- Door alarm and entrapment prevention (emergency release handles, door-ajar alarms)
- Equipment requirements (heated cabin for breaks, warm beverages station)
- Medical fitness requirements (annual occupational health check — badanie medycyny pracy)
- Incident statistics table (last 4 quarters)
Write 5,000-8,000 characters."""),

    ("SAFETY-MAN-004", "safety_manual", "warehouse", 1, "Loading Dock Operations",
     """Write a Loading Dock Operations Safety Manual.
6-8 pages. Include:
- Scope: 12 loading docks (6 with dock levelers, 6 ground-level)
- Vehicle approach procedure: 5 km/h speed limit, designated lanes, reverse into dock
- Wheel chocking procedure (both sides, chock must be in place before dock door opens)
- Dock leveler operation (hydraulic, manual override procedure, weight limits)
- Trailer inspection before loading: floor integrity, wall condition, cleanliness, temperature (for reefer units)
- Loading sequence rules: weight distribution, stack limits, load securing (EN 12195)
- Signal person hand signals (illustrated descriptions)
- Pedestrian separation from vehicle maneuvering areas
- Weather conditions: rain (wet dock surfaces), ice (salt/grit procedure), wind (door restrictions above 60 km/h)
- Night operations: minimum lighting levels (150 lux), hi-vis requirements
- Incident procedures: vehicle collision with dock structure, person struck
- Emergency stop locations (2 per dock bay)
Write 5,000-8,000 characters."""),

    ("SAFETY-MAN-005", "safety_manual", "warehouse", 1, "PPE Requirements Matrix",
     """Write a PPE Requirements Policy organized as a zone-by-zone matrix.
5-7 pages. Include:
- General warehouse zones: steel-toe boots (EN ISO 20345 S3), hi-vis vest (EN ISO 20471 Class 2), safety glasses
- Cold storage zones: add thermal coveralls, thermal gloves (EN 511), balaclava
- Chemical storage: add chemical-resistant gloves (EN 374), splash goggles, chemical apron
- Battery charging area: add face shield, acid-resistant gloves, rubber apron
- Loading docks: add hard hat (EN 397), hearing protection above 85 dB
- Office/visitor: safety shoes (minimum S1), hi-vis vest in warehouse areas
- Specific tasks: forklift operation (hard hat, seatbelt), racking inspection (hard hat, harness above 2m), confined space entry (gas detector, harness, rescue line)
- PPE issue, replacement, and return procedures
- Inspection and maintenance requirements (monthly checks, replacement criteria)
- Disciplinary consequences for PPE violations (progressive: verbal → written → suspension)
- Budget allocation per employee per year (PLN amounts)
- Supplier contracts and approved brands
Write 4,000-6,000 characters."""),

    ("SAFETY-MAN-006", "safety_manual", "warehouse", 1, "Night Shift Safety",
     """Write Night Shift Safety Protocols for warehouse operations.
5-7 pages. Include:
- Scope: applies to all night shift operations (22:00-06:00)
- Minimum staffing levels by zone (receiving: 2, storage: 3, shipping: 2, supervision: 1)
- Lone worker policy: no lone working; where unavoidable, 30-minute check-in via radio
- Fatigue management: maximum 4 consecutive night shifts, 48-hour break after night rotation, caffeine guidance
- Emergency lighting: monthly test schedule (30-min duration test), annual full-discharge test (3-hour), backup generator auto-start within 15 seconds
- Restricted areas after 22:00 (chemical storage, battery room — entry only with supervisor authorization)
- Security patrol schedule (every 2 hours, checkpoint log)
- Communication protocol: radio channel assignments, emergency codes
- First aid: minimum 1 trained first aider per shift, AED location and maintenance
- Handover procedure between shifts (outstanding issues, equipment status, safety concerns)
- Night shift premium and Kodeks Pracy Art. 151^8 compliance
Write 4,000-6,000 characters."""),

    ("SAFETY-MAN-007", "safety_manual", "warehouse", 1, "Heat Stress Prevention",
     """Write a Summer Heat Stress Prevention Program for warehouse workers.
5-6 pages. Include:
- Legal basis: Rozporządzenie w sprawie ogólnych przepisów BHP, Kodeks Pracy Art. 207
- Temperature action levels: Level 1 (28°C), Level 2 (32°C), Level 3 (35°C)
- Actions per level: hydration stations, modified break schedule, work/rest ratios, activity restrictions
- Hydration requirements: 250ml water every 20 minutes above 28°C, electrolyte drinks available
- Cooling measures: industrial fans, misting systems, air-conditioned break rooms, cooling vests for high-exertion tasks
- Heat illness recognition: heat cramps → heat exhaustion → heat stroke (symptoms, first aid, when to call 112)
- Acclimatization program for new workers and returning workers (gradual exposure over 5-7 days)
- Vulnerable workers: considerations for pregnant workers, workers on medication, workers over 55
- Clothing guidance: lightweight, breathable fabrics under required PPE
- Monitoring: wet-bulb globe temperature (WBGT) readings every 2 hours
- Record keeping and incident reporting
Write 4,000-6,000 characters."""),

    # HR POLICIES (7 docs)
    ("HR-POL-001", "hr_policy", "hr", 1, "Annual Leave Policy",
     """Write a comprehensive Annual Leave Policy (Regulamin Urlopowy).
8-10 pages. Include:
- Legal basis: Kodeks Pracy Art. 152-173, Ustawa o dniach wolnych od pracy
- Entitlement by tenure: 20 days (<10 years total work), 26 days (≥10 years) per Kodeks Pracy
- Additional company days: +2 days for warehouse staff (arduous conditions), +1 day for 5+ years at LogiCore
- Request procedure: minimum 14 days advance notice, via HR system, supervisor approval within 3 business days
- Blackout periods: November 15 - December 31 (peak logistics season), exceptions only with VP approval
- Carry-over rules: maximum 5 unused days to Q1 of following year per Art. 168 KP
- Mandatory consecutive leave: at least one period of 14 consecutive calendar days per year (Art. 162 KP)
- Public holidays list (all Polish public holidays with dates)
- Urlop na żądanie (on-demand leave): 4 days per year, notification by start of shift
- Special leave types: wedding (2 days), birth of child (2 days), death of family member (1-2 days)
- Unpaid leave provisions
- Leave during notice period
- Calculation of leave equivalent (ekwiwalent za urlop) on termination
- Impact on bonus eligibility
Write 6,000-10,000 characters."""),

    ("HR-POL-002", "hr_policy", "hr", 1, "Working Time and Overtime",
     """Write Working Time and Overtime Policy.
7-9 pages. Include:
- Legal basis: Kodeks Pracy Dział VI (Czas Pracy), Ustawa o czasie pracy kierowców
- Standard working time: 8 hours/day, 40 hours/week in 4-month settlement period
- Equivalent working time system for warehouse: up to 12-hour shifts with longer rest
- Driver-specific rules: EU Regulation 561/2006 + Polish implementation
- Overtime limits: max 150 hours/year above statutory limits, max 48 hours/week averaged over settlement period
- Overtime authorization: pre-approval by department head in HR system, emergency overtime verbal approval confirmed in writing within 24h
- Compensation: time off (1:1 for normal overtime, 1:1.5 for Sunday/holiday) OR pay premium (50% weekday, 100% Sunday/holiday/night)
- Night work premium: 20% of minimum wage hourly rate per Art. 151^8
- Sunday and holiday work: only permitted for continuous operations (warehouse, transport)
- Time recording: electronic system (TimeMoto), driver tachographs, manual correction procedure
- On-call (dyżur) rules: at workplace vs at home, compensation differences
- Rest periods: 11 hours daily, 35 hours weekly (may be reduced to 24 for shift workers per Art. 133)
- PIP (Państwowa Inspekcja Pracy) audit preparation
Write 6,000-9,000 characters."""),

    ("HR-POL-003", "hr_policy", "hr", 2, "Anti-Harassment Policy",
     """Write Workplace Harassment and Discrimination Prevention Policy.
7-8 pages. Include:
- Legal basis: Kodeks Pracy Art. 94^3 (mobbing), Art. 18^3a-18^3e (discrimination), Ustawa o równym traktowaniu (AGG equivalent)
- Definitions: mobbing, sexual harassment, discrimination (direct/indirect), victimization
- Protected characteristics per Polish law
- Examples of prohibited behavior (with specific scenarios relevant to logistics/warehouse)
- Reporting channels: direct supervisor, HR Business Partner, anonymous whistleblower hotline (external provider), email: zgloszenia@logicore.pl
- Investigation procedure: acknowledgment within 24 hours, investigation team appointed within 3 business days, interviews, evidence collection, conclusion within 30 days
- Confidentiality obligations for all parties
- Protection against retaliation (Art. 18^3e KP)
- Consequences: verbal warning → written warning → suspension → dismissal (Art. 52 KP for gross violations)
- External ombudsperson: contact details and role
- Support for victims: employee assistance program (EAP), temporary transfer options
- Training requirements: annual for all employees, additional for managers
- Monitoring and reporting (annual statistics to Management Board)
Write 5,000-8,000 characters."""),

    ("HR-POL-004", "hr_policy", "hr", 1, "Performance Review Process",
     """Write a Performance Management and Review Policy.
6-8 pages. Include:
- Review cycle: quarterly check-ins (Q1, Q2, Q3), annual formal review (Q4)
- Rating scale: 1 (Unsatisfactory), 2 (Below Expectations), 3 (Meets Expectations), 4 (Exceeds), 5 (Outstanding) — with behavioral descriptions for each level
- Goal setting: SMART framework, minimum 3 individual goals + 2 team goals
- Competency framework: role-specific competencies (driver, warehouse operator, office) + core values
- Self-assessment: employee completes before review meeting
- Calibration sessions: department heads align ratings across teams
- Performance Improvement Plan (PIP): triggered by two consecutive quarters rated 2 or below, 90-day duration, weekly check-ins, clear measurable targets
- PIP outcomes: successful (return to normal review), unsuccessful (termination per HR-POL-TERM procedures)
- Link to compensation: annual salary review based on rating (3=inflation adjustment, 4=+3-5%, 5=+5-8% + spot bonus)
- Link to promotion: minimum 2 consecutive years rated 4+ for promotion eligibility
- Documentation: all reviews stored in HR system, accessible to employee and manager
- Appeal procedure: employee may request re-review by skip-level manager within 14 days
Write 5,000-7,000 characters."""),

    ("HR-POL-005", "hr_policy", "hr", 2, "Data Privacy Notice (RODO)",
     """Write an Employee Data Privacy Notice (Klauzula Informacyjna RODO).
6-8 pages. Include:
- Data controller: LogiCore Sp. z o.o., NIP: [number], ul. Marszałkowska [number], 00-XXX Warszawa
- DPO (Inspektor Ochrony Danych): name, email iod@logicore.pl, phone
- Categories of personal data processed: identification, contact, employment, payroll, health (BHP), GPS tracking, CCTV, time and attendance
- Legal basis for each category (Art. 6(1)(b) contract, (c) legal obligation, (f) legitimate interest)
- Sensitive data (Art. 9): health certificates (badania lekarskie), trade union membership — explicit consent required
- Retention periods by data type (employment records: 10 years per Art. 94 KP, payroll: 50 years per ZUS regulations, CCTV: 30 days, GPS: 90 days)
- Recipients: ZUS, Urząd Skarbowy, payroll provider, insurance company, PIP on request
- Transfers outside EU/EEA: none (or specify Azure data center location)
- Employee rights: access (Art. 15), rectification (Art. 16), erasure (Art. 17), restriction (Art. 18), portability (Art. 20), objection (Art. 21)
- Right to lodge complaint with Prezes Urzędu Ochrony Danych Osobowych (PUODO)
- Automated decision-making: describe any algorithms used (route optimization, performance scoring)
- Consent withdrawal procedure
- Data breach notification procedure (72 hours to PUODO per Art. 33)
Write 5,000-8,000 characters."""),

    ("HR-POL-006", "hr_policy", "hr", 2, "Works Council Consultation",
     """Write a Trade Union and Employee Representation Consultation Procedures document.
5-7 pages. Include:
- Legal basis: Kodeks Pracy Art. 23^2 (consultation obligation), Ustawa o związkach zawodowych, Ustawa o radach pracowników
- Current union status at LogiCore (e.g., NSZZ Solidarność zakładowa organizacja związkowa)
- When consultation is mandatory:
  * Individual termination of union member (Art. 38 KP) — 5 business day consultation period
  * Group redundancies (Ustawa o szczególnych zasadach rozwiązywania stosunków pracy) — 20+ employees in 30 days
  * Changes to work regulations (Regulamin Pracy) — Art. 104^2 KP
  * Changes to remuneration rules (Regulamin Wynagradzania)
  * Introduction of monitoring/CCTV (Art. 22^2 KP)
  * Changes to working time systems
- Consultation timeline and process
- Information rights of employee council (Rada Pracowników) — quarterly reporting
- Dispute resolution: mediacja → Komisja Pojednawcza → Sąd Pracy
- Collective agreement (Zakładowy Układ Zbiorowy Pracy) modification procedure
- Management responsibilities and training
Write 4,000-6,000 characters."""),

    ("HR-POL-007", "hr_policy", "hr", 1, "Company Vehicle Policy",
     """Write a Company Vehicle and Fuel Card Policy.
5-7 pages. Include:
- Eligibility: managers, sales, fleet coordinators, and on-call maintenance staff
- Vehicle categories: passenger car (managers), commercial van (coordinators), company pool vehicles
- Private use: permitted within Poland, taxable benefit per PIT regulations (ryczałt: PLN 250/month for cars up to 1600cc, PLN 400/month above)
- Driver obligations: valid category B/C/CE license, report damage within 24 hours, maintain service schedule, no smoking in vehicle, dashcam must not be covered
- Fuel card (ORLEN Flota): limits by role (PLN 1,500/month standard, PLN 3,000 for field staff), PIN protected, personal fuel purchases prohibited
- Accident procedure: 1) ensure safety, 2) call 112 if injuries, 3) take photos, 4) exchange info with other party, 5) call fleet manager, 6) fill collision report (oświadczenie o zdarzeniu drogowym), 7) written report to HR within 24 hours
- Insurance: OC/AC/NNW covered by company, deductible (udział własny): PLN 1,000 at-fault incidents
- Return procedure on employment termination: vehicle, keys, fuel card, toll device (viaAuto), parking cards
- Alcohol and substance policy: zero tolerance, random testing
- Fines and penalties: traffic violations are employee's personal responsibility
Write 4,000-6,000 characters."""),

    # TECHNICAL SPECS (6 docs)
    ("TECH-SPEC-001", "technical_spec", "it", 1, "Temperature Monitoring System",
     """Write a Temperature Monitoring System Technical Specification.
8-10 pages. Include:
- System overview: SensoGuard TM-400 wireless sensors monitoring all temperature-controlled zones
- Sensor specifications: range -40°C to +80°C, accuracy ±0.3°C, resolution 0.1°C, battery life 3 years, IP67 rated
- Zone configuration: pharma storage (2-8°C, alert at ±1°C), frozen goods (-18°C ±2°C), blast freeze (-30°C ±3°C), ambient warehouse (15-25°C), office (20-24°C)
- Data logging: every 5 minutes, MQTT protocol to central gateway, InfluxDB time-series storage
- Alert thresholds: WARNING (±1°C from target), CRITICAL (±2°C), EMERGENCY (±3°C or sensor failure)
- Notification chain: WARNING → shift supervisor (SMS), CRITICAL → warehouse manager + quality manager (SMS + email), EMERGENCY → plant manager + customer notification (phone call)
- Dashboard: Grafana visualization, real-time and historical views, per-zone drill-down
- Integration: WMS (auto-quarantine trigger on CRITICAL), customer API (PharmaCorp real-time feed per GDP requirements)
- Calibration: every 6 months against NIST-traceable reference, calibration certificate stored in QMS
- Maintenance: battery replacement schedule, sensor cleaning (quarterly), gateway firmware updates
- Compliance: GDP Annex 9 (temperature mapping study annually), HACCP monitoring requirements
- Network architecture diagram description (sensors → gateway → MQTT broker → InfluxDB → Grafana)
- Disaster recovery: offline data buffering on gateway (72 hours), automatic resync
Write 6,000-10,000 characters."""),

    ("TECH-SPEC-002", "technical_spec", "it", 1, "Fleet GPS Tracking System",
     """Write a Fleet GPS Tracking System Technical Specification.
7-9 pages. Include:
- Device: Teltonika FMC130, LTE Cat 1, GPS/GLONASS, accelerometer, CAN bus reader
- Installation: professional installation by certified technician, tamper-proof mounting, connection to vehicle CAN bus for fuel and engine data
- Update interval: 30 seconds while moving, 5 minutes while stationary, 1 second during harsh event
- Data collected: GPS position, speed, heading, altitude, fuel level, engine RPM, odometer, temperature (for reefer units), door open/close sensor, harsh braking/acceleration/cornering events
- Geofencing: customer delivery sites (auto-ETA notification), depot boundaries, rest areas (driver compliance), country borders (automatic tachograph notification), restricted zones (city centers, environmental zones)
- Driver behavior scoring: algorithm weighing speeding (30%), harsh braking (25%), harsh cornering (20%), idling (15%), seatbelt (10%)
- Data retention: 2 years per RODO assessment, anonymized after retention period
- Privacy: driver privacy mode button (personal use hours — records only start/stop, no position), Rada Pracowników consultation completed per Art. 22^2 KP
- Integration: WMS (real-time ETA updates), customer portal (shipment tracking), Langfuse (API monitoring), SAP (trip data for cost allocation)
- API: REST API, webhooks for events, authentication via API key + IP whitelist
- Platform: Teltonika FOTA for firmware management, LogiCore Fleet Portal (custom Next.js dashboard)
- Backup: dual SIM (Orange + Play), offline storage 100,000 records, auto-sync on reconnection
Write 6,000-9,000 characters."""),

    ("TECH-SPEC-003", "technical_spec", "it", 2, "WMS Barcode Scanning Workflow",
     """Write a WMS Barcode Scanning Workflow Technical Specification.
6-8 pages. Include:
- Scanner hardware: Zebra TC52 (Android, 2D imager), battery life 14 hours, rugged (IP67, 1.8m drop)
- Supported barcode formats: GS1-128 (logistics labels), EAN-13 (retail), QR (internal tracking), Data Matrix (pharma serialization)
- Receiving workflow: 1) dock assignment scan, 2) trailer seal verification, 3) CMR document scan, 4) pallet label scan (GS1-128 SSCC), 5) quantity verification (count vs delivery note), 6) quality sampling trigger (1:20 standard, 100% pharma per GDP), 7) damage photo capture, 8) WMS putaway assignment
- Pick workflow: 1) wave assignment, 2) location scan, 3) item scan (verify correct SKU), 4) quantity confirmation, 5) bin scan (destination), 6) short pick procedure (flag, reallocate, notify)
- Shipping workflow: 1) order consolidation scan, 2) weight verification (±2% tolerance), 3) label print and apply, 4) dock assignment scan, 5) trailer load scan, 6) departure confirmation
- Error handling: unknown barcode → manual entry screen + supervisor alert, mismatched SKU → audible alarm + block, damaged label → reprint workflow
- Label printer integration: Zebra ZT411 (industrial), ZD421 (desktop), label templates in ZPL
- Offline mode: scan queue holds up to 500 transactions, auto-sync when WiFi reconnects, conflict resolution rules
- Performance targets: scan-to-response <200ms, picks per hour target 120, scan accuracy >99.8%
Write 5,000-8,000 characters."""),

    ("TECH-SPEC-004", "technical_spec", "it", 2, "Network Infrastructure",
     """Write a Warehouse Network Infrastructure Technical Specification.
6-8 pages. Include:
- WiFi: Cisco Catalyst 9130 access points, WiFi 6 (802.11ax), coverage target 99.8% at -67 dBm
- VLAN segmentation: VLAN 10 (OT — scanners, label printers), VLAN 20 (corporate IT), VLAN 30 (IoT sensors, temperature, CCTV), VLAN 40 (guest), VLAN 50 (management)
- Network topology: redundant core switches (Cisco 9300 stack), distribution to each warehouse zone, PoE+ for cameras and APs
- IP addressing scheme: 10.10.x.0/24 per VLAN per building
- Internet connectivity: dual ISP (Orange Business 500/100 Mbps + Polkomtel backup 200/50 Mbps), automatic failover via Cisco SD-WAN
- WAN: MPLS between depots (Warszawa-Katowice-Gdańsk-Wrocław-Poznań), 100 Mbps per site
- Security: Cisco ISE for NAC (802.1X for corporate, MAB for OT devices), Palo Alto PA-450 firewall, Cisco Umbrella DNS security
- Monitoring: PRTG Network Monitor, alerting to IT team (SMS + Slack), dashboards per site
- Uptime SLA: 99.9% for production network (43.8 min/month max downtime)
- Failover procedure: primary switch failure → automatic HSRP failover within 3 seconds, ISP failure → SD-WAN route optimization within 10 seconds
- Physical security: locked network closets, temperature monitoring, UPS (30 minutes runtime)
- Vendor support: Cisco SmartNet 24x7x4 for core, NBD for access layer
Write 5,000-8,000 characters."""),

    ("TECH-SPEC-005", "technical_spec", "it", 1, "Transport Order Lifecycle",
     """Write a Transport Order Lifecycle Technical Specification (SAP to delivery).
7-9 pages. Include:
- End-to-end flow: Customer order → SAP SD → Transport order → WMS pick → Driver app → Loading → GPS tracking → Delivery → POD → SAP billing
- SAP integration: IDoc ORDERS05 (inbound orders), IDoc DESADV (despatch advice), IDoc INVOIC (invoice), RFC calls for real-time stock check
- WMS interaction: transport order triggers pick wave, bin allocation, label generation
- Driver app: React Native, assigned runs, navigation (integration with Google Maps), delivery confirmation (signature capture, photo POD, temperature log upload)
- Loading confirmation: WMS scan → SAP goods issue → driver app notification
- GPS tracking: real-time position updates (see TECH-SPEC-002), ETA recalculation every 5 minutes, automatic customer notification at 30/15/5 minutes before arrival
- Delivery: driver confirms delivery in app → WMS updates → SAP goods receipt at customer → invoice trigger
- Exception handling: partial delivery (split shipment), refused delivery (return process), temperature breach (quarantine workflow), address change (re-routing), vehicle breakdown (reassignment)
- Message retry logic: 3 attempts with exponential backoff (1s, 5s, 25s), then dead letter queue, manual review within 4 hours
- Error states and resolution procedures for each integration point
- Performance targets: order-to-dispatch <4 hours, end-to-end visibility within 30 seconds of event
- Data model diagram description (entities and relationships)
Write 6,000-9,000 characters."""),

    ("TECH-SPEC-006", "technical_spec", "it", 2, "Disaster Recovery Plan",
     """Write a Disaster Recovery and Business Continuity Plan for IT systems.
7-9 pages. Include:
- Scope: all production IT systems (WMS, ERP, email, fleet tracking, temperature monitoring, telephony)
- RPO/RTO targets: Tier 1 (WMS, fleet tracking): RPO 1h / RTO 4h. Tier 2 (ERP, email): RPO 4h / RTO 8h. Tier 3 (reporting, dev): RPO 24h / RTO 48h.
- Backup schedule: Tier 1 hourly snapshots, Tier 2 daily full + 4-hourly incremental, Tier 3 daily
- Backup technology: Veeam Backup & Replication, stored on-site (NAS) + offsite (Azure Blob Storage, region: Poland Central)
- Replication: Tier 1 systems replicated to secondary site (Katowice) via Azure Site Recovery
- DR site: Katowice depot (secondary data center), capable of running Tier 1 workloads within RTO
- DR test procedure: quarterly tabletop exercise, annual full failover test (scheduled for May, Saturday 02:00-14:00)
- Escalation contacts: on-call IT engineer → IT Manager → CTO → external DR support (Capgemini SLA)
- Scenarios: power failure (UPS + generator), internet failure (dual ISP failover), server failure (VM restart on cluster), ransomware (isolate, restore from clean backup), natural disaster (full site failover to Katowice)
- Recovery procedures: step-by-step for each Tier 1 system
- Communication plan: internal (Teams + SMS cascade) + external (customer notification template, carrier notification)
- Post-incident review: RCA within 5 business days, lessons learned presentation to management
- Compliance: alignment with ISO 22301, RODO Art. 32 (security of processing)
Write 6,000-9,000 characters."""),

    # INCIDENT REPORTS (5 docs)
    ("INC-2025-031", "incident_report", "warehouse", 1, "Forklift Near-Miss",
     """Write a detailed incident investigation report for a forklift near-miss.
4-6 pages. Include:
- Incident reference: INC-2025-031
- Date/Time: 2025-08-14, 14:23
- Location: Warehouse A, intersection of Aisle 14 and Cross-Aisle C
- Personnel: forklift operator Tomasz Kowalski (FK-012), pedestrian Anna Wiśniewska (picker)
- Severity: Near-miss (Level 2 on 5-point scale)
- Detailed description: FK-012 rounded blind corner at approximately 12 km/h (limit: 5 km/h at intersections), nearly striking A. Wiśniewska who was crossing from Picking Zone B. Distance estimated at 0.5m. No contact, no injury.
- Root cause analysis (5-Why method): Why speed? Driver behind schedule. Why behind schedule? Late inbound delivery. Why blind corner? Convex mirror removed during Zone C renovation on 2025-07-28, not reinstalled.
- Contributing factors: absent mirror, time pressure, worn floor markings at intersection
- Immediate actions: area cordoned off, temporary mirror installed same day, driver verbal warning
- Corrective actions with deadlines: permanent mirror (responsible: Marek Zielinski, warehouse manager, deadline: 2025-08-21), floor markings repainted (deadline: 2025-08-28), intersection speed sensors pilot (deadline: 2025-09-30)
- Witness statements (2 witnesses, summarized)
- Photos attached (described)
- Lessons learned for safety committee
- Sign-off: safety officer, warehouse manager, HR representative
Write 4,000-6,000 characters."""),

    ("INC-2025-047", "incident_report", "warehouse", 2, "Cold Storage Temperature Excursion",
     """Write a detailed incident report for a temperature excursion in cold storage.
5-7 pages. Include:
- Incident reference: INC-2025-047
- Date/Time: 2025-09-22, discovered 06:15 (occurred overnight starting ~00:30)
- Location: Cold Storage Unit 3, Warehouse B, Katowice depot
- Product affected: 3 pallets FreshFoods yogurt (240 cases, batch FK-2025-09-187), 1 pallet PharmaCorp insulin pens (48 boxes, batch PH-INS-25Q3-004)
- Financial impact: yogurt EUR 12,400 (write-off), insulin EUR 87,500 (quarantined pending quality assessment — GDP temperature deviation investigation required)
- Temperature data: dropped from -18°C to -8°C over 6 hours, peak -6.2°C at 05:45, alarm triggered at -14°C (02:17) but night shift supervisor phone on silent
- Root cause: compressor bearing failure (Unit C3-COMP-02, Bitzer 4PCS-15.2Y), last preventive maintenance was 2025-08-08 (2 weeks overdue per monthly schedule)
- Contributing factors: maintenance backlog due to technician vacancy, alarm notification only to supervisor (no escalation), backup compressor isolation valve left closed from June maintenance
- Immediate actions: products quarantined, backup compressor activated manually at 06:30, temperature restored to -18°C by 08:45
- Customer notification: FreshFoods notified 07:00 (replacement shipment dispatched same day), PharmaCorp notified 07:15 (GDP deviation report required within 24 hours)
- Corrective actions with timeline and owners
- Insurance claim status
- Sign-offs
Write 5,000-7,000 characters."""),

    ("INC-2025-019", "incident_report", "logistics", 1, "Driver Fatigue Incident",
     """Write a detailed incident report for a driver fatigue event.
4-6 pages. Include:
- Incident reference: INC-2025-019
- Date/Time: 2025-07-03, 16:47
- Location: A8 motorway (Katowice direction), km 147.3, near Kraków
- Driver: Paweł Nowak, employee since 2019, clean driving record, ADR certified
- Vehicle: MAN TGX 18.510, registration KAT 5R78, loaded with chemical raw materials (ChemTrans shipment CT-2025-07-0342)
- Incident: vehicle drifted onto hard shoulder, lane departure warning (LDW) triggered, dashcam recorded 3-second drift, driver self-corrected
- Driver status at time: 11 hours on duty, 8.5 hours driving (approaching daily limit), had taken required breaks per tachograph
- Root cause: dispatcher assigned return run after late loading at origin (Płock refinery loading delayed 2.5 hours due to quality hold), pushing driver close to limits
- Tachograph analysis: detailed breakdown of driving/rest/other work periods
- Contributing factors: late loading not communicated to dispatch for re-planning, hot weather (34°C), driver reported poor sleep previous night
- Immediate actions: driver pulled over at next rest area, replacement driver dispatched from Kraków depot (arrived 19:30), shipment continued with new driver
- Regulatory: no violation per EU 561/2006 (driving time within limits), but fatigue management policy gap identified
- Corrective actions: dispatcher training, fatigue risk assessment tool, mandatory rest policy when on-duty exceeds 10 hours regardless of driving time
Write 4,000-6,000 characters."""),

    ("INC-2025-055", "incident_report", "warehouse", 1, "Loading Bay Slip and Fall",
     """Write a detailed incident report for a slip-and-fall injury.
4-5 pages. Include:
- Incident reference: INC-2025-055
- Date/Time: 2025-10-11, 11:35
- Location: Loading Bay 6, Warehouse A, Warszawa depot
- Injured person: Jakub Majewski, warehouse operator, 2 years tenure
- Injury: sprained right ankle, bruising to right hip
- Lost time: 3 working days (returned with modified duties for additional 2 weeks)
- Description: worker slipped on wet dock surface during heavy rain, fell from dock edge (height approximately 1.2m to ground level)
- Root cause: drainage channel adjacent to Bay 6 blocked by accumulated shrink wrap debris, causing water pooling on dock surface. Anti-slip rain mat (kept in maintenance storage) not deployed despite rain starting at 09:00.
- Contributing factors: rain mat deployment not included in shift handover checklist, drainage channel last cleaned 3 weeks prior (should be weekly), dock area lighting adequate (230 lux measured)
- First aid: cold compress applied, driven to Szpital Bielański emergency department, X-ray negative for fracture
- BHP (occupational safety) notification: reported to PIP within 24 hours per Art. 234 KP (accident at work)
- Corrective actions with timeline
- Prevention: automatic rain sensor trigger for mat deployment, weekly drainage cleaning schedule, dock surface anti-slip coating evaluation
Write 3,500-5,000 characters."""),

    ("INC-2025-008", "incident_report", "warehouse", 1, "Chemical Leak During Unloading",
     """Write a detailed incident report for a minor chemical leak.
4-5 pages. Include:
- Incident reference: INC-2025-008
- Date/Time: 2025-06-28, 09:15
- Location: Loading Bay 2, Warehouse A, Warszawa depot
- Chemical: industrial degreaser (Henkel Bonderite C-AK 5050), Class 8 corrosive, UN 1760
- Quantity leaked: approximately 2 liters from cracked 20L drum
- Description: during unloading of ChemTrans shipment CT-2025-06-0289, warehouse operator noticed wet packaging on middle tier of pallet. 20L drum had developed hairline crack along bottom seam. Approximately 2L had leaked onto dock floor. Spill contained within 8 minutes using SK-003 spill kit from Bay 2 station.
- Root cause: drum stacked 3-high on pallet without edge protection or separator boards, shifted during transport causing stress fracture on bottom drum
- Environmental impact: none — all liquid contained on dock surface, drained into internal collection sump (not storm water drain), hazmat contractor (EkoTeam) disposed of contaminated absorbent
- Regulatory: below reportable threshold (Rozporządzenie w sprawie substancji niebezpiecznych), no WIOŚ notification required
- Personnel exposure: operator wore standard PPE (safety boots, gloves), no skin contact, no medical treatment needed
- Corrective actions: supplier notified about packaging standards, incoming inspection enhanced for chemical shipments, stacking guidance updated
Write 3,500-5,000 characters."""),

    # MEETING MINUTES (6 docs)
    ("MTG-2025-10-BHP", "meeting_minutes", "warehouse", 1, "Safety Committee Oct 2025",
     """Write detailed Monthly Safety Committee Meeting Minutes.
5-7 pages. Include:
- Meeting: Monthly BHP Committee Meeting (Komisja BHP per Art. 237^12 KP)
- Date: 2025-10-15, 10:00-12:30, Conference Room B, Warszawa HQ
- Attendees (8 people): BHP Inspector (Agnieszka Pawlak, chair), Warehouse Manager (Marek Zieliński), Fleet Manager (Katarzyna Duda), HR Business Partner (Piotr Grabowski), Trade Union Rep (Stanisław Kowal, NSZZ Solidarność), Quality Manager (Ewa Michalska), Maintenance Supervisor (Robert Jankowski), occupational physician (Dr. Joanna Wójcik — phone)
- Minutes prepared by: Agnieszka Pawlak
- Agenda: 1) Review of September incidents, 2) Audit preparation update, 3) Winter safety campaign, 4) PPE budget Q4, 5) AOB
- September incident review: 2 near-misses (INC-2025-031 forklift, INC-2025-033 falling box from racking), 1 LTI (INC-2025-029 manual handling back strain, 5 lost days), stats comparison with same period last year
- ISO 45001 audit preparation: external audit scheduled for November 22-24 by TÜV Rheinland Polska, gap analysis findings, documentation checklist status
- Winter safety campaign: ice/snow clearing schedule, grit station locations, cold weather PPE issue, anti-slip footwear assessment
- PPE budget: Q4 request PLN 45,000 (breakdown by category), approved with condition
- Each agenda item with detailed discussion, decisions, and action items (owner + deadline)
Write 5,000-7,000 characters."""),

    ("MTG-2025-Q3-OPS", "meeting_minutes", "management", 2, "Q3 Operations Review",
     """Write Quarterly Operations Review Meeting Minutes.
5-7 pages. Include:
- Date: 2025-10-08, 14:00-17:00, Board Room, Warszawa HQ
- Attendees: COO (Michał Nowicki), VP Logistics (Anna Kowalczyk), VP Warehouse (Tomasz Jabłoński), Fleet Manager (Katarzyna Duda), Finance Controller (Paweł Sawicki), Customer Success Manager (Monika Szymańska)
- Q3 KPI dashboard: on-time delivery 96.2% (target 98%), fleet utilization 84%, fuel cost EUR 0.38/km (+5% YoY), customer complaints 45 (down 12% QoQ), warehouse throughput 12,400 pallets/week, picking accuracy 99.7%
- Revenue: EUR 4.2M (budget EUR 4.5M, -6.7%), EBITDA margin 10.2%
- Customer issues: 3 SLA breaches with FreshFoods (2x late delivery Wrocław route, 1x temperature), compensation paid EUR 1,200. PharmaCorp quarterly review positive, discussing 2 new routes for Q1 2026.
- ChemTrans expansion: 2 new routes approved (Płock-Puławy, Płock-Tarnów), require 2 additional ADR-certified drivers, 1 additional ADR vehicle — CapEx EUR 180K
- Fleet: 3 vehicles due for replacement in Q4, electric truck pilot assessment presented (MAN eTGM), decision deferred to board meeting
- Action items with owners and deadlines
Write 5,000-7,000 characters."""),

    ("MTG-2025-BOARD-EV", "meeting_minutes", "management", 3, "Board Meeting - Fleet Electrification",
     """Write Board Meeting Minutes (excerpt) on fleet electrification investment.
4-6 pages. Include:
- Date: 2025-10-22, 09:00-13:00, Board Room, Warszawa HQ
- Attendees: CEO (Krzysztof Mazur), CFO (Małgorzata Witek), COO (Michał Nowicki), Board members (3), invited: VP Logistics, Fleet Manager
- Agenda item 4: Fleet Electrification Investment Decision
- Proposal: EUR 2.4M CapEx for 12 electric trucks (MAN eTGM 26.360 E), phased over 18 months
- Business case: TCO analysis (EUR/km: diesel 0.38 vs electric 0.22, break-even year 5), EU Green Deal compliance, customer demand (FreshFoods sustainability requirements)
- EU subsidy: application submitted to NFOŚiGW (Narodowy Fundusz Ochrony Środowiska), potential 40% grant (EUR 960K), decision expected Q1 2026
- Charging infrastructure: 6 DC fast chargers (150kW) at Warszawa and Katowice depots, EUR 420K, installation by Ekoenergetyka-Polska
- Risks: range limitation (300km vs 800km diesel), charging time (2h vs 10min refuel), cold weather impact (-20% range), resale value uncertainty
- Timeline: first 4 vehicles Q2 2026 (urban Warszawa routes), next 4 Q4 2026 (Katowice), final 4 Q1 2027 (intercity if range proves sufficient)
- Vote: approved 8-2, with conditions (subsidy must be confirmed, pilot evaluation after 6 months)
- Dissenting view noted (2 board members — range concern for Gdańsk route)
Write 4,000-6,000 characters."""),

    ("MTG-2025-W44-HUDDLE", "meeting_minutes", "logistics", 1, "Weekly Logistics Huddle",
     """Write informal Weekly Logistics Huddle notes.
2-3 pages. Informal tone — these are quick standup notes, not formal minutes.
- Date: Monday 2025-11-03, 08:00-08:15, Standing at dispatch board
- Present: dispatch team (4), fleet coordinator, warehouse shift lead
- Driver availability: 28 of 32 drivers available (3 on leave, 1 sick — Paweł Nowak, back expected Wednesday)
- Peak season: volume forecast +35% weeks 47-51, temp agency drivers (4) starting Wednesday (3 from Adecco, 1 from Randstad), need induction training slots booked with BHP
- Route changes: R-017 (Warszawa-Łódź) closed Tuesday-Thursday for bridge works near Rawa Mazowiecka, detour via S8 adds 45 min, customers notified
- Vehicle status: KAT-5R78 in workshop (brake pads), expected back Tuesday. WAW-3T42 annual inspection (przegląd) booked Thursday at TÜV Rheinland Polska
- Customer notes: FreshFoods requested earlier delivery window for Kraków stores (04:30 instead of 05:00) starting next week — checking driver availability
- Open issue: trailer GPS tracker on WAW-NZ12 showing intermittent signal — IT ticket #4521 open
Write 2,000-3,000 characters."""),

    ("MTG-2025-IT-WMS", "meeting_minutes", "it", 2, "IT Steering Committee - WMS Upgrade",
     """Write IT Steering Committee Meeting Minutes on WMS upgrade.
4-6 pages. Include:
- Date: 2025-10-30, 14:00-16:00, Conference Room A, Warszawa HQ
- Attendees: CTO (Rafał Kowalski), IT Manager (Beata Zając), WMS Product Owner (Damian Lis), VP Warehouse (Tomasz Jabłoński), Change Manager (Sylwia Nowak), vendor representative (SAP — remote)
- Agenda: WMS upgrade from SAP EWM 9.5 to SAP S/4HANA EWM 2023
- Timeline: pilot in Warehouse B Katowice (January 2026), full rollout all sites (March 2026), parallel run 2 weeks per site
- Budget: EUR 180K (license uplift EUR 60K, implementation partner EUR 90K, internal costs EUR 30K)
- Risks: scanner firmware compatibility (Zebra TC52 — test with new RF framework needed), staff retraining (estimated 8h per user × 85 users = 680 training hours), integration points with custom fleet app (12 API endpoints to retest)
- Key improvements: real-time inventory visibility, improved pick path optimization (estimated 15% efficiency gain), mobile-first UI, integration with automation (future AMR robots)
- Data migration: 450K location records, 12K material masters, 3 years transaction history
- Go/no-go criteria: all 12 integration tests pass, user acceptance testing (5 business days), no P1 defects
- Decision: go/no-go deferred to December 2025 meeting pending integration test results
- Action items with owners and deadlines
Write 4,000-6,000 characters."""),

    ("MTG-2025-ZZ-CBA", "meeting_minutes", "hr", 3, "Works Council Negotiation Update",
     """Write confidential Works Council (Związki Zawodowe) Negotiation Update.
3-5 pages. Include:
- Date: 2025-10-25, 10:00-12:00, HR Conference Room (closed door)
- Attendees: HR Director (Joanna Grabowska), VP Operations (Michał Nowicki), Legal Counsel (Mec. Katarzyna Wiśniewska), union representatives (Stanisław Kowal — NSZZ Solidarność, Maria Lewandowska — OPZZ)
- Subject: New Zakładowy Układ Zbiorowy Pracy (collective agreement) for warehouse staff — round 4 of negotiations
- Union demands: 5.5% wage increase (vs company offer 3.2%), 2 additional leave days, night shift premium increase from 25% to 35%, job security guarantee for 3 years
- Company position: 3.2% wage increase (aligned with GUS inflation forecast), 1 additional leave day, night shift premium 30%, no job security guarantee (incompatible with business flexibility)
- Progress: agreement reached on night shift premium (30%), additional leave (1 day), flexible scheduling (2-week advance notice). Wage increase still open — union dropped to 4.5%, company raised to 3.5%. Gap: 1 percentage point = approximately PLN 420K annual cost.
- Next steps: management to present final offer at round 5 (November 8), union consultation with members (November 12-15), target signing by November 30
- Valid: 2026-2027
- CONFIDENTIAL — not for distribution outside negotiating parties
Write 3,000-5,000 characters."""),

    # SOPs (6 docs)
    ("SOP-WH-001", "sop", "warehouse", 1, "Inbound Goods Receiving",
     """Write a complete Standard Operating Procedure for Inbound Goods Receiving.
8-10 pages. Include:
- SOP Number: SOP-WH-001, Version 4.2, Effective: 2025-01-15
- Responsible: Warehouse Manager, applicable to all receiving staff
- Purpose: standardize receiving process to ensure quality, accuracy, and traceability
- Scope: all inbound shipments to all LogiCore warehouses
- Reference documents: ISO 9001:2015 Section 7.4, GDP Guidelines (Annex 5), HACCP plan (for food-grade zones)
- Pre-arrival: transport order received from SAP (T-12 hours), dock slot booked in WMS, receiving team briefed
- Step-by-step procedure (20+ numbered steps):
  1) Vehicle arrival — check-in at gate, verify transport documents (CMR, delivery note, ADR papers if applicable)
  2) Dock assignment — WMS auto-assigns based on cargo type and zone
  3) Seal verification — record seal number, compare with CMR, photograph if damaged
  4) Trailer inspection — floor condition, temperature check (reefer units — record on form WH-TEMP-001), odor check, pest signs
  5) Unloading — by forklift (palletized) or manual (parcels), count pallets/cases
  6) Quantity verification — WMS scan each pallet SSCC, compare with delivery note, note discrepancies
  7) Quality sampling — standard goods: 1 in 20 random inspection; pharma: 100% per GDP; food: per HACCP sampling plan
  8) Damage assessment — any damage photographed, logged in WMS with damage code, carrier notified
  9) Temperature logging — for temperature-controlled goods: record arrival temp, compare with acceptable range, quarantine if out of range
  10) WMS booking — goods receipt posted in WMS, triggers SAP goods movement (101)
  11) Putaway — WMS assigns storage location based on product attributes (ABC class, temperature zone, hazmat segregation)
  12) CMR signing — sign CMR, retain copy 2, return copy 1 to driver
- Quality checkpoints (marked QC at steps 4, 6, 7, 9)
- Exception handling: short delivery, over-delivery, wrong goods, damaged goods, temperature breach
- Forms and templates referenced
- Training requirements for receiving staff
Write 7,000-10,000 characters."""),

    ("SOP-TR-002", "sop", "logistics", 1, "ADR Dangerous Goods Loading",
     """Write a complete SOP for ADR Dangerous Goods Loading.
8-10 pages. Include:
- SOP Number: SOP-TR-002, Version 3.1, Effective: 2025-03-01
- Responsible: Fleet Manager + DGSA (Dangerous Goods Safety Adviser — Doradca ADR)
- Legal references: ADR 2023, Ustawa o przewozie towarów niebezpiecznych, Rozporządzenie w sprawie warunków technicznych pojazdów
- Pre-loading checks (detailed):
  * Vehicle ADR certification valid (Świadectwo dopuszczenia pojazdu ADR)
  * Driver ADR certificate (zaświadczenie ADR) valid and covers required classes
  * Vehicle equipment check: 2 warning triangles, 2 orange self-standing warning signs, orange plates (front and rear), wheel chock, drain seal, collection container, shovel, eye wash, warning vest, torch, gloves — per ADR 8.1.5
  * Fire extinguishers: 2kg (cab) + appropriate size for cargo (6kg/12kg per ADR 8.1.4)
  * Placards and UN number plates correct for cargo
- Loading sequence (detailed steps):
  1) Segregation check per ADR Table 7.5.2.1 — verify no incompatible classes co-loaded
  2) Packaging integrity check — every package inspected for damage, leaks, correct UN markings
  3) Securing — per EN 12195, blocking and bracing requirements for dangerous goods
  4) Load plan documentation
  5) Door seal application and recording
- Documentation requirements:
  * Transport document (ADR 5.4.1) — content requirements listed
  * Emergency instructions in writing (instrukcje pisemne) in languages of driver, loader, countries transited
  * Container packing certificate if applicable
- Departure checks
- Emergency procedures during loading (spill, fire, exposure)
- Record keeping (5 years per ADR 1.8.3.3)
Write 7,000-10,000 characters."""),

    ("SOP-QA-003", "sop", "warehouse", 1, "Cold Chain Verification",
     """Write a complete SOP for Cold Chain Verification.
6-8 pages. Include:
- SOP Number: SOP-QA-003, Version 2.4, Effective: 2025-06-01
- Applicable to: all temperature-controlled shipments (pharma GDP, HACCP food)
- Temperature zones: chilled (2-8°C), frozen (-18°C ±2°C), deep freeze (-25°C ±3°C)
- Pickup verification: temperature check at pickup location, reject if deviation >2°C from target, record on form QA-TEMP-002, photograph data logger display
- In-transit monitoring: SensoGuard TM-400 data logger in every temperature-controlled shipment, real-time alerts to dispatch (see TECH-SPEC-001 for alert thresholds)
- Delivery verification: customer sign-off on temperature log printout, data logger removed and returned to dispatch for data download
- Exception handling:
  * Minor deviation (<2°C, <30 minutes): document, deliver, notify quality manager
  * Major deviation (>2°C or >30 minutes): quarantine product, do NOT deliver without quality manager authorization, notify customer within 1 hour
  * For pharma (GDP): ANY deviation triggers full GDP deviation investigation (Form QA-GDP-001), customer (Qualified Person) decides product disposition, LogiCore provides complete temperature record within 24 hours
- Data retention: temperature records kept 3 years (5 years for pharma per GDP requirements)
- Calibration: all data loggers calibrated every 6 months against NIST-traceable reference
- Annual temperature mapping study per GDP Annex 9
Write 5,000-7,000 characters."""),

    ("SOP-WH-004", "sop", "warehouse", 1, "Customer Returns Processing",
     """Write a SOP for Customer Returns Processing.
5-6 pages. Include:
- SOP Number: SOP-WH-004, Version 2.0, Effective: 2025-04-01
- Scope: all customer returns across all product categories
- Return authorization: customer contacts Customer Service, return number (RET-YYYY-NNNN) issued in SAP
- Receipt: dedicated returns dock (Bay 11), scan return label, verify against RET authorization
- Condition assessment:
  * Grade A: original packaging intact, product undamaged → restock
  * Grade B: packaging damaged but product intact → repackage, then restock
  * Grade C: product damaged or expired → dispose (recycling or waste contractor)
  * Grade D: hazardous/contaminated → quarantine, DGSA assessment if chemical
- WMS processing: book return with reason code (wrong item, damaged in transit, quality issue, customer changed mind, recall), quality hold flag
- Credit note: auto-triggered for Grade A/B, manual approval for Grade C/D (finance team within 5 business days)
- Restocking: Grade A within 24 hours, Grade B within 48 hours (repackaging queue)
- Disposal: Grade C logged in waste register, collected by licensed contractor (monthly)
- Monthly returns analysis: report to Customer Success Manager, trend analysis by customer/product/reason
Write 4,000-5,500 characters."""),

    ("SOP-TR-005", "sop", "logistics", 1, "Cross-Docking Procedure",
     """Write a SOP for Cross-Docking time-critical shipments.
4-6 pages. Include:
- SOP Number: SOP-TR-005, Version 1.3, Effective: 2025-02-15
- Definition: goods transferred directly from inbound to outbound vehicle without putaway into storage
- Eligibility: pre-sorted shipments, time-critical deliveries, flow-through consolidation
- Pre-arrival notification: minimum 2 hours, inbound vehicle ETA confirmed via fleet tracking, outbound vehicle pre-assigned
- Dock reservation: adjacent inbound/outbound docks allocated in WMS (minimize travel distance)
- Procedure:
  1) Inbound arrival — standard receiving checks (SOP-WH-001 abbreviated: document check, seal verify, pallet count)
  2) Sorting: by destination route/customer per cross-dock manifest
  3) Direct transfer: forklift moves pallet from inbound dock to staging area to outbound dock
  4) No putaway — goods never enter rack storage
  5) Outbound loading: per standard loading procedure, CMR generated
  6) Maximum dwell time: 4 hours from inbound to outbound departure
  7) Escalation if delayed: at 3 hours, warehouse supervisor reviews and assigns priority resources
- Temperature-controlled cross-dock: goods must not leave controlled environment; reefer trailer to reefer trailer via insulated dock
- WMS transactions: goods receipt + goods issue in single workflow (301 movement type in SAP)
- Performance target: 95% of cross-dock shipments depart within 4-hour window
Write 3,500-5,000 characters."""),

    ("SOP-TR-006", "sop", "logistics", 1, "Driver Pre-Trip Checklist",
     """Write a SOP for Driver Pre-Trip Inspection and Departure.
5-6 pages. Include:
- SOP Number: SOP-TR-006, Version 3.0, Effective: 2025-01-01
- Applicable: all LogiCore drivers before every trip
- Vehicle walk-around inspection (exterior):
  * Tires: visual check for damage, tread depth (minimum 1.6mm, company standard 3mm), pressure gauge check (front, rear, trailer)
  * Lights: all positions (headlights, indicators, brake lights, marker lights, reflectors, number plate light)
  * Body: check for damage since last trip, report new damage immediately
  * Underside: visual check for fluid leaks (oil, coolant, fuel, air lines)
  * Coupling (tractor-trailer): king pin locked, air and electrical connections secure, landing gear fully raised
  * Load securing: straps/chains condition, ratchet function, edge protectors available
- Cab checks:
  * Mirrors and cameras adjusted
  * Windscreen clean, wipers functional, washer fluid level
  * Seatbelt functional
  * Dashboard warning lights — none illuminated after engine start
  * Fuel level: minimum 1/4 tank for departure
  * AdBlue level check
- Document verification:
  * Driving license (valid, correct category)
  * ADR certificate (if applicable)
  * CMR (waybill) for all shipments
  * Delivery schedule printed or loaded in driver app
  * Vehicle registration and insurance documents
  * Tachograph card inserted, driver activity set to "driving"
- Route review: load route in driver app, check for road works/closures, confirm ETA with dispatch
- Departure scan: scan vehicle barcode at exit gate, triggers GPS tracking activation
- ETA confirmation: driver confirms estimated arrival times for all stops via app
- Checklist form: paper (form TR-PRE-001) or digital (driver app checkbox workflow)
- Non-compliance: vehicle must NOT depart if any critical defect found (brakes, steering, lights, tires below minimum)
Write 4,000-6,000 characters."""),

    # COMPLIANCE/AUDIT (4 docs)
    ("AUDIT-QMS-2025", "compliance_audit", "warehouse", 2, "ISO 9001 Internal Audit",
     """Write an ISO 9001:2015 Internal Audit Summary Report.
6-8 pages. Include:
- Audit reference: IA-QMS-2025-003
- Scope: warehouse operations (receiving, storage, picking, shipping) and transport quality at Warszawa and Katowice sites
- Audit dates: September 15-19, 2025
- Lead Auditor: Sabine Fischer (external, TÜV Rheinland Polska, Lead Auditor Certificate #TRP-2019-4521)
- Team: 2 additional auditors (1 internal, 1 external)
- Standards: ISO 9001:2015 clauses 4-10, GDP (where applicable)
- Methodology: document review, process observation, staff interviews (35 interviews conducted), sampling of records
- Executive summary: 3 minor non-conformities, 0 major non-conformities, 5 observations (opportunities for improvement), overall status: MAINTAINS CERTIFICATION
- Non-conformity details:
  * NC-001 (Minor, Clause 7.1.5): Calibration records incomplete for 2 of 8 temperature sensors at Katowice site. Sensors TM-K-003 and TM-K-007 — calibration due August, not performed. Root cause: technician vacancy.
  * NC-002 (Minor, Clause 10.2): Corrective action log (CAR register) not updated since July. 4 CARs from Q2 showing "open" without progress notes. Process owner: Quality Manager.
  * NC-003 (Minor, Clause 8.2.1): Customer complaint response time exceeded 48-hour target in 2 of 12 sampled cases (CC-2025-089: 72h, CC-2025-103: 56h).
- Observations (detailed, 5 items with improvement suggestions)
- Positive findings (strengths noted by auditors)
- Corrective action plan: each NC with root cause, corrective action, responsible person, deadline, verification method
- Next audit: March 2026 (surveillance), September 2026 (recertification)
- Auditor sign-off and distribution list
Write 5,000-8,000 characters."""),

    ("AUDIT-ADR-2025", "compliance_audit", "logistics", 2, "ADR Compliance Self-Assessment",
     """Write an ADR Compliance Annual Self-Assessment Report.
5-7 pages. Include:
- Reference: ADR-SA-2025-001, per ADR 1.8.3.3 annual report requirement
- Prepared by: Jan Kowalski, DGSA (Doradca ds. bezpieczeństwa przewozu towarów niebezpiecznych), Certificate #DGSA-PL-2021-0847
- Period: January-September 2025
- Scope: transport of Class 3 (flammable liquids), Class 6.1 (toxic), Class 8 (corrosive), Class 9 (miscellaneous) — primarily for ChemTrans contract
- Vehicle fleet status: 12 ADR-certified vehicles, all Świadectwa ADR valid (expiry dates listed)
- Driver certification: 28 of 30 assigned drivers hold valid zaświadczenie ADR. 2 drivers (named) — certificates expired August 2025, renewal training booked for October 2025. STATUS: NON-COMPLIANT (2 drivers temporarily reassigned to non-ADR routes)
- Equipment inspection: all vehicles checked against ADR 8.1.4/8.1.5 equipment list. 1 vehicle (KAT-2R89) missing second warning sign — replaced same day.
- Placarding compliance: spot-checked 40 shipments in Q1-Q3, 100% compliant
- Documentation review: 50 transport documents sampled, 48 correct (96%), 2 with minor errors (wrong emergency phone number format — corrected)
- Emergency procedures: 2 tabletop exercises conducted (April, August), 0 real incidents involving dangerous goods release
- Training: annual refresher for all ADR drivers completed (March 2025), warehouse staff ADR awareness training completed (February 2025)
- Overall status: SUBSTANTIALLY COMPLIANT. 2 corrective actions required (driver certifications, transport document template update).
- DGSA recommendations for next year
Write 5,000-7,000 characters."""),

    ("AUDIT-RODO-2025", "compliance_audit", "it", 3, "GDPR/RODO Impact Assessment - Fleet Telematics",
     """Write a Data Protection Impact Assessment (DPIA / Ocena skutków dla ochrony danych) for fleet telematics.
6-8 pages. Include:
- Reference: DPIA-2025-003
- Prepared by: Inspektor Ochrony Danych (IOD) — Marta Kowalczyk, in consultation with CTO and Fleet Manager
- System assessed: fleet GPS tracking + driver behavior monitoring (see TECH-SPEC-002)
- Legal basis: Art. 6(1)(f) RODO (legitimate interest — fleet management, route optimization, duty of care)
- Data subjects: 94 active drivers employed by LogiCore Sp. z o.o.
- Data collected: GPS position (30s intervals while driving), speed, harsh events (braking/acceleration/cornering), fuel consumption, engine data (CAN bus), door sensor, temperature (reefer units)
- Data NOT collected: in-cab audio, personal phone data, off-duty location (privacy mode active)
- Retention: 90 days for individual tracking data (reduced from 1 year after Rada Pracowników consultation in Q2 2024), aggregated statistics retained indefinitely
- Necessity and proportionality assessment: GPS essential for customer delivery tracking, safety monitoring (driver fatigue prevention), regulatory compliance (tachograph supplement), fleet optimization
- Risk assessment: MEDIUM risk (continuous location monitoring of employees). Mitigations:
  * Privacy mode button: driver activates during personal use hours, records only start/end, no position
  * Data minimization: only operational data collected, no personal communication monitoring
  * Access controls: fleet manager and dispatch only, no HR access without specific justification
  * Pseudonymization: driver behavior scores aggregated and anonymized for reporting
- Consultation with Rada Pracowników completed (protocol dated 2024-06-15)
- Prior consultation with PUODO: not required (mitigations reduce residual risk to acceptable level)
- Review date: annually or upon significant system change
Write 5,000-8,000 characters."""),

    ("AUDIT-FIRE-2025", "compliance_audit", "warehouse", 1, "Annual Fire Safety Inspection",
     """Write an Annual Fire Safety Inspection Report by external assessor.
5-7 pages. Include:
- Report reference: FIRE-2025-001
- Inspector: inż. Marek Bauer, rzeczoznawca ds. zabezpieczeń przeciwpożarowych, License #RZ-2018-0234
- Inspection date: October 8-9, 2025
- Facilities inspected: Warehouse A (6,800 m²), Warehouse B (4,200 m²), Office Building (1,200 m²), Warszawa site
- Regulatory basis: Ustawa o ochronie przeciwpożarowej, Rozporządzenie MSWiA w sprawie ochrony przeciwpożarowej budynków
- Inspection results by area:
  * Warehouse A: fire extinguisher in Zone C-14 expired (gaśnica proszkowa GP-6, last service 2024-04-12, due 2025-04-12) — replaced during inspection. Emergency exit 3 partially blocked by 2 pallets — cleared immediately, supervisor notified. Sprinkler system test: satisfactory (8 sprinkler heads tested, all activated within specification). Fire alarm panel: functional, zones correctly mapped.
  * Warehouse B: all fire protection equipment current. Smoke detector in cold storage anteroom showing intermittent fault — maintenance ticket raised.
  * Office: all clear. Fire drill log reviewed — last drill September 12, 2025 (evacuation time: 3 minutes 42 seconds, within 4-minute target).
- Fire alarm system test: Bosch FPA-5000, full loop test, response time 2.3 minutes from activation to full alarm (target <3 min). All smoke/heat detectors functional.
- Fire suppression: sprinkler system (wet pipe, Warehouse A+B), verified adequate coverage, pressure test passed
- Emergency lighting: tested on battery backup, all illuminated signs functional, 2 exit signs dim (replacement ordered)
- Overall result: PASSED with 2 observations (expired extinguisher — corrected, blocked exit — corrected)
- Recommendations (3 items)
- Next inspection: October 2026
- Inspector certification and signature
Write 5,000-7,000 characters."""),

    # VENDOR AGREEMENTS (4 docs)
    ("VEND-PF-2025", "vendor_agreement", "legal", 2, "Fuel Supply Agreement",
     """Write a Fuel Supply Agreement summary/abstract.
5-7 pages. Include:
- Contract: PF-2025-001 between LogiCore Sp. z o.o. (Buyer) and PetroFlex Sp. z o.o. (Supplier)
- Effective: 2025-01-01, Term: 2 years with automatic renewal
- Scope: diesel fuel (EN 590) and AdBlue (ISO 22241) supply to 4 depots (Warszawa, Katowice, Gdańsk, Wrocław)
- Volumes: minimum 8,000L diesel per depot per week (128,000L/month total), AdBlue 2,000L/month total
- Pricing: indexed to Platts NWE Diesel (CIF NWE Cargoes), adjusted weekly, plus EUR 0.03/L handling fee, AdBlue at fixed EUR 0.35/L
- Delivery: tanker delivery weekly per schedule, minimum 48-hour advance order, emergency delivery within 24 hours (surcharge EUR 200)
- Quality: EN 590:2013+A1:2017 diesel standard, certificate of quality with each delivery, LogiCore reserves right to sample and test, non-conforming fuel replaced at supplier's cost
- Payment: 14 days from delivery date, electronic invoice to faktura@logicore.pl
- Penalty for short delivery: EUR 0.10/L shortfall below minimum order, plus LogiCore's cost of emergency alternative supply
- Tank maintenance: PetroFlex responsible for annual tank cleaning and calibration (included in handling fee)
- Environmental: supplier holds valid permit for fuel transport, spill liability during delivery rests with supplier until fuel enters LogiCore's storage tank
- Insurance: supplier maintains OC przewoźnika minimum EUR 2M
- Termination: 3 months written notice, immediate termination for quality failure or safety violation
- Governing law: Polish law, disputes to Sąd Arbitrażowy przy KIG
Write 4,000-6,000 characters."""),

    ("VEND-AS24-2025", "vendor_agreement", "legal", 2, "Fleet Maintenance Contract",
     """Write a Fleet Maintenance Contract summary.
5-7 pages. Include:
- Contract: MS-2025-001 between LogiCore Sp. z o.o. (Client) and AutoService24 Sp. z o.o. (Service Provider)
- Effective: 2025-04-01, Term: 3 years
- Scope: preventive and corrective maintenance for 45 commercial vehicles (32 tractors, 13 trailers)
- Preventive maintenance schedule: per manufacturer recommendations (MAN, Volvo, DAF), oil change every 60,000km, brake inspection every 90,000km, full service annually
- Response times: roadside assistance 4 hours (24/7), scheduled service 24 hours (business days), annual przegląd (technical inspection): 5 business days advance booking
- Service scope included: oil/filter changes, brake service (pads, discs, drums), tire management (rotation, replacement, seasonal change), electrical diagnostics, air system maintenance, annual TÜV/przegląd preparation, AdBlue system service
- Excluded: body damage repair, tachograph calibration (separate UDT contract), interior cleaning, accessories
- Parts: OEM or OEM-equivalent quality, warranty 12 months or 50,000km whichever comes first
- Monthly retainer: EUR 185 per vehicle (EUR 8,325/month for 45 vehicles) + parts at cost +15% markup
- KPIs: vehicle availability >96% (measured monthly), first-time fix rate >90%, mean time to repair <8 hours for non-major repairs
- Penalty: if vehicle availability falls below 94% in any month, 10% retainer reduction for that month
- Workshop locations: Warszawa (primary), Katowice, mobile service unit for roadside
- Reporting: monthly maintenance report, quarterly fleet health assessment, annual fleet replacement recommendation
Write 4,000-6,000 characters."""),

    ("VEND-CP-2025", "vendor_agreement", "legal", 1, "Cleaning and Pest Control",
     """Write a Warehouse Cleaning and Pest Control Service Agreement.
4-5 pages. Include:
- Contract: CP-2025-001 between LogiCore Sp. z o.o. and CleanPro Facility Services Sp. z o.o.
- Effective: 2025-02-01, Term: 2 years, auto-renewal
- Scope: cleaning and integrated pest management for Warszawa depot (Warehouse A, B, Office)
- Cleaning schedule:
  * Warehouse zones: weekly deep clean (vacuum, mop, rack surface dust), daily spot clean of spills
  * Office: daily clean (vacuum, desk wipe, bathroom sanitize, kitchen clean), weekly window clean
  * Loading docks: daily sweep, weekly pressure wash (weather permitting)
  * Cold storage: monthly defrost and clean (coordinated with warehouse schedule to minimize temperature disruption)
- Pest control:
  * Rodent monitoring: 24 bait stations (exterior) + 12 electronic monitoring traps (interior), checked monthly
  * Insect control: UV light traps in warehouse entrance areas (8 units), checked monthly, electric fly killers in food zone
  * Pest response SLA: 4 hours for critical (rodent sighting in warehouse), 24 hours for non-critical (insect activity)
  * Quarterly pest audit report submitted to LogiCore Quality Manager
- HACCP compliance: all cleaning products food-safe in Zones A-B (food storage), material safety data sheets (Karty Charakterystyki) provided
- Monthly fee: PLN 18,500 (cleaning PLN 14,500, pest control PLN 4,000)
- Penalty: failed HACCP/ISO audit attributable to cleaning/pest deficiency — PLN 8,000 per instance
- Insurance: OC minimum PLN 2M
- Key personnel: dedicated site supervisor (Warehouse A), available by phone 06:00-22:00
Write 3,500-5,000 characters."""),

    ("VEND-CYB-2025", "vendor_agreement", "it", 3, "Cyber Insurance Policy",
     """Write a Cyber Insurance Policy Summary.
4-6 pages. Include:
- Policy: CYB-2025-ELG-001
- Insurer: PZU Cyber Protection (PZU S.A.)
- Policyholder: LogiCore Sp. z o.o.
- Policy period: 2025-01-01 to 2025-12-31, renewable
- Coverage limit: EUR 5M per incident, EUR 10M aggregate per policy period
- Coverage includes:
  * Ransomware: decryption costs, ransom payment (with prior insurer approval), business interruption
  * Data breach: notification costs (per RODO Art. 34), forensic investigation, credit monitoring for affected individuals, legal defense
  * Business interruption: loss of revenue due to cyber incident, 72-hour waiting period, daily indemnity based on average daily revenue
  * Regulatory fines defense: legal costs to defend against PUODO fines (note: fines themselves may not be insurable under Polish law)
  * Third-party liability: claims from customers/partners affected by data breach originating from LogiCore systems
  * Crisis management: PR/communication consultant, customer notification services
- Exclusions:
  * Nation-state attacks (acts of cyber warfare)
  * Prior known vulnerabilities (unpatched systems where patch available >90 days)
  * Social engineering losses exceeding EUR 50,000 (separate crime policy required)
  * Intentional acts by senior management
  * Failure to maintain minimum security standards (see requirements below)
- Premium: EUR 28,000/year
- Deductible: EUR 15,000 per incident
- Security requirements (conditions for coverage):
  * MFA on all external-facing systems (verified annually)
  * Annual penetration test by certified firm (report submitted to insurer)
  * Endpoint detection and response (EDR) on all endpoints
  * Backup strategy meeting 3-2-1 rule (3 copies, 2 media types, 1 offsite)
  * Security awareness training for all employees (annually)
  * Incident response plan documented and tested
- Claims procedure: notify PZU within 24 hours of discovery, preserve evidence, engage insurer-approved forensics firm
Write 4,000-6,000 characters."""),
]


def generate_doc(client: httpx.Client, doc_spec: tuple) -> dict | None:
    """Generate a single long-form document via Azure OpenAI."""
    doc_id, doc_type, department, clearance, title_hint, prompt = doc_spec

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    user_msg = f"""{prompt}

Output a single JSON object (NOT an array) with these fields:
- "doc_id": "{doc_id}"
- "title": "{title_hint}" (expand to a proper document title)
- "doc_type": "{doc_type}"
- "department": "{department}"
- "clearance_level": {clearance}
- "text": the FULL document text (as specified in the prompt above — this should be LONG, 4000-10000+ characters)

Output ONLY the JSON object. No markdown, no explanation."""

    print(f"  [{doc_id}] {title_hint}...", end=" ", flush=True)
    start = time.time()

    try:
        resp = client.post(
            url,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json={
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_completion_tokens": 16384,
            },
            timeout=180.0,
        )
    except Exception as e:
        print(f"FAILED ({e})")
        return None

    elapsed = time.time() - start

    if resp.status_code != 200:
        print(f"FAILED (HTTP {resp.status_code}, {elapsed:.0f}s)")
        return None

    content = resp.json()["choices"][0]["message"].get("content", "").strip()
    if not content:
        print(f"FAILED (no content, {elapsed:.0f}s)")
        return None

    # Strip markdown fences
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        doc = json.loads(content)
        text_len = len(doc.get("text", ""))
        print(f"OK ({text_len} chars, {elapsed:.0f}s)")
        return doc
    except json.JSONDecodeError as e:
        # Try to find JSON object
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            try:
                doc = json.loads(content[start_idx:end_idx + 1])
                text_len = len(doc.get("text", ""))
                print(f"OK (extracted, {text_len} chars, {elapsed:.0f}s)")
                return doc
            except json.JSONDecodeError:
                pass
        print(f"FAILED (JSON: {e}, {elapsed:.0f}s)")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark corpus")
    parser.add_argument("--type", choices=["diverse", "homogeneous"], default="diverse")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    for var in ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY"]:
        if not os.environ.get(var):
            print(f"Missing: {var}")
            sys.exit(1)

    if args.type == "diverse":
        output_path = DATA_DIR / "diverse_docs.json"
        doc_specs = DIVERSE_DOCS
    else:
        # For homogeneous, we'll reuse generate_homogeneous_corpus.py
        print("Use scripts/generate_homogeneous_corpus.py for homogeneous corpus")
        sys.exit(0)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing docs if retrying
    existing: dict[str, dict] = {}
    if args.retry_failed and output_path.exists():
        with open(output_path) as f:
            for doc in json.load(f):
                existing[doc["doc_id"]] = doc
        print(f"Loaded {len(existing)} existing docs")

    print(f"Generating {len(doc_specs)} documents → {output_path}")
    print()

    all_docs: list[dict] = []
    with httpx.Client() as client:
        for spec in doc_specs:
            doc_id = spec[0]
            if doc_id in existing:
                print(f"  [{doc_id}] SKIP (already exists)")
                all_docs.append(existing[doc_id])
                continue

            doc = generate_doc(client, spec)
            if doc:
                # Ensure correct metadata
                doc["doc_id"] = doc_id
                doc["doc_type"] = spec[1]
                doc["department"] = spec[2]
                doc["clearance_level"] = spec[3]
                all_docs.append(doc)
            else:
                print(f"    WARNING: Failed to generate {doc_id}")

            # Save incrementally
            with open(output_path, "w") as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)

    # Stats
    print(f"\nTotal: {len(all_docs)} documents")
    lengths = [len(d.get("text", "")) for d in all_docs]
    if lengths:
        print(f"Text lengths: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths)//len(lengths)}")
        total_chars = sum(lengths)
        est_pages = total_chars // 2000  # rough estimate
        print(f"Total content: {total_chars:,} chars (~{est_pages} pages)")

    types = {}
    for d in all_docs:
        t = d.get("doc_type", "?")
        types[t] = types.get(t, 0) + 1
    print("\nDistribution:")
    for t, c in sorted(types.items()):
        print(f"  {t:<20} {c}")


if __name__ == "__main__":
    main()
