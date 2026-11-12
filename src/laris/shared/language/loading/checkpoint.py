"""Atomic training checkpoints with a provenance manifest.

A checkpoint directory contains:
- `model.pt`            model weights (state_dict)
- `training_state.pt`   optimizer, scheduler, grad scaler, RNG and counters (for exact resume)
- `manifest.json`       run provenance: config, tokenizer and dataset digests, metrics, step
"""

import hashlib
import json
import random
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

CHECKPOINT_SCHEMA_VERSION = "1.0.0"
MODEL_FILE = "model.pt"
STATE_FILE = "training_state.pt"
MANIFEST_FILE = "manifest.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit(repo_root: Optional[Path] = None) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def capture_rng_state() -> Dict[str, Any]:
    import torch

    state: Dict[str, Any] = {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()
    return state


def restore_rng_state(state: Dict[str, Any]) -> None:
    import torch

    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if "cuda" in state and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def save_checkpoint(
    directory: Path,
    *,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    counters: Dict[str, Any],
    provenance: Dict[str, Any],
    metrics: Optional[Dict[str, Any]] = None,
    extra_state: Optional[Dict[str, Any]] = None,
) -> Path:
    """Writes the checkpoint to a temporary sibling and renames it into place."""
    import torch

    directory = Path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.with_name(directory.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    torch.save(model.state_dict(), staging / MODEL_FILE)
    torch.save(
        {
            "optimizer": optimizer.state_dict() if optimizer is not None else None,
            "scheduler": scheduler.state_dict() if scheduler is not None else None,
            "scaler": scaler.state_dict() if scaler is not None else None,
            "counters": counters,
            "extra": extra_state or {},
            "rng": capture_rng_state(),
        },
        staging / STATE_FILE,
    )
    manifest = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "counters": counters,
        "metrics": metrics or {},
        "provenance": {k: _jsonable(v) for k, v in provenance.items()},
        "model_sha256": file_sha256(staging / MODEL_FILE),
    }
    with open(staging / MANIFEST_FILE, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False, default=str)

    if directory.exists():
        shutil.rmtree(directory)
    staging.rename(directory)
    return directory


def read_manifest(directory: Path) -> Dict[str, Any]:
    with open(Path(directory) / MANIFEST_FILE, "r", encoding="utf-8") as handle:
        manifest: Dict[str, Any] = json.load(handle)
    return manifest


def load_checkpoint(
    directory: Path,
    *,
    model: Any,
    optimizer: Any = None,
    scheduler: Any = None,
    scaler: Any = None,
    restore_rng: bool = True,
    map_location: Any = "cpu",
) -> Dict[str, Any]:
    """Restores weights and (when given) optimizer/scheduler/scaler/RNG.

    Returns `{"counters": ..., "extra": ...}` as stored by `save_checkpoint`.
    """
    import torch

    directory = Path(directory)
    manifest = read_manifest(directory)
    actual = file_sha256(directory / MODEL_FILE)
    if actual != manifest["model_sha256"]:
        raise ValueError(f"Checkpoint {directory} is corrupt: model.pt digest mismatch")

    model.load_state_dict(torch.load(directory / MODEL_FILE, map_location=map_location))
    state = torch.load(directory / STATE_FILE, map_location=map_location, weights_only=False)
    if optimizer is not None and state.get("optimizer") is not None:
        optimizer.load_state_dict(state["optimizer"])
    if scheduler is not None and state.get("scheduler") is not None:
        scheduler.load_state_dict(state["scheduler"])
    if scaler is not None and state.get("scaler") is not None:
        scaler.load_state_dict(state["scaler"])
    if restore_rng and state.get("rng") is not None:
        restore_rng_state(state["rng"])
    return {"counters": state["counters"], "extra": state.get("extra", {})}
