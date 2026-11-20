"""Unit tests for the centralized configuration system (schemas, loader, precedence, hashing).

Tests:
- Default values and schema validation of the runtime sections
- 4-tier precedence resolution (CLI overrides > Env vars > YAML file > Defaults)
- Deterministic cryptographic hashing (SHA-256)
- Secret redaction behavior
- The self-trained model's sections are gone (T233)
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from laris.shared.config.loader import (
    compute_config_hash,
    inspect_config,
    load_config,
)
from laris.shared.config.schemas import LarisConfig


class TestConfigSchemas:
    """Tests Pydantic V2 configuration schema validation."""

    def test_default_schema_instantiation(self) -> None:
        cfg = LarisConfig()
        assert cfg.config_version == "1.0.0"
        assert cfg.environment == "development"
        assert cfg.agent.max_steps == 10
        assert cfg.model_service.port == 8001
        assert cfg.model_service.chat_quantization == "8bit"

    def test_invalid_values_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            LarisConfig(agent={"max_steps": 11})
        with pytest.raises(ValidationError):
            LarisConfig(model_service={"chat_quantization": "2bit"})

    def test_encoder_sections_are_gone(self) -> None:
        """T233 (D48): no encoder, training, data-split or hardware section, no encoder keys."""
        fields = set(LarisConfig.model_fields)
        assert not fields & {"model", "training", "data", "hardware"}
        service = set(LarisConfig().model_service.model_dump())
        assert not service & {"checkpoint", "tokenizer_model", "embed_vram_bytes"}


class TestConfigLoaderPrecedence:
    """Tests 4-tier configuration resolution precedence."""

    def test_pure_defaults_when_no_inputs(self) -> None:
        cfg = load_config(config_path=None, overrides=None)
        assert cfg.agent.max_steps == 10

    def test_yaml_file_overrides_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("agent:\n  max_steps: 4\nmodel_service:\n  port: 9100\n")
        cfg = load_config(config_path=cfg_file)
        assert cfg.agent.max_steps == 4
        assert cfg.model_service.port == 9100
        # Unspecified fields retain default
        assert cfg.model_service.host == "127.0.0.1"

    def test_env_vars_override_yaml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("agent:\n  max_steps: 4\nmodel_service:\n  port: 9100\n")
        monkeypatch.setenv("LARIS_MODEL_SERVICE__PORT", "9200")
        monkeypatch.setenv("LARIS_ENVIRONMENT", "staging")

        cfg = load_config(config_path=cfg_file)
        assert cfg.agent.max_steps == 4
        assert cfg.model_service.port == 9200
        assert cfg.environment == "staging"

    def test_cli_overrides_override_env_and_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("agent:\n  max_steps: 4\nmodel_service:\n  port: 9100\n")
        monkeypatch.setenv("LARIS_MODEL_SERVICE__PORT", "9200")

        overrides = {"model_service.port": 9300, "environment": "production"}
        cfg = load_config(config_path=cfg_file, overrides=overrides)
        assert cfg.agent.max_steps == 4
        assert cfg.model_service.port == 9300
        assert cfg.environment == "production"


class TestConfigHashingAndRedaction:
    """Tests deterministic hashing and secret redaction."""

    def test_deterministic_sha256_hash(self) -> None:
        h1 = compute_config_hash(LarisConfig())
        h2 = compute_config_hash(LarisConfig())
        assert len(h1) == 64
        assert h1 == h2

        h3 = compute_config_hash(LarisConfig(model_service={"port": 9100}))
        assert h1 != h3

    def test_secret_redaction(self) -> None:
        raw = inspect_config(LarisConfig(), redact_secrets=True)
        assert raw["model_service"]["port"] == 8001
        assert raw["model_service"]["chat_quantization"] == "8bit"
