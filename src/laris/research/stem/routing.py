"""The STEM router measured (T287): routing labels, baselines, the oracle, and a router network that
may replace the rule router only through its held-out gates and the owner's promotion.

- **Labels.** Every development item is run once on each path, forced (`harness --path`):
  `model_free` (the T276 solver patterns, no model), `brain_only` (one certain Claim, T285, no
  model), `notes_model` (notes and the model, no solver), `model_solver` (the model with
  formalisation and the solver's check, no notes) and `bare_model` (T275). An item's label is
  the set of paths that answer it right.
- **The rule router** (T278) is read as a choice of path per item: `model_free` when it answered
  model-free, `model_solver` for the computable class, `notes_model` otherwise.
- **The network** reads features of the item's shape and of the filter (no free text) and scores,
  per model path, the chance that the path answers right; it picks the best path and abstains to
  the rule router below the owner's confidence. It is trained by the owner only (SR-M3); nothing
  here computes a gradient. Its gates (`configs/stem-router-gates.json`) were fixed before any
  number: N1 gain over the rule router with a bootstrap lower bound above zero, N2 no more wrong
  model-free or brain-only answers, N3 calibration, N4 abstention.

Deterministic and model-free; inference only.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from laris.research.stem import stats

PATHS = ("model_free", "brain_only", "notes_model", "model_solver", "bare_model")
DETERMINISTIC = ("model_free", "brain_only")
MODEL_PATHS = ("notes_model", "model_solver", "bare_model")

FEATURES = (
    "open_answer",
    "options",
    "numeric_option_share",
    "question_words_log",
    "quantities",
    "quantities_with_unit",
    "formulas",
    "elements",
    "constants",
    "language_en",
    "model_free_answered",
    "brain_only_answered",
)


# -- labels and choices ------------------------------------------------------------------------


def labels(
    deterministic: Dict[str, Dict[str, Any]],
    notes_model: Dict[str, Dict[str, Any]],
    model_solver: Dict[str, Dict[str, Any]],
    bare_model: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, bool]]:
    """Per item id, whether each path answered it right (an unanswered deterministic path is
    not right). Only items present in every run are labelled."""
    out: Dict[str, Dict[str, bool]] = {}
    for item_id, det in deterministic.items():
        if item_id not in notes_model or item_id not in model_solver or item_id not in bare_model:
            continue
        out[item_id] = {
            "model_free": det.get("final_from") == "model_free" and bool(det["correct"]),
            "brain_only": det.get("final_from") == "brain_only" and bool(det["correct"]),
            "notes_model": bool(notes_model[item_id]["correct"]),
            "model_solver": bool(model_solver[item_id]["correct"]),
            "bare_model": bool(bare_model[item_id]["correct"]),
        }
    return out


def rule_choice(record: Dict[str, Any]) -> str:
    """The path the rule router of T278 took for one of its run records."""
    if record.get("final_from") == "model_free":
        return "model_free"
    if record.get("final_from") == "brain_only":
        return "brain_only"
    return "model_solver" if record.get("cls") == "computable" else "notes_model"


def routing_table(
    label: Dict[str, Dict[str, bool]], choice: Dict[str, str], cls: Dict[str, str]
) -> Dict[str, Any]:
    """Routing accuracy (the chosen path is right, among items some path answers), the score of
    the choices under the labels, the oracle, and the confusion per class: for each class, how
    often each path is right and how often the chosen one was."""
    ids = [i for i in label if i in choice]
    answerable = [i for i in ids if any(label[i].values())]
    right = sum(1 for i in ids if label[i][choice[i]])
    confusion: Dict[str, Dict[str, Any]] = {}
    for i in ids:
        slot = confusion.setdefault(
            cls[i], {"items": 0, "none_right": 0, "chosen_right": 0, "chosen": {}, "right": {}}
        )
        slot["items"] += 1
        slot["none_right"] += int(not any(label[i].values()))
        slot["chosen_right"] += int(label[i][choice[i]])
        slot["chosen"][choice[i]] = slot["chosen"].get(choice[i], 0) + 1
        for path, ok in label[i].items():
            slot["right"][path] = slot["right"].get(path, 0) + int(ok)
    return {
        "items": len(ids),
        "answerable": len(answerable),
        "routing_accuracy": (
            sum(1 for i in answerable if label[i][choice[i]]) / len(answerable)
            if answerable
            else 0.0
        ),
        "choice_correct": right,
        "oracle_correct": len(answerable),
        "confusion": confusion,
    }


def accuracy_row(name: str, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Accuracy with its Wilson interval, wrong model-free and brain-only answers (B5), and cost."""
    correct = sum(1 for r in rows if r["correct"])
    low, high = stats.wilson_interval(correct, len(rows))
    det = [r for r in rows if r.get("final_from") in DETERMINISTIC]
    seconds = [float(r["cost"]["seconds"]) for r in rows if "cost" in r]
    calls = [float(r["cost"]["model_calls"]) for r in rows if "cost" in r]
    return {
        "name": name,
        "items": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0.0,
        "wilson_low": low,
        "wilson_high": high,
        "deterministic_answered": len(det),
        "deterministic_wrong": sum(1 for r in det if not r["correct"]),
        "model_calls_mean": sum(calls) / len(calls) if calls else 0.0,
        "seconds_median": stats.percentile(seconds, 0.5),
        "seconds_p95": stats.percentile(seconds, 0.95),
    }


