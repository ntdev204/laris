#!/usr/bin/env python3
"""Source shares and the QA no-answer share under the dataset sampling rule (T207).

The train loader draws a dataset with probability proportional to `rows ** exponent * weight`
(`dataset_sampling_exponents`, `dataset_sampling_weights`). This script reads the row counts and
the QA no-answer counts from `data/processed`, solves the per-dataset weights for the targets of
T207 by bisection, and prints the resulting shares. Reads data only; nothing trains.

Usage:
    .venv/bin/python -I scripts/measure_mixture_shares.py \
        --report reports/verification/T207-mixture-shares.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = REPO_ROOT / "data" / "processed"

DIRS: Dict[str, List[str]] = {
    "paraphrase": ["quora_duplicates", "paws", "mrpc_en", "paws_swap_en", "paws_unlabeled_en"],
    "nli": ["all_nli", "anli", "fever", "wanli_en", "scitail_en", "vitaminc_en"],
    "qa": [
        "squad",
        "hotpotqa",
        "squad_v2_en",
        "adversarial_qa_en",
        "duorc_en",
        "ropes_en",
        "quoref_en",
        "drop_en",
    ],
}
EXPONENT = 0.7  # `dataset_sampling_exponents` of english_r1.yaml for these tasks
# T207 targets
QA_NO_ANSWER_TARGET = 0.132  # T193 audit: the mixture's no-answer share before the new QA sources
PARAPHRASE_MODEL_LABEL_CAP = 0.15  # paws_unlabeled_en has model-assigned labels
NLI_VITAMINC_SHARE = 0.10  # new, carries the BIG-bench canary; one source of six


def rows(dirname: str) -> int:
    return sum(
        pq.ParquetFile(f).metadata.num_rows for f in (PROCESSED / dirname).glob("train*.parquet")
    )


def no_answer_rows(dirname: str) -> int:
    count = 0
    for f in (PROCESSED / dirname).glob("train*.parquet"):
        for answers in pq.read_table(f, columns=["answers"]).column("answers").to_pylist():
            if not (answers or {}).get("text") or not answers["text"][0]:
                count += 1
    return count


def shares(counts: Dict[str, int], weights: Dict[str, float]) -> Dict[str, float]:
    raw = {d: n**EXPONENT * weights.get(d, 1.0) for d, n in counts.items()}
    total = sum(raw.values())
    return {d: v / total for d, v in raw.items()}


def solve(counts: Dict[str, int], name: str, measure) -> float:
    """Bisect the weight of `name` (others 1) until `measure(shares)` crosses zero (monotone up)."""
    low, high = 1e-4, 1e4
    for _ in range(200):
        mid = (low * high) ** 0.5
        if measure(shares(counts, {name: mid})) < 0:
            low = mid
        else:
            high = mid
    return round((low * high) ** 0.5, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    counts = {task: {d: rows(d) for d in dirs} for task, dirs in DIRS.items()}
    no_answer = {d: no_answer_rows(d) for d in DIRS["qa"]}
    na_frac = {d: no_answer[d] / counts["qa"][d] for d in DIRS["qa"]}

    def na_share(s: Dict[str, float]) -> float:
        return sum(s[d] * na_frac[d] for d in s)

    weights: Dict[str, Dict[str, float]] = {}
    weights["paraphrase"] = {
        "paws_unlabeled_en": solve(
            counts["paraphrase"],
            "paws_unlabeled_en",
            lambda s: s["paws_unlabeled_en"] - PARAPHRASE_MODEL_LABEL_CAP,
        )
    }
    weights["nli"] = {
        "vitaminc_en": solve(
            counts["nli"], "vitaminc_en", lambda s: s["vitaminc_en"] - NLI_VITAMINC_SHARE
        )
    }
    weights["qa"] = {
        "squad_v2_en": solve(
            counts["qa"], "squad_v2_en", lambda s: na_share(s) - QA_NO_ANSWER_TARGET
        )
    }

    report: Dict[str, object] = {
        "exponent": EXPONENT,
        "targets": {
            "qa_no_answer_share": QA_NO_ANSWER_TARGET,
            "paws_unlabeled_share_cap": PARAPHRASE_MODEL_LABEL_CAP,
            "vitaminc_nli_share": NLI_VITAMINC_SHARE,
        },
        "weights": weights,
        "tasks": {},
    }
    for task in DIRS:
        before, after = shares(counts[task], {}), shares(counts[task], weights[task])
        entry: Dict[str, object] = {
            "rows": counts[task],
            "share_before": {d: round(v, 4) for d, v in before.items()},
            "share_after": {d: round(v, 4) for d, v in after.items()},
        }
        if task == "qa":
            entry["no_answer_fraction"] = {d: round(v, 4) for d, v in na_frac.items()}
            entry["no_answer_share_before"] = round(na_share(before), 4)
            entry["no_answer_share_after"] = round(na_share(after), 4)
        report["tasks"][task] = entry  # type: ignore[index]
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
