"""Tests for the bilingual expansion dataset partitioners (no network, synthetic fixtures)."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.splits.partitioners.cc100 import partition_cc100_physical, wikipedia_digests
from laris.corpus.splits.partitioners.common import normalized_text_digest
from laris.corpus.splits.partitioners.fever import partition_fever_physical
from laris.corpus.splits.partitioners.hotpotqa import partition_hotpotqa_physical
from laris.corpus.splits.partitioners.vinli import partition_vinli_physical
from laris.corpus.splits.partitioners.viquad_v2 import partition_viquad_v2_physical
from laris.corpus.splits.partitioners.vists import partition_vists_physical
from laris.corpus.splits.runner import execute_physical_partitioning


def _rows(path: Path):
    return pq.read_table(path).to_pylist()


def test_vinli_drops_other_label_and_cross_split_pairs(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    cols = ["gold_label", "sentence1", "sentence2"]
    shared = ("a", "b")
    pq.write_table(
        pa.table(dict(zip(cols, [["entailment", "other"], [shared[0], "x"], [shared[1], "y"]]))),
        raw / "train-00000-of-00001.parquet",
    )
    pq.write_table(
        pa.table(dict(zip(cols, [["neutral"], ["a"], ["b"]]))), raw / "dev-00000-of-00001.parquet"
    )
    pq.write_table(
        pa.table(dict(zip(cols, [["contradiction"], ["c"], ["d"]]))),
        raw / "test-00000-of-00001.parquet",
    )
    result = partition_vinli_physical(raw, tmp_path / "out")
    assert result.counts == {"train": 0, "val": 1, "test": 1} or result.counts == {
        "val": 1,
        "test": 1,
    }
    assert {r["label"] for r in _rows(result.files["val"])} == {"neutral"}


def test_vists_keeps_connected_sentences_in_one_split(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    lines = [
        {"sentence1": f"s{i}", "sentence2": f"s{i + 1}", "score": 5.0} for i in range(0, 60, 2)
    ]
    lines += [{"sentence1": "hub", "sentence2": f"leaf{i}", "score": 2.5} for i in range(40)]
    (raw / "sts12__x.jsonl").write_text("\n".join(json.dumps(r) for r in lines))
    result = partition_vists_physical(raw, tmp_path / "out")
    seen = {}
    for split, path in result.files.items():
        for r in _rows(path):
            for sentence in (r["sentence1"], r["sentence2"]):
                assert seen.setdefault(sentence, split) == split
            assert 0.0 <= r["score"] <= 1.0


def _hotpot_rec(idx: int, support: str, answer: str):
    return {
        "id": str(idx),
        "question": f"q{idx}?",
        "answer": answer,
        "type": "bridge",
        "level": "easy",
        "supporting_facts": {"title": [support], "sent_id": [0]},
        "context": {
            "title": ["Other", support],
            "sentences": [["Distractor text."], [f"{support} is {answer}."]],
        },
    }


def test_hotpotqa_puts_supporting_paragraph_first_and_locates_answer(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    train = [_hotpot_rec(i, f"T{i}", f"ans{i}") for i in range(30)]
    dev = [_hotpot_rec(100 + i, f"D{i}", "yes" if i % 2 else f"dans{i}") for i in range(30)]
    pq.write_table(pa.Table.from_pylist(train), raw / "distractor__train-00000-of-00002.parquet")
    pq.write_table(pa.Table.from_pylist(dev), raw / "distractor__validation-00000-of-00001.parquet")
    result = partition_hotpotqa_physical(raw, tmp_path / "out")
    train_rows = _rows(result.files["train"])
    row = train_rows[0]
    assert row["context"].startswith(row["title"])
    start = row["answers"]["answer_start"][0]
    text = row["answers"]["text"][0]
    assert row["context"][start : start + len(text)] == text
    val_titles = {r["title"] for r in _rows(result.files["val"])}
    test_titles = {r["title"] for r in _rows(result.files["test"])}
    assert not val_titles & test_titles
    held_out = _rows(result.files["val"]) + _rows(result.files["test"])
    assert held_out and all(r["answers"]["text"] for r in held_out)  # yes/no rows are dropped
    assert len(held_out) <= 15


def _fever_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()

    def table(ids, labels=None):
        labels = labels or ["SUPPORTS"] * len(ids)
        return pa.table({
            "id": [str(i) for i in ids],
            "label": labels,
            "claim": [f"claim {i}" for i in ids],
            "evidence_id": [1000 + i for i in ids],
            "evidence_wiki_url": [f"Page_{i}" for i in ids],
            "evidence_sentence_id": [0] * len(ids),
        })

    pq.write_table(table(range(0, 50)), raw / "v1.0__train__0000.parquet")
    pq.write_table(table(range(40, 80)), raw / "v1.0__labelled_dev__0000.parquet")
    pq.write_table(
        pa.table({
            "page": [f"Page_{i}" for i in range(80)],
            "sentence_id": pa.array([0] * 80, type=pa.int32()),
            "text": [f"evidence {i}" for i in range(80)],
        }),
        raw / "evidence_sentences.parquet",
    )
    return raw


def test_fever_dev_claims_do_not_appear_in_train(tmp_path: Path) -> None:
    result = partition_fever_physical(_fever_raw(tmp_path), tmp_path / "out")
    train = {r["hypothesis"] for r in _rows(result.files["train"])}
    held = {r["hypothesis"] for s in ("val", "test") for r in _rows(result.files[s])}
    assert train and held
    assert not train & held
    assert not {r["hypothesis"] for r in _rows(result.files["val"])} & {
        r["hypothesis"] for r in _rows(result.files["test"])
    }


def test_fever_pairs_join_evidence_and_drop_unresolvable_claims(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    claims = pa.table({
        "id": ["1", "2", "3", "4"],
        "label": ["SUPPORTS", "REFUTES", "NOT ENOUGH INFO", "SUPPORTS"],
        "claim": ["a", "b", "c", "d"],
        "evidence_id": [10, 11, 12, 13],
        "evidence_wiki_url": ["P", "P", None, "Missing"],
        "evidence_sentence_id": [0, 1, -1, 0],
    })
    pq.write_table(claims, raw / "v1.0__train__0000.parquet")
    pq.write_table(claims.slice(0, 0), raw / "v1.0__labelled_dev__0000.parquet")
    pq.write_table(
        pa.table({
            "page": ["P", "P"],
            "sentence_id": pa.array([0, 1], type=pa.int32()),
            "text": ["first", "second"],
        }),
        raw / "evidence_sentences.parquet",
    )
    result = partition_fever_physical(raw, tmp_path / "out")
    rows = {r["hypothesis"]: r for r in _rows(result.files["train"])}
    assert set(rows) == {"a", "b"}
    assert rows["a"] == {"premise": "first", "hypothesis": "a", "label": "entailment"}
    assert rows["b"]["label"] == "contradiction"


def test_viquad_v2_drops_contexts_shared_with_v1(tmp_path: Path) -> None:
    raw, v1 = tmp_path / "raw", tmp_path / "v1"
    raw.mkdir()
    v1.mkdir()
    (v1 / "dev.json").write_text(
        json.dumps(
            {"data": [{"title": "A", "paragraphs": [{"context": "Shared  context", "qas": []}]}]}
        )
    )

    def table(prefix):
        contexts = ["shared context"] + [f"a {prefix} ctx {i}" for i in range(30)]
        return pa.table(
            {
                "id": [f"{prefix}{i}" for i in range(31)],
                "uit_id": [f"u{i}" for i in range(31)],
                "title": ["Shared"] + [f"{prefix}T{i}" for i in range(30)],
                "context": contexts,
                "question": ["q?"] * 31,
                "answers": [None] + [{"text": ["a"], "answer_start": [0]}] * 30,
                "is_impossible": [False] * 31,
                "plausible_answers": [None] * 31,
            }
        )

    pq.write_table(table("t"), raw / "train-00000-of-00001.parquet")
    pq.write_table(table("v"), raw / "validation-00000-of-00001.parquet")
    result = partition_viquad_v2_physical(raw, tmp_path / "out", viquad_v1_dir=v1)
    contexts = {r["context"] for s in result.files for r in _rows(result.files[s])}
    assert "shared context" not in contexts
    assert sum(result.counts.values()) < 62


def test_cc100_removes_wikipedia_duplicates_and_is_exclusive(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki.parquet"
    pq.write_table(pa.table({"id": ["w"], "text": ["Nội dung   từ Wikipedia"]}), wiki)
    docs = [
        {"doc_id": f"d{i}", "text": f"tài liệu số {i}", "source": "cc100-vi"} for i in range(200)
    ]
    docs.append({"doc_id": "dup", "text": "nội dung từ wikipedia", "source": "cc100-vi"})
    docs.append({"doc_id": "dup2", "text": "tài liệu số 3", "source": "cc100-vi"})
    shard = tmp_path / "0000.parquet"
    pq.write_table(pa.Table.from_pylist(docs), shard)
    digests = wikipedia_digests([wiki])
    assert normalized_text_digest("nội dung từ wikipedia") in digests
    result = partition_cc100_physical([shard], tmp_path / "out", exclude_digests=digests)
    ids = [r["id"] for s in result.files for r in _rows(result.files[s])]
    assert "dup" not in ids and "dup2" not in ids
    assert len(ids) == len(set(ids)) == 200


def test_runner_skips_unreviewed_license_datasets_by_default(tmp_path: Path) -> None:
    data = tmp_path / "data"
    raw = data / "raw" / "vinli"
    raw.mkdir(parents=True)
    cols = ["gold_label", "sentence1", "sentence2"]
    for name in ("train", "dev", "test"):
        pq.write_table(
            pa.table(dict(zip(cols, [["entailment"], [name], ["h"]]))),
            raw / f"{name}-00000-of-00001.parquet",
        )
    (data / "acquisition_manifest.json").write_text(
        json.dumps(
            {"datasets": [{"dataset_id": "VINLI", "license_status": "NEEDS_LICENSE_REVIEW"}]}
        )
    )
    report = execute_physical_partitioning(data / "raw", data / "processed")
    assert report["total_datasets_partitioned"] == 0
    assert report["skipped_datasets"][0]["dataset_id"] == "VINLI"
    report = execute_physical_partitioning(
        data / "raw", data / "processed", include_unreviewed_licenses=True
    )
    assert report["total_datasets_partitioned"] == 1
    (data / "acquisition_manifest.json").write_text(
        json.dumps({"datasets": [{"dataset_id": "VINLI", "license_status": "APPROVED_BY_OWNER"}]})
    )
    report = execute_physical_partitioning(data / "raw", data / "processed")
    assert report["total_datasets_partitioned"] == 1 and not report["skipped_datasets"]


def test_viquad_v2_drops_rows_whose_answer_offset_is_wrong_but_keeps_unanswerable(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    n = 40
    answers = []
    for i in range(n):
        if i % 4 == 0:
            answers.append(None)  # unanswerable: a real label
        elif i % 4 == 1:
            answers.append({"text": ["bad"], "answer_start": [1]})  # off by one
        else:
            answers.append({"text": ["good"], "answer_start": [0]})

    def table(prefix):
        return pa.table(
            {
                "id": [f"{prefix}{i}" for i in range(n)],
                "uit_id": [f"u{i}" for i in range(n)],
                "title": [f"{prefix}T{i}" for i in range(n)],
                "context": ["bad good filler" if a and a["text"] == ["bad"] else "good filler"
                            for a in answers],
                "question": ["q?"] * n,
                "answers": answers,
                "is_impossible": [a is None for a in answers],
                "plausible_answers": [None] * n,
            }
        )

    pq.write_table(table("t"), raw / "train-00000-of-00001.parquet")
    pq.write_table(table("v"), raw / "validation-00000-of-00001.parquet")
    result = partition_viquad_v2_physical(raw, tmp_path / "out")
    rows = [r for s in result.files for r in _rows(result.files[s])]
    assert rows
    for r in rows:
        a = r["answers"]
        if a["text"]:
            start, text = a["answer_start"][0], a["text"][0]
            assert r["context"][start : start + len(text)] == text
    assert any(not r["answers"]["text"] for r in rows)  # unanswerable rows are kept
