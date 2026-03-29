"""Seed PostgreSQL with mock invoice and contract data.

Usage:
    uv run python scripts/seed_invoices.py

Reads from data/mock-invoices/invoices.json and contracts.json,
creates tables if they don't exist, and inserts all records.
Uses parameterized queries ($1, $2, ...) throughout.

Environment variables:
    POSTGRES_HOST (default: localhost)
    POSTGRES_PORT (default: 5432)
    POSTGRES_USER (default: logicore)
    POSTGRES_PASSWORD (default: changeme)
    POSTGRES_DB (default: logicore)
"""

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path

import asyncpg

DATA_DIR = Path(__file__).parent.parent / "data" / "mock-invoices"


CREATE_TABLES_SQL = """
-- Contracts table
CREATE TABLE IF NOT EXISTS contracts (
    contract_id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    effective_from DATE,
    effective_to DATE
);

-- Contract rates table
CREATE TABLE IF NOT EXISTS contract_rates (
    id SERIAL PRIMARY KEY,
    contract_id TEXT NOT NULL REFERENCES contracts(contract_id),
    cargo_type TEXT,
    rate NUMERIC(12, 4) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    unit TEXT NOT NULL,
    min_volume NUMERIC(12, 2),
    clearance_level INTEGER NOT NULL DEFAULT 1
);

-- Invoices table
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    vendor TEXT NOT NULL,
    contract_id TEXT REFERENCES contracts(contract_id),
    issue_date TIMESTAMPTZ NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR'
);

-- Invoice line items table
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id SERIAL PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
    description TEXT NOT NULL,
    quantity NUMERIC(12, 4) NOT NULL,
    unit TEXT NOT NULL,
    unit_price NUMERIC(12, 4) NOT NULL,
    total NUMERIC(12, 2) NOT NULL,
    cargo_type TEXT
);

-- Read-only role for SQL agents (defense-in-depth)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logicore_reader') THEN
        CREATE ROLE logicore_reader LOGIN PASSWORD 'reader_changeme';
    END IF;
END
$$;

GRANT SELECT ON contracts, contract_rates, invoices, invoice_line_items TO logicore_reader;
"""


async def seed() -> None:
    """Seed the database with mock data."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "logicore")
    password = os.getenv("POSTGRES_PASSWORD", "changeme")
    database = os.getenv("POSTGRES_DB", "logicore")

    conn = await asyncpg.connect(
        host=host, port=port, user=user, password=password, database=database
    )

    try:
        # Create tables
        await conn.execute(CREATE_TABLES_SQL)
        print("Tables created (or already exist).")

        # Load contracts
        contracts_path = DATA_DIR / "contracts.json"
        with open(contracts_path) as f:
            contracts = json.load(f)

        for contract in contracts:
            await conn.execute(
                "INSERT INTO contracts (contract_id, vendor, effective_from, effective_to) "
                "VALUES ($1, $2, $3::date, $4::date) "
                "ON CONFLICT (contract_id) DO NOTHING",
                contract["contract_id"],
                contract["vendor"],
                contract.get("effective_from"),
                contract.get("effective_to"),
            )

            for rate in contract.get("rates", []):
                # Check if rate already exists
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM contract_rates "
                    "WHERE contract_id = $1 AND cargo_type = $2",
                    contract["contract_id"],
                    rate.get("cargo_type"),
                )
                if existing == 0:
                    await conn.execute(
                        "INSERT INTO contract_rates "
                        "(contract_id, cargo_type, rate, currency, "
                        "unit, min_volume, clearance_level) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        contract["contract_id"],
                        rate.get("cargo_type"),
                        Decimal(rate["rate"]),
                        rate.get("currency", "EUR"),
                        rate["unit"],
                        Decimal(rate["min_volume"]) if rate.get("min_volume") else None,
                        rate.get("clearance_level", 1),
                    )

        print(f"Seeded {len(contracts)} contracts with rates.")

        # Load invoices
        invoices_path = DATA_DIR / "invoices.json"
        with open(invoices_path) as f:
            invoices = json.load(f)

        for invoice in invoices:
            await conn.execute(
                "INSERT INTO invoices "
                "(invoice_id, vendor, contract_id, "
                "issue_date, total_amount, currency) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "ON CONFLICT (invoice_id) DO NOTHING",
                invoice["invoice_id"],
                invoice["vendor"],
                invoice["contract_id"],
                invoice["issue_date"],
                Decimal(invoice["total_amount"]),
                invoice.get("currency", "EUR"),
            )

            for item in invoice.get("line_items", []):
                # Check if line item already exists
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM invoice_line_items "
                    "WHERE invoice_id = $1 AND description = $2",
                    invoice["invoice_id"],
                    item["description"],
                )
                if existing == 0:
                    await conn.execute(
                        "INSERT INTO invoice_line_items "
                        "(invoice_id, description, quantity, unit, unit_price, total, cargo_type) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        invoice["invoice_id"],
                        item["description"],
                        Decimal(item["quantity"]),
                        item["unit"],
                        Decimal(item["unit_price"]),
                        Decimal(item["total"]),
                        item.get("cargo_type"),
                    )

        print(f"Seeded {len(invoices)} invoices with line items.")
        print("Done. Database ready for audit workflows.")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
