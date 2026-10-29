"""`laris data check` readiness verification."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.cli.main import main


def _populate(root: Path, datasets: list) -> dict:
    entry = {"dataset_id": "X", "files": {}, "bytes": {}, "sha256": {}}
    for name in datasets:
        for split in ("train", "val", "test"):
            path = root / name / f"{split}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({"t": ["a", "b"]}), path)
    sample = root / datasets[0] / "train.parquet"
    entry["files"]["train"] = str(sample)
    entry["bytes"]["train"] = sample.stat().st_size
    entry["sha256"]["train"] = hashlib.sha256(sample.read_bytes()).hexdigest()
    return entry


def _write_manifest(root: Path, entry: dict) -> None:
    (root / "task_splits_manifest.json").write_text(json.dumps({"partitioned_datasets": [entry]}))


def test_complete_data_and_matching_manifest_report_no_data_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names = ["wikipedia_vi", "vinli", "quora_duplicates", "vists", "viquad_v2"]
    entry = _populate(tmp_path, names)
    _write_manifest(tmp_path, entry)
    main(["data", "check", "--data-dir", str(tmp_path), "--verify-sha256"])
    out = capsys.readouterr().out
    assert "has no" not in out and "differs" not in out and "missing" not in out


def test_missing_task_and_manifest_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _populate(tmp_path, ["vinli"])
    assert main(["data", "check", "--data-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "missing" in out and "task 'qa' has no train data" in out


def test_size_mismatch_against_manifest_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = _populate(tmp_path, ["vinli"])
    entry["bytes"]["train"] += 1
    _write_manifest(tmp_path, entry)
    assert main(["data", "check", "--data-dir", str(tmp_path)]) == 1
    assert "size differs from manifest" in capsys.readouterr().out
