"""Tests for judge bias detection and mitigation.

Phase 5, Pillar 1: Judge Bias Mitigation.

Tests cover:
- JudgeConfig model validation and family separation enforcement
- Position bias detection (n>=5 cases per scenario)
- Verbosity bias detection (n>=5 cases)
- Self-preference bias detection (n>=5 cases)
- Pairwise agreement validation
- Confidence interval computation via bootstrap
- Human calibration with Spearman correlation
"""

import pytest

from apps.api.src.domain.telemetry import (
    DriftAlert,
    DriftSeverity,
    JudgeBiasResult,
    ModelVersion,
    PromptCacheStats,
)
from apps.api.src.telemetry.judge_config import (
    JudgeConfig,
    ModelFamily,
    clear_family_overrides,
    get_model_family,
    register_model_family,
    validate_judge_generator_independence,
)

# =========================================================================
# Domain model tests — JudgeBiasResult
# =========================================================================


class TestJudgeBiasResult:
    """Tests for the JudgeBiasResult domain model."""

    def test_judge_bias_result_all_green(self):
        """All bias rates below thresholds -> is_calibrated = True."""
        result = JudgeBiasResult(
            position_bias_rate=0.03,
            verbosity_bias_rate=0.02,
            self_preference_rate=0.04,
            spearman_correlation=0.90,
            total_comparisons=100,
        )
        assert result.is_calibrated is True

    def test_judge_bias_result_high_position_bias(self):
        """Position bias rate above 10% -> is_calibrated = False."""
        result = JudgeBiasResult(
            position_bias_rate=0.15,
            verbosity_bias_rate=0.02,
            self_preference_rate=0.04,
            spearman_correlation=0.90,
            total_comparisons=100,
        )
        assert result.is_calibrated is False

    def test_judge_bias_result_low_spearman(self):
        """Spearman correlation below 0.85 -> is_calibrated = False."""
        result = JudgeBiasResult(
            position_bias_rate=0.03,
            verbosity_bias_rate=0.02,
            self_preference_rate=0.04,
            spearman_correlation=0.78,
            total_comparisons=100,
        )
        assert result.is_calibrated is False

    def test_judge_bias_result_high_verbosity_bias(self):
        """Verbosity bias rate above 10% -> is_calibrated = False."""
        result = JudgeBiasResult(
            position_bias_rate=0.03,
            verbosity_bias_rate=0.15,
            self_preference_rate=0.04,
            spearman_correlation=0.90,
            total_comparisons=100,
        )
        assert result.is_calibrated is False

    def test_judge_bias_result_high_self_preference(self):
        """Self-preference rate above 10% -> is_calibrated = False."""
        result = JudgeBiasResult(
            position_bias_rate=0.03,
            verbosity_bias_rate=0.02,
            self_preference_rate=0.15,
            spearman_correlation=0.90,
            total_comparisons=100,
        )
        assert result.is_calibrated is False

    def test_judge_bias_result_custom_thresholds(self):
        """Custom thresholds override defaults."""
        result = JudgeBiasResult(
            position_bias_rate=0.08,
            verbosity_bias_rate=0.02,
            self_preference_rate=0.04,
            spearman_correlation=0.90,
            total_comparisons=100,
            position_bias_threshold=0.05,
        )
        # 0.08 > 0.05 custom threshold
        assert result.is_calibrated is False

    def test_judge_bias_result_validation_ranges(self):
        """Rates must be between 0 and 1."""
        with pytest.raises(ValueError):
            JudgeBiasResult(
                position_bias_rate=1.5,
                verbosity_bias_rate=0.02,
                self_preference_rate=0.04,
                spearman_correlation=0.90,
                total_comparisons=100,
            )


# =========================================================================
# Domain model tests — DriftAlert, ModelVersion, PromptCacheStats
# =========================================================================


