"""Non-network checks of the NER conversion and partition (T187)."""

from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.research.corpus.acquisition.registry import NER_ACQUIRERS, NER_CONFIG
from laris.research.corpus.acquisition.sources import english_hf
from laris.research.corpus.splits.partitioners import english as E
from laris.research.corpus.splits.partitioners import ner as N

FEW = {
    "id": "FEW-NERD-EN",
    "tag_style": "type",
    "tag_names": ["O", "person", "location"],
    "type_map": {"person": "PERSON", "location": "LOCATION"},
}
WNUT = {
    "id": "WNUT-17-EN",
    "tag_style": "bio",
    "tag_names": ["O", "B-person", "I-person", "B-group", "I-group"],
    "type_map": {"person": "PERSON", "group": "ORGANIZATION"},
}


def test_types_to_bio_marks_runs_and_counts_entities() -> None:
    tags, entities = N.types_to_bio(["person", "person", None, "location", "person"])
    assert tags == ["B-person", "I-person", "O", "B-location", "B-person"]
    assert entities == 3


def test_repair_bio_fixes_orphan_inside_tags() -> None:
    assert N.repair_bio(["I-person", "I-person", "B-group", "I-person", "I-group"]) == (
        ["B-person", "I-person", "B-group", "B-person", "B-group"],
        3,
    )


@pytest.mark.parametrize(
    "name, split",
    [
        ("train-00000-of-00001.parquet", "train"),
        ("validation__0000.parquet", "val"),
        ("dev-1.parquet", "val"),
        ("test__0.parquet", "test"),
    ],
)
def test_raw_split_follows_the_official_file_name(name: str, split: str) -> None:
    assert N.raw_split(Path(name)) == split


def test_raw_split_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        N.raw_split(Path("extra-0.parquet"))


def _write_raw(directory: Path, split: str, rows: List[Dict[str, Any]], file: str = "") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [("id", pa.string()), ("tokens", pa.list_(pa.string())), ("ner_tags", pa.list_(pa.int64()))]
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema), directory / (file or f"{split}-0.parquet")
    )


def _row(row_id: str, text: str, tags: List[int]) -> Dict[str, Any]:
    return {"id": row_id, "tokens": text.split(), "ner_tags": tags}


def test_convert_source_keeps_official_splits_and_maps_types(tmp_path: Path) -> None:
    raw = tmp_path / "few_nerd_en"
    _write_raw(raw, "train", [_row("0", "Ada Lovelace lived in London", [1, 1, 0, 0, 2])])
    _write_raw(raw, "validation", [_row("1", "Rome", [2])])
    _write_raw(raw, "test", [_row("2", "Nothing here", [0, 0])])
    rows, stats = N.convert_source(FEW, raw)
    assert rows["train"][0]["labels"] == ["B-PERSON", "I-PERSON", "O", "O", "B-LOCATION"]
    assert rows["train"][0]["source_labels"] == ["B-person", "I-person", "O", "O", "B-location"]
    assert rows["train"][0]["id"] == "FEW-NERD-EN:train:0"
    assert [len(rows[s]) for s in ("train", "val", "test")] == [1, 1, 1]
    assert stats["train"]["entities"] == 2 and stats["test"]["entities"] == 0


def test_convert_source_maps_native_types_and_repairs(tmp_path: Path) -> None:
    raw = tmp_path / "wnut_17_en"
    _write_raw(raw, "train", [_row("0", "a b c", [2, 3, 4])], "train__0000.parquet")
    _write_raw(raw, "validation", [], "validation__0000.parquet")
    _write_raw(raw, "test", [], "test__0000.parquet")
    rows, stats = N.convert_source(WNUT, raw)
    assert rows["train"][0]["labels"] == ["B-PERSON", "B-ORGANIZATION", "I-ORGANIZATION"]
    assert rows["train"][0]["source_labels"] == ["B-person", "B-group", "I-group"]
    assert stats["train"]["repaired"] == 1


@pytest.mark.parametrize("tags, message", [([9, 0], "outside"), ([1], "tags")])
def test_convert_source_rejects_bad_rows(tmp_path: Path, tags: List[int], message: str) -> None:
    raw = tmp_path / "few_nerd_en"
    _write_raw(raw, "train", [_row("0", "a b", tags)])
    with pytest.raises(ValueError, match=message):
        N.convert_source(FEW, raw)


def test_partition_drops_heldout_text_from_train_only(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    directory = raw / "few_nerd_en"
    window = "the old stone bridge crosses the river near the village of Aldermere"
    _write_raw(
        directory,
        "train",
        [
            _row("0", "Ada Lovelace lived in London", [1, 1, 0, 0, 2]),
            _row("1", "Rome", [2]),  # equals a test sentence
            _row(
                "2", window + " today", [0] * (len(window.split()) + 1)
            ),  # shares an eight-word window with a val sentence
        ],
    )
    _write_raw(
        directory, "validation", [_row("3", "Yesterday " + window, [0] * (len(window.split()) + 1))]
    )
    _write_raw(directory, "test", [_row("4", "rome", [2]), _row("5", "Rome", [2])])
    ((result, stats),) = N.partition_ner([FEW], raw, out)
    assert result.counts == {"train": 1, "val": 1, "test": 2}  # held-out rows are never removed
    assert stats["train_dropped_heldout"] == {"ner_test_sentence": 1, "ner_val_sentence": 1}
    train = pq.read_table(out / "few_nerd_en" / "train.parquet").to_pylist()
    assert [r["id"] for r in train] == ["FEW-NERD-EN:train:0"]
    assert result.sha256["test"] and (out / "few_nerd_en" / "test.parquet").is_file()


def test_ner_config_lists_both_sources_and_matches_partition_config() -> None:
    config = english_hf.load_sources_config(NER_CONFIG)
    assert (
        set(NER_ACQUIRERS) == {s["id"] for s in config["sources"]} == {"FEW-NERD-EN", "WNUT-17-EN"}
    )
    assert all(s["role"] == "ner" and s["license_approved"] is True for s in config["sources"])
    partition = E.load_partition_config()
    assert {s["id"] for s in partition["ner"]} == set(NER_ACQUIRERS)
    for spec in partition["ner"]:
        assert set(spec["type_map"].values()) <= {
            "ART",
            "BUILDING",
            "EVENT",
            "LOCATION",
            "ORGANIZATION",
            "OTHER",
            "PERSON",
            "PRODUCT",
        }
