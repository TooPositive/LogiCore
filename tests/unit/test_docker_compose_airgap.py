"""Tests for docker-compose.airgap.yml (Phase 6 -- Air-Gapped Vault).

Validates YAML structure, required services, and network isolation config.
No Docker required -- just parses the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

AIRGAP_COMPOSE_PATH = (
    Path(__file__).resolve().parents[2] / "docker-compose.airgap.yml"
)


@pytest.fixture
def airgap_compose():
    """Load and parse docker-compose.airgap.yml."""
    assert AIRGAP_COMPOSE_PATH.exists(), (
        f"docker-compose.airgap.yml not found at {AIRGAP_COMPOSE_PATH}"
    )
    with open(AIRGAP_COMPOSE_PATH) as f:
        return yaml.safe_load(f)


class TestDockerComposeAirgap:
    """docker-compose.airgap.yml must define Ollama service for air-gapped mode."""

    def test_file_exists(self):
        """docker-compose.airgap.yml exists in project root."""
        assert AIRGAP_COMPOSE_PATH.exists()

    def test_has_services_key(self, airgap_compose):
        """Compose file has 'services' top-level key."""
        assert "services" in airgap_compose

    def test_has_ollama_service(self, airgap_compose):
        """Compose file defines an 'ollama' service."""
        assert "ollama" in airgap_compose["services"]

    def test_ollama_has_image(self, airgap_compose):
        """Ollama service specifies an image."""
        ollama = airgap_compose["services"]["ollama"]
        assert "image" in ollama
        assert "ollama" in ollama["image"].lower()

    def test_ollama_has_port_mapping(self, airgap_compose):
        """Ollama service maps port 11434."""
        ollama = airgap_compose["services"]["ollama"]
        assert "ports" in ollama
        ports_str = str(ollama["ports"])
        assert "11434" in ports_str

    def test_ollama_has_volume(self, airgap_compose):
        """Ollama service has persistent model volume."""
        ollama = airgap_compose["services"]["ollama"]
        assert "volumes" in ollama

    def test_ollama_has_memory_reservation(self, airgap_compose):
        """Ollama service reserves memory for model inference."""
        ollama = airgap_compose["services"]["ollama"]
        assert "deploy" in ollama
        resources = ollama["deploy"]["resources"]
        assert "reservations" in resources
        assert "memory" in resources["reservations"]

    def test_ollama_has_healthcheck(self, airgap_compose):
        """Ollama service has a health check."""
        ollama = airgap_compose["services"]["ollama"]
        assert "healthcheck" in ollama

    def test_has_volumes_section(self, airgap_compose):
        """Compose file declares named volumes."""
        assert "volumes" in airgap_compose

    def test_ollama_models_volume_declared(self, airgap_compose):
        """ollama-models volume is declared."""
        assert "ollama-models" in airgap_compose["volumes"]

    def test_api_service_references_ollama_host(self, airgap_compose):
        """API service sets OLLAMA_HOST pointing to ollama container."""
        if "api" in airgap_compose["services"]:
            api = airgap_compose["services"]["api"]
            env = api.get("environment", {})
            assert "OLLAMA_HOST" in env
            assert "ollama" in env["OLLAMA_HOST"].lower()

    def test_api_service_sets_llm_provider_ollama(self, airgap_compose):
        """API service sets LLM_PROVIDER=ollama for air-gapped mode."""
        if "api" in airgap_compose["services"]:
            api = airgap_compose["services"]["api"]
            env = api.get("environment", {})
            assert env.get("LLM_PROVIDER") == "ollama"

    def test_valid_yaml_structure(self, airgap_compose):
        """Compose file parses as valid YAML with expected structure."""
        assert isinstance(airgap_compose, dict)
        assert isinstance(airgap_compose["services"], dict)
