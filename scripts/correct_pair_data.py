#!/usr/bin/env python3
"""Pair-task data corrections found by the T193 audit (T206). Reads and writes data; nothing trains.

1. `sts_extra_en`: the SICK-EN rows carried the SICK NLI class divided by 5 instead of the
   human-graded `relatedness_score`. A precheck matches every SICK row of the current table to
   the raw SICK files and counts which column its score came from; the table is then rebuilt
   by `scripts/check_sts_leakage.py` with the score column and range declared per source in
   `configs/data/english_sources.yaml`. Rows keep their `source` column, so SICK-EN can be
   filtered out later without a rebuild.
2. `squad/train`: rows whose normalised (question, context) pair also occurs in `squad_v2_en`
   validation or test are removed. Only SQuAD v1 train changes: SQuAD v1 val and test and
   every SQuAD 2.0 split (including its unanswerable questions) stay byte-identical.

The originals are copied to `data/cache/superseded/T206/` before anything is written, and the
frozen `data/processed/r1/squad` symlink is replaced by a copy of the original files so the T96
revision keeps verifying. A lineage report with checksums goes to
`reports/verification/T206-pair-data-corrections.json`.

Usage:
    .venv/bin/python -I scripts/correct_pair_data.py            # dry run: precheck and counts only
    .venv/bin/python -I scripts/correct_pair_data.py --apply    # write the corrected data
"""

import argparse
import hashlib
import importlib.util
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "val", "test")
TOLERANCE = 1e-6

_spec = importlib.util.spec_from_file_location(
    "check_sts_leakage", ROOT / "scripts/check_sts_leakage.py"
)
assert _spec and _spec.loader
leak = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(leak)
normalise = leak.normalise


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pair_key(a: str, b: str) -> Tuple[str, str]:
    x, y = normalise(a), normalise(b)
    return (x, y) if x <= y else (y, x)


def qa_key(question: str, context: str) -> Tuple[str, str]:
    return normalise(question), normalise(context)


# --------------------------------------------------------------------------- SICK


def sick_index(raw_rows: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str], List[Dict[str, float]]]:
    """Unordered normalised SICK pair -> its (label, relatedness_score) records."""
    index: Dict[Tuple[str, str], List[Dict[str, float]]] = defaultdict(list)
    for r in raw_rows:
        index[pair_key(r["sentence_A"], r["sentence_B"])].append(
            {"label": float(r["label"]), "relatedness": float(r["relatedness_score"])}
        )
    return index


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def sick_score_origin(
    table_rows: Iterable[Dict[str, Any]],
    index: Dict[Tuple[str, str], List[Dict[str, float]]],
    low: float,
    high: float,
) -> Dict[str, int]:
    """Counts which raw SICK column each stored score of the SICK-EN rows matches."""
    c: Counter = Counter()
    for r in table_rows:
        if r.get("source") != "SICK-EN":
            continue
        c["sick_rows"] += 1
        raw = index.get(pair_key(r["sentence1"], r["sentence2"]))
        if not raw:
            c["not_matched_to_raw"] += 1
            continue
        score = float(r["score"])
        if any(_close(score, x["label"] / 5.0) for x in raw):
            c["equals_nli_label_div_5"] += 1
        if any(_close(score, x["relatedness"] / 5.0) for x in raw):
            c["equals_relatedness_div_5"] += 1
        if any(_close(score, (x["relatedness"] - low) / (high - low)) for x in raw):
            c["equals_relatedness_scaled"] += 1
    return dict(c)


# --------------------------------------------------------------------------- SQuAD


def heldout_qa_keys(tables: Iterable[pa.Table]) -> Set[Tuple[str, str]]:
    keys: Set[Tuple[str, str]] = set()
    for t in tables:
        for q, c in zip(t.column("question").to_pylist(), t.column("context").to_pylist()):
            keys.add(qa_key(q, c))
    return keys


def drop_heldout_rows(train: pa.Table, blocked: Set[Tuple[str, str]]) -> Tuple[pa.Table, int]:
    """Keeps the train rows whose (question, context) pair is not in `blocked`; schema unchanged."""
    keep = [
        qa_key(q, c) not in blocked
        for q, c in zip(train.column("question").to_pylist(), train.column("context").to_pylist())
    ]
    return train.filter(pa.array(keep, type=pa.bool_())), keep.count(False)


# --------------------------------------------------------------------------- files


def backup(paths: List[Path], dest_root: Path) -> Dict[str, str]:
    """Copies each file to `dest_root/<dataset dir>/<name>` (never overwrites); sha256 by path."""
    out = {}
    for p in paths:
        dest = dest_root / p.parent.name / p.name
        if dest.exists():
            if sha256_file(dest) != sha256_file(p):
                raise FileExistsError(
                    f"{dest} exists with other content; refusing to overwrite a backup"
                )
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        out[str(p.relative_to(ROOT))] = sha256_file(dest)
    return out


def freeze_symlink(link: Path, originals: Path) -> bool:
    """Replaces a revision symlink by a copy of the original files so it keeps verifying."""
    if not link.is_symlink():
        return False
    link.unlink()
    shutil.copytree(originals, link)
    return True


def update_manifest(
    manifest_path: Path, dataset_id: str, split: str, path: Path, rows: int
) -> Dict[str, Any]:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in m["partitioned_datasets"]:
        if entry["dataset_id"] == dataset_id:
            before = {k: entry[k][split] for k in ("counts", "bytes", "sha256")}
            entry["counts"][split] = rows
            entry["bytes"][split] = path.stat().st_size
            entry["sha256"][split] = sha256_file(path)
            manifest_path.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
            return {
                "before": before,
                "after": {k: entry[k][split] for k in ("counts", "bytes", "sha256")},
            }
    raise KeyError(f"{dataset_id} not in {manifest_path}")


