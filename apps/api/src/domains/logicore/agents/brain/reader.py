"""Reader Agent -- extracts contract rates via RAG + LLM.

Uses Phase 1/2 RAG retriever to find contract clauses, then
an LLM to extract structured rate data from the retrieved text.

All dependencies (retriever, LLM) are injected -- no hardcoded
API clients or credentials.
"""

import json
import logging
import re
from decimal import Decimal, InvalidOperation

from apps.api.src.domains.logicore.models.audit import ContractRate

logger = logging.getLogger(__name__)

# Patterns to neutralize in external content before LLM prompts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"new\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
]


def _sanitize_for_prompt(text: str) -> str:
    """Sanitize external content before including in LLM prompts."""
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("", text)
    # Truncate to reasonable length
    return text[:2000]


class ReaderAgent:
    """Extracts contract rates from the RAG pipeline.

    Idempotent: same (contract_id, cargo_type) always produces the same result,
    given the same corpus state. Safe for crash recovery re-execution.
    """

    def __init__(self, retriever, llm) -> None:
        self._retriever = retriever
        self._llm = llm

    async def extract_rates(
        self, contract_id: str, cargo_type: str
    ) -> list[ContractRate]:
        """Extract rates for a contract from the RAG corpus.

        Returns empty list if no matching contracts found or LLM fails to parse.
        """
        safe_contract_id = _sanitize_for_prompt(contract_id)
        safe_cargo_type = _sanitize_for_prompt(cargo_type)

        query = f"contract {safe_contract_id} rate for {safe_cargo_type} cargo"
        results = await self._retriever.search(query)

        if not results:
            return []

        context = "\n---\n".join(
            _sanitize_for_prompt(r.content) for r in results
        )

        prompt = (
            "Extract all contract rates from the following contract text. "
            "Return a JSON array of objects with these fields: "
            "contract_id, rate (numeric string), currency, unit, "
            "cargo_type, min_volume (numeric string or null), "
            "clearance_level (int 1-4).\n\n"
            "Return ONLY the JSON array, no markdown, no explanation.\n\n"
            f"Contract text:\n<<<\n{context}\n>>>"
        )

        try:
            response = await self._llm.ainvoke(prompt)
            content = response.content.strip()

            # Strip <think>...</think> tags (common in Ollama/qwen3 output)
            think_pattern = re.compile(
                r"<think>.*?</think>", re.DOTALL
            )
            content = think_pattern.sub("", content).strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            parsed = json.loads(content)
            if not isinstance(parsed, list):
                parsed = [parsed]

            rates = []
            for item in parsed:
                try:
                    rate = ContractRate(
                        contract_id=item["contract_id"],
                        rate=Decimal(str(item["rate"])),
                        currency=item["currency"],
                        unit=item["unit"],
                        cargo_type=item.get("cargo_type"),
                        min_volume=(
                            Decimal(str(item["min_volume"]))
                            if item.get("min_volume")
                            else None
                        ),
                        clearance_level=item.get("clearance_level", 1),
                    )
                    rates.append(rate)
                except (KeyError, InvalidOperation, ValueError) as e:
                    logger.warning("Failed to parse rate item %s: %s", item, e)
                    continue

            return rates

        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning("LLM response was not valid JSON: %s", e)
            return []
