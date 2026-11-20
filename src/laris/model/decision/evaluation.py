"""Data access, validation analysis and run records of the decision network (T170, ADR-024 9).

Nothing in this module trains: it reads the ``train`` and ``validation`` splits of a decision
dataset (T168), scores them with the float64 reference forward pass, fits the calibration and the
abstention threshold (T169), and writes or checks the records of an owner run. The loop that changes
the weights lives in ``scripts/train_decision_net.py`` and only the owner runs it.

The sealed splits (``heldout`` and ``heldout-unseen-advisor``) are never opened here: ``load_split``
refuses them by name, and the run record states which splits were read so that the intake can
reject a run that touched them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import calibration
from .features import ACTIONS, FEATURE_NAMES, encode_example
from .network import Net, NetworkError, dumps, sigmoid

READABLE_SPLITS: tuple[str, ...] = ("train", "validation")
SEALED_SPLITS: tuple[str, ...] = ("heldout", "heldout-unseen-advisor")
RUN_FORMAT = "laris-decision-net-run"
RUN_VERSION = 1
STOP_REASONS: tuple[str, ...] = ("patience", "max_epochs", "max_seconds")
FAILED_REASONS: tuple[str, ...] = ("non_finite_loss", "diverged")
CONFIG_KEYS: tuple[str, ...] = (
    "hidden",
    "seed",
    "batch_size",
    "learning_rate",
    "weight_decay",
    "max_epochs",
    "max_seconds",
    "patience",
    "min_delta",
    "divergence_factor",
    "max_parameters",
    "target_precision",
    "threads",
)


class SealedSplitError(PermissionError):
    """A sealed split was asked for."""


class DatasetError(ValueError):
    """The dataset directory does not match its manifest."""


def sha256_file(path: Path) -> str:
    """The sha256 of a file, read in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    """A JSON object from a file."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: not a JSON object")
    return value


@dataclass(frozen=True)
class Split:
    """One readable split as arrays. ``group`` numbers the states; rows of one state are the legal
    candidates the dataset has a label for."""

    name: str
    x: np.ndarray
    y: np.ndarray
    group: np.ndarray
    action: tuple[str, ...]
    scenario_share: float
    sha256: str

    def __len__(self) -> int:
        return int(self.y.shape[0])

    @property
    def groups(self) -> int:
        return int(self.group.max()) + 1 if len(self) else 0


def load_split(dataset: Path, name: str) -> Split:
    """The examples of ``train`` or ``validation``, after the file's checksum matched the manifest.

    Raises ``SealedSplitError`` for any other name, so the held-out data cannot be read by mistake.
    """
    if name not in READABLE_SPLITS:
        raise SealedSplitError(f"split {name!r} is not readable for training; sealed until T171")
    manifest = read_json(dataset / "manifest.json")
    entry = manifest.get("files", {}).get(f"{name}.jsonl")
    if entry is None:
        raise DatasetError(f"{name}.jsonl is not in the manifest")
    path = dataset / f"{name}.jsonl"
    actual = sha256_file(path)
    if actual != entry["sha256"]:
        raise DatasetError(f"{name}.jsonl: checksum differs from the manifest")
    rows: list[list[float]] = []
    labels: list[float] = []
    groups: list[int] = []
    actions: list[str] = []
    index: dict[str, int] = {}
    scenario = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        example = json.loads(line)
        if example.get("split") != name:
            raise DatasetError(f"{name}.jsonl line {number}: belongs to {example.get('split')!r}")
        vector, label = encode_example(example)
        rows.append(vector)
        labels.append(label)
        actions.append(example["action"])
        groups.append(index.setdefault(example["group"], len(index)))
        scenario += example["origin"] == "scenario"
    if len(rows) != entry["examples"]:
        raise DatasetError(
            f"{name}.jsonl: {len(rows)} examples, the manifest says {entry['examples']}"
        )
    return Split(
        name,
        np.asarray(rows, dtype=np.float64).reshape(len(rows), len(FEATURE_NAMES)),
        np.asarray(labels, dtype=np.float64),
        np.asarray(groups, dtype=np.int64),
        tuple(actions),
        scenario / len(rows) if rows else 0.0,
        actual,
    )


def logits_of(net: Net, x: np.ndarray) -> np.ndarray:
    """The raw scores of every row, with the float64 reference forward pass."""
    h = np.asarray(x, dtype=np.float64)
    for layer in net.layers:
        h = h @ layer.weights.T + layer.bias
        if layer.activation == "relu":
            h = np.maximum(h, 0.0)
    return h[:, 0]


def sigmoid_array(z: np.ndarray) -> np.ndarray:
    """Element-wise logistic function that stays finite."""
    out = np.empty_like(z, dtype=np.float64)
    positive = z >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    e = np.exp(z[~positive])
    out[~positive] = e / (1.0 + e)
    return out


def chosen_rows(score: np.ndarray, group: np.ndarray) -> np.ndarray:
    """For each state the row with the best score (the first row on a tie)."""
    best: dict[int, int] = {}
    for row, (g, s) in enumerate(zip(group.tolist(), score.tolist(), strict=True)):
        if g not in best or s > score[best[g]]:
            best[g] = row
    return np.asarray([best[g] for g in sorted(best)], dtype=np.int64)


def action_rates(split: Split) -> dict[str, float]:
    """The share of good outcomes per action: the table of the majority-by-action baseline."""
    rates: dict[str, float] = {}
    for action in ACTIONS:
        mask = np.asarray([a == action for a in split.action])
        if mask.any():
            rates[action] = float(split.y[mask].mean())
    return rates


def baseline_accuracy(split: Split, rates: Mapping[str, float]) -> float:
    """Accuracy of choosing, in each state, the action with the best rate in ``rates``."""
    score = np.asarray([rates.get(a, 0.0) for a in split.action], dtype=np.float64)
    rows = chosen_rows(score, split.group)
    return float(split.y[rows].mean())


def analyse(
    net: Net, split: Split, train_rates: Mapping[str, float] | None = None
) -> dict[str, Any]:
    """Validation analysis of one network on one readable split. Every number is a measurement of
    this split; none of it is a held-out gate (that is T171)."""
    logit = logits_of(net, split.x)
    probability = sigmoid_array(logit / net.temperature)
    rows = chosen_rows(logit, split.group)
    confidence = probability[rows]
    correct = split.y[rows] >= 0.5
    kept = confidence >= net.threshold
    per_group_good = np.bincount(split.group, weights=split.y)
    per_group_size = np.bincount(split.group)
    result: dict[str, Any] = {
        "split": split.name,
        "examples": len(split),
        "groups": split.groups,
        "scenario_share": split.scenario_share,
        "good_rate": float(split.y.mean()),
        "pair_log_loss": calibration.log_loss(logit, split.y, net.temperature),
        "pair_ece": calibration.expected_calibration_error(probability, split.y),
        "choice_accuracy": float(correct.mean()),
        "chosen_ece": calibration.expected_calibration_error(
            confidence, correct.astype(np.float64)
        ),
        "mean_confidence": float(confidence.mean()),
        "kept_share": float(kept.mean()),
        "kept_precision": float(correct[kept].mean()) if kept.any() else None,
        "ceiling_accuracy": float((per_group_good > 0).mean()),
        "random_legal_accuracy": float((per_group_good / per_group_size).mean()),
    }
    if train_rates is not None:
        result["majority_by_action_accuracy"] = baseline_accuracy(split, train_rates)
    return result


def fit_calibration(net: Net, validation: Split, target_precision: float) -> tuple[float, float]:
    """The temperature and the abstention threshold fitted on the validation split only."""
    logit = logits_of(net, validation.x)
    temperature = calibration.fit_temperature(logit, validation.y)
    probability = sigmoid_array(logit / temperature)
    rows = chosen_rows(logit, validation.group)
    threshold = calibration.fit_threshold(
        probability[rows], (validation.y[rows] >= 0.5).tolist(), target_precision
    )
    return temperature, threshold


def check_config(config: Mapping[str, Any]) -> list[str]:
    """Problems of a training configuration; empty means usable. No value has a default."""
    problems = [f"missing key: {key}" for key in CONFIG_KEYS if key not in config]
    problems += [f"unknown key: {key}" for key in config if key not in CONFIG_KEYS]
    if problems:
        return problems
    hidden = config["hidden"]
    if not (
        isinstance(hidden, list) and hidden and all(isinstance(h, int) and h > 0 for h in hidden)
    ):
        problems.append("hidden must be a non-empty list of positive integers")
    for key in ("seed", "batch_size", "max_epochs", "patience", "max_parameters", "threads"):
        if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 0:
            problems.append(f"{key} must be a non-negative integer")
    for key in ("learning_rate", "max_seconds", "divergence_factor"):
        if not isinstance(config[key], int | float) or config[key] <= 0:
            problems.append(f"{key} must be a positive number")
    for key in ("weight_decay", "min_delta"):
        if not isinstance(config[key], int | float) or config[key] < 0:
            problems.append(f"{key} must not be negative")
    if not (
        isinstance(config["target_precision"], int | float) and 0 < config["target_precision"] <= 1
    ):
        problems.append("target_precision must be in (0, 1]")
    for key in ("batch_size", "max_epochs", "patience", "threads"):
        if isinstance(config[key], int) and config[key] == 0:
            problems.append(f"{key} must be at least 1")
    return problems


def parameter_count(hidden: Sequence[int]) -> int:
    """The number of weights and biases of the architecture."""
    sizes = [len(FEATURE_NAMES), *hidden, 1]
    return sum(sizes[i] * sizes[i + 1] + sizes[i + 1] for i in range(len(sizes) - 1))


def stop_reason(
    history: Sequence[Mapping[str, float]], config: Mapping[str, Any], elapsed: float
) -> str | None:
    """Why the loop must stop after the epochs in ``history``, or ``None`` to go on.

    ``history`` holds one mapping per finished epoch with ``train_loss`` and ``validation_loss``.
    A failure (``non_finite_loss``, ``diverged``) is checked first, then the budget, then patience.
    """
    if not history:
        return None
    last = history[-1]
    if not (np.isfinite(last["train_loss"]) and np.isfinite(last["validation_loss"])):
        return "non_finite_loss"
    first = history[0]["validation_loss"]
    if last["validation_loss"] > first * config["divergence_factor"]:
        return "diverged"
    if len(history) >= config["max_epochs"]:
        return "max_epochs"
    if elapsed >= config["max_seconds"]:
        return "max_seconds"
    best = best_epoch(history, config["min_delta"])
    if len(history) - best >= config["patience"]:
        return "patience"
    return None


def best_epoch(history: Sequence[Mapping[str, float]], min_delta: float) -> int:
    """The 1-based epoch of the best validation loss; an epoch counts as better only when it
    improves on the best so far by more than ``min_delta``."""
    best = 0
    best_loss = float("inf")
    for number, row in enumerate(history, start=1):
        if row["validation_loss"] < best_loss - min_delta:
            best, best_loss = number, row["validation_loss"]
    return best


def epoch_order(count: int, seed: int, epoch: int) -> np.ndarray:
    """The order in which the examples are visited in an epoch: fixed by the seed and the epoch."""
    return np.random.RandomState(seed * 1_000_003 + epoch).permutation(count)  # noqa: NPY002


def finish_run(
    net: Net,
    train: Split,
    validation: Split,
    config: Mapping[str, Any],
    history: Sequence[Mapping[str, float]],
    stop: str,
    meta: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Calibrate the best network on the validation split and return ``(net_json, run_record)``.

    ``meta`` carries what only the loop knows: the dataset and config checksums, the seal checksum,
    the start time, the total seconds and the versions. The record names the splits that were read.
    """
    temperature, threshold = fit_calibration(net, validation, config["target_precision"])
    final = Net(net.layers, temperature, threshold)
    rates = action_rates(train)
    manifest = {
        "dataset_manifest_sha256": meta["dataset_manifest_sha256"],
        "config_sha256": meta["config_sha256"],
        "seed": config["seed"],
        "epochs_run": len(history),
        "best_epoch": best_epoch(history, config["min_delta"]),
    }
    net_json = dumps(final, manifest)
    record = {
        "format": RUN_FORMAT,
        "version": RUN_VERSION,
        "status": "complete" if stop in STOP_REASONS else "failed",
        "stop_reason": stop,
        "splits_read": list(READABLE_SPLITS),
        "epochs_run": len(history),
        "best_epoch": manifest["best_epoch"],
        "seconds": meta["seconds"],
        "parameters": final.parameter_count(),
        "net_sha256": hashlib.sha256(net_json.encode("utf-8")).hexdigest(),
        "train_sha256": train.sha256,
        "validation_sha256": validation.sha256,
        "train_action_rates": rates,
        "validation": analyse(final, validation, rates),
        "train": analyse(final, train, rates),
        **{
            key: meta[key]
            for key in (
                "dataset_manifest_sha256",
                "seal_sha256",
                "config_sha256",
                "started_at",
                "versions",
            )
        },
    }
    return net_json, record


__all__ = [
    "CONFIG_KEYS",
    "DatasetError",
    "NetworkError",
    "READABLE_SPLITS",
    "SEALED_SPLITS",
    "STOP_REASONS",
    "SealedSplitError",
    "Split",
    "analyse",
    "best_epoch",
    "check_config",
    "epoch_order",
    "finish_run",
    "load_split",
    "logits_of",
    "parameter_count",
    "sha256_file",
    "sigmoid",
    "stop_reason",
]
