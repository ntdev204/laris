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
from typing import Any, Dict, List, Optional, Sequence, Union, cast

import yaml

from laris.shared.config.schemas import LarisConfig
from laris.shared.config.user_layer import layer_from, read_settings
from laris.shared.core.errors import ModuleContractViolationError

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

        raw_key = env_k[len(env_prefix) :].lower()
        parts = raw_key.split("__")

        # Lists and objects are JSON, e.g. LARIS_SECURITY__EXTRA_SECRET_ENV='["X"]'
        val: Any = env_v
        if env_v.lstrip().startswith(("[", "{")):
            try:
                val = json.loads(env_v)
            except json.JSONDecodeError:
                val = env_v
        elif env_v.lower() in {"true", "yes"}:
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


def _read_yaml_mapping(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ModuleContractViolationError(f"Malformed YAML in {path}: {e}") from e
    return loaded if isinstance(loaded, dict) else {}


def assert_no_literal_secrets(data: Any, source: str, trail: str = "") -> None:
    """Reject YAML that embeds a credential; configs may only name an environment variable."""
    if isinstance(data, dict):
        for key, value in data.items():
            lowered = str(key).lower()
            where = f"{trail}.{key}" if trail else str(key)
            sensitive = any(marker in lowered for marker in SENSITIVE_KEY_SUBSTRINGS)
            if sensitive and not lowered.endswith(("_env", "_envs")) and isinstance(value, str):
                if value.strip() and lowered not in {"vocab_size", "special_tokens"}:
                    raise ModuleContractViolationError(
                        f"{source}: '{where}' looks like a literal secret; "
                        "store it in an environment variable and reference its name"
                    )
            assert_no_literal_secrets(value, source, where)
    elif isinstance(data, list):
        for item in data:
            assert_no_literal_secrets(item, source, trail)


def load_dotenv(path: Path, environ: Optional[Dict[str, str]] = None) -> int:
    """Load KEY=VALUE lines into the environment without overriding existing variables."""
    target = os.environ if environ is None else environ
    if not path.is_file():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if key and key not in target:
            target[key] = value.strip().strip("\"'")
            loaded += 1
    return loaded


def load_config(
    config_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "LARIS_",
    overrides: Optional[Dict[str, Any]] = None,
    extra_files: Optional[Sequence[Union[str, Path]]] = None,
    extra_layers: Optional[Sequence[Dict[str, Any]]] = None,
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
        file_data = _read_yaml_mapping(p)
        assert_no_literal_secrets(file_data, str(p))

    for extra in extra_files or []:  # later files win: user-level, then project-level
        extra_path = Path(extra)
        if extra_path.is_file():
            layer = _read_yaml_mapping(extra_path)
            assert_no_literal_secrets(layer, str(extra_path))
            file_data = _deep_merge_dict(file_data, layer)

    for layer in extra_layers or []:  # e.g. the user's saved preferences, above files, below env
        file_data = _deep_merge_dict(file_data, layer)

    # 1. Environment variables
    env_data = _parse_env_overrides(env_prefix=env_prefix)

    # 2. CLI overrides
    cli_data = _parse_cli_overrides(overrides)

    # Apply precedence merging: File -> Env -> CLI
    merged = _deep_merge_dict(file_data, env_data)
    merged = _deep_merge_dict(merged, cli_data)

    # Validate against canonical Pydantic model
    return LarisConfig(**merged)


_PROJECT_CONFIG = True


def ignore_project_config(ignore: bool = True) -> None:
    """The client calls this at start: no file inside a project contributes configuration
    (SR-C2, SR-C5); only `~/.laris/settings.json`, the environment and flags do."""
    global _PROJECT_CONFIG
    _PROJECT_CONFIG = not ignore


PROJECT_CONFIG_FILES = ("config.yaml", "config.yml", "settings.json", "settings.local.json")


def ignored_project_files(root: Path) -> List[Path]:
    """Configuration-looking files in `<root>/.laris/` (and a `.env` that sets `LARIS_*`) that the
    client ignores."""
    found = [root / ".laris" / n for n in PROJECT_CONFIG_FILES if (root / ".laris" / n).is_file()]
    dotenv = root / ".env"
    try:
        if dotenv.is_file() and any(
            line.strip().removeprefix("export ").lstrip().startswith("LARIS_")
            for line in dotenv.read_text(encoding="utf-8").splitlines()
        ):
            found.append(dotenv)
    except (OSError, UnicodeDecodeError):
        pass
    return found


def load_runtime_config(
    project_root: Optional[Union[str, Path]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    env_prefix: str = "LARIS_",
    user_layer: Optional[Dict[str, Any]] = None,
) -> LarisConfig:
    """Resolve the runtime configuration for a project.

    Order (later wins): schema defaults, `configs/default.yaml`, `~/.laris/config.yaml`,
    `<project>/.laris/config.yaml` (not on the client), the user's saved settings
    (`~/.laris/settings.json`, where `server.url` names the server), `LARIS_*` environment (after
    loading `<project>/.env`), then explicit overrides.
    """
    root = Path(project_root or Path.cwd())
    if _PROJECT_CONFIG:  # the client never lets a folder it opened set LARIS_* variables
        load_dotenv(root / ".env")
    if user_layer is None:  # the global settings.json (server address, model) applies everywhere
        user_layer = layer_from(read_settings(Path.home() / ".laris" / "settings.json")) or None
    default = root / "configs" / "default.yaml"
    project_files = [root / ".laris" / "config.yaml"] if _PROJECT_CONFIG else []
    return load_config(
        default if default.is_file() else None,
        env_prefix=env_prefix,
        overrides=overrides,
        extra_files=[Path.home() / ".laris" / "config.yaml", *project_files],
        extra_layers=[user_layer] if user_layer else None,
    )
