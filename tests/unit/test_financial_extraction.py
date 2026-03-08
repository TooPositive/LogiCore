"""Tests for financial extraction precision (Phase 6 Gap 2).

The highest-risk technical decision in air-gapped mode is whether the
local model (quantized) extracts EUR amounts correctly. These tests
verify the PARSING logic in ReaderAgent handles different number formats,
which is the actual quantization risk: the LLM outputs text, the parser
converts to Decimal.

Tests use mocked LLM responses simulating both Azure and Ollama response
styles to verify the parsing pipeline handles:
- Basic EUR rate extraction
- Polish number format (1.234,56)
- Rates buried in long contract text
- Quantization edge cases (0.449999 vs 0.45)
- Multiple rates from a single contract
- Volume-threshold tiered rates
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.domains.logicore.agents.brain.reader import ReaderAgent

# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def mock_retriever():
    """Mock RAG retriever returning a single contract result."""
    retriever = AsyncMock()
    retriever.search = AsyncMock(
        return_value=[
            MagicMock(
                content="Contract text placeholder.",
                score=0.95,
                source="contract.pdf",
                document_id="doc-001",
            ),
        ]
    )
    return retriever


def _make_llm(response_text: str) -> AsyncMock:
    """Create a mock LLM returning the given text."""
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(
        return_value=MagicMock(content=response_text)
    )
    return llm


# -----------------------------------------------------------------------
# Test 1: Basic EUR rate extraction
# -----------------------------------------------------------------------


class TestExtractEurRateBasic:
    """ReaderAgent parses a simple EUR rate from LLM output."""

    @pytest.mark.asyncio
    async def test_extract_eur_rate_basic(self, mock_retriever):
        """'Transport rate EUR 0.45/kg for standard cargo' -> extract 0.45."""
        llm = _make_llm(
            '[{"contract_id": "CTR-2024-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-2024-001", "standard")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.45")
        assert rates[0].currency == "EUR"
        assert rates[0].unit == "kg"

    @pytest.mark.asyncio
    async def test_extract_eur_rate_with_many_decimals(self, mock_retriever):
        """Rate with many decimal places is preserved precisely."""
        llm = _make_llm(
            '[{"contract_id": "CTR-2024-002", "rate": "1.23456", '
            '"currency": "EUR", "unit": "km", "cargo_type": "general", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-2024-002", "general")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("1.23456")

    @pytest.mark.asyncio
    async def test_extract_eur_rate_integer(self, mock_retriever):
        """Integer rate (no decimals) is parsed correctly."""
        llm = _make_llm(
            '[{"contract_id": "CTR-2024-003", "rate": "50", '
            '"currency": "EUR", "unit": "pallet", "cargo_type": "general", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-2024-003", "general")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("50")


# -----------------------------------------------------------------------
# Test 2: Polish number format
# -----------------------------------------------------------------------


class TestExtractEurRatePolishFormat:
    """Polish number format uses period as thousands separator and comma
    as decimal separator: 1.234,56 = 1234.56 in standard notation.

    The LLM is expected to normalize this in its JSON output (since JSON
    numbers use period as decimal), but the parser must handle both styles
    since a local quantized model might output the Polish format as a string.
    """

    @pytest.mark.asyncio
    async def test_extract_polish_format_normalized_by_llm(self, mock_retriever):
        """LLM normalizes Polish '1.234,56' to JSON '1234.56' -> Decimal('1234.56')."""
        llm = _make_llm(
            '[{"contract_id": "CTR-PL-001", "rate": "1234.56", '
            '"currency": "EUR", "unit": "transport", "cargo_type": "pharmaceutical", '
            '"clearance_level": 2}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-001", "pharmaceutical")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("1234.56")

    @pytest.mark.asyncio
    async def test_extract_polish_format_as_string(self, mock_retriever):
        """If LLM outputs Polish format '1234,56' as string, parser handles it.

        The ReaderAgent converts rate via Decimal(str(item["rate"])).
        If the LLM outputs "1234,56" (comma decimal), Decimal() will raise
        InvalidOperation and the item will be skipped with a warning.
        This test documents the current behavior: Polish comma-decimal
        strings that are NOT normalized by the LLM are skipped.
        """
        llm = _make_llm(
            '[{"contract_id": "CTR-PL-002", "rate": "1234,56", '
            '"currency": "EUR", "unit": "transport", "cargo_type": "general", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-002", "general")

        # Current behavior: Decimal("1234,56") raises InvalidOperation,
        # so the item is skipped and we get an empty list.
        # This is CORRECT behavior -- if the LLM doesn't normalize,
        # we'd rather skip than misparse a financial value.
        assert len(rates) == 0

    @pytest.mark.asyncio
    async def test_extract_large_polish_amount_normalized(self, mock_retriever):
        """Large amounts like '12500.00' are parsed correctly."""
        llm = _make_llm(
            '[{"contract_id": "CTR-PL-003", "rate": "12500.00", '
            '"currency": "EUR", "unit": "container", "cargo_type": "hazardous", '
            '"clearance_level": 3}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-003", "hazardous")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("12500.00")


# -----------------------------------------------------------------------
# Test 3: Rate buried in long contract text
# -----------------------------------------------------------------------


class TestExtractEurRateFromLongContract:
    """LLM extracts rate from a long contract context.

    The test is about whether the parser handles the LLM output correctly
    when the LLM was given a long context. The contract text is in the
    retriever; we test that the parser handles the LLM's extraction.
    """

    @pytest.mark.asyncio
    async def test_extract_rate_from_long_contract_context(self):
        """Rate correctly extracted even when retriever returns long text."""
        # Simulate a long contract text (500+ words)
        long_text = (
            "UMOWA TRANSPORTOWA nr CTR-2024-LONG\n\n"
            + "Artykul 1. Strony umowy\n" * 20
            + "Artykul 2. Przedmiot umowy - transport ladunkow farmaceutycznych\n" * 10
            + "Artykul 3. Postanowienia ogolne dotyczace transportu\n" * 15
            + "Artykul 4.2.1 Stawki transportowe:\n"
            + "Stawka za transport standardowy wynosi EUR 0.78 za kilogram.\n"
            + "Artykul 5. Postanowienia koncowe\n" * 20
        )

        retriever = AsyncMock()
        retriever.search = AsyncMock(
            return_value=[
                MagicMock(
                    content=long_text,
                    score=0.88,
                    source="CTR-2024-LONG.pdf",
                    document_id="doc-long",
                ),
            ]
        )

        llm = _make_llm(
            '[{"contract_id": "CTR-2024-LONG", "rate": "0.78", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=retriever, llm=llm)
        rates = await agent.extract_rates("CTR-2024-LONG", "standard")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.78")
        assert rates[0].contract_id == "CTR-2024-LONG"


# -----------------------------------------------------------------------
# Test 4: Quantization edge case
# -----------------------------------------------------------------------


class TestExtractEurRateQuantizationEdge:
    """Quantization may cause floating-point imprecision.

    'EUR 0.449999 per kilogram (rounded to 0.45)' -- the LLM may
    output either 0.45 or 0.449999. Both are acceptable since the
    parser uses Decimal (not float), preserving the exact string value.
    """

    @pytest.mark.asyncio
    async def test_extract_quantization_exact(self, mock_retriever):
        """LLM outputs exact rounded value 0.45."""
        llm = _make_llm(
            '[{"contract_id": "CTR-QUANT-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-QUANT-001", "standard")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_extract_quantization_precise(self, mock_retriever):
        """LLM outputs unrounded value 0.449999."""
        llm = _make_llm(
            '[{"contract_id": "CTR-QUANT-002", "rate": "0.449999", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-QUANT-002", "standard")

        assert len(rates) == 1
        # Decimal preserves the exact string value
        assert rates[0].rate == Decimal("0.449999")

    @pytest.mark.asyncio
    async def test_extract_quantization_very_small_rate(self, mock_retriever):
        """Very small rate (0.001) is preserved without rounding to 0."""
        llm = _make_llm(
            '[{"contract_id": "CTR-QUANT-003", "rate": "0.001", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "bulk", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-QUANT-003", "bulk")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.001")
        assert rates[0].rate > Decimal("0")

    @pytest.mark.asyncio
    async def test_extract_quantization_float_precision(self, mock_retriever):
        """Rate like 0.1 + 0.2 = 0.30000000000000004 in float, but
        Decimal('0.30') is exact. Parser uses Decimal(str()) so
        precision is preserved regardless of float math."""
        llm = _make_llm(
            '[{"contract_id": "CTR-QUANT-004", "rate": "0.30", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "general", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-QUANT-004", "general")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.30")
        # Verify it's NOT a float approximation
        assert str(rates[0].rate) == "0.30"


# -----------------------------------------------------------------------
# Test 5: Multiple rates from single contract
# -----------------------------------------------------------------------


class TestExtractMultipleRatesFromContract:
    """Contract may contain multiple rates for different cargo types."""

    @pytest.mark.asyncio
    async def test_extract_three_rates(self, mock_retriever):
        """Contract with 3 different rates -> all extracted correctly."""
        llm = _make_llm(
            '['
            '{"contract_id": "CTR-MULTI-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1},'
            '{"contract_id": "CTR-MULTI-001", "rate": "0.65", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "pharmaceutical", '
            '"clearance_level": 2},'
            '{"contract_id": "CTR-MULTI-001", "rate": "1.20", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "hazardous", '
            '"clearance_level": 3}'
            ']'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-MULTI-001", "all")

        assert len(rates) == 3
        assert rates[0].rate == Decimal("0.45")
        assert rates[0].cargo_type == "standard"
        assert rates[1].rate == Decimal("0.65")
        assert rates[1].cargo_type == "pharmaceutical"
        assert rates[2].rate == Decimal("1.20")
        assert rates[2].cargo_type == "hazardous"

    @pytest.mark.asyncio
    async def test_extract_multiple_with_one_malformed(self, mock_retriever):
        """If one rate in the array is malformed, others still extracted."""
        llm = _make_llm(
            '['
            '{"contract_id": "CTR-MULTI-002", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1},'
            '{"contract_id": "CTR-MULTI-002", "rate": "INVALID", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "broken", '
            '"clearance_level": 1},'
            '{"contract_id": "CTR-MULTI-002", "rate": "1.20", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "hazardous", '
            '"clearance_level": 3}'
            ']'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-MULTI-002", "all")

        # Should get 2 valid rates, skip the INVALID one
        assert len(rates) == 2
        assert rates[0].rate == Decimal("0.45")
        assert rates[1].rate == Decimal("1.20")


# -----------------------------------------------------------------------
# Test 6: Volume-threshold tiered rates
# -----------------------------------------------------------------------


class TestExtractRateWithVolumeThreshold:
    """Tiered pricing: different rates based on volume thresholds."""

    @pytest.mark.asyncio
    async def test_extract_tiered_rates(self, mock_retriever):
        """'EUR 0.45/kg up to 1000kg, EUR 0.40/kg above' -> both rates."""
        llm = _make_llm(
            '['
            '{"contract_id": "CTR-TIER-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"min_volume": null, "clearance_level": 1},'
            '{"contract_id": "CTR-TIER-001", "rate": "0.40", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"min_volume": "1000", "clearance_level": 1}'
            ']'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-TIER-001", "standard")

        assert len(rates) == 2

        # First rate: no volume minimum (base rate)
        assert rates[0].rate == Decimal("0.45")
        assert rates[0].min_volume is None

        # Second rate: volume >= 1000kg (discounted)
        assert rates[1].rate == Decimal("0.40")
        assert rates[1].min_volume == Decimal("1000")

    @pytest.mark.asyncio
    async def test_extract_tiered_rates_three_tiers(self, mock_retriever):
        """Three-tier pricing structure."""
        llm = _make_llm(
            '['
            '{"contract_id": "CTR-TIER-002", "rate": "0.50", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "general", '
            '"min_volume": null, "clearance_level": 1},'
            '{"contract_id": "CTR-TIER-002", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "general", '
            '"min_volume": "1000", "clearance_level": 1},'
            '{"contract_id": "CTR-TIER-002", "rate": "0.38", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "general", '
            '"min_volume": "5000", "clearance_level": 1}'
            ']'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-TIER-002", "general")

        assert len(rates) == 3
        assert rates[0].rate == Decimal("0.50")
        assert rates[0].min_volume is None
        assert rates[1].rate == Decimal("0.45")
        assert rates[1].min_volume == Decimal("1000")
        assert rates[2].rate == Decimal("0.38")
        assert rates[2].min_volume == Decimal("5000")


# -----------------------------------------------------------------------
# Additional edge cases for Decimal parsing
# -----------------------------------------------------------------------


class TestDecimalParsingEdgeCases:
    """Edge cases in the Decimal parsing path of ReaderAgent."""

    @pytest.mark.asyncio
    async def test_rate_as_numeric_not_string(self, mock_retriever):
        """LLM returns rate as JSON number (0.45) not string ('0.45').

        json.loads will produce a float; Decimal(str(float)) may lose
        precision, but for reasonable values it's safe.
        """
        llm = _make_llm(
            '[{"contract_id": "CTR-NUM-001", "rate": 0.45, '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-NUM-001", "standard")

        assert len(rates) == 1
        # Decimal(str(0.45)) == Decimal("0.45")
        assert rates[0].rate == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_rate_with_leading_zero(self, mock_retriever):
        """Rate '00.45' is equivalent to '0.45'."""
        llm = _make_llm(
            '[{"contract_id": "CTR-LZ-001", "rate": "00.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-LZ-001", "standard")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_negative_rate_rejected(self, mock_retriever):
        """Negative rate is rejected by ContractRate validation (ge=0)."""
        llm = _make_llm(
            '[{"contract_id": "CTR-NEG-001", "rate": "-0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-NEG-001", "standard")

        # Negative rate should be rejected by Pydantic validation (ge=0)
        assert len(rates) == 0

    @pytest.mark.asyncio
    async def test_llm_wraps_json_in_markdown_fences(self, mock_retriever):
        """Some models wrap JSON in ```json ... ``` fences."""
        llm = _make_llm(
            '```json\n'
            '[{"contract_id": "CTR-MD-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]\n'
            '```'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-MD-001", "standard")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_ollama_style_thinking_prefix(self, mock_retriever):
        """Ollama/qwen3 may include <think>...</think> before JSON.

        This tests whether the parser handles the common Ollama output
        style where the model "thinks" before producing the answer.
        The ReaderAgent must strip <think>...</think> tags to extract
        the JSON payload underneath.
        """
        llm = _make_llm(
            '<think>Let me extract the rate from this contract...</think>\n'
            '[{"contract_id": "CTR-THINK-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "standard", '
            '"clearance_level": 1}]'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-THINK-001", "standard")

        # After fix: <think> tags are stripped, JSON is parsed correctly
        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_ollama_thinking_with_markdown_fences(self, mock_retriever):
        """Ollama may combine <think> tags AND markdown fences."""
        llm = _make_llm(
            '<think>I need to extract the rates carefully...</think>\n'
            '```json\n'
            '[{"contract_id": "CTR-THINK-002", "rate": "0.65", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "pharma", '
            '"clearance_level": 2}]\n'
            '```'
        )

        agent = ReaderAgent(retriever=mock_retriever, llm=llm)
        rates = await agent.extract_rates("CTR-THINK-002", "pharma")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.65")
