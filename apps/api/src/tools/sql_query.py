"""SQL Query Tool -- read-only invoice lookups via asyncpg.

Security model:
  1. Parameterized queries only ($1 params) -- no string interpolation
  2. Read-only DB role (logicore_reader) -- SELECT only
  3. Input validation at tool boundary

The SQL agent uses this tool. Even if the agent is compromised,
it cannot DROP, UPDATE, DELETE, or INSERT -- the DB role prevents it,
and parameterized queries prevent injection.
"""

from datetime import datetime

from apps.api.src.domain.audit import Invoice, LineItem


class SqlQueryTool:
    """Read-only SQL interface for invoice data.

    Takes an asyncpg pool (injected). Uses parameterized queries exclusively.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def fetch_invoice(self, invoice_id: str) -> Invoice | None:
        """Fetch an invoice and its line items by ID.

        Returns None if the invoice doesn't exist.
        Raises ValueError if invoice_id is empty.
        """
        if not invoice_id:
            raise ValueError("invoice_id must not be empty")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT invoice_id, vendor, contract_id, issue_date, "
                "total_amount, currency FROM invoices WHERE invoice_id = $1",
                invoice_id,
            )

            if row is None:
                return None

            line_rows = await conn.fetch(
                "SELECT description, quantity, unit, unit_price, total, cargo_type "
                "FROM invoice_line_items WHERE invoice_id = $1 ORDER BY id",
                invoice_id,
            )

            issue_date = row["issue_date"]
            if isinstance(issue_date, str):
                issue_date = datetime.fromisoformat(issue_date)

            line_items = [
                LineItem(
                    description=lr["description"],
                    quantity=lr["quantity"],
                    unit=lr["unit"],
                    unit_price=lr["unit_price"],
                    total=lr["total"],
                    cargo_type=lr.get("cargo_type"),
                )
                for lr in line_rows
            ]

            return Invoice(
                invoice_id=row["invoice_id"],
                vendor=row["vendor"],
                contract_id=row["contract_id"],
                issue_date=issue_date,
                total_amount=row["total_amount"],
                currency=row["currency"],
                line_items=line_items if line_items else [
                    LineItem(
                        description="(no line items)",
                        quantity=0,
                        unit="n/a",
                        unit_price=0,
                        total=0,
                    )
                ],
            )
