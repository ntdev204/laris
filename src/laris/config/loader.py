"""Canonical configuration loader with 4-tier precedence and deterministic hashing.

Adheres to DOC-SPEC-TRAIN-001, ADR-001, ADR-002, ADR-005, and Issue #215.
Implements:
1. Explicit CLI overrides (highest precedence)
2. Environment variables (LARIS_<SECTION>__<KEY>)
3. Selected YAML configuration file
4. Safe Pydantic schema defaults (lowest precedence)
- Deterministic effective-config serialization and SHA-256 config digest
- Automatic secret redaction for sensitive fields
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union, cast

import yaml

from laris.config.schemas import LarisConfig
from laris.core.errors import ModuleContractViolationError

SENSITIVE_KEY_SUBSTRINGS = {"password", "secret", "token", "key", "credential"}


def _redact_dict_recursively(d: Any) -> Any:
    """Recursively walks dictionaries and redacts sensitive field values."""
    if isinstance(d, dict):
        redacted = {}
        for k, v in d.items():
            lower_k = str(k).lower()
            if any(sub in lower_k for sub in SENSITIVE_KEY_SUBSTRINGS) and lower_k not in {
                "vocab_size",
                "special_tokens",
                "pos_encoding",
            }:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = _redact_dict_recursively(v)
        return redacted
    elif isinstance(d, list):
        return [_redact_dict_recursively(item) for item in d]
    return d


def compute_config_hash(config: LarisConfig) -> str:
    """Computes a deterministic cryptographic SHA-256 hash over resolved configuration."""
    raw_dict = config.model_dump()
    redacted = _redact_dict_recursively(raw_dict)
    canonical_json = json.dumps(redacted, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def inspect_config(config: LarisConfig, redact_secrets: bool = True) -> Dict[str, Any]:
    """Returns resolved effective configuration dictionary with optional secret masking."""
    raw = config.model_dump()
    if redact_secrets:
        return cast(Dict[str, Any], _redact_dict_recursively(raw))
    return raw


def _deep_merge_dict(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges dictionary `update` into `base`."""
    result = dict(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_dict(result[k], v)
        else:
            result[k] = v
    return result


def _parse_env_overrides(env_prefix: str = "LARIS_") -> Dict[str, Any]:
    """Extracts configuration settings from environment variables.

    Pattern: LARIS_<SECTION>__<KEY>=<VALUE>
    Example: LARIS_MODEL__D_MODEL=384 -> {"model": {"d_model": 384}}
    """
    env_dict: Dict[str, Any] = {}

    for env_k, env_v in os.environ.items():
        if not env_k.startswith(env_prefix):
            continue

        raw_key = env_k[len(env_prefix):].lower()
        parts = raw_key.split("__")

        # Parse basic types
        val: Any = env_v
        if env_v.lower() in {"true", "yes"}:
            val = True
        elif env_v.lower() in {"false", "no"}:
            val = False
        else:
            try:
                if "." in env_v:
                    val = float(env_v)
                else:
                    val = int(env_v)
            except ValueError:
                val = env_v

        # Nesting
        target = env_dict
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = val

    return env_dict


def _parse_cli_overrides(overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Converts dot-separated CLI override keys into nested dictionary structures.

    Example: {"model.d_model": 384} -> {"model": {"d_model": 384}}
    """
    if not overrides:
        return {}

    nested: Dict[str, Any] = {}
    for k, v in overrides.items():
        parts = k.split(".")
        curr = nested
        for p in parts[:-1]:
            curr = curr.setdefault(p, {})
        curr[parts[-1]] = v

    return nested


def load_config(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "LARIS_",
    overrides: Optional[Dict[str, Any]] = None,
) -> LarisConfig:
    """Loads and resolves system configuration using strict 4-tier precedence.

    Precedence order:
    1. `overrides` dict (Highest)
    2. `LARIS_*` Environment variables
    3. YAML configuration file
    4. Safe Pydantic defaults (Lowest)

    Raises:
        FileNotFoundError: If an explicit config_path is given but does not exist.
        ModuleContractViolationError: If parsing or syntax fails.
        ValueError / ValidationError: If invariants or parameter constraints are violated.
    """
    file_data: Dict[str, Any] = {}

    if config_path is not None:
        p = Path(config_path)
        if not p.is_file():
            raise FileNotFoundError(f"Configuration file not found: {p}")
        try:
            with open(p, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                file_data = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError as e:
            raise ModuleContractViolationError(f"Malformed YAML in {p}: {e}") from e

    # 1. Environment variables
    env_data = _parse_env_overrides(env_prefix=env_prefix)

    # 2. CLI overrides
    cli_data = _parse_cli_overrides(overrides)

    # Apply precedence merging: File -> Env -> CLI
    merged = _deep_merge_dict(file_data, env_data)
    merged = _deep_merge_dict(merged, cli_data)

    # Validate against canonical Pydantic model
    return LarisConfig(**merged)
