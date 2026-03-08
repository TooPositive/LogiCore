"""Model version registry: track model versions and baseline quality scores.

Phase 5, Pillar 2: Drift Detection.

Domain-agnostic: tracks any model by name/version. Baseline scores are
arbitrary string->float dicts — works for any metric set.

For production, back this with PostgreSQL. In-memory implementation
is sufficient for testing and single-process deployments.
"""

from apps.api.src.domain.telemetry import ModelVersion


class ModelVersionRegistry:
    """In-memory model version registry with history tracking.

    Tracks the current version and full version history for each model.
    Used by DriftDetector to compare current quality scores against baselines.
    """

    def __init__(self) -> None:
        self._current: dict[str, ModelVersion] = {}
        self._history: dict[str, list[ModelVersion]] = {}

    def register(
        self,
        model_name: str,
        version: str,
        baseline_scores: dict[str, float],
    ) -> ModelVersion:
        """Register a new model version with baseline scores.

        If the model already has a registered version, the new version
        replaces the current one. Previous versions are retained in history.

        Args:
            model_name: Model identifier (e.g., "gpt-5.2").
            version: Version string (e.g., "2026-0301").
            baseline_scores: Quality metrics measured at registration time.

        Returns:
            The created ModelVersion object.
        """
        mv = ModelVersion(
            model_name=model_name,
            version=version,
            baseline_scores=baseline_scores,
        )
        self._current[model_name] = mv

        if model_name not in self._history:
            self._history[model_name] = []
        self._history[model_name].append(mv)

        return mv

    def get_current_version(self, model_name: str) -> ModelVersion | None:
        """Get the current registered version for a model.

        Returns None if the model has not been registered.
        """
        return self._current.get(model_name)

    def get_baseline_scores(self, model_name: str) -> dict[str, float]:
        """Get baseline scores for the current version of a model.

        Returns empty dict if model is not registered.
        """
        mv = self._current.get(model_name)
        if mv is None:
            return {}
        return mv.baseline_scores

    def detect_version_change(self, model_name: str, current_version: str) -> bool:
        """Check if a model's version has changed from the registered version.

        Returns True if:
        - The model has not been registered yet (first time seeing it).
        - The registered version differs from current_version.

        Args:
            model_name: Model identifier.
            current_version: The version currently being served.

        Returns:
            True if version change detected, False if same as registered.
        """
        mv = self._current.get(model_name)
        if mv is None:
            return True  # Never seen before
        return mv.version != current_version

    def get_version_history(self, model_name: str) -> list[ModelVersion]:
        """Get the full version history for a model, ordered by registration time.

        Returns empty list if model has not been registered.
        """
        return self._history.get(model_name, [])

    def list_models(self) -> list[str]:
        """List all model names currently tracked in the registry."""
        return list(self._current.keys())

    def update_baseline(
        self, model_name: str, new_scores: dict[str, float]
    ) -> None:
        """Update baseline scores for the current version of a model.

        Args:
            model_name: Model identifier.
            new_scores: New baseline scores to replace the existing ones.

        Raises:
            ValueError: If model is not registered.
        """
        mv = self._current.get(model_name)
        if mv is None:
            raise ValueError(f"Model '{model_name}' is not registered")
        # Create updated version (preserving version string and detected_at)
        updated = ModelVersion(
            model_name=mv.model_name,
            version=mv.version,
            baseline_scores=new_scores,
            detected_at=mv.detected_at,
        )
        self._current[model_name] = updated
        # Also update the last entry in history
        if model_name in self._history and self._history[model_name]:
            self._history[model_name][-1] = updated