# -- features and the sealed split -------------------------------------------------------------


def feature_vector(
    route_features: Dict[str, Any], screen: Dict[str, Any], det: Dict[str, Any]
) -> List[float]:
    """The network's input, in the order of `FEATURES`: the router's item-shape features, the
    filter's counts and language, and whether the deterministic paths answered (both known before
    any model call). No text."""
    entities = screen.get("entities") or {}
    return [
        float(route_features["options"] == 0),
        float(route_features["options"]),
        float(route_features["numeric_option_share"]),
        math.log1p(float(route_features["question_words"])),
        float(screen.get("quantities", 0)),
        float(screen.get("quantities_with_unit", 0)),
        float(entities.get("formulas", 0)),
        float(entities.get("elements", 0)),
        float(entities.get("constants", 0)),
        float(screen.get("language") == "en"),
        float(det.get("final_from") == "model_free"),
        float(det.get("final_from") == "brain_only"),
    ]


def is_heldout(item_id: str, seed: int, share: float) -> bool:
    """A seeded hash split: the item belongs to the sealed held-out part when its hash falls
    below `share`. Fixed before training; never depends on a label."""
    digest = hashlib.sha256(f"{seed}:{item_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12) < share


def fold_of(item_id: str, seed: int, folds: int) -> int:
    digest = hashlib.sha256(f"{seed}:fold:{item_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % folds


def file_sha256(path: Any) -> str:
    from pathlib import Path

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -- the network at inference ------------------------------------------------------------------


@dataclass
class RouterNetwork:
    """Per model path a logistic score over standardised features: `P(path right | features)`.
    Read from the JSON the owner's training run writes; inference only."""

    features: List[str]
    mean: List[float]
    std: List[float]
    weights: Dict[str, List[float]]
    bias: Dict[str, float]

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "RouterNetwork":
        if list(data["features"]) != list(FEATURES):
            raise ValueError("router network: features differ from FEATURES")
        if set(data["weights"]) != set(MODEL_PATHS):
            raise ValueError("router network: one score per model path is required")
        return cls(
            list(data["features"]),
            [float(x) for x in data["mean"]],
            [float(x) for x in data["std"]],
            {k: [float(x) for x in v] for k, v in data["weights"].items()},
            {k: float(v) for k, v in data["bias"].items()},
        )

    def scores(self, x: Sequence[float]) -> Dict[str, float]:
        z = [(v - m) / (s if s > 0 else 1.0) for v, m, s in zip(x, self.mean, self.std)]
        out = {}
        for path in MODEL_PATHS:
            t = self.bias[path] + sum(w * v for w, v in zip(self.weights[path], z))
            out[path] = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, t))))
        return out


@dataclass(frozen=True)
class Decision:
    path: str
    confidence: float
    by: str  # "network" or "rule" (an abstention, or a deterministic answer)


