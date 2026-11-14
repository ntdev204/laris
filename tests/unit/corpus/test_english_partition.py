"""Partitioning of the English sources: chunking, determinism, deduplication and SQuAD v1 leakage removal."""

import pyarrow as pa
import pyarrow.parquet as pq

from laris.research.corpus.splits.partitioners import english as E

CONFIG = {
    "seed": "t",
    "mlm_ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
    "supervised_ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
    "mlm_chunk_chars": 120,
    "mlm_min_chunk_chars": 20,
}


def test_chunks_respect_size_and_boundaries():
    text = "First sentence here. " * 20 + "\n\n" + "Second paragraph stays apart. " * 6
    chunks = E.chunk_text(text, 120, 20)
    assert chunks and all(len(c) <= 120 for c in chunks)
    assert E.chunk_text("tiny", 120, 20) == []


def test_mlm_split_is_deterministic_and_documents_do_not_straddle(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    docs = [{"id": f"d{i}", "text": f"Document {i}. " * 40} for i in range(60)]
    docs.append({"id": "dup", "text": docs[0]["text"]})  # exact duplicate of d0
    pq.write_table(pa.Table.from_pylist(docs), raw / "a.parquet")
    spec = {"id": "X-EN", "text": "text", "doc_id": "id"}
    runs = []
    for run in ("one", "two"):
        _, stats = E.partition_mlm_source(spec, raw, tmp_path / run, CONFIG, set())
        runs.append(
            {
                s: pq.read_table(tmp_path / run / f"{s}.parquet").column("id").to_pylist()
                for s in ("train", "val", "test")
                if (tmp_path / run / f"{s}.parquet").exists()
            }
        )
    assert runs[0] == runs[1] and stats["duplicates"] == 1
    owner = {}
    for split, ids in runs[0].items():
        for chunk_id in ids:
            assert owner.setdefault(chunk_id.split("#")[0], split) == split


def test_min_date_drops_old_and_undated_rows(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = [
        {"id": "old", "text": "Old patent text. " * 20, "created": "1924-05-27"},
        {"id": "none", "text": "Undated patent text. " * 20, "created": None},
        {"id": "new", "text": "Modern patent text. " * 20, "created": "2008-12-09"},
    ]
    pq.write_table(pa.Table.from_pylist(rows), raw / "p.parquet")
    spec = {
        "id": "P",
        "text": "text",
        "doc_id": "id",
        "min_date": {"field": "created", "value": "1976-01-01"},
    }
    _, stats = E.partition_mlm_source(spec, raw, tmp_path / "out", CONFIG, set())
    assert stats["filtered"] == 2 and stats["documents"] == 1


def test_pairs_drop_unknown_labels_and_duplicates(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = [
        {"premise": "a b", "hypothesis": "c d", "gold": "entailment"},
        {"premise": "c d", "hypothesis": "a b", "gold": "entailment"},  # same pair reversed
        {"premise": "x", "hypothesis": "y", "gold": "-"},
        {"premise": "p", "hypothesis": "q", "gold": "contradiction"},
    ]
    pq.write_table(pa.Table.from_pylist(rows), raw / "t.parquet")
    spec = {"id": "N", "premise": "premise", "hypothesis": "hypothesis", "label": "gold"}
    result = E.partition_pairs(spec, "nli", raw, tmp_path / "out", CONFIG)
    assert sum(result.counts.values()) == 2


def test_qa_rows_from_squad_v1_heldout_articles_are_removed(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    ans = {"text": ["x"], "answer_start": [0]}
    rows = [
        {"id": "1", "title": "Oxygen", "context": "c1", "question": "q", "answers": ans},
        {"id": "2", "title": "Kept_Title", "context": "c2", "question": "q", "answers": ans},
    ]
    pq.write_table(pa.Table.from_pylist(rows), raw / "t.parquet")
    result, stats = E.partition_qa_source(
        {"id": "Q"}, raw, tmp_path / "out", CONFIG, {E._norm_title("Oxygen")}, set()
    )
    assert stats == {"dropped_squad_v1_heldout": 1, "kept": 1}
    assert sum(result.counts.values()) == 1