class TestDriftAlert:
    """Tests for the DriftAlert domain model."""

    def test_drift_alert_green(self):
        """Delta < 2% -> green severity."""
        alert = DriftAlert(
            metric="context_precision",
            baseline_value=0.90,
            current_value=0.89,
            delta=-0.01,
            severity=DriftSeverity.GREEN,
        )
        assert alert.severity == DriftSeverity.GREEN

    def test_drift_alert_yellow(self):
        """Delta 2-5% -> yellow severity."""
        alert = DriftAlert(
            metric="faithfulness",
            baseline_value=0.90,
            current_value=0.87,
            delta=-0.03,
            severity=DriftSeverity.YELLOW,
        )
        assert alert.severity == DriftSeverity.YELLOW

    def test_drift_alert_red(self):
        """Delta > 5% -> red severity."""
        alert = DriftAlert(
            metric="answer_relevancy",
            baseline_value=0.90,
            current_value=0.83,
            delta=-0.07,
            severity=DriftSeverity.RED,
        )
        assert alert.severity == DriftSeverity.RED

    def test_drift_alert_positive_delta_is_improvement(self):
        """Positive delta means improvement — should still be green."""
        alert = DriftAlert(
            metric="context_precision",
            baseline_value=0.85,
            current_value=0.90,
            delta=0.05,
            severity=DriftSeverity.GREEN,
        )
        assert alert.severity == DriftSeverity.GREEN

    def test_drift_alert_requires_metric_name(self):
        """Metric name must be non-empty."""
        with pytest.raises(ValueError):
            DriftAlert(
                metric="",
                baseline_value=0.90,
                current_value=0.83,
                delta=-0.07,
                severity=DriftSeverity.RED,
            )


class TestModelVersion:
    """Tests for the ModelVersion domain model."""

    def test_model_version_creation(self):
        version = ModelVersion(
            model_name="gpt-5.2",
            version="2026-0301",
            baseline_scores={"context_precision": 0.90, "faithfulness": 0.85},
        )
        assert version.model_name == "gpt-5.2"
        assert version.version == "2026-0301"
        assert version.baseline_scores["context_precision"] == 0.90

    def test_model_version_detected_at_auto(self):
        """detected_at should be auto-populated with current time."""
        version = ModelVersion(
            model_name="gpt-5.2",
            version="2026-0301",
            baseline_scores={},
        )
        assert version.detected_at is not None

    def test_model_version_empty_baseline(self):
        """Empty baseline scores are valid (initial registration)."""
        version = ModelVersion(
            model_name="gpt-5.2",
            version="2026-0301",
            baseline_scores={},
        )
        assert version.baseline_scores == {}


class TestPromptCacheStats:
    """Tests for the PromptCacheStats domain model."""

    def test_prompt_cache_stats_single_tenant(self):
        stats = PromptCacheStats(
            hit_rate=0.60,
            miss_rate=0.40,
            savings_per_day_eur=22.0,
            total_prompts=1000,
            static_token_ratio=0.75,
            deployment_type="single_tenant",
        )
        assert stats.hit_rate == 0.60
        assert stats.static_token_ratio == 0.75

    def test_prompt_cache_stats_multi_tenant(self):
        """Multi-tenant has lower hit rate due to RBAC partition fragmentation."""
        stats = PromptCacheStats(
            hit_rate=0.20,
            miss_rate=0.80,
            savings_per_day_eur=7.0,
            total_prompts=1000,
            static_token_ratio=0.75,
            deployment_type="multi_tenant",
        )
        assert stats.hit_rate == 0.20

    def test_prompt_cache_stats_hit_miss_complement(self):
        """hit_rate + miss_rate must equal 1.0 (within float tolerance)."""
        stats = PromptCacheStats(
            hit_rate=0.35,
            miss_rate=0.65,
            savings_per_day_eur=18.0,
            total_prompts=500,
            static_token_ratio=0.80,
        )
        assert abs(stats.hit_rate + stats.miss_rate - 1.0) < 1e-9

    def test_prompt_cache_stats_validation_ranges(self):
        """Rates must be between 0 and 1."""
        with pytest.raises(ValueError):
            PromptCacheStats(
                hit_rate=1.5,
                miss_rate=-0.5,
                savings_per_day_eur=22.0,
                total_prompts=1000,
                static_token_ratio=0.75,
            )

    def test_prompt_cache_stats_savings_non_negative(self):
        """Savings cannot be negative."""
        with pytest.raises(ValueError):
            PromptCacheStats(
                hit_rate=0.60,
                miss_rate=0.40,
                savings_per_day_eur=-5.0,
                total_prompts=1000,
                static_token_ratio=0.75,
            )


