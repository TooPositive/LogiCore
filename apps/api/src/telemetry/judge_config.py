"""Judge configuration: model family separation and bias mitigation settings.

The critical rule: judge and generator must be from DIFFERENT model families.
GPT-5-mini judging GPT-5.2 is STILL same-family self-preference bias.

Domain-agnostic: model family registry is configurable via FAMILY_PATTERNS.
Only the default pattern set is domain-specific (OpenAI, Anthropic, etc.).
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ModelFamily(StrEnum):
    """Known model families for self-preference bias detection."""

    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    META = "META"
    COHERE = "COHERE"
    MISTRAL = "MISTRAL"
    UNKNOWN = "UNKNOWN"


# Prefix-based family detection. Order matters — first match wins.
# Configurable: replace this dict for deployments with custom model names.
FAMILY_PATTERNS: dict[str, ModelFamily] = {
    "gpt-": ModelFamily.OPENAI,
    "o1-": ModelFamily.OPENAI,
    "o3-": ModelFamily.OPENAI,
    "claude-": ModelFamily.ANTHROPIC,
    "llama-": ModelFamily.META,
    "command-r": ModelFamily.COHERE,
    "mistral-": ModelFamily.MISTRAL,
}


# Exact-match overrides for models that don't follow prefix patterns.
# Use register_model_family() to add entries at runtime.
_EXACT_FAMILY_OVERRIDES: dict[str, ModelFamily] = {}


def register_model_family(model_name: str, family: ModelFamily) -> None:
    """Register an exact model name to a family (for fine-tuned/custom models).

    Use this when model names don't follow standard prefix patterns:
    - Fine-tuned: "ft:gpt-5.2:logicore:2026" -> OPENAI
    - Azure deployments: "logicore-gpt52-deployment" -> OPENAI
    - Local models: "qwen3:8b" -> META (or custom)

    This is the recommended way to handle deployment-specific model names
    that can't be identified by prefix matching alone.

    Args:
        model_name: Exact model identifier (case-insensitive matching).
        family: The model family to assign.
    """
    _EXACT_FAMILY_OVERRIDES[model_name.lower()] = family


def clear_family_overrides() -> None:
    """Clear all registered family overrides (for testing)."""
    _EXACT_FAMILY_OVERRIDES.clear()


def get_model_family(
    model_name: str,
    family_patterns: dict[str, ModelFamily] | None = None,
) -> ModelFamily:
    """Identify the model family from a model name.

    Resolution order:
    1. Exact-match overrides (from register_model_family)
    2. Prefix matching against FAMILY_PATTERNS
    3. ModelFamily.UNKNOWN

    Case-insensitive throughout.

    Args:
        model_name: The model identifier (e.g., "gpt-5.2", "claude-sonnet-4.6").
        family_patterns: Custom pattern dict. Defaults to FAMILY_PATTERNS.

    Returns:
        The identified ModelFamily.
    """
    lower_name = model_name.lower()

    # 1. Check exact-match overrides first
    if lower_name in _EXACT_FAMILY_OVERRIDES:
        return _EXACT_FAMILY_OVERRIDES[lower_name]

    # 2. Prefix matching
    patterns = family_patterns or FAMILY_PATTERNS
    for prefix, family in patterns.items():
        if lower_name.startswith(prefix):
            return family
    return ModelFamily.UNKNOWN


def validate_judge_generator_independence(
    judge_model: str,
    generator_model: str,
    family_patterns: dict[str, ModelFamily] | None = None,
) -> bool:
    """Validate that judge and generator are from different model families.

    Returns True only if:
    1. Both models map to known families (not UNKNOWN)
    2. The families are different

    GPT-5-mini judging GPT-5.2 output returns False (same OPENAI family).
    Claude-sonnet-4.6 judging GPT-5.2 output returns True (ANTHROPIC != OPENAI).

    Args:
        judge_model: The model used for evaluation/judging.
        generator_model: The model that generated the output being judged.
        family_patterns: Custom pattern dict for family detection.

    Returns:
        True if families are different and both are known. False otherwise.
    """
    judge_family = get_model_family(judge_model, family_patterns)
    generator_family = get_model_family(generator_model, family_patterns)

    # Unknown family cannot be validated as independent
    if judge_family == ModelFamily.UNKNOWN or generator_family == ModelFamily.UNKNOWN:
        return False

    return judge_family != generator_family


class JudgeConfig(BaseModel):
    """Configuration for LLM-as-Judge evaluation.

    Encapsulates judge model selection, bias mitigation settings,
    and calibration thresholds. Domain-agnostic — works for any
    evaluation domain by adjusting thresholds and model names.
    """

    judge_model: str
    generator_model: str

    # Bias mitigation settings
    position_swap: bool = True  # Run each comparison twice with A/B swapped
    max_position_bias_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    max_verbosity_bias_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    max_self_preference_rate: float = Field(default=0.10, ge=0.0, le=1.0)

    # Human calibration threshold
    min_spearman_correlation: float = Field(default=0.85, ge=-1.0, le=1.0)

    @property
    def judge_family(self) -> ModelFamily:
        """Get the model family of the judge."""
        return get_model_family(self.judge_model)

    @property
    def generator_family(self) -> ModelFamily:
        """Get the model family of the generator."""
        return get_model_family(self.generator_model)

    @property
    def is_cross_family(self) -> bool:
        """Check if judge and generator are from different families.

        This is the critical independence check. Same-family judging
        (e.g., GPT-5-mini judging GPT-5.2) exhibits 10-15% self-preference
        bias in published benchmarks.
        """
        return validate_judge_generator_independence(
            self.judge_model, self.generator_model
        )
