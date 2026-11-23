#!/usr/bin/env python3
"""Build, freeze, scan and measure the STEM main-brain snapshot (T277, ADR-026 section 5).

    python scripts/acquire_openstax.py              # network, once: pinned books + provenance
    cargo build --release -p laris-server
    python scripts/build_stem_brain.py build NAME   # proposals -> write gate -> vault -> manifest
    python scripts/build_stem_brain.py scan NAME    # B6: 13-gram scan against every benchmark item
    python scripts/build_stem_brain.py recall NAME  # retrieval on the development splits

Settings: `configs/stem-brain.json`. The snapshot is `data/brain/snapshots/NAME/` (outside Git):
`proposals.jsonl`, `vault/` (written only by the gate, through `laris-server brain import`),
`import.json` (the gate's decisions, counted), `snapshot.json` (every file's SHA-256 and the
snapshot hash) and `scan.json` / `recall.json`. A snapshot is built once into a new folder and not
changed afterwards; a changed build is a new NAME.

The recall measure is a proxy, since no relevance labels exist: for a multiple-choice development
item whose correct option is words (no digits), whether a retrieved passage holds every content
word of that option, against the same rate for the wrong options. Reports carry counts and rates,
never a question or an option. Nothing here trains; the model is not involved and is NOT QUALIFIED.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.research.knowledge import build  # noqa: E402
from laris.research.stem import data, leakage  # noqa: E402

_STOP = set(
    "a an the is are was were be been of in on at to for by with and or it its this that these "
    "those as from has have had can may will than which what not no all none both only".split()
)


def load(path: str) -> Dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def snapshot_dir(config: Dict[str, Any], name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
        raise SystemExit("a snapshot name is letters, digits, dot, dash or underscore")
    return ROOT / config["data_dir"] / "snapshots" / name


def server_env(config: Dict[str, Any], vault: Path) -> Dict[str, str]:
    gate = config["gate"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("LARIS_SERVER__")}
    env.update(
        {
            "LARIS_SERVER__MAIN_BRAIN_DIR": str(vault),
            "LARIS_SERVER__MAIN_BRAIN_MIN_SUPPORT": str(gate["min_support"]),
            "LARIS_SERVER__MAIN_BRAIN_MIN_EQUIVALENCE": str(gate["min_equivalence"]),
            "LARIS_SERVER__MAIN_BRAIN_SUBJECT_OVERLAP": str(gate["subject_overlap"]),
            "LARIS_SERVER__MAIN_BRAIN_SEARCH_DEPTH": str(gate["search_depth"]),
            "LARIS_SERVER__MAIN_BRAIN_MAX_BYTES": str(gate["max_bytes"]),
        }
    )
    return env


def server(
    args: argparse.Namespace, config: Dict[str, Any], vault: Path, *cmd: str, stdout=None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ROOT / args.server_bin), "brain", *cmd],
        env=server_env(config, vault),
        check=True,
        text=True,
        stdout=stdout or subprocess.PIPE,
    )


def git_revision() -> str:
    """HEAD, with `+changes` when the working tree differs from it (the build's code identity)."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return head + ("+changes" if dirty else "")


def cmd_build(args: argparse.Namespace) -> int:
    from laris.model.solver import SolverSettings
    from laris.model.solver.runner import run as solver_run
    from laris.shared.config.loader import load_runtime_config

    config = load(args.config)
    out = snapshot_dir(config, args.name)
    if out.exists():
        raise SystemExit(f"{out.relative_to(ROOT)} exists: a snapshot is built once")
    out.mkdir(parents=True)
    provenance = json.loads(
        (ROOT / config["data_dir"] / "raw" / "openstax" / "provenance.json").read_text("utf-8")
    )
    settings = SolverSettings.from_config(load_runtime_config(ROOT).model_service)
    bench_config = data.load_config(ROOT / args.bench_config)
    overlaps = benchmark_overlap(bench_config)
    links = build.SolverLinks(
        lambda problem: solver_run(problem, settings), config["build"]["proposer"], overlaps
    )
    sources, claims, counts = build.openstax_lines(
        config, ROOT, provenance, links, overlaps, int(bench_config["leakage"]["ngram"])
    )
    from laris.model.solver.constants import PACKAGED

    codata_table = Path(settings.codata_file) if settings.codata_file else PACKAGED
    c_sources, c_claims, c_counts = build.codata_lines(
        config, codata_table, settings.codata_sha256, links, overlaps
    )
    proposals = out / "proposals.jsonl"
    total = build.write_lines(
        proposals, [list(links.sources.values()), sources, c_sources, claims, c_claims]
    )
    counts.update(c_counts)
    counts["solver"] = {
        "tried": links.tried,
        "linked_by_status": links.linked,
        "tool_run_sources": len(links.sources),
    }
    counts["proposal_lines"] = total
    print(json.dumps(counts, indent=1))
    result = server(args, config, out / "vault", "import", str(proposals), "--date", config["date"])
    decisions = json.loads(result.stdout)
    server(args, config, out / "vault", "freeze", str(out / "snapshot.json"))
    manifest = json.loads((out / "snapshot.json").read_text("utf-8"))
    record = {
        "counts": counts,
        "gate": decisions,
        "config_sha256": build.sha256((ROOT / args.config).read_bytes()),
        "provenance_sha256": build.sha256(
            (ROOT / config["data_dir"] / "raw" / "openstax" / "provenance.json").read_bytes()
        ),
        "snapshot_sha256": manifest["snapshot_sha256"],
        "code_revision": git_revision(),
    }
    (out / "import.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    summary = {
        k: manifest[k]
        for k in (
            "snapshot_sha256",
            "files",
            "notes_by_type",
            "claims_by_level",
            "claims_with_solver_ref",
            "lint_problems",
            "lint_by_code",
        )
    }
    print(json.dumps({"gate": decisions, "snapshot": summary}, indent=1))
    return 0 if manifest["lint_problems"] == 0 else 1


def _benchmark_items(bench_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every benchmark item, dev and sealed (read from the raw files as the T275 scan does)."""
    raw = ROOT / bench_config["data_dir"] / "raw"
    seed = int(bench_config["option_shuffle_seed"])
    items = data.read_math500(raw) + data.read_math_train(raw)
    items += data.read_mmlu_pro(raw, bench_config["splits"]["mmlu_pro_stem"]["categories"])
    items += data.read_gpqa(raw, "gpqa_main.csv", seed) + data.read_gpqa(
        raw, "gpqa_diamond.csv", seed
    )
    return items


def benchmark_overlap(bench_config: Dict[str, Any]) -> build.Overlap:
    """Whether a text shares a word n-gram (the scan's n) with any benchmark item, dev or sealed.
    The build leaves such text out; benchmark text itself never enters the brain."""
    n = int(bench_config["leakage"]["ngram"])
    grams = set(leakage.item_index(_benchmark_items(bench_config), n))
    return lambda text: not grams.isdisjoint(leakage.ngrams(text, n))


def cmd_scan(args: argparse.Namespace) -> int:
    config = load(args.config)
    bench_config = data.load_config(ROOT / args.bench_config)
    out = snapshot_dir(config, args.name)
    cfg = bench_config["leakage"]
    items = _benchmark_items(bench_config)
    hits = leakage.scan_folder(out / "vault", items, int(cfg["ngram"]), cfg["note_suffixes"])
    by_bench: Dict[str, int] = {}
    for hit in hits:
        bench = hit["item"].split("/", 1)[0]
        by_bench[bench] = by_bench.get(bench, 0) + 1
    report = {
        "ngram": cfg["ngram"],
        "items_scanned": len(items),
        "hits": len(hits),
        "hits_by_item_prefix": by_bench,
        "detail": hits,
    }
    (out / "scan.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "detail"}, indent=1))
    return 1 if hits else 0


def content_words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 3 and w not in _STOP]


def _supported(words: List[str], passages: List[str]) -> bool:
    return bool(words) and any(all(w in p for w in words) for p in passages)


def cmd_recall(args: argparse.Namespace) -> int:
    config = load(args.config)
    bench_config = data.load_config(ROOT / args.bench_config)
    out = snapshot_dir(config, args.name)
    ks = sorted(config["retrieval"]["k"])
    report: Dict[str, Any] = {
        "snapshot": json.loads((out / "snapshot.json").read_text("utf-8"))["snapshot_sha256"],
        "measure": "answer-word support of the correct option vs the wrong "
        "options, word options only (no digits)",
        "k": ks,
        "benchmarks": {},
    }
    tmp = out / "recall-queries.jsonl"
    for bench in ("mmlu_pro_stem", "gpqa_diamond", "math500"):
        items = data.load_items(bench_config, ROOT, bench, "dev")
        with tmp.open("w", encoding="utf-8") as f:
            for item in items:
                query = item["question"] + " " + " ".join(item.get("options") or [])
                f.write(json.dumps({"id": item["id"], "query": query}) + "\n")
        result = server(args, config, out / "vault", "retrieve", str(tmp), str(ks[-1]))
        hits = {}
        for line in result.stdout.splitlines():
            row = json.loads(line)
            hits[row["id"]] = [h["text"].lower() for h in row["hits"]]
        entry: Dict[str, Any] = {
            "items": len(items),
            "with_hits": sum(1 for i in items if hits.get(i["id"])),
        }
        eligible = []
        for item in items:
            options = item.get("options") or []
            letter = item["answer"].strip().upper()
            if not options or len(letter) != 1 or not "A" <= letter <= "Z":
                continue
            gold_index = ord(letter) - ord("A")
            if gold_index >= len(options) or re.search(r"\d", options[gold_index]):
                continue
            eligible.append((item, gold_index))
        entry["eligible"] = len(eligible)
        for k in ks:
            gold = wrong = wrong_n = 0
            for item, gi in eligible:
                passages = hits.get(item["id"], [])[:k]
                gold += _supported(content_words(item["options"][gi]), passages)
                for j, option in enumerate(item["options"]):
                    if j != gi and not re.search(r"\d", option):
                        wrong += _supported(content_words(option), passages)
                        wrong_n += 1
            entry[f"at_{k}"] = {
                "correct_option_supported": round(gold / len(eligible), 4) if eligible else None,
                "wrong_option_supported": round(wrong / wrong_n, 4) if wrong_n else None,
            }
        report["benchmarks"][bench] = entry
    tmp.unlink()
    (out / "recall.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/stem-brain.json")
    parser.add_argument("--bench-config", default="configs/stem-benchmarks.json")
    parser.add_argument("--server-bin", default="target/release/laris-server")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("build", cmd_build), ("scan", cmd_scan), ("recall", cmd_recall)):
        p = sub.add_parser(name)
        p.add_argument("name")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
