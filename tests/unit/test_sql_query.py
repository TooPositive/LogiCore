"""Tests for SQL Query Tool — read-only invoice lookups.

Security model: parameterized queries only, read-only DB role.
The SQL agent CANNOT execute write queries even if compromised.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestSqlQueryTool:
    """SQL query tool for invoice data retrieval."""

    @pytest.fixture
    def mock_pool(self):
        """Mock asyncpg connection pool."""
        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        return pool, conn

    async def test_fetch_invoice_returns_data(self, mock_pool):
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-2024-0847",
            "vendor": "PharmaCorp",
            "contract_id": "CTR-2024-001",
            "issue_date": "2024-11-15T00:00:00Z",
            "total_amount": Decimal("4368.00"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[
            {
                "description": "Pharmaceutical cargo transport",
                "quantity": Decimal("8400"),
                "unit": "kg",
                "unit_price": Decimal("0.52"),
                "total": Decimal("4368.00"),
                "cargo_type": "pharmaceutical",
            }
        ])

        tool = SqlQueryTool(pool=pool)
        result = await tool.fetch_invoice("INV-2024-0847")

        assert result is not None
        assert result.invoice_id == "INV-2024-0847"
        assert result.vendor == "PharmaCorp"
        assert len(result.line_items) == 1

    async def test_fetch_invoice_not_found_returns_none(self, mock_pool):
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)

        tool = SqlQueryTool(pool=pool)
        result = await tool.fetch_invoice("INV-NONEXISTENT")
        assert result is None

    async def test_fetch_invoice_uses_parameterized_query(self, mock_pool):
        """SECURITY: must use $1 params, never string interpolation."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)

        tool = SqlQueryTool(pool=pool)
        await tool.fetch_invoice("INV-2024-0847")

        # Verify fetchrow was called with parameterized query
        call_args = conn.fetchrow.call_args
        query = call_args[0][0]
        # Query must contain $1 placeholder
        assert "$1" in query, "Query must use parameterized $1 placeholder"
        # Query must NOT contain the invoice_id string-interpolated
        assert "INV-2024-0847" not in query, "Invoice ID must NOT be in query string"
        # The invoice_id must be passed as a separate parameter
        assert call_args[0][1] == "INV-2024-0847"

    async def test_fetch_invoice_sql_injection_safe(self, mock_pool):
        """SECURITY: SQL injection attempt is harmless — it's just a param value."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value=None)

        tool = SqlQueryTool(pool=pool)
        malicious_id = '"; DROP TABLE invoices; --'
        await tool.fetch_invoice(malicious_id)

        call_args = conn.fetchrow.call_args
        query = call_args[0][0]
        # The injection attempt should be passed as a parameter, not in the query
        assert "DROP" not in query
        assert call_args[0][1] == malicious_id

    async def test_fetch_invoice_multiple_line_items(self, mock_pool):
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-2024-0840",
            "vendor": "CargoFlex",
            "contract_id": "CTR-2024-002",
            "issue_date": "2024-11-28T00:00:00Z",
            "total_amount": Decimal("7150.00"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[
            {
                "description": "General cargo pallets",
                "quantity": Decimal("80"),
                "unit": "pallet",
                "unit_price": Decimal("50.00"),
                "total": Decimal("4000.00"),
                "cargo_type": "general",
            },
            {
                "description": "Hazardous materials pallets",
                "quantity": Decimal("30"),
                "unit": "pallet",
                "unit_price": Decimal("105.00"),
                "total": Decimal("3150.00"),
                "cargo_type": "hazardous",
            },
        ])

        tool = SqlQueryTool(pool=pool)
        result = await tool.fetch_invoice("INV-2024-0840")

        assert result is not None
        assert len(result.line_items) == 2
        assert result.total_amount == Decimal("7150.00")

    async def test_line_items_query_uses_parameterized_query(self, mock_pool):
        """SECURITY: line items query also uses $1 params."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-001",
            "vendor": "Test",
            "contract_id": "CTR-001",
            "issue_date": "2024-01-01T00:00:00Z",
            "total_amount": Decimal("100"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[])

        tool = SqlQueryTool(pool=pool)
        await tool.fetch_invoice("INV-001")

        # Verify fetch (line items) was called with parameterized query
        call_args = conn.fetch.call_args
        query = call_args[0][0]
        assert "$1" in query, "Line items query must use parameterized $1 placeholder"

    async def test_fetch_invoice_validates_invoice_id_format(self, mock_pool):
        """Input validation at tool boundary."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        tool = SqlQueryTool(pool=pool)

        # Empty invoice_id should raise
        with pytest.raises(ValueError, match="invoice_id"):
            await tool.fetch_invoice("")

    async def test_fetch_invoice_returns_correct_types(self, mock_pool):
        """Verify returned Invoice has correct Decimal types."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool, conn = mock_pool
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-001",
            "vendor": "Test",
            "contract_id": "CTR-001",
            "issue_date": "2024-01-01T00:00:00Z",
            "total_amount": Decimal("500.00"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[
            {
                "description": "Test item",
                "quantity": Decimal("100"),
                "unit": "kg",
                "unit_price": Decimal("5.00"),
                "total": Decimal("500.00"),
                "cargo_type": "general",
            }
        ])

        tool = SqlQueryTool(pool=pool)
        result = await tool.fetch_invoice("INV-001")

        assert isinstance(result.total_amount, Decimal)
        assert isinstance(result.line_items[0].unit_price, Decimal)
