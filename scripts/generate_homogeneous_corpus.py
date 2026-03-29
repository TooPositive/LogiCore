"""Generate production-quality HOMOGENEOUS corpus (all logistics contracts).

Polish logistics company (LogiCore Sp. z o.o.) context.
Creates 45 realistic transport/logistics contracts — each generated individually
for quality and length (4,000-8,000 chars per contract).

Usage:
    python scripts/generate_homogeneous_corpus.py
    python scripts/generate_homogeneous_corpus.py --retry-failed

Output: data/benchmark-corpus/homogeneous_docs.json
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

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "benchmark-corpus"
    / "homogeneous_docs.json"
)

SYSTEM_PROMPT = (
    "You generate realistic transport/logistics service agreements for a POLISH "
    "logistics company called LogiCore Sp. z o.o., headquartered in Warszawa with "
    "depots in Katowice, Gdansk, Wroclaw, and Poznan. Documents reference Polish "
    "law (Kodeks Cywilny, Prawo Przewozowe, Ustawa o transporcie drogowym), Polish "
    "regulatory bodies (UTK, GITD, UOKiK), and Polish/European cities and routes. "
    "Currency: EUR for international contracts, PLN for domestic. "
    "Use Polish terms naturally (Sp. z o.o., faktura, zlecenie transportowe, CMR, "
    "list przewozowy). Write as a Polish logistics company would — professional "
    "contract summaries mixing Polish legal terminology into English text. "
    "Output ONLY valid JSON."
)

# ---------------------------------------------------------------------------
# 45 individual contract specs — each generates one long contract
# ---------------------------------------------------------------------------
CONTRACT_SPECS: list[tuple[str, str, str]] = [
    # (doc_id, title_hint, prompt)

    # Batch 1: Classic logistics verticals (1-15)
    ("CTR-2025-001", "PharmaCorp Temperature-Controlled Distribution",
     """Write a detailed transport service agreement summary for pharmaceutical distribution.
5-7 pages. Include:
- Contract: CTR-2025-001 between LogiCore Sp. z o.o. (Carrier) and PharmaCorp Polska Sp. z o.o. (Client)
- Effective: 2025-01-01, Term: 3 years with automatic 1-year renewal
- Scope: temperature-controlled pharmaceutical logistics across Poland (Warszawa-Krakow-Katowice-Wroclaw network, 45 pharmacy chains)
- GDP (Good Distribution Practice) compliance per Prawo Farmaceutyczne and EU Guidelines 2013/C 343/01
- Temperature ranges: 2-8°C (vaccines, biologics), 15-25°C (standard pharma), -20°C (select biologics)
- SLA: on-time delivery >= 98.5%, temperature excursion rate < 0.1%
- Penalty structure: EUR 500/late shipment, EUR 2,000/temperature excursion + full batch replacement, EUR 10,000/GDP audit failure
- Fleet requirements: 8 dedicated reefer vehicles, real-time temperature monitoring (SensoGuard TM-400), dual-redundant cooling
- Annual value: EUR 1,200,000
- Insurance: cargo EUR 500,000/shipment, product liability EUR 5M aggregate
- Quarterly business reviews, monthly KPI reporting
- Detailed penalty escalation table, force majeure provisions, termination clauses
Write 5,000-8,000 characters."""),

    ("CTR-2025-002", "FreshFoods Refrigerated Transport",
     """Write a detailed transport agreement for fresh food distribution.
5-7 pages. Include:
- Contract: CTR-2025-002 between LogiCore Sp. z o.o. and FreshFoods S.A.
- 12 fixed routes across Mazowsze, Malopolska, Slask voivodeships, 180 retail locations (Biedronka, Lidl, Zabka)
- HACCP compliance mandatory, food safety per Ustawa o bezpieczenstwie zywnosci
- Temperature: 2-6°C fresh produce, -18°C frozen, dual-compartment vehicles
- Delivery windows: 05:00-07:00 morning, 14:00-16:00 afternoon
- Penalty: EUR 200/late store delivery, EUR 1,000/temperature breach, product replacement at carrier cost
- Annual value: EUR 650,000, peak season surcharge Nov-Dec +15%
- Returns handling included, reusable crate deposit system (EUR 5/crate)
- Driver requirements: food hygiene certificate (Ksiazeczka sanepid), clean uniform
- Vehicle cleaning schedule: daily sanitization, weekly deep clean, quarterly audit
Write 5,000-7,000 characters."""),

    ("CTR-2025-003", "AutoParts Express Non-Perishable Distribution",
     """Write a detailed transport agreement for auto parts distribution.
4-6 pages. Include:
- Contract: CTR-2025-003 between LogiCore and AutoParts Express Sp. z o.o.
- 8 routes across Slask voivodeship, 120 workshops and dealerships
- No temperature requirements, standard dry cargo
- Same-day delivery for orders before 10:00, next-day for remainder
- Reusable plastic crate deposit system (EUR 5/crate), packaging return logistics
- Dangerous goods EXCLUDED (batteries, oils shipped separately under ADR)
- Penalty: EUR 100/late delivery, EUR 500/damaged goods (carrier responsible if packaging intact at origin)
- Annual value: EUR 320,000, 2-year term
- Insurance: EUR 50,000/shipment
- KPIs: on-time 97%, damage rate <0.5%, order accuracy 99.5%
Write 4,000-6,000 characters."""),

    ("CTR-2025-004", "ChemTrans Hazardous Materials Transport",
     """Write a detailed ADR hazardous materials transport agreement.
6-8 pages. Include:
- Contract: CTR-2025-004 between LogiCore and ChemTrans S.A.
- ADR-certified transport per Ustawa o przewozie towarow niebezpiecznych
- Routes: Plock refinery to chemical plants in Tarnow, Police, Pulawy
- UN-approved packaging per ADR Chapter 6, DGSA oversight required
- Driver requirements: valid ADR certificate (zaswiadczenie ADR), annual refresher
- Vehicle requirements: ADR equipment kit, EXIII-rated vehicles for Class 3/8 goods
- Penalty: EUR 5,000/compliance violation, EUR 25,000/safety incident, immediate termination for willful violation
- Emergency response plan per ADR 1.8.3.1, 24/7 emergency hotline
- Annual value: EUR 2,100,000 (highest-value contract)
- Insurance: hazmat liability EUR 10M, environmental damage EUR 5M
- Monthly safety audits, quarterly DGSA reports
- Detailed incident reporting procedure (2-hour notification, 24-hour written report)
Write 6,000-8,000 characters."""),

    ("CTR-2025-005", "ElectroHub Consumer Electronics Distribution",
     """Write a detailed transport agreement for consumer electronics.
