//! Mock data definitions for LogiCore Transport GmbH.
//!
//! The "simulated world" — contracts, invoices, documents, warehouses.
//! Seeded into PostgreSQL and Qdrant on first run.

use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct Company {
    pub name: &'static str,
    pub hq: &'static str,
    pub fleet_size: u32,
    pub warehouses: u32,
    pub cold_storage: u32,
    pub countries: &'static [&'static str],
}

pub const COMPANY: Company = Company {
    name: "LogiCore Transport GmbH",
    hq: "Hamburg, Germany",
    fleet_size: 50,
    warehouses: 10,
    cold_storage: 5,
    countries: &["DE", "CH", "AT", "NL", "IT"],
};

#[derive(Debug, Clone, Serialize)]
pub struct Warehouse {
    pub id: &'static str,
    pub city: &'static str,
    pub country: &'static str,
    pub warehouse_type: &'static str,
    pub capacity_pallets: Option<u32>,
    pub temp_range: Option<&'static str>,
}

pub const WAREHOUSES: &[Warehouse] = &[
    Warehouse { id: "WH-DE-HH-01", city: "Hamburg",   country: "DE", warehouse_type: "standard",     capacity_pallets: Some(5000), temp_range: None },
    Warehouse { id: "WH-DE-FR-02", city: "Frankfurt",  country: "DE", warehouse_type: "standard",     capacity_pallets: Some(3500), temp_range: None },
    Warehouse { id: "WH-DE-MU-03", city: "Munich",     country: "DE", warehouse_type: "standard",     capacity_pallets: Some(4000), temp_range: None },
    Warehouse { id: "WH-NL-AM-04", city: "Amsterdam",  country: "NL", warehouse_type: "standard",     capacity_pallets: Some(3000), temp_range: None },
    Warehouse { id: "WH-NL-RT-05", city: "Rotterdam",  country: "NL", warehouse_type: "standard",     capacity_pallets: Some(6000), temp_range: None },
    Warehouse { id: "WH-AT-VI-06", city: "Vienna",     country: "AT", warehouse_type: "standard",     capacity_pallets: Some(2500), temp_range: None },
    Warehouse { id: "WH-IT-MI-07", city: "Milan",      country: "IT", warehouse_type: "standard",     capacity_pallets: Some(3500), temp_range: None },
    Warehouse { id: "CS-DE-HH-01", city: "Hamburg",    country: "DE", warehouse_type: "cold_storage", capacity_pallets: None, temp_range: Some("-25C to +8C") },
    Warehouse { id: "CS-CH-ZH-04", city: "Zurich",     country: "CH", warehouse_type: "cold_storage", capacity_pallets: None, temp_range: Some("-25C to +8C") },
    Warehouse { id: "CS-DE-MU-02", city: "Munich",     country: "DE", warehouse_type: "cold_storage", capacity_pallets: None, temp_range: Some("-25C to +8C") },
    Warehouse { id: "CS-NL-RT-03", city: "Rotterdam",  country: "NL", warehouse_type: "cold_storage", capacity_pallets: None, temp_range: Some("-25C to +8C") },
    Warehouse { id: "CS-AT-VI-05", city: "Vienna",     country: "AT", warehouse_type: "cold_storage", capacity_pallets: None, temp_range: Some("-20C to +8C") },
];

#[derive(Debug, Clone, Serialize)]
pub struct Contract {
    pub id: &'static str,
    pub client: &'static str,
    pub contract_type: &'static str,
    pub rate_per_kg: f64,
    pub min_volume_kg: u32,
    pub temperature_requirement: Option<&'static str>,
    pub penalty_late_delivery_pct: u8,
    pub insurance_required: bool,
    pub clearance_level: u8,
    pub department: &'static str,
}

pub const CONTRACTS: &[Contract] = &[
    Contract {
        id: "CTR-2024-001", client: "PharmaCorp AG", contract_type: "pharmaceutical",
        rate_per_kg: 0.45, min_volume_kg: 5000, temperature_requirement: Some("2-8C continuous"),
        penalty_late_delivery_pct: 15, insurance_required: true, clearance_level: 3, department: "logistics",
    },
    Contract {
        id: "CTR-2024-002", client: "FreshFoods GmbH", contract_type: "frozen_food",
        rate_per_kg: 0.28, min_volume_kg: 10000, temperature_requirement: Some("-18C or below"),
        penalty_late_delivery_pct: 10, insurance_required: true, clearance_level: 2, department: "logistics",
    },
    Contract {
        id: "CTR-2024-003", client: "ElectroParts BV", contract_type: "electronics",
        rate_per_kg: 0.35, min_volume_kg: 2000, temperature_requirement: None,
        penalty_late_delivery_pct: 8, insurance_required: true, clearance_level: 2, department: "logistics",
    },
    Contract {
        id: "CTR-2024-004", client: "ChemTrans SE", contract_type: "chemicals",
        rate_per_kg: 0.52, min_volume_kg: 3000, temperature_requirement: Some("10-20C"),
        penalty_late_delivery_pct: 20, insurance_required: true, clearance_level: 3, department: "logistics",
    },
    Contract {
        id: "CTR-2024-005", client: "AutoLogistik", contract_type: "automotive_parts",
        rate_per_kg: 0.22, min_volume_kg: 15000, temperature_requirement: None,
        penalty_late_delivery_pct: 5, insurance_required: false, clearance_level: 1, department: "logistics",
    },
];

