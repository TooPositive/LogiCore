"""Tests for Polish language quality in LLM providers (Phase 6 Gap 3).

Verifies that:
1. Providers accept Polish text input without errors
2. Parsing handles Polish LLM responses correctly
3. Polish number format parsing works (1.234,56 vs 1,234.56)

These are UNIT tests using mocked providers -- they test the parsing
and handling logic, not the model's actual Polish capability.
For live Polish tests, see tests/integration/test_financial_extraction_live.py.
"""

from decimal import Decimal, InvalidOperation
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# -----------------------------------------------------------------------
# Test 1: Polish prompt accepted by providers
# -----------------------------------------------------------------------


class TestPolishPromptAccepted:
    """Verify providers accept Polish text without errors."""

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_ollama_accepts_polish_prompt(self, mock_chat_cls):
        """OllamaProvider.generate() accepts Polish text."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_response = MagicMock()
        mock_response.content = "Odpowiedz po polsku."
        mock_response.usage_metadata = {
            "input_tokens": 30,
            "output_tokens": 10,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        result = await provider.generate(
            "Jakie sa stawki za transport farmaceutyczny?"
        )

        assert result.content == "Odpowiedz po polsku."
        assert result.input_tokens == 30
        mock_instance.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_azure_accepts_polish_prompt(self, mock_chat_cls):
        """AzureOpenAIProvider.generate() accepts Polish text."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_response = MagicMock()
        mock_response.content = "Stawka wynosi EUR 0.45 za kilogram."
        mock_response.usage_metadata = {
            "input_tokens": 25,
            "output_tokens": 12,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )

        result = await provider.generate(
            "Znajdz dokumenty dotyczace nadgodzin pracownikow"
        )

        assert result.content == "Stawka wynosi EUR 0.45 za kilogram."
        mock_instance.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_ollama_accepts_polish_with_diacritics(self, mock_chat_cls):
        """OllamaProvider handles Polish diacritics (ogonki)."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_response = MagicMock()
        mock_response.content = "Zrozumiano zapytanie."
        mock_response.usage_metadata = {
            "input_tokens": 40,
            "output_tokens": 5,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        # Polish text with full diacritics
        result = await provider.generate(
            "Prosz\u0119 o informacje o za\u0142adunku "
            "w magazynie g\u0142\u00f3wnym we Wroc\u0142awiu."
        )

        assert result.content is not None
        assert len(result.content) > 0


# -----------------------------------------------------------------------
# Test 2: Polish extraction prompt parsing
# -----------------------------------------------------------------------


class TestPolishExtractionPromptParsing:
    """Verify parsing works when LLM returns Polish text mixed with JSON."""

    @pytest.mark.asyncio
    async def test_polish_response_json_extraction(self):
        """ReaderAgent handles LLM returning JSON after Polish context."""
        from apps.api.src.domains.logicore.agents.brain.reader import ReaderAgent

        retriever = AsyncMock()
        retriever.search = AsyncMock(
            return_value=[
                MagicMock(
                    content=(
                        "Umowa CTR-PL-001. Stawka za transport "
                        "standardowy: EUR 0.52/kg."
                    ),
                    score=0.9,
                ),
            ]
        )

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=(
                    '[{"contract_id": "CTR-PL-001", "rate": "0.52", '
                    '"currency": "EUR", "unit": "kg", '
                    '"cargo_type": "standardowy", "clearance_level": 1}]'
                )
            )
        )

        agent = ReaderAgent(retriever=retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-001", "standardowy")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.52")
        assert rates[0].cargo_type == "standardowy"

    @pytest.mark.asyncio
    async def test_polish_cargo_types_preserved(self):
        """Polish cargo type names are preserved in extraction."""
        from apps.api.src.domains.logicore.agents.brain.reader import ReaderAgent

        retriever = AsyncMock()
        retriever.search = AsyncMock(
            return_value=[MagicMock(content="Contract text.", score=0.9)]
        )

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=(
                    '['
                    '{"contract_id": "CTR-PL-002", "rate": "0.65", '
                    '"currency": "EUR", "unit": "kg", '
                    '"cargo_type": "farmaceutyczny", "clearance_level": 2},'
                    '{"contract_id": "CTR-PL-002", "rate": "1.20", '
                    '"currency": "EUR", "unit": "kg", '
                    '"cargo_type": "niebezpieczny", "clearance_level": 3}'
                    ']'
                )
            )
        )

        agent = ReaderAgent(retriever=retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-002", "farmaceutyczny")

        assert len(rates) == 2
        assert rates[0].cargo_type == "farmaceutyczny"
        assert rates[1].cargo_type == "niebezpieczny"

    @pytest.mark.asyncio
    async def test_polish_response_with_think_tags(self):
        """Polish LLM response with <think> tags (Ollama style)."""
        from apps.api.src.domains.logicore.agents.brain.reader import ReaderAgent

        retriever = AsyncMock()
        retriever.search = AsyncMock(
            return_value=[MagicMock(content="Umowa transportowa.", score=0.9)]
        )

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=(
                    "<think>Musz\u0119 wyci\u0105gn\u0105\u0107 stawki "
                    "z tej umowy transportowej...</think>\n"
                    '[{"contract_id": "CTR-PL-003", "rate": "0.48", '
                    '"currency": "EUR", "unit": "kg", '
                    '"cargo_type": "ogolny", "clearance_level": 1}]'
                )
            )
        )

        agent = ReaderAgent(retriever=retriever, llm=llm)
        rates = await agent.extract_rates("CTR-PL-003", "ogolny")

        assert len(rates) == 1
        assert rates[0].rate == Decimal("0.48")


# -----------------------------------------------------------------------
# Test 3: Polish number format parsing
# -----------------------------------------------------------------------


class TestPolishNumberFormatParsing:
    """Polish uses period as thousands sep and comma as decimal sep.

    1.234,56 (Polish) = 1234.56 (US/JSON)
    The LLM should normalize to JSON format, but we test what happens
    when it doesn't.
    """

    def test_polish_format_comma_decimal_fails_decimal(self):
        """Decimal('1234,56') raises InvalidOperation (expected behavior)."""
        with pytest.raises(InvalidOperation):
            Decimal("1234,56")

    def test_standard_format_period_decimal_succeeds(self):
        """Decimal('1234.56') works correctly."""
        val = Decimal("1234.56")
        assert val == Decimal("1234.56")

    def test_polish_thousands_separator_fails(self):
        """Decimal('1.234.56') fails (ambiguous format)."""
        # This would be "1,234.56" in US format, but with periods
        # it's ambiguous and Decimal correctly rejects it.
        with pytest.raises(InvalidOperation):
            Decimal("1.234.56")

    def test_json_normalized_rate_succeeds(self):
        """JSON number 1234.56 -> str -> Decimal works."""
        import json

        data = json.loads('{"rate": 1234.56}')
        val = Decimal(str(data["rate"]))
        assert val == Decimal("1234.56")

    def test_json_string_rate_succeeds(self):
        """JSON string "1234.56" -> Decimal works."""
        import json

        data = json.loads('{"rate": "1234.56"}')
        val = Decimal(str(data["rate"]))
        assert val == Decimal("1234.56")

    def test_polish_comma_in_json_string_fails(self):
        """JSON string "1234,56" -> Decimal raises (safe failure)."""
        import json

        data = json.loads('{"rate": "1234,56"}')
        with pytest.raises(InvalidOperation):
            Decimal(str(data["rate"]))


# -----------------------------------------------------------------------
# Live Polish test (skipif no Ollama)
# -----------------------------------------------------------------------


def _ollama_available() -> bool:
    """Check if Ollama is running."""
    try:
        import httpx

        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


class TestLiveOllamaPolishResponse:
    """Live test: send Polish prompt to Ollama, verify response."""

    @pytest.mark.integration
    @pytest.mark.skipif(
        not _ollama_available(),
        reason="Ollama not running at localhost:11434",
    )
    @pytest.mark.asyncio
    async def test_live_ollama_polish_response(self):
        """Send Polish prompt to Ollama, verify response is meaningful."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        result = await provider.generate(
            "Odpowiedz po polsku w jednym zdaniu: "
            "Czym jest transport intermodalny?"
        )

        assert result.content is not None
        assert len(result.content) > 10  # Non-trivial response
        assert result.input_tokens > 0
        assert result.output_tokens > 0
