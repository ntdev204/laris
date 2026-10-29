"""UIT-ViQuAD 2.0: official train kept, validation sub-split by article.

ViQuAD 2.0 contains every 1.1 context (plus unanswerable questions), so it supersedes 1.1:
use one of the two as a QA source, never both. `viquad_v1_dir` optionally drops shared contexts
for callers that must combine them."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import (
    bucket_dev_split,
    normalized_text_digest,
    write_split_tables,
)
from laris.corpus.splits.physical import PhysicalSplitResult

QA_COLUMNS = ["id", "title", "context", "question", "answers"]


def viquad_v1_context_digests(viquad_v1_dir: Union[str, Path]) -> Set[bytes]:
    """Digests of every paragraph in the UIT-ViQuAD 1.1 train/dev JSON files."""
    digests: Set[bytes] = set()
    for path in sorted(Path(viquad_v1_dir).glob("*.json")):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for article in payload.get("data", []):
            for paragraph in article.get("paragraphs", []):
                digests.add(normalized_text_digest(paragraph["context"]))
    return digests


def _answers_or_empty(answers: Optional[dict]) -> dict:
    return answers if answers and answers.get("text") else {"text": [], "answer_start": []}


def _offsets_match(context: str, answers: dict) -> bool:
    """Only a row with no answer text is unanswerable (a real label). An answer whose offset is
    missing or points at other text is a data defect and is dropped, not relabelled."""
    texts, starts = answers.get("text") or [], answers.get("answer_start") or []
    if not texts or not texts[0]:
        return True
    if not starts:
        return False
    return bool(context[int(starts[0]) : int(starts[0]) + len(texts[0])] == texts[0])


def partition_viquad_v2_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "UIT-VIQUAD-V2",
    viquad_v1_dir: Optional[Union[str, Path]] = None,
    seed: str = "laris-viquad2-partition-seed-v1",
) -> PhysicalSplitResult:
    """The official test split has no public answers and is not used.

    Rows whose answer offset does not point at the answer text are dropped.

    If `viquad_v1_dir` is given, contexts shared with UIT-ViQuAD 1.1 are dropped.
    """
    in_dir = Path(raw_dir)
    blocked = viquad_v1_context_digests(viquad_v1_dir) if viquad_v1_dir else set()

    def load(name: str) -> List[dict]:
        rows = []
        for rec in pq.read_table(in_dir / f"{name}-00000-of-00001.parquet").to_pylist():
            if normalized_text_digest(rec["context"]) in blocked:
                continue
            row = {k: rec[k] for k in QA_COLUMNS}
            row["answers"] = _answers_or_empty(rec["answers"])
            if not _offsets_match(row["context"], row["answers"]):
                continue
            rows.append(row)
        return rows

    train_rows, dev_all = load("train"), load("validation")
    held: Dict[DatasetSplit, List[dict]] = {DatasetSplit.VAL: [], DatasetSplit.TEST: []}
    for rec in dev_all:
        held[bucket_dev_split(rec["title"], seed)].append(rec)
    dev_titles = {r["title"] for rs in held.values() for r in rs}
    train_rows = [r for r in train_rows if r["title"] not in dev_titles]

    schema = pa.schema(
        [
            ("id", pa.string()),
            ("title", pa.string()),
            ("context", pa.string()),
            ("question", pa.string()),
            (
                "answers",
                pa.struct(
                    [("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]
                ),
            ),
        ]
    )
    tables = {
        DatasetSplit.TRAIN: pa.Table.from_pylist(train_rows, schema=schema),
        DatasetSplit.VAL: pa.Table.from_pylist(held[DatasetSplit.VAL], schema=schema),
        DatasetSplit.TEST: pa.Table.from_pylist(held[DatasetSplit.TEST], schema=schema),
    }
    return write_split_tables(dataset_id, Path(output_dir), tables)
