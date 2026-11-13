#!/usr/bin/env python3
"""Read-only intake of one owner-run foundation training round (T99).

Checks the returned run against the runbook: checkpoint and manifest integrity, lineage (initial
checkpoint, tokenizer, retrieval weight), the step count, the stop rules, the peak memory in the log
and per-task validation change against a reference run. It loads no model and trains nothing; it
refuses to run when training authorization is set in its own environment.

Exit 0 when every check passes, 1 when a check fails, 2 on unusable input.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts/checkpoints/language_encoder"
AUTH_VARS = ("LARIS_TRAINING_AUTHORIZED", "LARIS_TOKENIZER_TRAINING_AUTHORIZED")
TASKS = ("mlm", "nli", "paraphrase", "qa", "similarity")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(run: Path, which: str) -> Dict[str, Any]:
    data: Dict[str, Any] = json.loads((run / which / "manifest.json").read_text(encoding="utf-8"))
    return data


def parse_log(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    mems = [float(m) for m in re.findall(r"mem=([0-9.]+)G", text)]
    secs = [float(m) for m in re.findall(r"([0-9.]+)s/step", text)]
    return {
        "success": "[SUCCESS]" in text,
        "nan": bool(re.search(r"\bnan\b|\binf\b", text, re.IGNORECASE)),
        "peak_mem_gib": max(mems) if mems else None,
        "median_s_per_step": sorted(secs)[len(secs) // 2] if secs else None,
    }


def last_validation(manifest: Dict[str, Any]) -> Dict[str, float]:
    evaluations = manifest["counters"]["loop"]["evaluations"]
    last: Dict[str, float] = evaluations[-1]
    return last


def check(rows: List[Tuple[str, bool, str]], name: str, ok: bool, detail: str) -> None:
    rows.append((name, ok, detail))


def run_checks(args: argparse.Namespace) -> List[Tuple[str, bool, str]]:
    rows: List[Tuple[str, bool, str]] = []
    run = RUNS / args.run_id
    best, last = load_manifest(run, "best"), load_manifest(run, "last")
    for which, manifest in (("best", best), ("last", last)):
        digest = sha256_file(run / which / "model.pt")
        check(
            rows,
            f"{which} model.pt equals manifest model_sha256",
            digest == manifest["model_sha256"],
            digest[:16],
        )
    prov = last["provenance"]
    steps = last["counters"]["trainer"]["optimizer_steps"]
    check(
        rows,
        "optimizer steps reached",
        steps == args.expect_steps,
        f"{steps} of {args.expect_steps}",
    )
    check(rows, "no skipped steps", last["counters"]["trainer"]["skipped_steps"] == 0, "")
    weight = prov["training"]["loss_lambda_retrieval"]
    check(
        rows,
        "retrieval loss weight recorded",
        math.isclose(weight, args.expect_retrieval_weight),
        f"{weight}",
    )
    tok = Path(args.tokenizer_model)
    check(
        rows,
        "tokenizer sha256 equals the accepted candidate",
        prov["tokenizer_sha256"] == sha256_file(tok),
        prov["tokenizer_sha256"][:16],
    )
    if args.init_run:
        init = load_manifest(RUNS / args.init_run, "best")
        check(
            rows,
            "initialised from the named run's best checkpoint",
            prov["initial_model_sha256"] == init["model_sha256"],
            str(prov["initial_model_sha256"])[:16],
        )
    else:
        check(
            rows,
            "trained from scratch (no initial checkpoint)",
            prov["initial_checkpoint"] is None,
            "",
        )
    loop = last["counters"]["loop"]
    run_cfg = prov["run_config"]
    check(
        rows,
        "stale evaluations within patience",
        loop["stale_evals"] <= run_cfg["patience"],
        f"{loop['stale_evals']} / {run_cfg['patience']}",
    )
    final = last_validation(last)
    finite = all(math.isfinite(final[t]) for t in TASKS if t in final)
    check(rows, "final validation losses finite", finite, "")
    if args.log:
        log = parse_log(Path(args.log))
        check(rows, "log reports [SUCCESS]", log["success"], "")
        check(rows, "log has no nan or inf", not log["nan"], "")
        peak = log["peak_mem_gib"]
        check(
            rows,
            f"peak memory <= {args.max_peak_gib} GiB",
            peak is not None and peak <= args.max_peak_gib,
            f"{peak} GiB, median {log['median_s_per_step']} s/step",
        )
    if args.reference_run:
        ref = last_validation(load_manifest(RUNS / args.reference_run, "best"))
        for task in TASKS:
            if task in final and task in ref and task != "qa":
                limit = ref[task] * (1.0 + args.forgetting_tolerance)
                check(
                    rows,
                    f"{task} validation loss not worse than reference by > "
                    f"{args.forgetting_tolerance:.0%}",
                    final[task] <= limit,
                    f"{final[task]:.4f} vs reference {ref[task]:.4f}",
                )
        check(rows, "qa validation loss reported", "qa" in final, f"{final.get('qa')}")
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expect-steps", type=int, required=True)
    parser.add_argument("--expect-retrieval-weight", type=float, required=True)
    parser.add_argument("--tokenizer-model", required=True)
    parser.add_argument("--init-run", help="run whose best checkpoint initialised this one")
    parser.add_argument("--reference-run", help="run to compare validation loss against")
    parser.add_argument("--log")
    parser.add_argument("--max-peak-gib", type=float, default=14.5)
    parser.add_argument("--forgetting-tolerance", type=float, default=0.10)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    for var in AUTH_VARS:
        if os.environ.get(var):
            print(f"[FAIL] {var} is set; intake never runs with training authorized.")
            return 2
    try:
        rows = run_checks(args)
    except (OSError, KeyError, ValueError) as exc:
        print(f"[FAIL] unusable input: {exc!r}")
        return 2
    ok = all(passed for _, passed, _ in rows)
    for name, passed, detail in rows:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "passed": ok,
                    "checks": [{"name": n, "passed": p, "detail": d} for n, p, d in rows],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    print("[PASS] intake" if ok else "[FAIL] intake")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
