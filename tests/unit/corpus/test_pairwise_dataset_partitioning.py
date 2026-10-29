"""Tests for the official-split partitioners (All-NLI, ANLI, PAWS, STSB) and manifest merging."""

import json
from pathlib import Path
from typing import Dict, List

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.splits.partitioners.pairwise import (
    partition_all_nli_physical,
    partition_anli_physical,
    partition_paws_physical,
    partition_stsb_physical,
)
from laris.corpus.splits.runner import execute_physical_partitioning


def _write(path: Path, columns: Dict[str, List]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)


def _rows(path: Path) -> List[dict]:
    return pq.read_table(path).to_pylist()


def _all_nli(raw: Path) -> None:
    def cols(pairs, labels):
        return {
            "premise": [p for p, _ in pairs],
            "hypothesis": [h for _, h in pairs],
            "label": labels,
        }

    _write(
        raw / "train-00000-of-00001.parquet",
        cols([("a", "b"), ("x", "y"), ("u", "v")], [0, 1, -1]),
    )
    _write(raw / "dev-00000-of-00001.parquet", cols([("a", "b")], [2]))
    _write(raw / "test-00000-of-00001.parquet", cols([("c", "d")], [0]))


def test_all_nli_maps_labels_and_drops_unlabeled_and_collisions(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    _all_nli(raw)
    result = partition_all_nli_physical(raw, tmp_path / "out")
    assert result.counts == {"train": 1, "val": 1, "test": 1}
    assert _rows(result.files["train"]) == [
        {"premise": "x", "hypothesis": "y", "label": "neutral"}
    ]
    assert _rows(result.files["val"])[0]["label"] == "contradiction"


def test_anli_merges_rounds_and_maps_labels(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    for rnd in ("R1", "R2", "R3"):
        for name in ("train", "dev", "test"):
            rec = {"context": f"{rnd}-{name}", "hypothesis": "h", "label": "e"}
            target = raw / "anli_v0.1" / rnd / f"{name}.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(rec) + "\n")
    result = partition_anli_physical(raw, tmp_path / "out")
    assert result.counts == {"train": 3, "val": 3, "test": 3}
    assert {r["label"] for r in _rows(result.files["train"])} == {"entailment"}


def test_paws_removes_train_pairs_sharing_a_sentence_with_held_out(tmp_path: Path) -> None:
    raw = tmp_path / "raw"

    def cols(ids, s1, s2, labels):
        return {"id": ids, "sentence1": s1, "sentence2": s2, "label": labels}

    _write(
        raw / "train-00000-of-00001.parquet",
        cols([1, 2], ["shared", "own"], ["t1", "t2"], [1, 0]),
    )
    _write(raw / "validation-00000-of-00001.parquet", cols([3], ["v1"], ["shared"], [1]))
    _write(raw / "test-00000-of-00001.parquet", cols([4], ["e1"], ["e2"], [0]))
    result = partition_paws_physical(raw, tmp_path / "out")
    assert [r["id"] for r in _rows(result.files["train"])] == [2]
    assert result.counts["val"] == result.counts["test"] == 1


def test_stsb_keeps_scores_and_splits(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    for name, s1 in (("train", "a"), ("validation", "b"), ("test", "c")):
        _write(
            raw / f"{name}-00000-of-00001.parquet",
            {"sentence1": [s1], "sentence2": ["z"], "score": [0.6]},
        )
    result = partition_stsb_physical(raw, tmp_path / "out")
    assert result.counts == {"train": 1, "val": 1, "test": 1}
    assert _rows(result.files["test"])[0]["score"] == 0.6


def test_partial_run_merges_into_existing_manifest(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "processed"
    _all_nli(raw / "all_nli")
    for name, s1 in (("train", "a"), ("validation", "b"), ("test", "c")):
        _write(
            raw / "stsb" / f"{name}-00000-of-00001.parquet",
            {"sentence1": [s1], "sentence2": ["z"], "score": [0.5]},
        )
    execute_physical_partitioning(raw, out, datasets=["STSB"])
    summary = execute_physical_partitioning(raw, out, datasets=["ALL-NLI"])
    ids = sorted(d["dataset_id"] for d in summary["partitioned_datasets"])
    assert ids == ["ALL-NLI", "STSB"]
    on_disk = json.loads((out / "task_splits_manifest.json").read_text())
    assert on_disk["total_datasets_partitioned"] == 2

    rerun = execute_physical_partitioning(raw, out, datasets=["STSB"])
    assert sorted(d["dataset_id"] for d in rerun["partitioned_datasets"]) == ["ALL-NLI", "STSB"]
