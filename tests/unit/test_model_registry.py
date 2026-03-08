"""Tests for the model version registry.

Phase 5, Pillar 2: Drift Detection — model_registry.py.

Tests cover:
- Version registration and retrieval
- Baseline score CRUD
- Version change detection
- History tracking
- Multiple model support
"""

import pytest

from apps.api.src.core.domain.telemetry import ModelVersion
from apps.api.src.core.telemetry.model_registry import ModelVersionRegistry


class TestModelVersionRegistry:
    """Tests for ModelVersionRegistry — version tracking and baseline CRUD."""

    def test_register_new_model_version(self):
        """Register a new model version with baseline scores."""
        registry = ModelVersionRegistry()
        registry.register(
            model_name="gpt-5.2",
            version="2026-0301",
            baseline_scores={"context_precision": 0.90, "faithfulness": 0.85},
        )
        version = registry.get_current_version("gpt-5.2")
        assert version is not None
        assert version.version == "2026-0301"
        assert version.baseline_scores["context_precision"] == 0.90

    def test_register_updates_current_version(self):
        """Registering a new version replaces the current one."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "2026-0301", {"precision": 0.90})
        registry.register("gpt-5.2", "2026-0415", {"precision": 0.87})

        version = registry.get_current_version("gpt-5.2")
        assert version.version == "2026-0415"
        assert version.baseline_scores["precision"] == 0.87

    def test_get_current_version_not_registered(self):
        """Getting a version for an unregistered model returns None."""
        registry = ModelVersionRegistry()
        assert registry.get_current_version("unknown-model") is None

    def test_get_baseline_scores(self):
        """Retrieve baseline scores for the current version."""
        registry = ModelVersionRegistry()
        registry.register(
            "gpt-5.2",
            "2026-0301",
            {"context_precision": 0.90, "faithfulness": 0.85, "answer_relevancy": 0.88},
        )
        scores = registry.get_baseline_scores("gpt-5.2")
        assert scores == {
            "context_precision": 0.90,
            "faithfulness": 0.85,
            "answer_relevancy": 0.88,
        }

    def test_get_baseline_scores_unregistered(self):
        """Baseline scores for unregistered model returns empty dict."""
        registry = ModelVersionRegistry()
        assert registry.get_baseline_scores("unknown") == {}

    def test_detect_version_change_same_version(self):
        """No change when version matches current."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "2026-0301", {"precision": 0.90})
        changed = registry.detect_version_change("gpt-5.2", "2026-0301")
        assert changed is False

    def test_detect_version_change_different_version(self):
        """Change detected when version differs from current."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "2026-0301", {"precision": 0.90})
        changed = registry.detect_version_change("gpt-5.2", "2026-0415")
        assert changed is True

    def test_detect_version_change_unregistered_model(self):
        """Change detected for a model not yet registered (first time seeing it)."""
        registry = ModelVersionRegistry()
        changed = registry.detect_version_change("gpt-5.2", "2026-0301")
        assert changed is True

    def test_version_history_maintained(self):
        """Registry keeps history of all versions for a model."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "2026-0101", {"p": 0.90})
        registry.register("gpt-5.2", "2026-0301", {"p": 0.88})
        registry.register("gpt-5.2", "2026-0415", {"p": 0.85})

        history = registry.get_version_history("gpt-5.2")
        assert len(history) == 3
        assert [v.version for v in history] == ["2026-0101", "2026-0301", "2026-0415"]

    def test_version_history_empty_for_unknown_model(self):
        """History for an unregistered model returns empty list."""
        registry = ModelVersionRegistry()
        assert registry.get_version_history("unknown") == []

    def test_multiple_models_tracked_independently(self):
        """Different models have independent version tracking."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        registry.register("gpt-5-mini", "v2", {"p": 0.85})

        v1 = registry.get_current_version("gpt-5.2")
        v2 = registry.get_current_version("gpt-5-mini")
        assert v1.version == "v1"
        assert v2.version == "v2"

    def test_list_tracked_models(self):
        """List all models being tracked."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        registry.register("gpt-5-mini", "v2", {"p": 0.85})
        registry.register("claude-sonnet-4.6", "v1", {"p": 0.92})

        models = registry.list_models()
        assert sorted(models) == ["claude-sonnet-4.6", "gpt-5-mini", "gpt-5.2"]

    def test_update_baseline_scores(self):
        """Update baseline scores for an existing version."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        registry.update_baseline("gpt-5.2", {"p": 0.88, "f": 0.82})

        scores = registry.get_baseline_scores("gpt-5.2")
        assert scores == {"p": 0.88, "f": 0.82}

    def test_update_baseline_unregistered_raises(self):
        """Updating baseline for unregistered model raises ValueError."""
        registry = ModelVersionRegistry()
        with pytest.raises(ValueError, match="not registered"):
            registry.update_baseline("unknown", {"p": 0.90})

    def test_register_returns_model_version(self):
        """register() returns the created ModelVersion object."""
        registry = ModelVersionRegistry()
        mv = registry.register("gpt-5.2", "v1", {"p": 0.90})
        assert isinstance(mv, ModelVersion)
        assert mv.model_name == "gpt-5.2"
        assert mv.version == "v1"