4-6 pages. Include:
- Contract: CTR-2025-005 between LogiCore and ElectroHub Polska Sp. z o.o.
- National distribution from central warehouse (Stryków near Łódź) to 85 retail stores
- High-value cargo: smartphones, laptops, TVs — average shipment value EUR 45,000
- Anti-theft requirements: GPS-tracked sealed trailers, tamper-evident seals, driver verification protocol
- Delivery windows: stores open 10:00, delivery 07:00-09:30 mandatory
- Penalty: EUR 300/late delivery, EUR 250/missed window, full replacement for theft/loss
- Annual value: EUR 480,000
- Insurance: EUR 200,000/shipment, all-risk including theft
- Seasonal peaks: Black Friday, Christmas (November-December volume +60%)
- Returns logistics: defective product pickup from stores, consolidation, return to service center
Write 4,000-6,000 characters."""),

    ("CTR-2025-006", "BudMat Construction Materials Transport",
     """Write a detailed transport agreement for construction materials.
4-6 pages. Include:
- Contract: CTR-2025-006 between LogiCore and BudMat S.A.
- Heavy cargo: cement, steel rebar, prefab concrete panels, roofing materials
- Routes: 6 manufacturing plants to construction sites across Mazowsze and Łódzkie
- Oversized load permits (zezwolenie na przejazd pojazdu nienormatywnego) for prefab panels
- Crane offloading coordination, site access restrictions (narrow roads, weight limits)
- Vehicle types: flatbed trailers, curtain-siders, crane-equipped trucks
- Penalty: EUR 150/late delivery (construction crew standby cost), EUR 2,000/site damage
- Annual value: EUR 550,000, seasonal (March-November peak, December-February -40%)
- Safety: construction site PPE required for drivers (hard hat, hi-vis, steel-toe boots)
- Weight verification: all loads weighed at origin, CMR weight must match within 2%
Write 4,000-6,000 characters."""),

    ("CTR-2025-007", "MedDevice Sterile Medical Equipment Transport",
     """Write a detailed transport agreement for medical device logistics.
5-7 pages. Include:
- Contract: CTR-2025-007 between LogiCore and MedDevice Europe Sp. z o.o.
- Sterile medical devices: surgical instruments, implants, diagnostic equipment
- Cleanroom packaging requirements, anti-vibration transport for sensitive equipment
- Temperature: 15-25°C controlled environment, humidity monitoring
- Traceability: full lot tracking, UDI (Unique Device Identification) scanning at every handover
- Delivery to 35 hospitals across Poland, including emergency deliveries (4-hour SLA)
- Regulatory: EU MDR 2017/745 compliance, Urząd Rejestracji Produktów Leczniczych oversight
- Penalty: EUR 1,000/late routine delivery, EUR 5,000/late emergency delivery, EUR 15,000/sterility breach
- Annual value: EUR 890,000
- Driver training: medical device handling certification, sterile protocol awareness
- Monthly compliance audits, annual regulatory inspection support
Write 5,000-7,000 characters."""),

    ("CTR-2025-008", "VinoPolska Wine and Spirits Distribution",
     """Write a transport agreement for wine and spirits distribution.
4-6 pages. Include:
- Contract: CTR-2025-008 between LogiCore and VinoPolska Sp. z o.o. (importer/distributor)
- Temperature-controlled: 12-16°C for wine, ambient for spirits
- Routes: bonded warehouse (Warszawa Okęcie) to 200+ HoReCa venues and retail chains
- Akcyza (excise duty) compliance: banderol verification, EMCS (System EMCS PL2) documentation
- Fragile cargo handling: wine case breakage rate target <0.3%
- Delivery scheduling: restaurants prefer 10:00-14:00 (before service), retail 06:00-08:00
- Penalty: EUR 150/late delivery, full replacement for breakage during transport
- Annual value: EUR 380,000, peak Nov-Dec (Christmas) and May-Jun (wedding season)
- Age verification: driver must verify recipient is authorized to receive alcohol
- Insurance: EUR 100,000/shipment, glass breakage cover included
Write 4,000-6,000 characters."""),

    ("CTR-2025-009", "AgroTrans Grain and Agricultural Transport",
     """Write a transport agreement for agricultural commodities.
