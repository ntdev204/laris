"""Writes the parity fixtures of the decision network (T169, gate N6): a network with seeded random
weights (it is
not trained and says nothing about decisions) and cases with the scores the Python reference
computes. The Rust
inference must reproduce them to 1e-5.

    python scripts/make_decision_net_fixture.py            # write
    python scripts/make_decision_net_fixture.py --check    # fail if the files on disk differ
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.model.decision.features import ACTIONS, encode  # noqa: E402
from laris.model.decision.network import Net, dumps, random_net  # noqa: E402

OUT = ROOT / "crates" / "laris-brain" / "tests" / "fixtures" / "decision-net"
LEVELS = ["sourced", "corroborated", "verified", "reviewed"]


def signals(rng: np.random.RandomState) -> dict:
    level = None if rng.rand() < 0.3 else LEVELS[rng.randint(len(LEVELS))]
    return {
        "missing_slot": "drug" if rng.rand() < 0.15 else None,
        "coverage": round(float(rng.rand()), 4),
        "best_level": level,
        "accepted": int(rng.randint(0, 12)),
        "below_required": int(rng.randint(0, 3)),
        "pending_candidates": int(rng.randint(0, 3)),
        "open_conflicts": int(rng.randint(0, 6)),
        "retracted_dependencies": int(rng.randint(0, 2)),
        "acquisition_allowed": bool(rng.rand() < 0.5),
        "retrievals": int(rng.randint(0, 6)),
        "acquisitions": int(rng.randint(0, 6)),
        "advisor_asks": int(rng.randint(0, 10)),
        "fresh_since_retrieve": bool(rng.rand() < 0.3),
        "call": ["none", "legal", "refused"][int(rng.randint(3))],
        "repeats": int(rng.randint(0, 10)),
        "advisor_accept_rate": None if rng.rand() < 0.4 else round(float(rng.rand()), 4),
        "advisor_agreement": None if rng.rand() < 0.5 else round(float(rng.rand()), 4),
        "tool_risk": int(rng.randint(0, 4)),
        "steps_left": int(rng.randint(0, 14)),
        "time_left_seconds": round(float(rng.rand() * 400 - 20), 3),
        "budget_left": round(float(rng.rand() * 1.2 - 0.1), 4),
    }


def build() -> tuple[str, str, Net]:
    net = random_net(169)
    net = Net(net.layers, 1.7, 0.55)
    rng = np.random.RandomState(7)  # noqa: NPY002
    cases = []
    for _ in range(40):
        sig = signals(rng)
        count = int(rng.randint(2, len(ACTIONS) + 1))
        picked = sorted(rng.choice(len(ACTIONS), size=count, replace=False))
        candidates = [ACTIONS[i] for i in picked]
        scores = {a: net.probability(encode(sig, a, count)) for a in candidates}
        logits = {a: net.logit(encode(sig, a, count)) for a in candidates}
        best = candidates[0]
        for a in candidates:
            if scores[a] > scores[best]:
                best = a
        cases.append(
            {
                "signals": sig,
                "candidates": candidates,
                "logits": logits,
                "probabilities": scores,
                "chosen": best,
                "confidence": scores[best],
            }
        )
    return (
        dumps(net, {"note": "seeded random weights, not trained: parity fixture only"}),
        json.dumps({"cases": cases}, sort_keys=True, indent=1) + "\n",
        net,
    )


def main(argv: list[str]) -> int:
    net_text, cases_text, _ = build()
    files = {"net.json": net_text, "cases.json": cases_text}
    if "--check" in argv:
        stale = [
            n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != t
        ]
        for n in stale:
            print(f"[FAIL] {n} differs from the generator")
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_text(text)
    print(f"wrote {len(files)} files to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