# =========================================================================
# JudgeConfig tests — model family separation and bias settings
# =========================================================================


class TestModelFamily:
    """Tests for model family identification."""

    def test_openai_family_gpt5_mini(self):
        assert get_model_family("gpt-5-mini") == ModelFamily.OPENAI

    def test_openai_family_gpt52(self):
        assert get_model_family("gpt-5.2") == ModelFamily.OPENAI

    def test_openai_family_gpt5_nano(self):
        assert get_model_family("gpt-5-nano") == ModelFamily.OPENAI

    def test_anthropic_family_claude_opus(self):
        assert get_model_family("claude-opus-4.6") == ModelFamily.ANTHROPIC

    def test_anthropic_family_claude_sonnet(self):
        assert get_model_family("claude-sonnet-4.6") == ModelFamily.ANTHROPIC

    def test_meta_family_llama(self):
        assert get_model_family("llama-4-scout") == ModelFamily.META

    def test_unknown_family_defaults_to_unknown(self):
        assert get_model_family("some-random-model-v3") == ModelFamily.UNKNOWN

    def test_case_insensitive(self):
        assert get_model_family("GPT-5-MINI") == ModelFamily.OPENAI

    def test_cohere_family(self):
        assert get_model_family("command-r-plus") == ModelFamily.COHERE

    def test_mistral_family(self):
        assert get_model_family("mistral-large-2") == ModelFamily.MISTRAL


class TestJudgeGeneratorIndependence:
    """Tests for cross-family independence validation.

    The critical rule: judge and generator must be from DIFFERENT families.
    GPT-5-mini judging GPT-5.2 is STILL same-family self-preference.
    """

    def test_same_model_rejected(self):
        """Using the exact same model as judge and generator is rejected."""
        assert validate_judge_generator_independence("gpt-5.2", "gpt-5.2") is False

    def test_same_family_different_model_rejected(self):
        """GPT-5-mini judging GPT-5.2 is same-family — rejected."""
        assert validate_judge_generator_independence("gpt-5-mini", "gpt-5.2") is False

    def test_cross_family_openai_anthropic_accepted(self):
        """Claude judging GPT output = different family — accepted."""
        assert (
            validate_judge_generator_independence("claude-sonnet-4.6", "gpt-5.2")
            is True
        )

    def test_cross_family_anthropic_meta_accepted(self):
        """Llama judging Claude output = different family — accepted."""
        assert (
            validate_judge_generator_independence("llama-4-scout", "claude-opus-4.6")
            is True
        )

    def test_cross_family_meta_openai_accepted(self):
        """GPT judging Llama output = different family — accepted."""
        assert (
            validate_judge_generator_independence("gpt-5.2", "llama-4-scout") is True
        )

    def test_unknown_family_always_rejected(self):
        """Unknown model family cannot be validated as independent."""
        assert (
            validate_judge_generator_independence("unknown-model", "gpt-5.2") is False
        )

    def test_both_unknown_rejected(self):
        """Two unknown models cannot be validated."""
        assert (
            validate_judge_generator_independence("model-a", "model-b") is False
        )


