"""HotpotQA (distractor setting) converted to extractive QA records."""

import glob
from pathlib import Path
from typing import Any, Dict, List, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import bucket_dev_split, write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult

SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("title", pa.string()),
        ("question", pa.string()),
        ("context", pa.string()),
        (
            "answers",
            pa.struct([("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]),
        ),
        ("type", pa.string()),
    ]
)


def _record_to_qa(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Builds the context with supporting paragraphs first so answers fall in the model window."""
    support = list(dict.fromkeys(rec["supporting_facts"]["title"]))
    titles: List[str] = rec["context"]["title"]
    sentences: List[List[str]] = rec["context"]["sentences"]
    order = [t for t in support if t in titles] + [t for t in titles if t not in support]
    by_title = dict(zip(titles, sentences))
    context = "\n".join(f"{t}: {''.join(by_title[t]).strip()}" for t in order)
    answer = (rec.get("answer") or "").strip()
    # boolean answers are not spans; a substring match of "yes"/"no" would be spurious
    is_boolean = answer.lower() in ("yes", "no")
    start = context.find(answer) if answer and not is_boolean else -1
    # yes/no and unlocatable answers carry no span label
    answers: Dict[str, List[Any]] = (
        {"text": [answer], "answer_start": [start]}
        if start >= 0
        else {"text": [], "answer_start": []}
    )
    return {
        "id": rec["id"],
        "title": support[0] if support else titles[0],
        "question": rec["question"],
        "context": context,
        "answers": answers,
        "type": rec.get("type") or "",
    }


def _has_span(row: dict) -> bool:
    """Extractive QA needs a located span; yes/no and unlocatable answers have none."""
    return bool(row["answers"]["text"])


def partition_hotpotqa_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "HOTPOTQA",
    seed: str = "laris-hotpotqa-partition-seed-v1",
) -> PhysicalSplitResult:
    """Train comes from the official train files; the official validation set is sub-split
    into val/test grouped by the first supporting article so no article spans both.

    Questions without a located answer span (yes/no, unlocatable) are dropped: labelling them
    "no answer" would teach the span head a false target.
    """
    in_dir = Path(raw_dir)
    train_rows: List[dict] = []
    for path in sorted(glob.glob(str(in_dir / "distractor__train-*.parquet"))):
        train_rows.extend(
            qa
            for qa in map(_record_to_qa, pq.read_table(path).to_pylist())
            if _has_span(qa)
        )

    dev_rows: Dict[DatasetSplit, List[dict]] = {DatasetSplit.VAL: [], DatasetSplit.TEST: []}
    dev_titles = set()
    for path in sorted(glob.glob(str(in_dir / "distractor__validation-*.parquet"))):
        for raw in pq.read_table(path).to_pylist():
            qa = _record_to_qa(raw)
            if not _has_span(qa):
                continue
            dev_rows[bucket_dev_split(qa["title"], seed)].append(qa)
            dev_titles.add(qa["title"])

    # an article that anchors a held-out question must not anchor a training question
    train_rows = [r for r in train_rows if r["title"] not in dev_titles]
    tables = {
        DatasetSplit.TRAIN: pa.Table.from_pylist(train_rows, schema=SCHEMA),
        DatasetSplit.VAL: pa.Table.from_pylist(dev_rows[DatasetSplit.VAL], schema=SCHEMA),
        DatasetSplit.TEST: pa.Table.from_pylist(dev_rows[DatasetSplit.TEST], schema=SCHEMA),
    }
    return write_split_tables(dataset_id, Path(output_dir), tables)
