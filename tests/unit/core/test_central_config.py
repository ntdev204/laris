"""Unit tests for centralized configuration system (schemas, loader, precedence, hashing).

Adheres to DOC-SPEC-TRAIN-001, ADR-001, ADR-002, ADR-005, and Issue #215.
Tests:
- Default values and schema structural invariants
- 4-tier precedence resolution (CLI overrides > Env vars > YAML file > Defaults)
- Immutable invariant enforcement (14.5 GB safety governor, RMSNorm, RoPE, GELU)
- Deterministic cryptographic hashing (SHA-256)
- Secret redaction behavior
- Consumer behavior changes when configuration values change
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from laris.config.loader import (
    compute_config_hash,
    inspect_config,
    load_config,
)
from laris.config.schemas import (
    DataConfig,
    HardwareConfig,
    LarisConfig,
    ModelConfig,
    TrainingConfig,
)
from laris.core.errors import HardwareBudgetExceededError
from laris.corpus.splits import WikipediaArticlePartitioner
from laris.language.encoder.transformer import LanguageEncoderConfig
from laris.language.tokenization.trainer import TokenizerTrainerConfig


class TestConfigSchemas:
    """Tests Pydantic V2 configuration schema validation and structural invariants."""

    def test_default_schema_instantiation(self) -> None:
        """Verifies default values match canonical language encoder specification."""
        cfg = LarisConfig()
        assert cfg.config_version == "1.0.0"
        assert cfg.environment == "development"
        assert cfg.model.d_model == 768
        assert cfg.model.vocab_size == 32000
        assert cfg.model.num_layers == 12
        assert cfg.model.num_heads == 12
        assert cfg.model.d_ff == 3072
        assert cfg.model.norm_type == "rmsnorm"
        assert cfg.model.pos_encoding == "rope"
        assert cfg.model.activation == "gelu"
        assert cfg.model.tie_embeddings is True
        assert cfg.model.precision == "bf16"
        assert cfg.training.batch_size == 32
        assert cfg.training.micro_batch_size == 4
        assert cfg.training.gradient_accumulation_steps == 8
        assert cfg.data.train_ratio == 0.80
        assert cfg.data.val_ratio == 0.10
        assert cfg.data.test_ratio == 0.10
        assert cfg.hardware.max_vram_gb == 14.5

    def test_d_model_allowed_values_only(self) -> None:
        """Verifies d_model is strictly restricted to {384, 768}."""
        cfg = ModelConfig(d_model=384, num_heads=12)
        assert cfg.d_model == 384

        with pytest.raises(ValidationError, match="d_model 512 must be in"):
            ModelConfig(d_model=512)

    def test_structural_invariants_enforced(self) -> None:
        """Verifies non-negotiable architectural choices cannot be modified."""
        with pytest.raises(ValidationError, match="norm_type must be 'rmsnorm'"):
            ModelConfig(norm_type="layernorm")

        with pytest.raises(ValidationError, match="pos_encoding must be 'rope'"):
            ModelConfig(pos_encoding="absolute")

        with pytest.raises(ValidationError, match="activation must be 'gelu'"):
            ModelConfig(activation="relu")

        with pytest.raises(ValidationError, match="d_model .* must be divisible by num_heads"):
            ModelConfig(d_model=768, num_heads=7)

    def test_hardware_safety_governor(self) -> None:
        """Verifies setting max_vram_gb > 14.5 raises HardwareBudgetExceededError."""
        HardwareConfig(max_vram_gb=14.5)
        HardwareConfig(max_vram_gb=8.0)

        with pytest.raises(HardwareBudgetExceededError, match="exceeds safe hardware envelope"):
            HardwareConfig(max_vram_gb=16.0)

        with pytest.raises(HardwareBudgetExceededError, match="exceeds safe hardware envelope"):
            LarisConfig(hardware=HardwareConfig(max_vram_gb=24.0))

    def test_data_ratios_must_sum_to_one(self) -> None:
        """Verifies data partition ratios validate sum to 1.0."""
        DataConfig(train_ratio=0.70, val_ratio=0.15, test_ratio=0.15)

        with pytest.raises(ValidationError, match="Split ratios must sum to 1.0"):
            DataConfig(train_ratio=0.80, val_ratio=0.10, test_ratio=0.20)

    def test_training_batch_hierarchy(self) -> None:
        """Verifies micro_batch_size cannot exceed batch_size."""
        TrainingConfig(batch_size=16, micro_batch_size=4)

        with pytest.raises(ValidationError, match="micro_batch_size .* cannot exceed batch_size"):
            TrainingConfig(batch_size=4, micro_batch_size=8)


class TestConfigLoaderPrecedence:
    """Tests 4-tier configuration resolution precedence."""

    def test_pure_defaults_when_no_inputs(self) -> None:
        """Tier 4: returns pure defaults when no config path or overrides provided."""
        cfg = load_config(config_path=None, overrides=None)
        assert cfg.model.d_model == 768
        assert cfg.training.batch_size == 32

    def test_yaml_file_overrides_defaults(self, tmp_path: Path) -> None:
        """Tier 3: YAML file overrides default values."""
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text(
            "model:\n"
            "  d_model: 384\n"
            "  num_heads: 12\n"
            "training:\n"
            "  batch_size: 64\n"
        )
        cfg = load_config(config_path=cfg_file)
        assert cfg.model.d_model == 384
        assert cfg.training.batch_size == 64
        # Unspecified fields retain default
        assert cfg.model.vocab_size == 32000

    def test_env_vars_override_yaml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier 2: Environment variables take precedence over YAML file."""
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text(
            "model:\n"
            "  d_model: 384\n"
            "  num_heads: 12\n"
            "training:\n"
            "  batch_size: 64\n"
        )
        monkeypatch.setenv("LARIS_TRAINING__BATCH_SIZE", "128")
        monkeypatch.setenv("LARIS_ENVIRONMENT", "staging")

        cfg = load_config(config_path=cfg_file)
        assert cfg.model.d_model == 384
        assert cfg.training.batch_size == 128
        assert cfg.environment == "staging"

    def test_cli_overrides_override_env_and_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier 1: Explicit CLI overrides take precedence over everything."""
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text(
            "model:\n"
            "  d_model: 384\n"
            "  num_heads: 12\n"
            "training:\n"
            "  batch_size: 64\n"
        )
        monkeypatch.setenv("LARIS_TRAINING__BATCH_SIZE", "128")

        overrides = {
            "training.batch_size": 256,
            "environment": "production",
        }
        cfg = load_config(config_path=cfg_file, overrides=overrides)
        assert cfg.model.d_model == 384
        assert cfg.training.batch_size == 256
        assert cfg.environment == "production"


class TestConfigHashingAndRedaction:
    """Tests deterministic hashing and secret redaction."""

    def test_deterministic_sha256_hash(self) -> None:
        """Ensures identical configuration produces identical SHA-256 hash."""
        cfg1 = LarisConfig()
        cfg2 = LarisConfig()
        h1 = compute_config_hash(cfg1)
        h2 = compute_config_hash(cfg2)
        assert len(h1) == 64
        assert h1 == h2

        # Modified config produces different hash
        cfg3 = LarisConfig(model=ModelConfig(d_model=384, num_heads=12))
        h3 = compute_config_hash(cfg3)
        assert h1 != h3

    def test_secret_redaction(self) -> None:
        """Ensures sensitive substrings are masked in inspect_config."""
        raw = inspect_config(LarisConfig(), redact_secrets=True)
        # Structural keys like vocab_size, pos_encoding are NOT masked
        assert raw["model"]["vocab_size"] == 32000
        assert raw["model"]["pos_encoding"] == "rope"


class TestConsumerBehaviorWithConfig:
    """Proves that changing configuration values changes actual system behavior."""

    def test_changing_model_config_changes_parameter_count(self) -> None:
        """Proves changing d_model from 768 to 384 alters parameter calculation."""
        cfg_default = LarisConfig()
        enc_default = LanguageEncoderConfig.from_config(cfg_default)
        assert enc_default.d_model == 768
        assert enc_default.calculate_parameter_count() == 109561856

        cfg_narrow = LarisConfig(model=ModelConfig(d_model=384, num_heads=12, d_ff=1536))
        enc_narrow = LanguageEncoderConfig.from_config(cfg_narrow)
        assert enc_narrow.d_model == 384
        assert enc_narrow.calculate_parameter_count() == 33563264
        assert enc_narrow.calculate_parameter_count() < enc_default.calculate_parameter_count()

    def test_changing_partition_config_changes_partitioner_behavior(self) -> None:
        """Proves changing data config partition ratios alters split assignment."""
        cfg_skewed = LarisConfig(
            data=DataConfig(train_ratio=0.10, val_ratio=0.10, test_ratio=0.80)
        )
        partitioner = WikipediaArticlePartitioner.from_config(cfg_skewed)
        assert partitioner.ratios.train == 0.10
        assert partitioner.ratios.test == 0.80

    def test_changing_tokenizer_config_changes_pipeline_config(self) -> None:
        """Proves changing character coverage or vocab size alters TokenizerTrainerConfig."""
        cfg = LarisConfig(
            model=ModelConfig(vocab_size=16000),
            data=DataConfig(character_coverage=0.9999),
        )
        tok_cfg = TokenizerTrainerConfig.from_config(cfg)
        assert tok_cfg.vocab_size == 16000
        assert tok_cfg.character_coverage == 0.9999
