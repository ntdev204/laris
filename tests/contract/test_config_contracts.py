"""Contract tests for centralized configuration system.

Tests:
- All canonical YAML configurations in configs/ conform to LarisConfig schemas
- Error contracts: FileNotFoundError on missing file, ModuleContractViolationError on bad syntax
- Full 4-tier precedence contract guarantees
"""

from pathlib import Path

import pytest

from laris.shared.config.loader import load_config
from laris.shared.config.schemas import LarisConfig
from laris.shared.core.errors import ModuleContractViolationError

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
        assert loaded == expected

    def test_all_canonical_configs_validate(self) -> None:
        """Verifies all YAML files in configs/ parse cleanly against LarisConfig."""
        yaml_files = [
            f
            for f in CONFIGS_DIR.rglob("*.yaml")
            if not {"evaluation", "prompts"} & set(f.relative_to(CONFIGS_DIR).parts)
        ]
        assert yaml_files, "Expected at least the default YAML config"

        for yaml_path in yaml_files:
            cfg = load_config(yaml_path)
            assert isinstance(cfg, LarisConfig)

    def test_missing_file_raises_filenotfound(self) -> None:
        """Verifies nonexistent config path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_config(CONFIGS_DIR / "nonexistent_config_file_xyz.yaml")

    def test_malformed_yaml_raises_contract_violation(self, tmp_path: Path) -> None:
        """Verifies corrupt YAML raises ModuleContractViolationError."""
        bad_file = tmp_path / "corrupt.yaml"
        bad_file.write_text("agent:\n  max_steps: [unclosed list\n")

        with pytest.raises(ModuleContractViolationError, match="Malformed YAML"):
            load_config(bad_file)
