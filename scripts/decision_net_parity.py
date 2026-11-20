#!/usr/bin/env python3
"""Gate N6 of the decision network (T171, ADR-024 8): Python float64 reference against Rust scores.

    python scripts/decision_net_parity.py --net NET.json --dataset DIR \
        --scores SCORES.json --out PARITY.json

``SCORES.json`` is written by ``cargo xtask decision-gates --scores-out``: the calibrated
probability of every held-out example, by example id. This script scores the same examples with the
numpy reference forward pass and writes the largest absolute difference. It trains and optimises
nothing; it reads the sealed held-out file only after its checksum matched the manifest. Exit
status 0 when the difference is within ``--limit``, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.model.decision import evaluation as ev  # noqa: E402
from laris.model.decision.features import encode_example  # noqa: E402
from laris.model.decision.network import load  # noqa: E402


def measure(net_path: Path, dataset: Path, scores_path: Path) -> dict[str, object]:
    """The parity record for the held-out examples."""
    net = load(ev.read_json(net_path))
    manifest = ev.read_json(dataset / "manifest.json")
    heldout = dataset / "heldout.jsonl"
    if ev.sha256_file(heldout) != manifest["files"]["heldout.jsonl"]["sha256"]:
        raise ev.DatasetError("heldout.jsonl: checksum differs from the manifest")
    rust: dict[str, float] = json.loads(scores_path.read_text(encoding="utf-8"))
    ids: list[str] = []
    rows: list[list[float]] = []
    for line in heldout.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        example = json.loads(line)
        ids.append(example["id"])
        rows.append(encode_example(example)[0])
    missing = sorted(set(ids) ^ set(rust))
    if missing:
        raise ev.DatasetError(f"{len(missing)} example ids are not in both files")
    z = ev.logits_of(net, np.asarray(rows, dtype=np.float64)) / net.temperature
    python = ev.sigmoid_array(z)
    theirs = np.asarray([rust[i] for i in ids], dtype=np.float64)
    return {
        "compared": len(ids),
        "max_abs_diff": float(np.max(np.abs(python - theirs))) if ids else 0.0,
        "net_sha256": ev.sha256_file(net_path),
        "heldout_sha256": ev.sha256_file(heldout),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--net", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=float, default=1e-5, help="gate N6: 1e-5")
    args = parser.parse_args()
    record = measure(args.net, args.dataset, args.scores)
    record["limit"] = args.limit
    record["pass"] = bool(record["max_abs_diff"] <= args.limit)  # type: ignore[operator]
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(
        f"N6: max |python - rust| = {record['max_abs_diff']:.3e} over {record['compared']} scores"
    )
    return 0 if record["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
