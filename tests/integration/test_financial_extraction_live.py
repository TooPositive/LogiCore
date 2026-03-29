"""Live integration tests for financial extraction with Ollama (Phase 6 Gap 2).

These tests send real contract excerpts to Ollama and verify the extracted
rates match ground truth. They measure the ACTUAL quantization risk: does
the local model extract EUR amounts correctly from contract text?

Requires: Ollama running at localhost:11434 with qwen3:8b pulled.

Run: pytest tests/integration/test_financial_extraction_live.py -v -m integration
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

import httpx
import pytest

OLLAMA_HOST = "http://localhost:11434"


def ollama_available() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ollama_available(),
        reason="Ollama not running at localhost:11434",
    ),
]


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------

EXTRACTION_PROMPT_TEMPLATE = (
    "Extract all transport/contract rates from the following text. "
    "Return a JSON array of objects with these fields: "
    "rate (numeric, use period as decimal separator), currency, unit, cargo_type.\n\n"
    "Return ONLY the JSON array, no markdown fences, no explanation, "
    "no thinking tags.\n\n"
    "Text:\n<<<\n{text}\n>>>"
)


async def extract_rates_via_ollama(text: str) -> list[dict]:
    """Send text to Ollama and parse the extracted rates."""
    from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

    provider = OllamaProvider(host=OLLAMA_HOST, model="qwen3:8b")
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(text=text)

    response = await provider.generate(prompt)
    content = response.content.strip()

    # Strip <think>...</think> tags
    think_pattern = re.compile(r"<think>.*?</think>", re.DOTALL)
    content = think_pattern.sub("", content).strip()

    # Strip markdown fences
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            parsed = [parsed]
        return parsed
    except json.JSONDecodeError:
        return []


# -----------------------------------------------------------------------
# Ground truth: English contract excerpts with known rates
# -----------------------------------------------------------------------

ENGLISH_CONTRACT_EXCERPTS = [
    {
        "id": "en_1",
        "text": (
            "Contract C-2024-001: Standard cargo transport rate is "
            "EUR 0.45 per kilogram for all shipments within the EU corridor."
        ),
        "expected_rate": Decimal("0.45"),
        "expected_currency": "EUR",
    },
    {
        "id": "en_2",
        "text": (
            "As per agreement A-2024-015, the pharmaceutical cold chain "
            "transport rate shall be EUR 1.25 per kilogram, including "
            "temperature monitoring and insurance coverage."
        ),
        "expected_rate": Decimal("1.25"),
        "expected_currency": "EUR",
    },
    {
        "id": "en_3",
        "text": (
            "Container shipping rates for the Gdansk-Hamburg route: "
            "EUR 850.00 per standard 20ft container, effective from "
            "January 1, 2024 through December 31, 2024."
        ),
        "expected_rate": Decimal("850"),
        "expected_currency": "EUR",
    },
    {
        "id": "en_4",
        "text": (
            "Hazardous materials surcharge: an additional EUR 0.35 per "
            "kilogram applies on top of the base rate for all ADR-classified "
            "cargo. This surcharge is non-negotiable."
        ),
        "expected_rate": Decimal("0.35"),
        "expected_currency": "EUR",
    },
    {
        "id": "en_5",
        "text": (
            "Express delivery premium: for guaranteed next-day delivery, "
            "the rate is EUR 2.80 per kilogram. Standard delivery remains "
            "at the base contract rate."
        ),
        "expected_rate": Decimal("2.80"),
        "expected_currency": "EUR",
    },
]


# -----------------------------------------------------------------------
# Ground truth: Polish contract excerpts with known rates
# -----------------------------------------------------------------------

POLISH_CONTRACT_EXCERPTS = [
    {
        "id": "pl_1",
        "text": (
            "Umowa transportowa C-PL-001: Stawka za transport ladunkow "
            "standardowych wynosi EUR 0.52 za kilogram na trasie "
            "Wroclaw-Warszawa."
        ),
        "expected_rate": Decimal("0.52"),
        "expected_currency": "EUR",
    },
    {
        "id": "pl_2",
        "text": (
            "Zgodnie z aneksem nr 3 do umowy ramowej, stawka za transport "
            "ladunkow farmaceutycznych w kontrolowanej temperaturze wynosi "
            "EUR 1.85 za kilogram, wliczajac monitoring temperatury."
        ),
        "expected_rate": Decimal("1.85"),
        "expected_currency": "EUR",
    },
    {
        "id": "pl_3",
        "text": (
            "Taryfa za przewoz kontenerow na trasie Gdynia-Rotterdam: "
            "EUR 720.00 za kontener 20-stopowy (TEU). Stawka obowiazuje "
            "od 1 stycznia 2024 roku."
        ),
        "expected_rate": Decimal("720"),
        "expected_currency": "EUR",
    },
    {
        "id": "pl_4",
        "text": (
            "Doplata za materialy niebezpieczne klasy ADR: EUR 0.48 za "
            "kilogram ponad stawke bazowa. Doplata obowiazuje dla "
            "wszystkich ladunkow sklasyfikowanych jako ADR."
        ),
        "expected_rate": Decimal("0.48"),
        "expected_currency": "EUR",
    },
    {
        "id": "pl_5",
        "text": (
            "Stawka za transport ekspresowy z gwarancja dostawy nastepnego "
            "dnia roboczego: EUR 3.15 za kilogram. Transport standardowy "
            "pozostaje w cenie bazowej."
        ),
        "expected_rate": Decimal("3.15"),
        "expected_currency": "EUR",
    },
]


# -----------------------------------------------------------------------
# Tests: English extraction
# -----------------------------------------------------------------------


class TestLiveOllamaRateExtraction:
    """Live tests: Ollama extracts EUR rates from English contract text."""

    @pytest.mark.asyncio
    async def test_live_ollama_rate_extraction(self):
        """Send 5 real contract excerpts to Ollama, verify extracted rates.

        Ground truth: each excerpt has exactly one rate.
        Success criteria: at least 4/5 rates extracted correctly.
        """
        correct = 0
        results = []

        for excerpt in ENGLISH_CONTRACT_EXCERPTS:
            rates = await extract_rates_via_ollama(excerpt["text"])
            found_rate = None

            for r in rates:
                try:
                    rate_val = Decimal(str(r.get("rate", "")))
                    if rate_val == excerpt["expected_rate"]:
                        found_rate = rate_val
                        break
                except (InvalidOperation, ValueError):
                    continue

            if found_rate is not None:
                correct += 1

            results.append(
                {
                    "id": excerpt["id"],
                    "expected": str(excerpt["expected_rate"]),
                    "found": str(found_rate) if found_rate else "NOT FOUND",
                    "raw_rates": rates,
                }
            )

        # Report results for benchmark data
        print(f"\n  English extraction: {correct}/{len(ENGLISH_CONTRACT_EXCERPTS)}")
        for r in results:
            status = "PASS" if r["found"] != "NOT FOUND" else "FAIL"
            print(f"    [{status}] {r['id']}: expected={r['expected']}, got={r['found']}")

        # At least 4/5 must match (80% threshold)
        assert correct >= 4, (
            f"Only {correct}/{len(ENGLISH_CONTRACT_EXCERPTS)} rates extracted correctly. "
            f"Results: {results}"
        )


# -----------------------------------------------------------------------
# Tests: Polish extraction
# -----------------------------------------------------------------------


class TestLiveOllamaPolishRateExtraction:
    """Live tests: Ollama extracts EUR rates from Polish contract text."""

    @pytest.mark.asyncio
    async def test_live_ollama_polish_rate_extraction(self):
        """Send 5 Polish contract excerpts to Ollama, verify extracted rates.

        This is the critical test for air-gapped deployment with a Polish
        logistics company. If qwen3:8b cannot extract rates from Polish
        contract text, the air-gapped mode is not viable for LogiCore.

        Success criteria: at least 4/5 rates extracted correctly.
        """
        correct = 0
        results = []

        for excerpt in POLISH_CONTRACT_EXCERPTS:
            rates = await extract_rates_via_ollama(excerpt["text"])
            found_rate = None

            for r in rates:
                try:
                    rate_val = Decimal(str(r.get("rate", "")))
                    if rate_val == excerpt["expected_rate"]:
                        found_rate = rate_val
                        break
                except (InvalidOperation, ValueError):
                    continue

            if found_rate is not None:
                correct += 1

            results.append(
                {
                    "id": excerpt["id"],
                    "expected": str(excerpt["expected_rate"]),
                    "found": str(found_rate) if found_rate else "NOT FOUND",
                    "raw_rates": rates,
                }
            )

        # Report results for benchmark data
        print(f"\n  Polish extraction: {correct}/{len(POLISH_CONTRACT_EXCERPTS)}")
        for r in results:
            status = "PASS" if r["found"] != "NOT FOUND" else "FAIL"
            print(f"    [{status}] {r['id']}: expected={r['expected']}, got={r['found']}")

        # At least 4/5 must match (80% threshold)
        assert correct >= 4, (
            f"Only {correct}/{len(POLISH_CONTRACT_EXCERPTS)} Polish rates extracted correctly. "
            f"Results: {results}"
        )
