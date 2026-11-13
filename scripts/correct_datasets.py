#!/usr/bin/env python3
"""Write corrected, frozen revisions of STS-B and ViQuAD v2 beside the originals (T96, SR-M4).

Nothing is trained and no original file is modified. Corrections are decided before any
model is scored on them:

* STS-B: a normalized sentence pair (NFC, casefold, whitespace-collapsed, order-insensitive)
  that occurs in a later evaluation split is removed from the earlier split: test is never
  touched, validation loses its pairs shared with test, train loses its pairs shared with
  validation or test.
* ViQuAD v2: an answer whose `answer_start` does not point at its text is moved to the one
  place where the text occurs in the context when that place is unique and within
  `MAX_SHIFT` characters; otherwise the answer is dropped and the row is reported. No answer
  text and no question changes.

Output: `data/processed/r1/` holds the two new datasets, symlinks to every unchanged dataset
directory and a `task_splits_manifest.json` (same format as the original), so
`laris data check --data-dir data/processed/r1 --verify-sha256` verifies it. A lineage report
with checksums goes to `reports/verification/T96-data-corrections.json`.
"""

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "val", "test")
MAX_SHIFT = 2
REVISION = "r1"
NEW_NAMES = {"stsb": "STSB", "viquad_v2": "UIT-VIQUAD-V2"}


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def pair_key(a: str, b: str) -> str:
    return json.dumps(sorted([normalize(a), normalize(b)]))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def correct_stsb(
    rows: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    keys = {s: {pair_key(r["sentence1"], r["sentence2"]) for r in rows[s]} for s in SPLITS}
    later = {"train": keys["val"] | keys["test"], "val": keys["test"], "test": set()}
    out: Dict[str, List[Dict[str, Any]]] = {}
    removed: Dict[str, int] = {}
    for split in SPLITS:
        out[split] = [
            r for r in rows[split] if pair_key(r["sentence1"], r["sentence2"]) not in later[split]
        ]
        removed[split] = len(rows[split]) - len(out[split])
    return out, {"rows_removed": removed, "rows_after": {s: len(out[s]) for s in SPLITS}}


def fix_answers(row: Dict[str, Any]) -> Tuple[Dict[str, Any], Counter]:
    context = row["context"]
    texts, starts = row["answers"]["text"], row["answers"]["answer_start"]
    stats: Counter = Counter()
    new_texts: List[str] = []
    new_starts: List[int] = []
    for text, start in zip(texts, starts):
        if text and start is not None and start >= 0 and context[start : start + len(text)] == text:
            new_texts.append(text)
            new_starts.append(start)
            continue
        found = [i for i in range(len(context)) if context.startswith(text, i)] if text else []
        if len(found) == 1 and start is not None and abs(found[0] - start) <= MAX_SHIFT:
            new_texts.append(text)
            new_starts.append(found[0])
            stats["offset_moved"] += 1
        else:
            stats["answer_dropped"] += 1
    return {**row, "answers": {"text": new_texts, "answer_start": new_starts}}, stats


def correct_viquad(
    rows: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    report: Dict[str, Any] = {}
    for split in SPLITS:
        fixed: List[Dict[str, Any]] = []
        total: Counter = Counter()
        touched: List[str] = []
        for row in rows[split]:
            new_row, stats = fix_answers(row)
            if stats:
                touched.append(row["id"])
            total.update(stats)
            fixed.append(new_row)
        out[split] = fixed
        report[split] = {
            "rows": len(fixed),
            "rows_touched": touched,
            **{k: total[k] for k in sorted(total)},
        }
    return out, report


def read_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows


def write_split(path: Path, template: Path, rows: List[Dict[str, Any]]) -> None:
    schema = pq.read_schema(template)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed", type=Path, default=ROOT / "data/processed")
    parser.add_argument(
        "--report", type=Path, default=ROOT / "reports/verification/T96-data-corrections.json"
    )
    args = parser.parse_args(argv)

    processed: Path = args.processed
    out_root = processed / REVISION
    manifest_path = processed / "task_splits_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_sha = {
        name: {s: sha256_file(processed / name / f"{s}.parquet") for s in SPLITS}
        for name in NEW_NAMES
    }
    for entry in manifest["partitioned_datasets"]:
        name = Path(entry["files"]["train"]).parent.name
        if name in NEW_NAMES:
            for s in SPLITS:
                if original_sha[name][s] != entry["sha256"][s]:
                    print(f"[FAIL] {name}/{s} differs from the frozen manifest; not correcting")
                    return 1

    corrections = {"stsb": correct_stsb, "viquad_v2": correct_viquad}
    lineage: Dict[str, Any] = {}
    for name, fn in corrections.items():
        rows = {s: read_rows(processed / name / f"{s}.parquet") for s in SPLITS}
        new_rows, info = fn(rows)
        files: Dict[str, Any] = {}
        for s in SPLITS:
            target = out_root / name / f"{s}.parquet"
            write_split(target, processed / name / f"{s}.parquet", new_rows[s])
            files[s] = {
                "path": target.relative_to(ROOT).as_posix(),
                "rows": len(new_rows[s]),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
                "source_sha256": original_sha[name][s],
            }
        lineage[name] = {"corrections": info, "files": files}

    for child in sorted(processed.iterdir()):
        link = out_root / child.name
        if (
            child.is_dir()
            and child.name != REVISION
            and child.name not in NEW_NAMES
            and not link.exists()
        ):
            link.symlink_to(Path("..") / child.name)

    new_entries = []
    for entry in manifest["partitioned_datasets"]:
        name = Path(entry["files"]["train"]).parent.name
        if name in NEW_NAMES:
            files = lineage[name]["files"]
            entry = {
                **entry,
                "files": {s: files[s]["path"] for s in SPLITS},
                "counts": {s: files[s]["rows"] for s in SPLITS},
                "bytes": {s: files[s]["bytes"] for s in SPLITS},
                "sha256": {s: files[s]["sha256"] for s in SPLITS},
                "revision": REVISION,
            }
        new_entries.append(entry)
    new_manifest = {
        **manifest,
        "manifest_version": manifest["manifest_version"] + f"+{REVISION}",
        "description": "Revision r1: STS-B cross-split pairs removed, ViQuAD offsets fixed (T96).",
        "partitioned_datasets": new_entries,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "task_splits_manifest.json").write_text(
        json.dumps(new_manifest, indent=2), encoding="utf-8"
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "task": "T96",
        "revision": REVISION,
        "source_manifest_sha256": sha256_file(manifest_path),
        "originals_modified": False,
        "model_executed": False,
        "training_executed": False,
        "rules": {
            "stsb": "remove cross-split normalized pairs from the earlier split; test untouched",
            "viquad_v2": f"move answer_start to the unique occurrence within {MAX_SHIFT} chars",
        },
        "datasets": lineage,
    }
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({n: v["corrections"] for n, v in lineage.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