#[derive(Debug, Clone, Serialize)]
pub struct Invoice {
    pub invoice_id: &'static str,
    pub contract_id: &'static str,
    pub billed_rate: f64,
    pub weight_kg: u32,
    pub discrepancy: bool,
}

pub const INVOICES: &[Invoice] = &[
    Invoice { invoice_id: "INV-2024-0001", contract_id: "CTR-2024-001", billed_rate: 0.45, weight_kg: 7200,  discrepancy: false },
    Invoice { invoice_id: "INV-2024-0002", contract_id: "CTR-2024-002", billed_rate: 0.28, weight_kg: 12500, discrepancy: false },
    Invoice { invoice_id: "INV-2024-0003", contract_id: "CTR-2024-003", billed_rate: 0.35, weight_kg: 3100,  discrepancy: false },
    Invoice { invoice_id: "INV-2024-0847", contract_id: "CTR-2024-001", billed_rate: 0.52, weight_kg: 8400,  discrepancy: true },
    Invoice { invoice_id: "INV-2024-0923", contract_id: "CTR-2024-004", billed_rate: 0.61, weight_kg: 5200,  discrepancy: true },
    Invoice { invoice_id: "INV-2024-1102", contract_id: "CTR-2024-005", billed_rate: 0.29, weight_kg: 18700, discrepancy: true },
];

#[derive(Debug, Clone, Serialize)]
pub struct Document {
    pub id: &'static str,
    pub title: &'static str,
    pub department: &'static str,
    pub clearance_level: u8,
    pub pages: u32,
}

pub const DOCUMENTS: &[Document] = &[
    Document { id: "DOC-HR-001",     title: "Employee Handbook 2024",             department: "hr",         clearance_level: 1, pages: 47 },
    Document { id: "DOC-HR-002",     title: "Executive Compensation Policy",      department: "hr",         clearance_level: 4, pages: 12 },
    Document { id: "DOC-HR-003",     title: "Driver Safety Protocol",             department: "operations", clearance_level: 1, pages: 23 },
    Document { id: "DOC-HR-004",     title: "Termination Procedures",             department: "hr",         clearance_level: 3, pages: 8 },
    Document { id: "DOC-SAFETY-001", title: "ISO 9001 Quality Manual",            department: "quality",    clearance_level: 1, pages: 65 },
    Document { id: "DOC-SAFETY-002", title: "Hazmat Transport Protocol",          department: "operations", clearance_level: 2, pages: 34 },
    Document { id: "DOC-SAFETY-003", title: "Cold Chain Compliance Guide",        department: "operations", clearance_level: 2, pages: 28 },
    Document { id: "DOC-LEGAL-001",  title: "Swiss Customs Regulation Summary",   department: "legal",      clearance_level: 2, pages: 19 },
    Document { id: "DOC-LEGAL-002",  title: "EU AI Act Compliance Checklist",     department: "legal",      clearance_level: 3, pages: 15 },
    Document { id: "DOC-LEGAL-003",  title: "GDPR Data Processing Agreement",     department: "legal",      clearance_level: 3, pages: 22 },
    Document { id: "DOC-FIN-001",    title: "Q3 2024 Financial Summary",          department: "finance",    clearance_level: 4, pages: 31 },
    Document { id: "DOC-FIN-002",    title: "Vendor Payment Terms",               department: "finance",    clearance_level: 2, pages: 9 },
];

#[derive(Debug, Clone, Serialize)]
pub struct User {
    pub id: &'static str,
    pub name: &'static str,
    pub role: &'static str,
    pub department: &'static str,
    pub clearance_level: u8,
}

pub const USERS: &[User] = &[
    User { id: "user-warehouse-01", name: "Max Weber",      role: "warehouse_worker",  department: "operations", clearance_level: 1 },
    User { id: "user-driver-01",    name: "Hans Muller",     role: "driver",            department: "operations", clearance_level: 1 },
    User { id: "user-logistics-01", name: "Anna Schmidt",    role: "logistics_manager", department: "logistics",  clearance_level: 2 },
    User { id: "user-hr-01",        name: "Katrin Fischer",  role: "hr_director",       department: "hr",         clearance_level: 3 },
    User { id: "user-legal-01",     name: "Stefan Braun",    role: "legal_counsel",     department: "legal",      clearance_level: 3 },
    User { id: "user-cfo-01",       name: "Martin Lang",     role: "cfo",               department: "finance",    clearance_level: 4 },
    User { id: "user-ceo-01",       name: "Eva Richter",     role: "ceo",               department: "executive",  clearance_level: 4 },
];