def decide(
    network: Optional[RouterNetwork],
    x: Sequence[float],
    rule_path: str,
    abstain_below: float,
) -> Decision:
    """The route of one item: a deterministic answer stays the rule router's (the network never
    overrides a model-free or brain-only answer); otherwise the network's best model path when its
    confidence reaches `abstain_below`, else the rule router's path."""
    if network is None or rule_path in DETERMINISTIC:
        return Decision(rule_path, 1.0, "rule")
    scores = network.scores(x)
    path = max(MODEL_PATHS, key=lambda p: (scores[p], -MODEL_PATHS.index(p)))
    if scores[path] < abstain_below:
        return Decision(rule_path, scores[path], "rule")
    return Decision(path, scores[path], "network")


# -- gates -------------------------------------------------------------------------------------


def ece(pairs: Iterable[Tuple[float, bool]], bins: int) -> float:
    """Expected calibration error of (confidence, right) pairs over equal-width bins."""
    pairs = list(pairs)
    if not pairs:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        chunk = [(c, ok) for c, ok in pairs if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if chunk:
            conf = sum(c for c, _ in chunk) / len(chunk)
            acc = sum(1 for _, ok in chunk if ok) / len(chunk)
            total += len(chunk) / len(pairs) * abs(conf - acc)
    return total


def paired_bootstrap(
    diff: Sequence[int], resamples: int, seed: int, pct: float
) -> Tuple[float, float]:
    """Percentile interval of the mean of per-item differences (network right minus rule right)."""
    rng = random.Random(seed)
    n = len(diff)
    if n == 0:
        return 0.0, 0.0
    means = sorted(sum(diff[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    tail = (100.0 - pct) / 200.0
    return means[int(tail * resamples)], means[min(resamples - 1, int((1 - tail) * resamples))]


def gates(
    rows: Sequence[Dict[str, Any]], network: Optional[RouterNetwork], cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """N1-N4 of `configs/stem-router-gates.json` on held-out rows (`x`, `labels`, `rule_path`).
    Without a network every gate is NOT VERIFIED and the rule router stays."""
    if network is None:
        return {
            "verdict": "NOT VERIFIED: no trained network",
            "items": len(rows),
            "gates": {g: "NOT VERIFIED" for g in ("N1", "N2", "N3", "N4")},
        }
    below = float(cfg["n4_abstain_below"])
    diff, conf_pairs, rule_wrong_det, net_wrong_det, abstained, by_net = [], [], 0, 0, 0, 0
    for row in rows:
        lab = row["labels"]
        d = decide(network, row["x"], row["rule_path"], below)
        net_right, rule_right = lab[d.path], lab[row["rule_path"]]
        diff.append(int(net_right) - int(rule_right))
        if d.path in DETERMINISTIC:
            net_wrong_det += int(not net_right)
        if row["rule_path"] in DETERMINISTIC:
            rule_wrong_det += int(not rule_right)
        if d.by == "network":
            by_net += 1
            conf_pairs.append((d.confidence, net_right))
        elif row["rule_path"] not in DETERMINISTIC:
            abstained += 1
    n = len(rows)
    gain = 100.0 * sum(diff) / n if n else 0.0
    low, high = paired_bootstrap(
        diff,
        int(cfg["n1_bootstrap_resamples"]),
        int(cfg["n1_bootstrap_seed"]),
        float(cfg["n1_confidence_pct"]),
    )
    error = ece(conf_pairs, int(cfg["n3_ece_bins"]))
    out = {
        "items": n,
        "gain_points": gain,
        "bootstrap": [100.0 * low, 100.0 * high],
        "wrong_deterministic": {"network": net_wrong_det, "rule": rule_wrong_det},
        "ece": error,
        "decided_by_network": by_net,
        "abstained_to_rule": abstained,
        "gates": {
            "N1": "PASS" if gain >= float(cfg["n1_min_gain_points"]) and low > 0 else "FAIL",
            "N2": "PASS" if net_wrong_det <= rule_wrong_det else "FAIL",
            "N3": "PASS" if error <= float(cfg["n3_max_ece"]) else "FAIL",
            # N4 holds by construction of `decide`; it is checked, not assumed
            "N4": "PASS" if all(c >= below for c, _ in conf_pairs) else "FAIL",
        },
    }
    out["verdict"] = (
        "gates pass: the owner may promote"
        if all(v == "PASS" for v in out["gates"].values())
        else "NOT PROMOTED: the rule router stays"
    )
    return out


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True)
