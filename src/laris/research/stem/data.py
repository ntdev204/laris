"""STEM benchmark data: download with provenance, seeded splits, manifest and the sealed guard
(T275, ADR-026).

Layout under the configured `data_dir` (outside Git):

    raw/<source>/...            files as downloaded at a pinned revision
    provenance.json             per file: repo, revision, licence, size, SHA-256
    splits/dev/<bench>.jsonl    development items (tuning allowed)
    splits/sealed/<bench>.jsonl sealed test items (read only by a sealed run)
    manifest.json               seed, counts and SHA-256 of every split file
    sealed_runs.jsonl           one line per sealed run (candidate, time)

Benchmarks: `math500`, `mmlu_pro_stem`, `gpqa_diamond`. Items are normalised to `{"id", "question",
"options", "answer", "category"}`; `options` is empty for MATH and `answer` is a letter for multiple
choice. Sealed files are opened only through `load_items(..., sealed_order=...)` with the order the
owner put in the configured environment variable, and each candidate is sealed-run at most once.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

BENCHMARKS = ("math500", "mmlu_pro_stem", "gpqa_diamond")
LETTERS = "ABCDEFGHIJ"


class SealedAccessError(PermissionError):
    """A sealed split was asked for outside an authorised sealed run."""


def load_config(path: Path) -> Dict[str, Any]:
    config: Dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return config


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# -- download ------------------------------------------------------------------------------------


def download(config: Dict[str, Any], root: Path) -> Dict[str, Any]:
    """Fetch every configured source file at its pinned revision; write and return
    `provenance.json`."""
    from huggingface_hub import hf_hub_download  # network: only here

    data_dir = root / config["data_dir"]
    provenance: Dict[str, Any] = {"downloaded_at": _now(), "sources": {}}
    for name, source in config["sources"].items():
        target = data_dir / "raw" / name
        files = []
        for filename in source["files"]:
            path = Path(
                hf_hub_download(
                    source["repo"],
                    filename,
                    repo_type="dataset",
                    revision=source["revision"],
                    local_dir=target,
                )
            )
            files.append(
                {"file": filename, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            )
        provenance["sources"][name] = {
            "repo": source["repo"],
            "revision": source["revision"],
            "licence_card": source["licence_card"],
            "licence_source": source["licence_source"],
            "files": files,
        }
    _write_json(data_dir / "provenance.json", provenance)
    return provenance


def verify_provenance(config: Dict[str, Any], root: Path) -> None:
    """Raise if a raw file is missing or its SHA-256 differs from `provenance.json`."""
    data_dir = root / config["data_dir"]
    provenance = json.loads((data_dir / "provenance.json").read_text(encoding="utf-8"))
    for name, source in provenance["sources"].items():
        for entry in source["files"]:
            path = data_dir / "raw" / name / entry["file"]
            if sha256_file(path) != entry["sha256"]:
                raise ValueError(f"raw file changed since download: {name}/{entry['file']}")


# -- raw readers -----------------------------------------------------------------------------------


def _read_parquet(path: Path) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    rows: List[Dict[str, Any]] = pq.read_table(path).to_pylist()
    return rows


def read_math500(raw: Path) -> List[Dict[str, Any]]:
    items = []
    for line in (raw / "math500" / "test.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            items.append(
                {
                    "id": "math500/" + row["unique_id"],
                    "question": row["problem"],
                    "options": [],
                    "answer": row["answer"],
                    "category": row["subject"],
                    "level": row.get("level"),
                }
            )
    return items


def read_math_train(raw: Path) -> List[Dict[str, Any]]:
    from laris.research.stem.answers import last_boxed

    items = []
    for folder in sorted(p for p in (raw / "math_train").iterdir() if p.is_dir()):
        for path in sorted(folder.glob("train-*.parquet")):
            for index, row in enumerate(_read_parquet(path)):
                answer = last_boxed(row["solution"])
                if answer is None:
                    continue
                items.append(
                    {
                        "id": f"math_train/{folder.name}/{index}",
                        "question": row["problem"],
                        "options": [],
                        "answer": answer,
                        "category": row.get("type") or folder.name,
                        "level": row.get("level"),
                    }
                )
    return items


def read_mmlu_pro(raw: Path, categories: Iterable[str]) -> List[Dict[str, Any]]:
    wanted = set(categories)
    items = []
    for row in _read_parquet(raw / "mmlu_pro" / "data" / "test-00000-of-00001.parquet"):
        if row["category"] not in wanted:
            continue
        options = [str(o) for o in row["options"]]
        items.append(
            {
                "id": f"mmlu_pro/{row['question_id']}",
                "question": row["question"],
                "options": options,
                "answer": LETTERS[int(row["answer_index"])],
                "category": row["category"],
            }
        )
    return items


def read_gpqa(raw: Path, filename: str, shuffle_seed: int) -> List[Dict[str, Any]]:
    """GPQA rows with the four options shuffled by a seed derived from the record id (recorded
    seed)."""
    items = []
    with open(raw / "gpqa" / filename, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            record = row["Record ID"].strip()
            correct = row["Correct Answer"].strip()
            options = [correct] + [row[f"Incorrect Answer {i}"].strip() for i in (1, 2, 3)]
            order = list(range(4))
            random.Random(f"{shuffle_seed}:{record}").shuffle(order)
            shuffled = [options[i] for i in order]
            items.append(
                {
                    "id": f"gpqa/{record}",
                    "question": row["Question"].strip(),
                    "options": shuffled,
                    "answer": LETTERS[order.index(0)],
                    "category": row.get("High-level domain", "").strip(),
                }
            )
    return items


# -- splits ----------------------------------------------------------------------------------------


def normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def stratified_sample(
    items: List[Dict[str, Any]], fraction: float, seed: int
) -> List[Dict[str, Any]]:
    """A seeded sample of `fraction` of the items within every category (rounded per category)."""
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)
    chosen: List[Dict[str, Any]] = []
    for category in sorted(by_category):
        group = sorted(by_category[category], key=lambda i: i["id"])
        rng = random.Random(f"{seed}:{category}")
        chosen.extend(rng.sample(group, round(len(group) * fraction)))
    return sorted(chosen, key=lambda i: i["id"])


def build_splits(
    math500: List[Dict[str, Any]],
    math_train: List[Dict[str, Any]],
    mmlu_stem: List[Dict[str, Any]],
    gpqa_main: List[Dict[str, Any]],
    gpqa_diamond: List[Dict[str, Any]],
    *,
    seed: int,
    math_dev_size: int,
    mmlu_dev_fraction: float,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """The ADR-026 section 3 splits: `{bench: {"dev": [...], "sealed": [...]}}`."""
    sealed_math = {normalise_text(i["question"]) for i in math500}
    pool = sorted(
        (i for i in math_train if normalise_text(i["question"]) not in sealed_math),
        key=lambda i: i["id"],
    )
    math_dev = sorted(
        random.Random(f"{seed}:math").sample(pool, math_dev_size), key=lambda i: i["id"]
    )

    mmlu_dev = stratified_sample(mmlu_stem, mmlu_dev_fraction, seed)
    dev_ids = {i["id"] for i in mmlu_dev}
    mmlu_sealed = [i for i in mmlu_stem if i["id"] not in dev_ids]

    diamond_ids = {i["id"] for i in gpqa_diamond}
    diamond_text = {normalise_text(i["question"]) for i in gpqa_diamond}
    gpqa_dev = [
        i
        for i in gpqa_main
        if i["id"] not in diamond_ids and normalise_text(i["question"]) not in diamond_text
    ]
    return {
        "math500": {"dev": math_dev, "sealed": list(math500)},
        "mmlu_pro_stem": {"dev": mmlu_dev, "sealed": mmlu_sealed},
        "gpqa_diamond": {"dev": gpqa_dev, "sealed": list(gpqa_diamond)},
    }


def write_splits(config: Dict[str, Any], root: Path) -> Dict[str, Any]:
    """Read the raw files, write the split files once and the manifest; refuse to overwrite."""
    data_dir = root / config["data_dir"]
    verify_provenance(config, root)
    if (data_dir / "manifest.json").exists():
        raise FileExistsError("splits already written; they are written once (ADR-026 section 3)")
    raw = data_dir / "raw"
    split_cfg = config["splits"]
    shuffle_seed = int(config["option_shuffle_seed"])
    splits = build_splits(
        read_math500(raw),
        read_math_train(raw),
        read_mmlu_pro(raw, split_cfg["mmlu_pro_stem"]["categories"]),
        read_gpqa(raw, "gpqa_main.csv", shuffle_seed),
        read_gpqa(raw, "gpqa_diamond.csv", shuffle_seed),
        seed=int(config["split_seed"]),
        math_dev_size=int(split_cfg["math500"]["dev_size"]),
        mmlu_dev_fraction=float(split_cfg["mmlu_pro_stem"]["dev_fraction"]),
    )
    manifest: Dict[str, Any] = {
        "written_at": _now(),
        "split_seed": config["split_seed"],
        "option_shuffle_seed": shuffle_seed,
        "provenance_sha256": sha256_file(data_dir / "provenance.json"),
        "benchmarks": {},
    }
    for bench, parts in splits.items():
        manifest["benchmarks"][bench] = {}
        for part, items in parts.items():
            path = data_dir / "splits" / part / f"{bench}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                for item in items:
                    handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            categories: Dict[str, int] = {}
            for item in items:
                categories[item["category"]] = categories.get(item["category"], 0) + 1
            manifest["benchmarks"][bench][part] = {
                "file": str(path.relative_to(data_dir)),
                "items": len(items),
                "categories": dict(sorted(categories.items())),
                "sha256": sha256_file(path),
            }
    _write_json(data_dir / "manifest.json", manifest)
    return manifest


# -- reading splits (sealed guard) ----------------------------------------------------------------


def load_items(
    config: Dict[str, Any],
    root: Path,
    bench: str,
    split: str,
    *,
    sealed_order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Items of one split, checked against the manifest hash. `sealed` needs an authorised sealed
    run."""
    if bench not in BENCHMARKS or split not in ("dev", "sealed"):
        raise ValueError(f"unknown split {bench}/{split}")
    data_dir = root / config["data_dir"]
    if split == "sealed":
        authorise_sealed_run(config, data_dir, sealed_order)
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["benchmarks"][bench][split]
    path = data_dir / entry["file"]
    if sha256_file(path) != entry["sha256"]:
        raise ValueError(f"split file changed since it was written: {entry['file']}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def authorise_sealed_run(config: Dict[str, Any], data_dir: Path, order: Optional[str]) -> None:
    """Refuse unless `order` (the candidate id) equals the owner's order in the environment, and the
    candidate has not been sealed-run before, and fewer than the configured maximum candidates
    ran."""
    expected = os.environ.get(config["sealed_order_env"], "")
    if not order or order != expected:
        raise SealedAccessError(
            "sealed test files are read only by a sealed run ordered by the owner "
            "(ADR-026 section 7)"
        )
    runs = _sealed_log(data_dir)
    if any(r["candidate"] == order and r.get("finished_at") for r in runs):
        raise SealedAccessError(f"candidate {order!r} was already sealed-run; each runs once")
    candidates = {r["candidate"] for r in runs}
    if order in candidates:
        return  # the same run reads its several sealed files; it was logged when it started
    if len(candidates) >= int(config["max_sealed_candidates"]):
        raise SealedAccessError("the maximum number of sealed-run candidates is reached")
    _append_sealed_log(data_dir, {"candidate": order, "started_at": _now()})


def finish_sealed_run(config: Dict[str, Any], root: Path, order: str) -> None:
    """Close a candidate's sealed run: its sealed files are refused from now on."""
    _append_sealed_log(root / config["data_dir"], {"candidate": order, "finished_at": _now()})


def _sealed_log(data_dir: Path) -> List[Dict[str, Any]]:
    log = data_dir / "sealed_runs.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _append_sealed_log(data_dir: Path, entry: Dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "sealed_runs.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
