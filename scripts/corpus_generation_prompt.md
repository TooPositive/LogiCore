# Corpus Generation Prompt

Paste this into a Claude/ChatGPT session. Copy the JSON output and save it to `data/benchmark-corpus/diverse_docs.json`.

---

## PROMPT (copy everything below this line)

You are generating a realistic document corpus for a German logistics company called **EuroLogistics GmbH** (fictional). These documents will be used to benchmark a retrieval system.

**CRITICAL RULES:**
1. Each document must read like a REAL internal company document — not a template with filled blanks
2. Vary writing styles: some formal (legal), some procedural (SOPs), some informal (meeting notes)
3. Vary lengths: 400-2000 characters per document
4. Include realistic details: specific dates, names, amounts, locations, reference numbers
5. Some documents should reference other documents (cross-references)
6. Use a mix of English and occasional German terms (this is a German company)
7. Do NOT use any of these exact IDs: CTR-2024-001 through CTR-2024-004, DOC-LEGAL-001 through DOC-LEGAL-005, DOC-HR-002 through DOC-HR-005, DOC-SAFETY-001 through DOC-SAFETY-003

**OUTPUT FORMAT:** A single JSON array. Each element:
```json
{
  "doc_id": "string (unique ID like SAFETY-MAN-001, HR-POL-012, etc.)",
  "title": "string",
  "doc_type": "string (one of: safety_manual, hr_policy, technical_spec, incident_report, meeting_minutes, sop, training_material, compliance_audit, vendor_agreement)",
  "department": "string (one of: warehouse, hr, logistics, management, legal, it)",
  "clearance_level": 1-4,
  "text": "string (the full document text, 400-2000 chars)"
}
```

**Generate exactly 45 documents across these categories:**

### 1. Safety Manuals & Procedures (7 docs)
Documents about warehouse safety, chemical handling, PPE requirements, emergency procedures. These should mention topics like: fire safety, spill response, forklift operations, temperature monitoring, loading dock safety, driver safety checks. They should be DIFFERENT from each other — not variations of the same template.

Example topics (write unique content for each):
- HAZMAT spill response procedure for warehouse chemicals
- Warehouse racking inspection and load limits policy
- Cold storage safety — hypothermia prevention and equipment
- Loading dock operations — vehicle approach, chocking, signals
- PPE requirements by zone (warehouse, cold storage, chemical storage)
- Night shift safety protocols and lone worker procedures
- Seasonal weather preparedness (winter ice, summer heat stress)

### 2. HR Policies & Documents (7 docs)
Employment-related documents. Topics like: leave policies, disciplinary procedures, remote work policy, training requirements, works council agreements, overtime rules, workplace harassment policy. Include German labor law references (BetrVG, Arbeitszeitgesetz, etc.).

Example topics:
- Annual leave policy and public holiday schedule (Urlaubsgesetz)
- Overtime and time tracking policy (Arbeitszeitgesetz compliance)
- Workplace harassment and discrimination policy (AGG)
- Performance review process and rating scale
- Employee data privacy notice (DSGVO/GDPR for HR)
- Works council (Betriebsrat) consultation procedures
- Company car and fleet vehicle usage policy

### 3. Technical Specifications & IT (6 docs)
WMS configuration, vehicle telematics, temperature monitoring systems, SAP integration, GPS tracking, network infrastructure. Include specific system names, IP addresses, configuration values.

Example topics:
- Temperature monitoring system specs (sensor model, alert thresholds, calibration schedule)
- Fleet GPS tracking system — device specs, data retention, geofencing rules
- WMS barcode scanning workflow — scanner models, label formats, error handling
- Network infrastructure — warehouse WiFi coverage, VLAN setup, redundancy
- ERP data flow — transport order lifecycle from SAP to WMS to driver app
- Backup and disaster recovery plan for logistics systems

### 4. Incident Reports (5 docs)
Real-looking incident reports with dates, times, witnesses, root cause analysis, corrective actions. Mix of severity levels.

Example topics:
- Forklift collision with racking in Aisle 14 (near-miss, no injury)
- Temperature excursion in cold storage unit 3 (product loss EUR 12,400)
- Driver fatigue incident — vehicle left lane on A8 motorway
- Slip and fall injury in loading bay during rain (lost time: 3 days)
- Chemical container leak during unloading (small spill, contained)

### 5. Meeting Minutes & Reports (6 docs)
Board meetings, safety committee meetings, operations reviews, quarterly business updates. Include attendee lists, action items, deadlines.

Example topics:
- Monthly safety committee meeting (incident stats, audit findings, training updates)
- Q3 2025 operations review (KPIs, fleet utilization, customer complaints)
- Board meeting — fleet electrification investment decision
- Weekly logistics huddle — route changes, driver availability, peak season prep
- IT steering committee — WMS upgrade timeline, budget approval
- Union negotiation update — new collective agreement terms

### 6. Standard Operating Procedures (6 docs)
Step-by-step procedures for logistics operations. Numbered steps, responsible roles, quality checkpoints.

Example topics:
- Inbound goods receiving and quality inspection SOP
- Dangerous goods (ADR) loading and documentation SOP
- Cold chain verification procedure — from pickup to delivery
- Customer returns processing and restocking workflow
- Cross-docking procedure for time-critical shipments
- Driver pre-trip inspection and departure checklist

### 7. Compliance & Audit (4 docs)
Audit reports, certification records, regulatory compliance checklists, GDPR assessments.

Example topics:
- ISO 9001:2015 internal audit findings — 3 minor non-conformities
- ADR (dangerous goods transport) compliance self-assessment
- GDPR data processing impact assessment for fleet telematics
- Annual fire safety inspection report by external assessor

### 8. Vendor Agreements & Procurement (4 docs)
Contracts with suppliers, maintenance providers, insurance terms. Different from the existing customer transport contracts.

Example topics:
- Fuel supply agreement with PetroFlex GmbH (pricing, delivery schedule, quality specs)
- Fleet maintenance contract with AutoService24 (scope, response times, parts warranty)
- Warehouse cleaning and pest control service agreement
- Cyber insurance policy summary (coverage, exclusions, claims process)

**IMPORTANT for benchmark quality:**
These documents will be mixed with existing transport contracts (PharmaCorp, FreshFoods, AutoParts, ChemTrans). Queries like "penalty fees for late deliveries" should semantically match both the real contracts AND some of these noise documents (e.g., incident reports mentioning penalties, meeting minutes discussing SLA breaches, vendor agreements with penalty clauses). This creates a realistic retrieval challenge where a re-ranker must distinguish truly relevant results from topically adjacent noise.

Make each document genuinely unique — not a template with swapped variables. Real companies have documents written by different people at different times with different styles.

Output ONLY the JSON array, no commentary.
