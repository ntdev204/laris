"""Fixture tests of the T206 pair-data corrections (no model, no training)."""

import importlib.util
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fix = _load("correct_pair_data")
leak = _load("check_sts_leakage")


def test_score_spec_is_required_and_scaled_linearly():
    assert leak.score_spec(
        {"id": "S", "score_field": "relatedness_score", "score_range": [1, 5]}
    ) == ("relatedness_score", 1.0, 5.0)
    with pytest.raises(ValueError):
        leak.score_spec({"id": "S"})
    with pytest.raises(ValueError):
        leak.score_spec({"id": "S", "score_field": "x", "score_range": [5, 1]})
    assert leak.scale_score(1.0, 1.0, 5.0) == 0.0
    assert leak.scale_score(3.0, 1.0, 5.0) == 0.5
    assert leak.scale_score(5.0, 0.0, 5.0) == 1.0
    assert leak.scale_score(7.0, 0.0, 5.0) == 1.0


def test_extract_pair_reads_only_the_configured_column():
    row = {"sentence_A": "a", "sentence_B": "b", "label": 0, "relatedness_score": 4.5}
    assert leak.extract_pair(row, "relatedness_score") == ("a", "b", 4.5)
    assert leak.extract_pair(row, "label") == ("a", "b", 0.0)
    assert leak.extract_pair({"sentence1": "a", "sentence2": "b"}, "score") is None


def test_sick_score_origin_detects_the_nli_label():
    raw = [{"sentence_A": "A cat", "sentence_B": "A dog", "label": 2, "relatedness_score": 3.0}]
    index = fix.sick_index(raw)
    rows = [
        {
            "sentence1": "a dog",
            "sentence2": "a cat",
            "score": 0.4,
            "source": "SICK-EN",
        },  # label 2 / 5
        {"sentence1": "x", "sentence2": "y", "score": 0.1, "source": "SICK-EN"},
        {"sentence1": "a cat", "sentence2": "a dog", "score": 0.4, "source": "STS-COMPANION-EN"},
    ]
    c = fix.sick_score_origin(rows, index, 1.0, 5.0)
    assert c["sick_rows"] == 2 and c["not_matched_to_raw"] == 1
    assert c["equals_nli_label_div_5"] == 1 and "equals_relatedness_scaled" not in c
    fixed = [{"sentence1": "A cat", "sentence2": "A dog", "score": 0.5, "source": "SICK-EN"}]
    assert fix.sick_score_origin(fixed, index, 1.0, 5.0)["equals_relatedness_scaled"] == 1


def test_drop_heldout_rows_matches_question_and_context_together():
    train = pa.table(
        {"question": ["Q1", "Q1", "Q2"], "context": ["C1", "C2", "C1"], "id": ["1", "2", "3"]}
    )
    held = pa.table({"question": ["q1!"], "context": ["c1"]})
    kept, dropped = fix.drop_heldout_rows(train, fix.heldout_qa_keys([held]))
    assert dropped == 1
    assert kept.column("id").to_pylist() == [
        "2",
        "3",
    ]  # same question or same context alone is kept
    assert kept.schema == train.schema


def test_backup_never_overwrites_different_content(tmp_path):
    src = tmp_path / "squad" / "train.parquet"
    src.parent.mkdir()
    src.write_bytes(b"one")
    monkey_root = tmp_path
    fix_root = fix.ROOT
    fix.ROOT = monkey_root
    try:
        out = fix.backup([src], tmp_path / "bk")
        assert (tmp_path / "bk/squad/train.parquet").read_bytes() == b"one"
        assert out == {"squad/train.parquet": fix.sha256_file(src)}
        fix.backup([src], tmp_path / "bk")  # same content: fine
        src.write_bytes(b"two")
        with pytest.raises(FileExistsError):
            fix.backup([src], tmp_path / "bk")
    finally:
        fix.ROOT = fix_root


def test_freeze_symlink_copies_originals(tmp_path):
    orig = tmp_path / "orig"
    orig.mkdir()
    (orig / "train.parquet").write_bytes(b"x")
    link = tmp_path / "r1_squad"
    link.symlink_to(orig)
    assert fix.freeze_symlink(link, orig)
    assert not link.is_symlink() and (link / "train.parquet").read_bytes() == b"x"
    assert not fix.freeze_symlink(link, orig)


def test_update_manifest_changes_only_the_split(tmp_path):
    data = tmp_path / "train.parquet"
    pq.write_table(pa.table({"a": [1, 2]}), data)
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "partitioned_datasets": [
                    {
                        "dataset_id": "SQUAD",
                        "counts": {"train": 9, "val": 1},
                        "bytes": {"train": 9, "val": 1},
                        "sha256": {"train": "old", "val": "v"},
                    }
                ]
            }
        )
    )
    out = fix.update_manifest(manifest, "SQUAD", "train", data, 2)
    entry = json.loads(manifest.read_text())["partitioned_datasets"][0]
    assert entry["counts"] == {"train": 2, "val": 1} and entry["sha256"]["val"] == "v"
    assert out["before"]["counts"] == 9 and out["after"]["sha256"] == fix.sha256_file(data)
