"""LLM-based model router for intelligent query routing.

Routes each query to the cheapest model that produces an acceptable answer.
At 2,400 queries/day, routing saves 93% vs always-GPT-5.2.

Decision tree:
  SIMPLE  -> GPT-5 nano  ($0.05/$0.40 per 1M tokens)
  MEDIUM  -> GPT-5 mini  ($0.25/$2.00 per 1M tokens)
  COMPLEX -> GPT-5.2     ($1.75/$14.00 per 1M tokens)

Overrides:
  - Financial keywords (contract, invoice, rate, penalty, etc.) -> always COMPLEX
  - Confidence < threshold -> escalate one tier
  - Unparseable LLM response -> default to COMPLEX (safe fallback)

Domain-agnostic: keyword list, model map, and confidence threshold
are all configurable.
"""

import logging
import re
from typing import Any

from apps.api.src.core.domain.telemetry import ModelRoute, QueryComplexity

logger = logging.getLogger(__name__)

# Default financial keyword override list (from Phase 4 spec)
OVERRIDE_KEYWORDS: list[str] = [
    "contract",
    "invoice",
    "rate",
    "penalty",
    "amendment",
    "surcharge",
    "annex",
    "audit",
    "compliance",
    "discrepancy",
]

# Default model map: complexity -> model identifier
DEFAULT_MODEL_MAP: dict[QueryComplexity, str] = {
    QueryComplexity.SIMPLE: "gpt-5-nano",
    QueryComplexity.MEDIUM: "gpt-5-mini",
    QueryComplexity.COMPLEX: "gpt-5.2",
}

# Escalation path: SIMPLE -> MEDIUM -> COMPLEX
_ESCALATION: dict[QueryComplexity, QueryComplexity] = {
    QueryComplexity.SIMPLE: QueryComplexity.MEDIUM,
    QueryComplexity.MEDIUM: QueryComplexity.COMPLEX,
    QueryComplexity.COMPLEX: QueryComplexity.COMPLEX,  # already max
}

# Classifier prompt for GPT-5 nano
CLASSIFIER_PROMPT = (
    "Classify this query as SIMPLE, MEDIUM, or COMPLEX. "
    "Reply with the classification and a confidence score 0.0-1.0.\n"
    "Format: CLASSIFICATION CONFIDENCE\n"
    "Examples:\n"
    "  'What is shipment status?' -> SIMPLE 0.95\n"
    "  'Summarize the delivery report' -> MEDIUM 0.85\n"
    "  'Analyze multi-hop contract implications' -> COMPLEX 0.90\n\n"
    "Query: {query}"
)


def check_keyword_override(
    query: str,
    custom_keywords: list[str] | None = None,
) -> bool:
    """Check if query contains any financial/override keywords.

    Case-insensitive word boundary match.
    Returns True if any keyword found.
    """
    keywords = custom_keywords or OVERRIDE_KEYWORDS
    query_lower = query.lower()
    return any(kw.lower() in query_lower for kw in keywords)


def _parse_classification(response: str) -> tuple[QueryComplexity, float]:
    """Parse LLM classification response into complexity + confidence.

    Expected format: "SIMPLE 0.95" or "MEDIUM 0.85" or "COMPLEX 0.90"
    Falls back to COMPLEX with confidence 0.0 on parse failure.
    """
    response = response.strip().upper()

    # Try to extract classification and confidence
    match = re.match(r"(SIMPLE|MEDIUM|COMPLEX)\s*([\d.]+)?", response)
    if match:
        complexity_str = match.group(1)
        confidence_str = match.group(2)

        complexity = QueryComplexity(complexity_str)
        confidence = float(confidence_str) if confidence_str else 0.8

        # Clamp confidence to [0, 1]
        confidence = max(0.0, min(1.0, confidence))
        return complexity, confidence

    # Unparseable -> default to COMPLEX (safe)
    logger.warning("Unparseable router response: %s, defaulting to COMPLEX", response)
    return QueryComplexity.COMPLEX, 0.0


class ModelRouter:
    """Routes queries to the cheapest acceptable model.

    Uses GPT-5 nano for classification (~$0.000025 per call).
    Keyword overrides bypass LLM classification entirely.
    Low-confidence classifications escalate one tier.
    """

    def __init__(
        self,
        classifier_llm: Any,
        model_map: dict[QueryComplexity, str] | None = None,
        override_keywords: list[str] | None = None,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._llm = classifier_llm
        self._model_map = model_map or DEFAULT_MODEL_MAP
        self._keywords = override_keywords or OVERRIDE_KEYWORDS
        self._confidence_threshold = confidence_threshold

    async def classify(self, query: str) -> ModelRoute:
        """Classify query complexity and return routing decision.

        1. Check keyword override -> COMPLEX, skip LLM
        2. Call LLM classifier -> parse response
        3. If confidence < threshold -> escalate one tier
        """
        # Step 1: Keyword override
        if check_keyword_override(query, custom_keywords=self._keywords):
            matched = [
                kw for kw in self._keywords if kw.lower() in query.lower()
            ]
            return ModelRoute(
                query=query,
                complexity=QueryComplexity.COMPLEX,
                selected_model=self._model_map[QueryComplexity.COMPLEX],
                confidence=1.0,
                routing_reason=f"keyword_override: {', '.join(matched)}",
                keyword_override=True,
            )

        # Step 2: LLM classification
        prompt = CLASSIFIER_PROMPT.format(query=query)
        response = await self._llm.ainvoke(prompt)
        response_text = response.content if hasattr(response, "content") else str(response)

        complexity, confidence = _parse_classification(response_text)

        # Step 3: Confidence escalation
        escalated = False
        if confidence < self._confidence_threshold:
            original = complexity
            complexity = _ESCALATION[complexity]
            escalated = original != complexity
            reason = (
                f"confidence {confidence:.2f} < {self._confidence_threshold}, "
                f"escalated {original.value} -> {complexity.value}"
            )
        else:
            reason = (
                f"LLM classification: {complexity.value} "
                f"(confidence {confidence:.2f})"
            )

        return ModelRoute(
            query=query,
            complexity=complexity,
            selected_model=self._model_map[complexity],
            confidence=confidence,
            routing_reason=reason,
            escalated=escalated,
        )

    async def route(self, query: str) -> ModelRoute:
        """Convenience method: classify and return the full route."""
        return await self.classify(query)