# --------------------------------------------------------------------------- driver


def run(args: argparse.Namespace) -> Dict[str, Any]:
    processed = Path(args.processed)
    sts_path = processed / "sts_extra_en/train.parquet"
    squad_dir = processed / "squad"
    v2_dir = processed / "squad_v2_en"
    from laris.research.corpus.acquisition.sources.english_hf import load_sources_config

    config = load_sources_config(args.config)
    sick = next(s for s in config["sources"] if s["id"] == "SICK-EN")
    field, low, high = leak.score_spec(sick)
    if field != "relatedness_score":
        raise ValueError(f"SICK-EN score_field is {field!r}; T206 expects relatedness_score")
    raw_sick = [
        r
        for f in sorted((ROOT / "data/raw/sick_en").glob("*.parquet"))
        for r in pq.read_table(f).to_pylist()
    ]
    index = sick_index(raw_sick)

    sts_before = pq.read_table(sts_path).to_pylist()
    report: Dict[str, Any] = {
        "task": "T206",
        "applied": bool(args.apply),
        "sick": {
            "raw_rows": len(raw_sick),
            "score_field": field,
            "score_range": [low, high],
            "precheck_current_table": sick_score_origin(sts_before, index, low, high),
            "rows_by_source_before": dict(Counter(r["source"] for r in sts_before)),
        },
    }

    squad_train = pq.read_table(squad_dir / "train.parquet")
    blocked = heldout_qa_keys(pq.read_table(v2_dir / f"{s}.parquet") for s in ("val", "test"))
    squad_kept, dropped = drop_heldout_rows(squad_train, blocked)
    report["squad"] = {
        "train_rows_before": squad_train.num_rows,
        "squad_v2_heldout_pairs": len(blocked),
        "train_rows_dropped": dropped,
        "train_rows_after": squad_kept.num_rows,
        "rule": "drop squad/train rows whose normalised (question, context) is in squad_v2_en "
        "val or test",
    }
    untouched = [squad_dir / "val.parquet", squad_dir / "test.parquet"] + [
        v2_dir / f"{s}.parquet" for s in SPLITS
    ]
    sha_before = {str(p.relative_to(ROOT)): sha256_file(p) for p in untouched}
    if not args.apply:
        return report

    backup_root = ROOT / args.backup_dir
    report["backup"] = {
        "dir": args.backup_dir,
        "sha256": backup([sts_path, *[squad_dir / f"{s}.parquet" for s in SPLITS]], backup_root),
    }
    report["r1_squad_frozen"] = freeze_symlink(processed / "r1/squad", backup_root / "squad")

    leak.main(
        [
            "--config",
            str(args.config),
            "--output",
            str(sts_path),
            "--report",
            str(ROOT / args.sts_report),
        ]
    )
    sts_after = pq.read_table(sts_path).to_pylist()
    report["sick"]["postcheck_rebuilt_table"] = sick_score_origin(sts_after, index, low, high)
    report["sick"]["rows_by_source_after"] = dict(Counter(r["source"] for r in sts_after))
    other_before = Counter(
        (r["sentence1"], r["sentence2"], round(float(r["score"]), 6), r["source"])
        for r in sts_before
        if r["source"] != "SICK-EN"
    )
    other_after = Counter(
        (r["sentence1"], r["sentence2"], round(float(r["score"]), 6), r["source"])
        for r in sts_after
        if r["source"] != "SICK-EN"
    )
    report["sick"]["non_sick_rows_unchanged"] = other_before == other_after
    report["sts_extra_en"] = {"rows": len(sts_after), "sha256": sha256_file(sts_path)}

    pq.write_table(squad_kept, squad_dir / "train.parquet")
    remaining = heldout_qa_keys([pq.read_table(squad_dir / "train.parquet")]) & blocked
    report["squad"]["postcheck_train_pairs_in_v2_heldout"] = len(remaining)
    report["squad"]["manifest"] = update_manifest(
        processed / "task_splits_manifest.json",
        "SQUAD",
        "train",
        squad_dir / "train.parquet",
        squad_kept.num_rows,
    )
    sha_after = {k: sha256_file(ROOT / k) for k in sha_before}
    report["untouched_files_identical"] = sha_after == sha_before
    report["untouched_sha256"] = sha_after
    if args.r1_manifest and (processed / "r1/task_splits_manifest.json").exists():
        r1 = json.loads((processed / "r1/task_splits_manifest.json").read_text(encoding="utf-8"))
        entry = next(e for e in r1["partitioned_datasets"] if e["dataset_id"] == "SQUAD")
        report["r1_squad_verifies"] = all(
            sha256_file(processed / "r1/squad" / f"{s}.parquet") == entry["sha256"][s]
            for s in SPLITS
        )
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=ROOT / "configs/data/english_sources.yaml")
    p.add_argument("--processed", default=str(ROOT / "data/processed"))
    p.add_argument("--backup-dir", default="data/cache/superseded/T206")
    p.add_argument("--sts-report", default="reports/verification/T206-sts-extra-rebuild.json")
    p.add_argument(
        "--report", type=Path, default=ROOT / "reports/verification/T206-pair-data-corrections.json"
    )
    p.add_argument("--no-r1-manifest", dest="r1_manifest", action="store_false")
    p.add_argument("--apply", action="store_true", help="write the corrections (default: dry run)")
    args = p.parse_args(argv)
    report = run(args)
    text = json.dumps(report, indent=2) + "\n"
    if args.apply:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