4-6 pages. Include:
- Contract: CTR-2025-009 between LogiCore and AgroTrans Wielkopolska Sp. z o.o.
- Bulk grain transport: wheat, rapeseed, corn from farms to silos and processing plants
- Routes: Wielkopolska and Kujawy regions (Poland's grain belt)
- Vehicle types: tipper trailers (walking floor), bulk tankers for liquid feed
- Seasonal: harvest peak July-October (volume +200%), rest of year reduced
- Quality: clean trailers mandatory (no contamination), fumigation certificate if required
- Weight: all loads weighed at origin and destination, tolerance 0.5%
- Phytosanitary compliance per Państwowa Inspekcja Ochrony Roślin i Nasiennictwa
- Penalty: EUR 100/late delivery during harvest (time-critical), EUR 5,000/contamination
- Annual value: EUR 290,000 (variable based on harvest volume)
- Payment: 30 days from CMR signature, seasonal prepayment option for harvest peak
Write 4,000-6,000 characters."""),

    ("CTR-2025-010", "MuseumTrans Art and Exhibition Logistics",
     """Write a transport agreement for museum/art logistics.
5-7 pages. Include:
- Contract: CTR-2025-010 between LogiCore and Muzeum Narodowe w Warszawie (via MuseumTrans Sp. z o.o.)
- White-glove handling: fine art, sculptures, historical artifacts
- Climate-controlled: 18-22°C, 45-55% relative humidity, vibration-dampened vehicles
- Custom crating: museum-standard wooden crates with foam inlay, condition reports at pickup and delivery
- Security: GPS tracking, sealed compartment, escort for items valued >EUR 100,000
- Insurance: nail-to-nail coverage, declared value per item (some items EUR 1M+)
- Routes: inter-museum loans across Poland and EU (Berlin, Prague, Vienna, Budapest)
- Couriers: museum courier accompanies high-value shipments (LogiCore provides seat in cab)
- Penalty: EUR 10,000/damage to artwork, full restoration cost liability (uncapped for negligence)
- Annual value: EUR 180,000 (low volume, extremely high value per shipment)
- Customs: ATA Carnet handling for temporary exhibition imports/exports
Write 5,000-7,000 characters."""),

    ("CTR-2025-011", "EventPro Concert and Exhibition Logistics",
     """Write a transport agreement for event/exhibition logistics.
4-6 pages. Include:
- Contract: CTR-2025-011 between LogiCore and EventPro Polska Sp. z o.o.
- Concert equipment, trade show booths, staging, lighting rigs
- Time-critical: setup deadlines are absolute (venue access windows, show times)
- Routes: major venues across Poland (Tauron Arena Kraków, Atlas Arena Łódź, PGE Narodowy Warszawa)
- Vehicle types: 40-foot trailers, tail-lift trucks, low-loader for heavy staging
- Crew: driver + 1 helper for loading/unloading (LogiCore provides)
- Weekend and night work standard (events typically Saturday/Sunday)
- Penalty: EUR 2,000/hour late (crew standby cost), EUR 5,000 if show delayed due to logistics
- Annual value: EUR 420,000, peaks in summer festival season
- Insurance: equipment value EUR 300,000/shipment
- Storage: LogiCore provides 200m² heated storage for inter-event equipment
Write 4,000-6,000 characters."""),

    ("CTR-2025-012", "E-Fulfillment Last-Mile Delivery",
     """Write a transport agreement for e-commerce fulfillment.
5-7 pages. Include:
- Contract: CTR-2025-012 between LogiCore and ShopNow.pl Sp. z o.o. (e-commerce platform)
- Last-mile delivery: parcels from fulfillment center (Piotrków Trybunalski) to end consumers
- Coverage: all 16 voivodeships, next-day delivery target for 90% of Poland
- Volume: 5,000-8,000 parcels/day standard, 15,000+/day during peaks (Black Friday, Christmas)
- Delivery options: standard (next-day), express (same-day major cities), scheduled (2-hour window)
- Penalty: EUR 3/failed first delivery attempt, EUR 10/parcel if >2 days late, EUR 1,000/lost parcel
- Returns handling: customer returns picked up, consolidated, returned to fulfillment center within 48h
- POD (Proof of Delivery): photo + signature on mobile app, real-time status updates to ShopNow API
- Annual value: EUR 1,800,000 (volume-based, per-parcel pricing EUR 4.50 standard, EUR 8.50 express)
- Peak season: temporary driver hiring, LogiCore guarantees capacity via subcontractor network
- Cash on delivery (pobranie): handling included, daily settlement
Write 5,000-7,000 characters."""),

    ("CTR-2025-013", "WasteManagement Industrial Waste Transport",
     """Write a transport agreement for industrial waste management.
4-6 pages. Include:
- Contract: CTR-2025-013 between LogiCore and EkoRecykling Sp. z o.o.
- Industrial waste: packaging waste, scrap metal, used oils, electronic waste (WEEE)
- Regulatory: Ustawa o odpadach, BDO (Baza danych o produktach i opakowaniach) registration required
- Routes: factory collection points across Silesia to recycling/processing facilities
- Vehicle types: skip containers, roll-on/roll-off, ADR vehicles for hazardous waste
- Waste transfer notes (Karta przekazania odpadu) for every shipment
- Penalty: EUR 500/incomplete documentation (regulatory risk), EUR 2,000/environmental incident
- Annual value: EUR 340,000
- Weighing: all loads weighed at collection and delivery, KPO (karta przekazania odpadu) reconciliation monthly
- Scheduling: regular collections (weekly/fortnightly per site), on-call for spill response
Write 4,000-6,000 characters."""),

    ("CTR-2025-014", "DefenseLogistics Military Equipment Transport",
     """Write a transport agreement for defense/military logistics.
5-7 pages. Include:
- Contract: CTR-2025-014 between LogiCore and Polska Grupa Zbrojeniowa S.A. (via MON framework)
- CONFIDENTIAL marking on all documentation
- Scope: non-classified military equipment, spare parts, uniforms, provisions
- Security clearance: drivers must hold Poświadczenie Bezpieczeństwa (security clearance) — minimum POUFNE level
- Routes: military bases across Poland (exact locations classified, grid references used)
- Escort requirements: military escort for convoys >3 vehicles, police notification for oversized loads
- Vehicle requirements: GPS tracking disabled on request, radio silence capable, military-spec tie-down points
- No subcontracting permitted — all shipments on LogiCore-owned vehicles with cleared drivers
- Penalty: EUR 10,000/security breach, immediate contract termination for unauthorized personnel access
- Annual value: EUR 750,000 (framework agreement, actual orders via zlecenie transportowe)
- Insurance: government self-insured, LogiCore carries EUR 2M general liability
- Inspection: random vehicle inspections by Żandarmeria Wojskowa at origin and destination
Write 5,000-7,000 characters."""),

    ("CTR-2025-015", "AeroParts Aerospace Component Transport",
     """Write a transport agreement for aerospace components.
5-7 pages. Include:
- Contract: CTR-2025-015 between LogiCore and PZL Mielec (Lockheed Martin subsidiary)
- Aerospace components: fuselage sections, avionics, landing gear assemblies
- Cleanroom packaging: ISO Class 8 equivalent during transport, anti-static wrapping
- Vibration monitoring: accelerometers on every shipment, max 0.5g threshold
- Oversized loads: wing sections require route surveys, permits, pilot vehicles
- Routes: PZL Mielec (Podkarpackie) to Kraków airport, Rzeszów rail head, and EU destinations
- Temperature: some avionics require 15-25°C
- Penalty: EUR 5,000/vibration exceedance, EUR 50,000/component damage (aerospace parts extremely expensive)
- Annual value: EUR 620,000
- Customs: ITAR compliance for US-origin components, EUC (End User Certificate) verification
- Quality: AS9100 certified logistics provider required (LogiCore holds certification)
- Each shipment: pre-transport inspection, photo documentation, chain of custody log
Write 5,000-7,000 characters."""),

    # Batch 2: Creative/niche verticals (16-30)
    ("CTR-2025-016", "LuxuryBrands High-Value Fashion Logistics",
     """Write a transport agreement for luxury fashion logistics.
4-6 pages. Include:
- Contract: CTR-2025-016 between LogiCore and LuxuryBrands Distribution Polska Sp. z o.o.
- High-value: designer clothing, watches, jewelry — average shipment value EUR 120,000
- Garment-on-hanger (GOH) transport: specialized vehicles with hanging rails
- Security: sealed compartment, GPS tracking, armed escort for jewelry shipments
- Chain of custody: item-level tracking with barcode/RFID, reconciliation at every handover
- Routes: bonded warehouse (Warszawa) to 25 boutiques across Poland + seasonal pop-up stores
- Delivery: white-glove, suited driver, branded delivery van for boutique deliveries
- Penalty: EUR 500/late delivery, full retail value for lost/damaged items
- Annual value: EUR 350,000
- Seasonal collections: 4 major deliveries/year (Spring/Summer, Autumn/Winter, Cruise, Pre-Fall)
- Returns: unsold stock collection at end of season, return to regional hub
Write 4,000-6,000 characters."""),

    ("CTR-2025-017", "BioLab Clinical Sample Transport",
     """Write a transport agreement for laboratory/biospecimen transport.
5-7 pages. Include:
- Contract: CTR-2025-017 between LogiCore and BioLab Diagnostyka Sp. z o.o.
- Clinical samples: blood, tissue, biological specimens — UN 3373 Category B
- Time-critical: samples must reach lab within 4 hours of collection for viability
- Temperature: ambient (15-25°C) and cold (2-8°C) in validated shipping containers
- Routes: 120 collection points (hospitals, clinics) across Mazowsze to central lab in Warszawa
- Triple packaging per ADR P650, biohazard marking, absorbent material
- Driver training: UN 3373 handling, spill response, infection control basics
- Penalty: EUR 200/late pickup, EUR 1,000/lost sample (irreplaceable), EUR 5,000/packaging violation
- Annual value: EUR 520,000
- Volume: 800-1,200 pickups/day, 6 days/week
- IT integration: real-time pickup confirmation via LogiCore API → BioLab LIMS
Write 5,000-7,000 characters."""),

    ("CTR-2025-018", "WindPower Oversized Renewable Energy Transport",
     """Write a transport agreement for wind turbine component transport.
5-7 pages. Include:
- Contract: CTR-2025-018 between LogiCore and WindPower Polska Sp. z o.o.
- Oversized cargo: wind turbine blades (75m), nacelles (90 tonnes), tower sections
- Route surveys required: bridge clearances, turning radii, overhead line heights
- Permits: zezwolenie na przejazd pojazdu nienormatywnego (Kategoria VII for blades)
- Escort: 2 pilot vehicles mandatory, police escort in urban areas, night-only transport in some sections
- Specialized trailers: extendable blade trailers (Goldhofer, Scheuerle), self-propelled modular transporters
- Routes: port of Gdynia/Świnoujście to wind farm sites across Pomorze, Warmia-Mazury, Zachodniopomorskie
- Penalty: EUR 5,000/day delay (crane crew standby), EUR 100,000/blade damage
- Annual value: EUR 1,500,000 (project-based, 3 wind farm installations per year)
- Environmental: route restoration after heavy transport (road damage repair included in price)
- Weather restrictions: no transport in winds >60 km/h (blade transport), no transport in ice conditions
Write 5,000-7,000 characters."""),

    ("CTR-2025-019", "HospitalSupply Healthcare Consumables",
     """Write a transport agreement for hospital consumable supplies.
4-6 pages. Include:
- Contract: CTR-2025-019 between LogiCore and MedSupply Polska Sp. z o.o.
- Hospital consumables: gloves, syringes, bandages, PPE, cleaning supplies, office supplies
- Sterile products: must remain in sealed original packaging, no repackaging permitted
- Routes: central warehouse (Łódź) to 45 hospitals and clinics across central Poland
- Emergency escalation: 4-hour emergency delivery for critical items (surgical supplies, blood bags)
- Delivery: to hospital loading dock, NOT to ward (hospital porters handle internal distribution)
- Penalty: EUR 200/late routine delivery, EUR 2,000/late emergency, product replacement for damage
- Annual value: EUR 680,000
- Lot tracking: every delivery reconciled with purchase order, lot numbers recorded in hospital system
- Regulatory: products registered with Urząd Rejestracji Produktów Leczniczych where applicable
- COVID/pandemic clause: volume surge provision (+300% capacity guarantee), PPE for drivers
Write 4,000-6,000 characters."""),

    ("CTR-2025-020", "DataCenter IT Equipment Logistics",
     """Write a transport agreement for data center equipment.
5-7 pages. Include:
- Contract: CTR-2025-020 between LogiCore and CloudInfra Polska Sp. z o.o.
- Server racks, UPS systems, networking equipment, fiber optic cable
- Anti-static requirements: ESD-safe packaging, grounding straps during handling
- Climate control: 15-25°C, humidity <60%, no condensation
- High-value: single rack delivery can exceed EUR 200,000
- Security: sealed trailer, GPS tracking, driver NDA, no stops between origin and destination
- Routes: import (Frankfurt/Amsterdam/Warsaw airport) to data centers in Warszawa, Kraków, Wrocław
- Time-critical: data center commissioning deadlines, rack delivery must be ±2 hours of scheduled time
- Penalty: EUR 1,000/hour late (data center crew standby), full replacement for ESD damage
- Annual value: EUR 440,000
- Crane/hydraulic tail-lift required: racks weigh 500-1200kg
- White-glove: driver + 2 helpers for rack positioning at destination
Write 5,000-7,000 characters."""),

    ("CTR-2025-021", "BrewCo Beverage Distribution",
     """Write a transport agreement for brewery/beverage distribution.
4-6 pages. Include:
- Contract: CTR-2025-021 between LogiCore and Kompania Piwowarska S.A.
- Beer, soft drinks, water — heavy, high-volume
- Returnable container system: keg deposit EUR 30, crate deposit EUR 5, bottle deposit PLN 0.50
- Routes: brewery (Poznań) to 500+ retail and HoReCa points across Wielkopolska and Mazowsze
- Seasonal peaks: summer (+40% volume), major sporting events, Christmas
- Vehicle types: curtain-siders with tail-lift, specialized keg delivery trucks
- Delivery windows: retail 06:00-10:00, restaurants 10:00-14:00
- Penalty: EUR 100/late delivery, EUR 50/missed returns pickup
- Annual value: EUR 920,000
- Akcyza compliance: driver carries copies of all required excise documentation
- Empties collection: every delivery vehicle collects empty kegs/crates on return leg
- Fleet branding: 5 vehicles wrapped in Kompania Piwowarska livery (included in contract)
Write 4,000-6,000 characters."""),

    ("CTR-2025-022", "PetFood Animal Feed Distribution",
     """Write a transport agreement for pet food and animal feed.
4-5 pages. Include:
- Contract: CTR-2025-022 between LogiCore and ZooKarma Polska Sp. z o.o.
- Dry pet food, wet pet food (canned), animal feed supplements
- Allergen separation: some products allergen-free, dedicated trailer zones required
- Organic certification: Bio/Eko products transported separately, audit trail maintained
- Routes: factory (Grodzisk Mazowiecki) to pet store chains (120 locations) and veterinary clinics
- Bulk bags (25kg) and retail units (0.5-15kg) — mixed pallets common
- Temperature: ambient, but avoid >30°C (product quality degradation)
- Penalty: EUR 100/late delivery, EUR 500/contamination or allergen cross-contact
- Annual value: EUR 260,000
- Returns: damaged packaging returns weekly, credit note process within 5 business days
Write 4,000-5,000 characters."""),

    ("CTR-2025-023", "PrintMedia Newspaper and Magazine Distribution",
     """Write a transport agreement for print media distribution.
4-5 pages. Include:
- Contract: CTR-2025-023 between LogiCore and Agora S.A. (Gazeta Wyborcza publisher)
- Daily newspapers: time-critical, must arrive at kiosks by 05:00 (before morning commuters)
- Magazines: weekly/monthly, less time-critical but still scheduled
- Routes: printing plant (Piaseczno) to 2,500 RUCH/Kolporter kiosks across Mazowsze
- Night operations: loading from 22:00, delivery runs 01:00-05:00, 7 days/week
- Weight: newspapers are HEAVY (single pallet of Gazeta Wyborcza = 800kg)
- Returns: unsold copies collected next delivery run, publisher credits LogiCore for return transport
- Penalty: EUR 50/late delivery per route (reader complaints), EUR 500/missed route (kiosks empty)
- Annual value: EUR 310,000 (declining — print circulation falling 5-8% per year)
- Flexibility: route optimization quarterly as kiosk network changes
- Sustainability: recycled paper transport on return legs to printing plant
Write 4,000-5,000 characters."""),

    ("CTR-2025-024", "FrozenSeafood Deep-Freeze Fish Distribution",
     """Write a transport agreement for frozen seafood logistics.
5-7 pages. Include:
- Contract: CTR-2025-024 between LogiCore and NordFish Polska Sp. z o.o.
- Deep-freeze transport: -25°C for raw frozen fish, -18°C for processed products
- HACCP compliance, MSC chain of custody for sustainable seafood
- Routes: Gdynia/Gdańsk port to cold storage facilities and processing plants across Poland
- Traceability: from vessel to plate — each pallet tracked with catch date, vessel ID, species
- Temperature monitoring: continuous, with 15-minute logging interval, alarm at -15°C
- Defrost zero tolerance: any temperature above -15°C = full batch rejection
- Penalty: EUR 1,500/temperature breach, full product replacement cost, EUR 5,000/traceability gap
- Annual value: EUR 560,000
- Vehicle standards: HACCP-certified reefer trailers, ATP certificate required
- Seasonal: peak in Lent (February-March) and Christmas (November-December)
- Import documentation: health certificate, SVD (Świadectwo Weterynaryjne), customs clearance
Write 5,000-7,000 characters."""),

    ("CTR-2025-025", "FurniturePro Home Delivery",
     """Write a transport agreement for furniture home delivery.
4-6 pages. Include:
- Contract: CTR-2025-025 between LogiCore and FurniturePro Polska Sp. z o.o. (online furniture retailer)
- White-glove home delivery: 2-person crew, carry to room of choice, unpack, assembly if purchased
- Delivery windows: 4-hour customer-selected windows, SMS notification 30 min before arrival
- Routes: Warszawa distribution center to customer homes across Mazowsze (urban and suburban)
- Damage: extremely common issue in furniture delivery — detailed condition check at warehouse, photos before and after
- Penalty: EUR 100/missed window, EUR 200/failed delivery (customer not home), full item cost for damage
- Annual value: EUR 390,000
- Returns: customer has 14-day return right (Ustawa o prawach konsumenta), LogiCore handles pickup
- Vehicle types: box trucks with tail-lift, furniture blankets, floor protection mats
- Assembly service: optional, EUR 25/item, driver team trained on top 50 SKUs
- Customer satisfaction: NPS survey sent after every delivery, target score >60
Write 4,000-6,000 characters."""),

    # Batch 3: Complex/specialized (26-45)
    ("CTR-2025-026", "HumanitarianAid Emergency Relief Logistics",
     """Write a transport agreement for humanitarian aid logistics.
5-7 pages. Include:
- Contract: CTR-2025-026 between LogiCore and Polski Czerwony Krzyż (Polish Red Cross)
- Emergency response: natural disasters, refugee crises, pandemic response
- Standby capacity: 10 vehicles on 24-hour notice, 20 vehicles within 72 hours
- Goods: food supplies, water, blankets, medical kits, tents, hygiene packages
- Routes: PCK warehouse (Warszawa Annopol) to disaster sites across Poland and neighboring countries
- Cross-border: simplified customs per humanitarian exemptions, coordination with UNHCR for international
- Cost model: framework agreement with pre-agreed rates, actual cost per activation
- No penalty clause (humanitarian exception), but SLA for response times (24h domestic, 72h cross-border)
- Annual value: EUR 120,000 framework + actual activations (EUR 200-500K in major disaster year)
- Volunteer coordination: LogiCore drivers may be augmented by PCK volunteers (supervision required)
- Reporting: UN OCHA-format logistics reports for international activations
Write 5,000-7,000 characters."""),

    ("CTR-2025-027", "AutoJIT Automotive Just-In-Time Delivery",
     """Write a transport agreement for automotive JIT delivery.
5-7 pages. Include:
- Contract: CTR-2025-027 between LogiCore and FCA Powertrain Polska (Stellantis) in Bielsko-Biała
- Just-in-time: components must arrive within ±15 minute window at assembly line dock
- Components: engine parts, transmission assemblies, wiring harnesses from 8 Tier 1 suppliers
- Milk-run logistics: single vehicle collects from multiple suppliers on optimized route
- Line-stop cost: EUR 15,000/minute if assembly line stops due to missing component
- Penalty: EUR 5,000/late delivery (before line stop), line-stop costs fully charged to carrier
- Annual value: EUR 1,400,000
- Volume: 12-16 deliveries/day, 6 days/week, plant operates 3 shifts
- EDI integration: ASN (Advanced Shipping Notice) transmitted via LogiCore system → Stellantis MES
- Sequencing: some deliveries must be in exact assembly sequence (color-coded labels)
- Contingency: backup vehicle permanently stationed 15 min from plant, instant dispatch on call
Write 5,000-7,000 characters."""),

    ("CTR-2025-028", "TextileFashion Seasonal Collection Distribution",
     """Write a transport agreement for textile/fashion logistics.
4-6 pages. Include:
- Contract: CTR-2025-028 between LogiCore and Modna Polska S.A. (Polish fashion brand)
- Garment-on-hanger (GOH) and flat-packed clothing
- 4 seasonal collections per year + flash collections (2-week turnaround)
- Routes: distribution center (Łódź) to 65 own-brand stores across Poland
- Visual merchandising: deliveries organized by store planogram, pre-sorted by rack position
- Returns: end-of-season unsold stock collection, return to DC for markdown/outlet
- Penalty: EUR 300/late collection launch delivery (store opens without new stock), EUR 100/late restock
- Annual value: EUR 280,000
- Peak: pre-Christmas (November) and pre-summer (April-May)
- Packaging: reusable garment bags, branded hanger covers, folding plastic crates for accessories
- Sustainability: carbon-neutral delivery target by 2027 (LogiCore to provide CO2 reports per shipment)
Write 4,000-6,000 characters."""),

    ("CTR-2025-029", "RetailChain Multi-Store Replenishment",
     """Write a transport agreement for retail chain store replenishment.
5-7 pages. Include:
- Contract: CTR-2025-029 between LogiCore and Drogeria Natura Sp. z o.o. (drugstore chain)
- Multi-store replenishment: 180 stores across northern Poland (Pomorze, Warmia-Mazury, Podlaskie)
- Mixed cargo: cosmetics, household chemicals, health products, seasonal items
- Multi-temperature: ambient + 15-25°C for cosmetics with temperature sensitivity
- Delivery frequency: 2x/week per store, scheduled day and window
- Cross-docking: some supplier pallets flow through LogiCore DC without putaway
- Penalty: EUR 150/late delivery, EUR 300/short delivery (items missing from manifest), EUR 100/damages
- Annual value: EUR 720,000
- Promotional peaks: 3 major promotions/year (volume +50%), advance notification 4 weeks
- Returns: damaged goods, expired products, seasonal remnants — monthly collection cycle
- VMI (Vendor Managed Inventory): LogiCore monitors store stock levels via EDI, triggers replenishment
Write 5,000-7,000 characters."""),

    ("CTR-2025-030", "ChemRaw Chemical Raw Materials",
     """Write a transport agreement for chemical raw materials.
5-7 pages. Include:
- Contract: CTR-2025-030 between LogiCore and CIECH S.A. (Polish chemical company)
- Bulk chemicals: soda ash, salt, calcium chloride — UN classified materials
- REACH compliance per Rozporządzenie REACH, SDS (Safety Data Sheets) with every shipment
- ADR Class 8 (corrosive) and Class 9 (miscellaneous) materials
- Routes: CIECH Soda Polska (Inowrocław) to industrial customers across Poland and Czech Republic
- Tank containers and IBCs (Intermediate Bulk Containers) — cleaning between loads mandatory
- DGSA oversight, emergency response per ADR 1.8.3.1
- Penalty: EUR 3,000/ADR violation, EUR 10,000/environmental incident, EUR 500/late delivery
- Annual value: EUR 980,000
- Cross-border: DE, CZ, SK — ECMT permits, CMR international, customs declaration
- Vehicle cleaning: certificate of cleanliness after each load, dedicated fleet for food-grade sodium bicarb
Write 5,000-7,000 characters."""),

    ("CTR-2025-031", "DiplomaticCourier Embassy Supplies",
     """Write a transport agreement for diplomatic/embassy logistics.
4-5 pages. Include:
- Contract: CTR-2025-031 between LogiCore and MSZ RP (Ministry of Foreign Affairs) via framework
- Embassy supplies: office furniture, IT equipment, diplomatic correspondence (non-pouch)
- Security: drivers with Poświadczenie Bezpieczeństwa, vehicle GPS tracking
- Routes: MSZ warehouse (Warszawa) to Polish embassies in Berlin, Prague, Vienna, Bratislava, Vilnius
- Diplomatic protocols: customs-exempt documentation (Vienna Convention), embassy access procedures
- Confidentiality: driver NDA, no subcontracting, no co-loading with other customers' cargo
- Response time: standard 5 business days, urgent 48 hours
- Penalty: EUR 1,000/security breach, EUR 500/late delivery
- Annual value: EUR 160,000 (framework, actual based on orders)
- Insurance: government requirement EUR 1M per shipment
- IT equipment: anti-tamper seals, chain of custody documentation, destination IT officer sign-off
Write 4,000-5,000 characters."""),

    ("CTR-2025-032", "RecyclingGlass Glass Container Reverse Logistics",
     """Write a transport agreement for glass recycling reverse logistics.
4-5 pages. Include:
- Contract: CTR-2025-032 between LogiCore and Vetropack Polska S.A.
- Reverse logistics: collecting empty glass bottles/jars from retail chains and HoReCa
- Routes: collection points across Mazowsze and Śląsk to Vetropack factory (Gostyń)
- Vehicle types: roll-off containers, walking floor trailers for cullet (broken glass)
- Weight: glass is heavy — strict axle weight compliance per Prawo o ruchu drogowym
- Environmental: waste transport per Ustawa o odpadach, BDO registration
- Volume: 800-1,200 tonnes/month, seasonal variation (summer beer consumption higher)
- Penalty: EUR 200/late collection (storage space at retailers is limited), EUR 100/contaminated load
- Annual value: EUR 230,000
- Quality: color-sorted glass (clear, green, brown) — contamination means rejection at factory gate
- Scheduling: regular weekly collections from 45 collection points, on-demand for overflow
Write 4,000-5,000 characters."""),

    ("CTR-2025-033", "LivestockFeed Animal Feed Bulk Transport",
     """Write a transport agreement for livestock feed logistics.
4-5 pages. Include:
- Contract: CTR-2025-033 between LogiCore and PasFeed Polska Sp. z o.o.
- Bulk animal feed: pellets, meal, mineral supplements
- Vehicle types: pneumatic bulk tankers (blow-off), tipper trailers
- Cross-contamination prevention: medicated vs non-medicated feed NEVER in same vehicle without cleaning
- GMP+ certified transport per GMP+ International B4 standard
- Routes: feed mills (Kutno, Bydgoszcz) to farms across Mazowsze, Podlasie, Warmia-Mazury
- Seasonal: peak autumn (silage supplement season), steady year-round for dairy/poultry
- Penalty: EUR 1,000/cross-contamination (recall risk), EUR 100/late delivery (animals need feeding on schedule)
- Annual value: EUR 310,000
- Cleaning certificates: after every load, before loading different product type
- Driver knowledge: farm biosecurity protocols (wheel wash, restricted zones, boot covers)
Write 4,000-5,000 characters."""),

    ("CTR-2025-034", "SteelDistribution Steel Products Transport",
     """Write a transport agreement for steel distribution.
4-6 pages. Include:
- Contract: CTR-2025-034 between LogiCore and ArcelorMittal Poland S.A.
- Steel products: coils, plates, beams, rebar, tubes — extremely heavy
- Weight-critical: single coil can weigh 25 tonnes, strict axle weight distribution
- Routes: mills (Dąbrowa Górnicza, Kraków) to construction sites, fabricators, service centers
- Vehicle types: coil wells (saddle trailers), flatbeds with stanchions, extendable trailers for long beams
- Lashing: per EN 12195-1 load securing standard, driver responsible for securing
- Penalty: EUR 200/late delivery, EUR 5,000/load shift incident (safety critical)
- Annual value: EUR 1,100,000
- Seasonal: construction peak March-November, winter reduced but still steady to fabricators
- Crane offload: most deliveries require crane at destination, LogiCore coordinates with site
- Quality: rust protection — tarpaulin cover mandatory for coils and plates during rain
Write 4,000-6,000 characters."""),

    ("CTR-2025-035", "CosmeticsDistro Beauty Product Distribution",
     """Write a transport agreement for cosmetics distribution.
4-5 pages. Include:
- Contract: CTR-2025-035 between LogiCore and Inglot Sp. z o.o. (Polish cosmetics brand)
- High-value, temperature-sensitive: some products degraded by >30°C
- Routes: factory (Przemyśl) to 80 own-brand stores and department store counters across Poland and EU
- Fragile: glass bottles, mirrors, compacts — breakage rate target <0.2%
- Visual merchandising: pre-merchandised display units delivered ready for shelf placement
- Penalty: EUR 200/late delivery, full retail value for damaged premium products
- Annual value: EUR 270,000
- Seasonal peaks: Christmas gift sets (November), Valentine's Day, Mother's Day
- Returns: damaged stock, expired products, end-of-line — quarterly collection and destruction
- Cross-border: shipments to EU stores (DE, UK via NI, FR) — customs post-Brexit complexity for UK
Write 4,000-5,000 characters."""),

    ("CTR-2025-036", "TireLogistics Seasonal Tire Distribution",
     """Write a transport agreement for tire logistics.
4-5 pages. Include:
- Contract: CTR-2025-036 between LogiCore and Michelin Polska Sp. z o.o.
- Seasonal tire distribution: summer tires (March-May), winter tires (September-November)
- Routes: Michelin factory (Olsztyn) + import warehouse to 300 tire service centers across Poland
- Extreme seasonality: 70% of annual volume in 2 peak months (April and October)
- Storage: LogiCore provides 2,000m² overflow storage during pre-season build-up
- Stacking: max 4 tires high on pallet, no heavy cargo on top — deformation risk
- Penalty: EUR 100/late delivery during peak (workshop has customers waiting), EUR 50 off-peak
- Annual value: EUR 410,000
- Returns: used tire collection for recycling (odzysk opon per Ustawa o odpadach), reverse logistics
- Fleet: dedicated 10 vehicles during peak, standard 3 vehicles off-peak
Write 4,000-5,000 characters."""),

    ("CTR-2025-037", "BookDistribution Publishing Logistics",
     """Write a transport agreement for book distribution.
4-5 pages. Include:
- Contract: CTR-2025-037 between LogiCore and Wydawnictwo Znak Sp. z o.o.
- Books: heavy, low-margin, time-sensitive for new releases
- Routes: printing houses (Kraków, Białystok) to Znak's central warehouse and direct to bookstore chains (Empik, Świat Książki)
- New release logistics: coordinated national launch, all stores stocked on same day (strict embargo dates)
- Weight: full pallet of hardcovers = 900kg, vehicle payload critical
- Penalty: EUR 500/embargo breach (early delivery — books visible before launch), EUR 100/late delivery
- Annual value: EUR 190,000
- Returns: unsold books return to publisher quarterly (right of return standard in publishing)
- Seasonal: Christmas (Oct-Dec +60%), school year start (Aug-Sep textbooks), literary awards season
- E-commerce: Znak's online store orders — parcel-level fulfillment via LogiCore's parcel network
Write 4,000-5,000 characters."""),

    ("CTR-2025-038", "FlowerFresh Cut Flower Logistics",
     """Write a transport agreement for cut flower logistics.
4-6 pages. Include:
- Contract: CTR-2025-038 between LogiCore and FloraHolland Polska Sp. z o.o. (Dutch flower auction subsidiary)
- Extremely perishable: flowers lose value by the hour, maximum 48 hours farm-to-vase
- Temperature: 2-5°C strict, ethylene-free environment (ethylene accelerates wilting)
- Routes: Warszawa Okęcie airport (import from Netherlands/Kenya/Colombia) to flower wholesalers across Poland
- Time-critical: auction results at 05:00 CET, flowers loaded by 08:00, delivered by 16:00 same day
- Vehicle requirements: ethylene filter equipped reefer, adjustable humidity control
- Penalty: EUR 500/temperature breach (full batch = compost), EUR 200/hour late after 12:00
- Annual value: EUR 340,000
- Extreme peaks: Valentine's Day (volume 5x normal), Mother's Day (3x), All Saints' Day (4x — chrysanthemums)
- Water supply: vehicles equipped with water buckets for bucket-shipped roses
- Customs: phytosanitary certificate verification at airport, ISPM-15 pallet compliance
Write 4,000-6,000 characters."""),

    ("CTR-2025-039", "PaintCoatings Industrial Paint Distribution",
     """Write a transport agreement for paint and coatings distribution.
4-5 pages. Include:
- Contract: CTR-2025-039 between LogiCore and Śnieżka S.A. (Polish paint manufacturer)
- Paint products: water-based (non-hazardous), solvent-based (ADR Class 3 flammable)
- Dual ADR/non-ADR logistics: segregation on vehicle, mixed loads per ADR exemption thresholds
- Temperature: must not freeze (<5°C degrades water-based paint), max 30°C for all products
- Routes: factories (Lubzina, Brzeźnica) to DIY chains (Castorama, Leroy Merlin, OBI) and paint distributors
- Heavy: 10L paint buckets on pallets — weight limits critical
- Seasonal: spring (March-June) = 55% of annual volume (renovation season)
- Penalty: EUR 100/late delivery, EUR 500/frozen paint (batch rejection)
- Annual value: EUR 450,000
- Returns: defective batches, expired shelf life — return to factory for recycling/disposal
- Color matching: damaged cans in transit are problematic — custom-tinted paint is irreplaceable
Write 4,000-5,000 characters."""),

    ("CTR-2025-040", "EnergyParts Solar Panel Distribution",
     """Write a transport agreement for solar panel logistics.
4-6 pages. Include:
- Contract: CTR-2025-040 between LogiCore and SolarTech Polska Sp. z o.o.
- Solar panels: fragile glass surfaces, heavy (25kg each), awkward dimensions (2m x 1m)
- Stacking: manufacturer-specified max stack height, edge-standing transport only
- Inverters and mounting systems: separate pallets, electronics require anti-static handling
- Routes: import warehouse (Łódź) to installation companies across Poland
- Seasonal: peak March-September (installation season), government subsidy deadlines cause spikes
- Penalty: EUR 200/late delivery, full panel cost for breakage (micro-cracks render panels useless)
- Annual value: EUR 380,000 (growing +25% annually)
- Installation coordination: delivery timed to installation crew availability on-site
- Insurance: full replacement value per panel, glass breakage specifically covered
- Returns: defective panels return to manufacturer under warranty (LogiCore handles reverse)
Write 4,000-6,000 characters."""),

    ("CTR-2025-041", "PoolChemicals Swimming Pool Chemical Distribution",
     """Write a transport agreement for pool chemical distribution.
3-5 pages. Include:
- Contract: CTR-2025-041 between LogiCore and AquaChem Sp. z o.o.
- Pool chemicals: chlorine (UN 2880 Class 5.1 oxidizer), pH regulators, algaecides
- ADR transport required for chlorine products, non-ADR for other pool chemicals
- Seasonal: extremely concentrated March-June (pool opening season), minimal November-February
- Routes: factory (Tarnów) to pool supply distributors, municipal swimming pools, hotels
- Storage incompatibility: chlorine products NEVER stored/transported with acid-based pH reducers
- Penalty: EUR 2,000/ADR violation, EUR 500/incompatible co-loading, EUR 100/late delivery
- Annual value: EUR 180,000
- Emergency response: chlorine spill kit mandatory on vehicle, driver trained in oxidizer hazards
- Small orders: many deliveries are 2-5 pallets to small distributors — groupage service
Write 3,500-5,000 characters."""),

    ("CTR-2025-042", "GasIndustrial Industrial Gas Cylinder Logistics",
     """Write a transport agreement for industrial gas cylinder logistics.
5-7 pages. Include:
- Contract: CTR-2025-042 between LogiCore and Linde Gaz Polska Sp. z o.o.
- Industrial gas cylinders: oxygen, nitrogen, argon, CO2, acetylene, specialty gas mixtures
- ADR Class 2 (gases): compressed, liquefied, dissolved
- Cylinder management: full/empty exchange system, cylinder tracking by serial number
- Routes: filling plants (Kraków, Wrocław) to industrial users (welding shops, hospitals, food processors)
- Safety-critical: acetylene + oxygen MUST be segregated on vehicle per ADR 7.5.2
- Vehicle requirements: open-sided or ventilated body, cylinder securing per ADR 7.5.7
- Penalty: EUR 3,000/segregation violation, EUR 500/lost cylinder (expensive assets), EUR 100/late delivery
- Annual value: EUR 580,000
- Medical oxygen: separate dedicated vehicles, GDP compliance for medical-grade gases
- Volume: 2,000-3,000 cylinders/week, steady year-round
- Cylinder testing: LogiCore checks cylinder test dates (ważność badania), rejects expired cylinders
Write 5,000-7,000 characters."""),

    ("CTR-2025-043", "TextileRecycling Used Clothing Collection",
     """Write a transport agreement for used clothing collection logistics.
3-5 pages. Include:
- Contract: CTR-2025-043 between LogiCore and ReWear Polska Sp. z o.o.
- Used clothing collection from 500 street containers and charity drop-off points across Warszawa and Łódź
- Routes: optimized collection routes, GPS-tracked container fill levels trigger collection
- Vehicle types: compactor trucks, box trucks with tail-lift
- Sorting: collected to ReWear sorting facility (Łódź), LogiCore does NOT sort
- Waste classification: used clothing is technically waste until sorted (BDO registration)
- Volume: 200-300 tonnes/month, seasonal peak post-Christmas (January donation surge)
- Penalty: EUR 100/overflowing container not collected within 24h (public complaint risk)
- Annual value: EUR 190,000
- Environmental reporting: tonnage collected per month, CO2 savings calculation provided quarterly
- Container maintenance: LogiCore reports damaged/graffitied containers, ReWear arranges repair
Write 3,500-5,000 characters."""),

    ("CTR-2025-044", "LabEquipment Scientific Instrument Transport",
     """Write a transport agreement for scientific/laboratory equipment.
5-7 pages. Include:
- Contract: CTR-2025-044 between LogiCore and LabTech Instruments Polska Sp. z o.o.
- Scientific instruments: mass spectrometers, HPLC systems, electron microscopes — extremely sensitive
- Vibration: maximum 0.3g during transport, accelerometer monitoring mandatory
- Climate: 18-22°C, humidity 40-60%, no condensation (instruments contain sensitive optics/electronics)
- Calibration: instruments calibrated before shipment — any shock/vibration requires recalibration (EUR 5,000-20,000)
- Routes: import (Frankfurt, Amsterdam, Vienna) to universities and research institutes across Poland
- White-glove: specialized crew (2-3 people), anti-vibration air-ride suspension vehicles
- Penalty: EUR 5,000/vibration exceedance, recalibration cost if triggered, full replacement for damage (some instruments EUR 500K+)
- Annual value: EUR 290,000 (low volume, extremely high value)
- Insurance: declared value per instrument, typically EUR 100K-500K
- Installation support: LogiCore crew trained in basic instrument placement per manufacturer specs
Write 5,000-7,000 characters."""),

    ("CTR-2025-045", "EUFunding Grant-Funded Equipment Distribution",
     """Write a transport agreement for EU-funded equipment distribution.
4-5 pages. Include:
- Contract: CTR-2025-045 between LogiCore and PARP (Polska Agencja Rozwoju Przedsiębiorczości)
- EU-funded equipment: machinery, IT infrastructure, lab equipment distributed to SME grant recipients
- Public procurement: contract awarded via Prawo zamówień publicznych (Pzp), strict compliance
- Documentation: delivery protocols per EU audit requirements, photo documentation, GPS route log
- Routes: central warehouse (Radom) to grant recipients across all 16 voivodeships
- Delivery confirmation: recipient signature, serial number verification, condition report — all archived for EU audit
- Time-bound: equipment must be delivered within grant milestones (delay = grant clawback risk for recipient)
- Penalty: EUR 300/late delivery, EUR 1,000/incomplete documentation (EU audit finding)
- Annual value: EUR 210,000 (framework, depends on EU programming period)
- Insurance: full replacement value, EU requires specific insurance documentation
- Transparency: all invoices, CMRs, delivery reports available for NIK (Najwyższa Izba Kontroli) audit
Write 4,000-5,000 characters."""),
]


def generate_doc(client: httpx.Client, spec: tuple[str, str, str]) -> dict | None:
    """Generate a single long-form contract via Azure OpenAI."""
    doc_id, title_hint, prompt = spec

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    api_key = os.environ["AZURE_OPENAI_API_KEY"]
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

    user_msg = f"""{prompt}

Output a single JSON object with these fields:
- "doc_id": "{doc_id}"
- "title": "{title_hint}" (expand to a proper contract title)
- "doc_type": "contract"
- "department": "legal"
- "clearance_level": 2
- "text": the FULL contract text (as specified above — 4000-8000+ characters)

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
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            try:
                doc = json.loads(content[start_idx : end_idx + 1])
                text_len = len(doc.get("text", ""))
                print(f"OK (extracted, {text_len} chars, {elapsed:.0f}s)")
                return doc
            except json.JSONDecodeError:
                pass
        print(f"FAILED (JSON: {e}, {elapsed:.0f}s)")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate homogeneous benchmark corpus")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    for var in ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY"]:
        if not os.environ.get(var):
            print(f"Missing: {var}")
            sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing docs if retrying
    existing: dict[str, dict] = {}
    if args.retry_failed and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            for doc in json.load(f):
                existing[doc["doc_id"]] = doc
        print(f"Loaded {len(existing)} existing docs")

    print(f"Generating {len(CONTRACT_SPECS)} contracts → {OUTPUT_PATH}")
    print()

    all_docs: list[dict] = []
    with httpx.Client() as client:
        for spec in CONTRACT_SPECS:
            doc_id = spec[0]
            if doc_id in existing:
                print(f"  [{doc_id}] SKIP (already exists)")
                all_docs.append(existing[doc_id])
                continue

            doc = generate_doc(client, spec)
            if doc:
                doc["doc_id"] = doc_id
                doc["doc_type"] = "contract"
                doc["department"] = "legal"
                doc["clearance_level"] = 2
                all_docs.append(doc)
            else:
                print(f"    WARNING: Failed to generate {doc_id}")

            # Save incrementally
            with open(OUTPUT_PATH, "w") as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)

    # Stats
    print(f"\nTotal: {len(all_docs)} contracts")
    lengths = [len(d.get("text", "")) for d in all_docs]
    if lengths:
        print(
            f"Text lengths: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths) // len(lengths)}"
        )
        total_chars = sum(lengths)
        est_pages = total_chars // 2000
        print(f"Total content: {total_chars:,} chars (~{est_pages} pages)")


if __name__ == "__main__":
    main()
