import json
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.acquisition.fever_evidence import (
    build_evidence_table,
    collect_needed_sentences,
    detokenize,
)


def test_detokenize_restores_brackets_quotes_and_spacing() -> None:
    raw = "Fox -LRB- network -RRB- said `` hi '' , then left ."
    assert detokenize(raw) == 'Fox (network) said " hi ", then left.'


def _claims(path: Path) -> None:
    pq.write_table(
        pa.table({
            "evidence_wiki_url": ["A", "A", None, "B"],
            "evidence_sentence_id": [0, 2, -1, 1],
        }),
        path,
    )


def test_collect_needed_ignores_missing_references(tmp_path: Path) -> None:
    _claims(tmp_path / "claims.parquet")
    assert collect_needed_sentences([tmp_path / "claims.parquet"]) == {"A": {0, 2}, "B": {1}}


def test_build_evidence_table_keeps_only_referenced_sentences(tmp_path: Path) -> None:
    _claims(tmp_path / "claims.parquet")
    pages = [
        {"id": "A", "lines": "0\ta0 -LRB- x -RRB-\tlink\n1\ta1\t\n2\ta2\t"},
        {"id": "B", "lines": "0\tb0\t\n1\tb1\t"},
        {"id": "C", "lines": "0\tc0\t"},
    ]
    with zipfile.ZipFile(tmp_path / "wiki.zip", "w") as zf:
        zf.writestr("wiki-pages/wiki-001.jsonl", "\n".join(json.dumps(p) for p in pages) + "\n")
    out = tmp_path / "evidence.parquet"
    count = build_evidence_table([tmp_path / "claims.parquet"], tmp_path / "wiki.zip", out)
    rows = pq.read_table(out).to_pylist()
    assert count == 3
    assert [(r["page"], r["sentence_id"], r["text"]) for r in rows] == [
        ("A", 0, "a0 (x)"),
        ("A", 2, "a2"),
        ("B", 1, "b1"),
    ]