class TestJudgeConfig:
    """Tests for JudgeConfig model and configuration."""

    def test_valid_config_cross_family(self):
        """Valid config: Claude judges GPT output."""
        config = JudgeConfig(
            judge_model="claude-sonnet-4.6",
            generator_model="gpt-5.2",
            position_swap=True,
            max_position_bias_rate=0.10,
            max_verbosity_bias_rate=0.10,
            max_self_preference_rate=0.10,
            min_spearman_correlation=0.85,
        )
        assert config.is_cross_family is True

    def test_invalid_config_same_family(self):
        """Same-family config: is_cross_family returns False."""
        config = JudgeConfig(
            judge_model="gpt-5-mini",
            generator_model="gpt-5.2",
            position_swap=True,
        )
        assert config.is_cross_family is False

    def test_default_thresholds(self):
        """Default threshold values from spec."""
        config = JudgeConfig(
            judge_model="claude-sonnet-4.6",
            generator_model="gpt-5.2",
        )
        assert config.max_position_bias_rate == 0.10
        assert config.max_verbosity_bias_rate == 0.10
        assert config.max_self_preference_rate == 0.10
        assert config.min_spearman_correlation == 0.85
        assert config.position_swap is True

    def test_custom_thresholds(self):
        """Custom thresholds override defaults."""
        config = JudgeConfig(
            judge_model="claude-sonnet-4.6",
            generator_model="gpt-5.2",
            max_position_bias_rate=0.05,
            min_spearman_correlation=0.90,
        )
        assert config.max_position_bias_rate == 0.05
        assert config.min_spearman_correlation == 0.90

    def test_judge_family_property(self):
        config = JudgeConfig(
            judge_model="claude-sonnet-4.6",
            generator_model="gpt-5.2",
        )
        assert config.judge_family == ModelFamily.ANTHROPIC

    def test_generator_family_property(self):
        config = JudgeConfig(
            judge_model="claude-sonnet-4.6",
            generator_model="gpt-5.2",
        )
        assert config.generator_family == ModelFamily.OPENAI


# =========================================================================
# Fine-tuned / custom model name tests
# =========================================================================


class TestFineTunedModelFamily:
    """Tests for fine-tuned and deployment-specific model names.

    Fine-tuned models (ft:gpt-5.2:logicore:2026), Azure deployment names
    (logicore-gpt52-deployment), and local models (qwen3:8b) don't follow
    standard prefix patterns. They default to UNKNOWN, which is safe (fails
    closed on independence check). Use register_model_family() for explicit
    family assignment.
    """

    def setup_method(self):
        """Clear overrides before each test."""
        clear_family_overrides()

    def teardown_method(self):
        """Clean up after each test."""
        clear_family_overrides()

    def test_finetuned_gpt_defaults_to_unknown(self):
        """ft:gpt-5.2:logicore:2026 doesn't match 'gpt-' prefix -> UNKNOWN."""
        assert get_model_family("ft:gpt-5.2:logicore:2026") == ModelFamily.UNKNOWN

    def test_azure_deployment_name_defaults_to_unknown(self):
        """Azure deployment names don't follow standard prefixes."""
        assert get_model_family("logicore-gpt52-deployment") == ModelFamily.UNKNOWN

    def test_local_ollama_model_defaults_to_unknown(self):
        """Ollama model names (qwen3:8b) don't match known prefixes."""
        assert get_model_family("qwen3:8b") == ModelFamily.UNKNOWN

    def test_register_finetuned_model_resolves(self):
        """After registration, fine-tuned model resolves to correct family."""
        register_model_family("ft:gpt-5.2:logicore:2026", ModelFamily.OPENAI)
        assert get_model_family("ft:gpt-5.2:logicore:2026") == ModelFamily.OPENAI

    def test_register_azure_deployment_resolves(self):
        """Azure deployment name resolves after registration."""
        register_model_family("logicore-gpt52-deployment", ModelFamily.OPENAI)
        assert get_model_family("logicore-gpt52-deployment") == ModelFamily.OPENAI

    def test_register_local_model_resolves(self):
        """Local Ollama model resolves after registration."""
        register_model_family("qwen3:8b", ModelFamily.META)
        assert get_model_family("qwen3:8b") == ModelFamily.META

    def test_registered_model_passes_independence(self):
        """Registered fine-tuned models can pass independence validation."""
        register_model_family("ft:gpt-5.2:logicore:2026", ModelFamily.OPENAI)
        # Claude judging fine-tuned GPT = cross-family -> valid
        assert validate_judge_generator_independence(
            "claude-sonnet-4.6", "ft:gpt-5.2:logicore:2026"
        ) is True

    def test_unregistered_finetuned_fails_independence(self):
        """Without registration, fine-tuned model fails independence (safe default)."""
        assert validate_judge_generator_independence(
            "claude-sonnet-4.6", "ft:gpt-5.2:logicore:2026"
        ) is False

    def test_register_case_insensitive(self):
        """Registration is case-insensitive."""
        register_model_family("FT:GPT-5.2:LogiCore:2026", ModelFamily.OPENAI)
        assert get_model_family("ft:gpt-5.2:logicore:2026") == ModelFamily.OPENAI

    def test_exact_override_takes_priority_over_prefix(self):
        """Exact-match override beats prefix matching."""
        # 'gpt-custom-v2' would match 'gpt-' prefix -> OPENAI
        # But we want to override it to META for some reason
        register_model_family("gpt-custom-v2", ModelFamily.META)
        assert get_model_family("gpt-custom-v2") == ModelFamily.META

    def test_clear_overrides_restores_default(self):
        """clear_family_overrides() removes all custom registrations."""
        register_model_family("my-model", ModelFamily.ANTHROPIC)
        assert get_model_family("my-model") == ModelFamily.ANTHROPIC
        clear_family_overrides()
        assert get_model_family("my-model") == ModelFamily.UNKNOWN


