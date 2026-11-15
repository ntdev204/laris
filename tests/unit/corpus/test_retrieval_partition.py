"""Retrieval-pair partitioning (T178): leakage removal, deduplication and split isolation."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.research.corpus.splits.partitioners import retrieval as R

CONFIG = {
    "seed": "t",
    "retrieval_ratios": {"train": 0.5, "val": 0.25, "test": 0.25},
    "retrieval_max_chars": 200,
}
HELD_PARAGRAPH = (
    "The mitochondrion is a double membrane bound organelle found in most eukaryotic organisms "
    "and it generates most of the chemical energy needed to power the cell"
)


def _blocklist() -> R.Blocklist:
    block = R.Blocklist()
    block.add_exact("squad_v1_test_question", "What does the mitochondrion generate?")
    block.add_passage("squad_v1_test_paragraph", HELD_PARAGRAPH)
    block.add_exact("scifact_claim", "Vitamin D deficiency increases fracture risk.")
    block.add_exact("stsb_test_sentence", "A man is playing a guitar.")
    return block


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _read(out_dir):
    rows = []
    for split in ("train", "val", "test"):
        file = out_dir / f"{split}.parquet"
        if file.exists():
            rows += [{**r, "split": split} for r in pq.read_table(file).to_pylist()]
    return rows


def test_held_out_text_is_removed_on_either_side_or_by_overlap(tmp_path):
    raw = tmp_path / "raw"
    _write(
        raw / "a.parquet",
        [
            {
                "q": "What does the mitochondrion generate?",
                "a": "Energy for the cell.",
            },  # held-out question
            {
                "q": "Which organelle makes energy?",
                "a": HELD_PARAGRAPH.upper(),
            },  # held-out paragraph
            {
                "q": "Where is it found?",
                "a": "Notes: " + HELD_PARAGRAPH + " Further reading follows.",  # eight-word overlap
            },
            {"q": "Vitamin D deficiency increases fracture risk", "a": "A claim."},  # SciFact claim
            {"q": "Describe a guitar scene", "a": "A man is playing a guitar"},  # STS-B sentence
            {"q": "Clean query one", "a": "A perfectly clean answer about rivers."},
            {"q": "Clean query two", "a": "Another unrelated answer about mountains."},
        ],
    )
    spec = {"id": "X-EN", "query": "q", "positive": "a"}
    result, stats = R.partition_retrieval_source(
        spec, raw, tmp_path / "out", CONFIG, _blocklist(), set()
    )
    kept = {r["query"] for r in _read(tmp_path / "out")}
    assert kept == {"Clean query one", "Clean query two"}
    assert stats["leaked_total"] == 5 and stats["kept"] == 2
    assert stats["leaked"] == {
        "squad_v1_test_question": 1,
        "squad_v1_test_paragraph": 2,
        "scifact_claim": 1,
        "stsb_test_sentence": 1,
    }
    assert sum(result.counts.values()) == 2


def test_duplicates_are_dropped_across_sources_and_split_is_deterministic(tmp_path):
    raw_a, raw_b = tmp_path / "ra", tmp_path / "rb"
    pairs = [{"q": f"Question number {i}", "a": f"Answer number {i} " * 3} for i in range(80)]
    _write(raw_a / "a.parquet", pairs)
    _write(raw_b / "b.parquet", pairs[:10] + [{"q": "Other question", "a": "Other answer"}])
    spec = {"id": "X", "query": "q", "positive": "a"}
    seen = set()
    _, first = R.partition_retrieval_source(
        spec, raw_a, tmp_path / "o1", CONFIG, R.Blocklist(), seen
    )
    _, second = R.partition_retrieval_source(
        {**spec, "id": "Y"}, raw_b, tmp_path / "o2", CONFIG, R.Blocklist(), seen
    )
    assert first["kept"] == 80 and second["duplicate"] == 10 and second["kept"] == 1
    _, again = R.partition_retrieval_source(
        spec, raw_a, tmp_path / "o3", CONFIG, R.Blocklist(), set()
    )
    assert _read(tmp_path / "o1") == _read(tmp_path / "o3") and again["kept"] == 80


def test_one_query_with_several_positives_stays_in_one_split(tmp_path):
    raw = tmp_path / "raw"
    rows = [{"q": f"Query {i}", "a": f"Answer {i}.{j} text"} for i in range(40) for j in range(3)]
    _write(raw / "a.parquet", rows)
    R.partition_retrieval_source(
        {"id": "X", "query": "q", "positive": "a"},
        raw,
        tmp_path / "out",
        CONFIG,
        R.Blocklist(),
        set(),
    )
    owner = {}
    for row in _read(tmp_path / "out"):
        assert owner.setdefault(row["query"], row["split"]) == row["split"]
    assert len(owner) == 40


def test_symmetric_pairs_keep_a_chain_of_captions_in_one_split(tmp_path):
    raw = tmp_path / "raw"
    # captions c0-c1, c1-c2, ... form chains; every chain must stay whole
    rows = [
        {"x": f"caption {chain} number {i}", "y": f"caption {chain} number {i + 1}"}
        for chain in range(30)
        for i in range(4)
    ]
    _write(raw / "a.parquet", rows)
    R.partition_retrieval_source(
        {"id": "C", "query": "x", "positive": "y", "symmetric": True},
        raw, tmp_path / "out", CONFIG, R.Blocklist(), set(),
    )  # fmt: skip
    owner = {}
    for row in _read(tmp_path / "out"):
        chain = row["query"].split()[1]
        assert owner.setdefault(chain, row["split"]) == row["split"]
    assert len(owner) == 30 and len(set(owner.values())) > 1


def test_msmarco_uses_only_selected_passages(tmp_path):
    raw = tmp_path / "raw"
    _write(
        raw / "m.parquet",
        [
            {
                "query": "what is a river",
                "passages": {
                    "is_selected": [0, 1, 0],
                    "passage_text": [
                        "Unjudged one.",
                        "A river is a natural stream.",
                        "Unjudged two.",
                    ],
                    "url": ["u", "v", "w"],
                },
            },
            {
                "query": "nothing selected",
                "passages": {"is_selected": [0], "passage_text": ["Nope."], "url": ["u"]},
            },
        ],
    )
    R.partition_retrieval_source(
        {"id": "M", "kind": "msmarco"}, raw, tmp_path / "out", CONFIG, R.Blocklist(), set()
    )
    assert [(r["query"], r["positive"]) for r in _read(tmp_path / "out")] == [
        ("what is a river", "A river is a natural stream.")
    ]


def test_stack_exchange_style_files_with_different_columns(tmp_path):
    raw = tmp_path / "raw"
    _write(raw / "title.parquet", [{"title1": "How to boil water", "title2": "Boiling water how"}])
    _write(raw / "body.parquet", [{"body1": "Body one text", "body2": "Body two text"}])
    spec = {
        "id": "SE", "symmetric": True,
        "columns": [["title1", "title2"], ["body1", "body2"]],
    }  # fmt: skip
    _, stats = R.partition_retrieval_source(
        spec, raw, tmp_path / "out", CONFIG, R.Blocklist(), set()
    )
    assert stats["kept"] == 2


def test_isolation_scan_counts_queries_in_two_splits(tmp_path):
    a, b = tmp_path / "train.parquet", tmp_path / "val.parquet"
    _write(a, [{"query": "Same Query!", "positive": "x", "source": "S"}])
    _write(b, [{"query": "same query", "positive": "y", "source": "S"}])
    report = R.scan_split_isolation({"S": [a, b]})
    assert report["queries_in_two_splits_within_source"] == 1


def test_missing_raw_files_fail_loudly(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        R.partition_retrieval_source(
            {"id": "Z", "query": "q", "positive": "a"},
            tmp_path / "empty", tmp_path / "out", CONFIG, R.Blocklist(), set(),
        )  # fmt: skip
