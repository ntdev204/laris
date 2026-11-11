#!/usr/bin/env python3
"""Benchmark the vault at scale (SR-H4): a synthetic vault of N notes.

Measures the full index, the incremental update of one note (with the disposable cache), peak
resident memory, and BM25 search latency (P95). Writes a JSON report; with --check it compares the
result with the stored budgets and fails when a figure is worse than the budget by more than 20
percent (and always when a spec target is missed). `--record` stores the measured numbers, with
20 percent headroom, as the budgets. Deterministic content; timings vary with the machine, which is
why the budget is recorded from a measurement on the development workstation.

    python scripts/benchmark_vault.py --notes 10000 --out reports/performance/vault.json
    python scripts/benchmark_vault.py --check
"""

import argparse
import json
import random
import resource
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vault.index import VaultIndex  # noqa: E402
from vault.search import NoteSearch  # noqa: E402

TARGETS = {"full_index_s": 30.0, "incremental_s": 1.0, "peak_rss_mb": 500.0, "search_p95_ms": 300.0}
BUDGETS = ROOT / "reports" / "performance" / "budgets.json"
REGRESSION = 0.20
WORDS = (
    "perovskite lithium transformer attention citation graph vault note concept method dataset "
    "metric claim limitation source evidence retrieval ranking passage index cache cell energy "
    "battery "
    "language model protein folding sequence structure analysis result figure table benchmark"
).split()


def build_vault(root: Path, count: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    for i in range(count):
        folder = root / f"Folder{i % 20}"
        folder.mkdir(parents=True, exist_ok=True)
        links = " ".join(f"[[Note {rng.randrange(count)}]]" for _ in range(4))
        body = " ".join(rng.choice(WORDS) for _ in range(120))
        (folder / f"Note {i}.md").write_text(
            f"---\ntype: concept\ncreated: 2026-01-01\ntags: [t{i % 50}]\n---\n"
            f"# Note {i}\n{body}\n{links}\n",
            encoding="utf-8",
        )


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0  # Linux: kilobytes


def measure(count: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "vault"
        build_vault(root, count)
        cache = Path(tmp) / "cache" / "index.json"
        started = time.perf_counter()
        index = VaultIndex.build(root, cache_file=cache)
        full = time.perf_counter() - started
        target = root / "Folder3" / "Note 3.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nedited line\n", encoding="utf-8")
        started = time.perf_counter()
        index = VaultIndex.build(root, cache_file=cache)
        incremental = time.perf_counter() - started
        searcher = NoteSearch(index)
        rng = random.Random(11)
        timings = []
        for _ in range(200):
            query = " ".join(rng.sample(WORDS, 3))
            started = time.perf_counter()
            searcher.search(query, 10)
            timings.append((time.perf_counter() - started) * 1000.0)
        timings.sort()
        return {
            "notes": len(index.notes),
            "full_index_s": round(full, 3),
            "incremental_s": round(incremental, 3),
            "peak_rss_mb": round(peak_rss_mb(), 1),
            "search_p95_ms": round(timings[int(len(timings) * 0.95) - 1], 2),
            "search_median_ms": round(timings[len(timings) // 2], 2),
        }


def violations(result: dict, budgets: dict) -> list:
    problems = []
    for name, limit in TARGETS.items():
        if result[name] > limit:
            problems.append(f"{name} {result[name]} misses the spec target {limit}")
    for name, budget in budgets.get("budgets", {}).items():
        if result[name] > budget * (1 + REGRESSION):
            problems.append(
                f"{name} {result[name]} is over budget {budget} by more than 20 percent"
            )
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--notes", type=int, default=10000)
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true", help="Fail on a target miss or regression")
    parser.add_argument("--record", action="store_true", help="Store this run as the budgets")
    args = parser.parse_args(argv)
    result = measure(args.notes)
    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.record:
        BUDGETS.parent.mkdir(parents=True, exist_ok=True)
        BUDGETS.write_text(
            json.dumps(
                {
                    "notes": result["notes"],
                    "targets": TARGETS,
                    "budgets": {k: result[k] for k in TARGETS},
                    "note": "measured on the development workstation; a figure more than 20 "
                    "percent above its budget fails --check",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    budgets = json.loads(BUDGETS.read_text()) if BUDGETS.is_file() else {}
    problems = violations(result, budgets)
    for problem in problems:
        print("[FAIL]", problem)
    return 1 if (args.check and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