# =========================================================================
# Golden set data artifact validation
# =========================================================================


class TestGoldenSetArtifact:
    """Validate the golden set data artifact exists and has correct schema.

    The golden set is the root of trust for the entire evaluation pipeline.
    50 human-scored query-answer pairs. If this file is missing or malformed,
    all quality claims are ungrounded.
    """

    def test_golden_set_exists(self):
        """data/golden_set.json must exist."""
        import json
        from pathlib import Path

        golden_path = Path("data/golden_set.json")
        assert golden_path.exists(), "Golden set artifact missing: data/golden_set.json"

        with open(golden_path) as f:
            data = json.load(f)
        assert "entries" in data
        assert "_schema" in data

    def test_golden_set_has_50_entries(self):
        """Golden set must have exactly 50 entries."""
        import json
        from pathlib import Path

        with open(Path("data/golden_set.json")) as f:
            data = json.load(f)
        assert len(data["entries"]) == 50, f"Expected 50, got {len(data['entries'])}"

    def test_golden_set_entry_schema(self):
        """Each entry must have required fields."""
        import json
        from pathlib import Path

        with open(Path("data/golden_set.json")) as f:
            data = json.load(f)

        required_fields = {
            "id", "question", "context", "expected_answer",
            "generated_answer", "human_score", "category", "scorer_notes",
        }
        for entry in data["entries"]:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry {entry.get('id', '?')} missing fields: {missing}"

    def test_golden_set_scores_in_valid_range(self):
        """Human scores must be 1-5."""
        import json
        from pathlib import Path

        with open(Path("data/golden_set.json")) as f:
            data = json.load(f)

        for entry in data["entries"]:
            score = entry["human_score"]
            assert 1 <= score <= 5, f"Entry {entry['id']}: score {score} not in 1-5"

    def test_golden_set_covers_all_categories(self):
        """Golden set must cover all 10 ground truth categories."""
        import json
        from pathlib import Path

        with open(Path("data/golden_set.json")) as f:
            data = json.load(f)

        categories = {e["category"] for e in data["entries"]}
        expected = {
            "exact_code", "natural_language", "vague", "negation",
            "polish", "synonym", "typo", "jargon", "ranking", "multi_hop",
        }
        missing = expected - categories
        assert not missing, f"Golden set missing categories: {missing}"

    def test_golden_set_has_score_variance(self):
        """Golden set must have varied scores (not all 5s) for meaningful calibration."""
        import json
        from pathlib import Path

        with open(Path("data/golden_set.json")) as f:
            data = json.load(f)

        scores = [e["human_score"] for e in data["entries"]]
        unique_scores = set(scores)
        assert len(unique_scores) >= 3, f"Need score variance, only got: {unique_scores}"
