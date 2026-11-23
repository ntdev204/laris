#!/usr/bin/env python3
"""The owner's training run of the STEM router network (T287, SR-M3). The agent never runs it.

    python scripts/stem_benchmarks.py router-dataset --out data/benchmarks/router/RUN
    python scripts/train_stem_router.py --owner-run --dataset data/benchmarks/router/RUN \
        --config configs/stem-router-training.json --out data/benchmarks/router/RUN/net.json
    python scripts/stem_benchmarks.py router-gates --dataset data/benchmarks/router/RUN \
        --net data/benchmarks/router/RUN/net.json --report reports/benchmarks/T287-router-gates.json

Reads `pool.jsonl` only (checked against the manifest) and never opens `heldout.jsonl`. Per model
path (`routing.MODEL_PATHS`) it fits a logistic score `P(path right | features)` by full-batch
gradient descent with L2 on standardised features. It first cross-fits: for each fold it trains on
the other folds and scores the fold, and reports the cross-fitted accuracy of the network's choice
(with abstention to the rule router) against the rule router's on the same items. It then trains on
the whole pool and writes the network. The held-out gates decide; the owner promotes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.research.stem import routing  # noqa: E402


def fit(rows: List[Dict[str, Any]], cfg: Dict[str, Any], deadline: float) -> Dict[str, Any]:
    import numpy as np

    x = np.array([r["x"] for r in rows], dtype=np.float64)
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std == 0] = 1.0
    z = (x - mean) / std
    rng = np.random.default_rng(int(cfg["seed"]))
    weights, bias = {}, {}
    for path in routing.MODEL_PATHS:
        y = np.array([float(r["labels"][path]) for r in rows])
        w = rng.normal(0.0, 0.01, z.shape[1])
        b = 0.0
        for _ in range(int(cfg["epochs"])):
            if time.monotonic() > deadline:
                raise SystemExit("train_stem_router: max_seconds reached")
            p = 1.0 / (1.0 + np.exp(-(z @ w + b)))
            grad = p - y
            w -= float(cfg["learning_rate"]) * (z.T @ grad / len(y) + float(cfg["l2"]) * w)
            b -= float(cfg["learning_rate"]) * float(grad.mean())
        weights[path], bias[path] = [float(v) for v in w], float(b)
    return {
        "features": list(routing.FEATURES),
        "mean": [float(v) for v in mean],
        "std": [float(v) for v in std],
        "weights": weights,
        "bias": bias,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-run", action="store_true", help="required: the owner trains")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--gates", default="configs/stem-router-gates.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not args.owner_run:
        raise SystemExit("train_stem_router: training is the owner's run (SR-M3); pass --owner-run")
    folder = Path(args.dataset)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    pool_path = folder / "pool.jsonl"
    if hashlib.sha256(pool_path.read_bytes()).hexdigest() != manifest["pool_sha256"]:
        raise SystemExit("train_stem_router: pool.jsonl does not match the manifest")
    cfg_bytes = Path(args.config).read_bytes()
    cfg = json.loads(cfg_bytes)
    gates = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in pool_path.read_text(encoding="utf-8").splitlines()]
    deadline = time.monotonic() + float(cfg["max_seconds"])
    below = float(gates["n4_abstain_below"])
    folds = sorted({r["fold"] for r in rows})
    net_right = rule_right = 0
    for fold in folds:
        train = [r for r in rows if r["fold"] != fold]
        network = routing.RouterNetwork.from_json(fit(train, cfg, deadline))
        for r in (r for r in rows if r["fold"] == fold):
            d = routing.decide(network, r["x"], r["rule_path"], below)
            net_right += int(r["labels"][d.path])
            rule_right += int(r["labels"][r["rule_path"]])
    final = fit(rows, cfg, deadline)
    final["training"] = {
        "config_sha256": hashlib.sha256(cfg_bytes).hexdigest(),
        "pool_sha256": manifest["pool_sha256"],
        "crossfit": {"items": len(rows), "network_right": net_right, "rule_right": rule_right},
    }
    Path(args.out).write_text(json.dumps(final, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(final["training"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
