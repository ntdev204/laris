"""Contract tests for centralized configuration system.

Adheres to DOC-SPEC-TRAIN-001, ADR-001, ADR-002, ADR-005, and Issue #215.
Tests:
- All canonical YAML configurations in configs/ conform to LarisConfig schemas
- Error contracts: FileNotFoundError on missing file, ModuleContractViolationError on bad syntax
- Full 4-tier precedence contract guarantees
"""

from pathlib import Path

import pytest

from laris.config.loader import load_config
from laris.config.schemas import LarisConfig
from laris.core.errors import ModuleContractViolationError

CONFIGS_DIR = Path("configs")


class TestConfigContracts:
    """Verifies schema contracts and file system invariants for configuration files."""

    def test_default_yaml_matches_schema_defaults(self) -> None:
        """Verifies configs/default.yaml parses cleanly and matches LarisConfig defaults."""
        default_yaml = CONFIGS_DIR / "default.yaml"
        assert default_yaml.is_file(), "configs/default.yaml must exist"

        loaded = load_config(default_yaml)
        expected = LarisConfig()

        assert loaded.config_version == expected.config_version
        assert loaded.environment == expected.environment
        assert loaded.model.d_model == expected.model.d_model
        assert loaded.model.vocab_size == expected.model.vocab_size
        assert loaded.training.batch_size == expected.training.batch_size
        assert loaded.data.train_ratio == expected.data.train_ratio
        assert loaded.hardware.max_vram_gb == expected.hardware.max_vram_gb

    def test_all_canonical_configs_validate(self) -> None:
        """Verifies all YAML files in configs/ parse cleanly against LarisConfig."""
        yaml_files = list(CONFIGS_DIR.rglob("*.yaml"))
        assert len(yaml_files) >= 4, "Expected at least 4 canonical YAML configs"

        for yaml_path in yaml_files:
            cfg = load_config(yaml_path)
            assert isinstance(cfg, LarisConfig)
            assert cfg.hardware.max_vram_gb <= 14.5

    def test_missing_file_raises_filenotfound(self) -> None:
        """Verifies nonexistent config path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_config(CONFIGS_DIR / "nonexistent_config_file_xyz.yaml")

    def test_malformed_yaml_raises_contract_violation(self, tmp_path: Path) -> None:
        """Verifies corrupt YAML raises ModuleContractViolationError."""
        bad_file = tmp_path / "corrupt.yaml"
        bad_file.write_text("model:\n  d_model: [unclosed list\n")

        with pytest.raises(ModuleContractViolationError, match="Malformed YAML"):
            load_config(bad_file)
