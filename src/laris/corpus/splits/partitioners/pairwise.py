"""Official-split partitioners for All-NLI, ANLI, PAWS-Wiki and STSB."""

import json
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Set, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import normalized_text_digest, write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult

Row = Dict[str, object]
KeyFn = Callable[[Row], Sequence[bytes]]

NLI_LABELS = {0: "entailment", 1: "neutral", 2: "contradiction"}
ANLI_LABELS = {"e": "entailment", "n": "neutral", "c": "contradiction"}
NLI_SCHEMA = pa.schema(
    [("premise", pa.string()), ("hypothesis", pa.string()), ("label", pa.string())]
)
PAWS_SCHEMA = pa.schema(
    [
        ("id", pa.int64()),
        ("sentence1", pa.string()),
        ("sentence2", pa.string()),
        ("label", pa.int64()),
    ]
)
STSB_SCHEMA = pa.schema(
    [("sentence1", pa.string()), ("sentence2", pa.string()), ("score", pa.float64())]
)


def _pair_key(first: str, second: str) -> KeyFn:
    def key(row: Row) -> Sequence[bytes]:
        return (normalized_text_digest(f"{row[first]}\x00{row[second]}"),)

    return key


def _sentence_keys(first: str, second: str) -> KeyFn:
    def key(row: Row) -> Sequence[bytes]:
        return (normalized_text_digest(str(row[first])), normalized_text_digest(str(row[second])))

    return key


def _assemble(
    dataset_id: str,
    output_dir: Union[str, Path],
    rows_by_split: Dict[DatasetSplit, List[Row]],
    schema: pa.Schema,
    key: KeyFn,
) -> PhysicalSplitResult:
    """Keeps official splits; drops train rows whose key also occurs in val/test."""
    held_out: Set[bytes] = set()
    tables: Dict[DatasetSplit, pa.Table] = {}
    for split in (DatasetSplit.TEST, DatasetSplit.VAL, DatasetSplit.TRAIN):
        kept: List[Row] = []
        for row in rows_by_split[split]:
            digests = key(row)
            if split == DatasetSplit.TRAIN and any(d in held_out for d in digests):
                continue
            kept.append(row)
            if split != DatasetSplit.TRAIN:
                held_out.update(digests)
        tables[split] = pa.Table.from_pylist(kept, schema=schema)
    return write_split_tables(dataset_id, Path(output_dir), tables)


def _read(path: Path) -> List[Row]:
    rows: List[Row] = pq.read_table(path).to_pylist()
    return rows


def _nli_rows(raw: List[Row]) -> List[Row]:
    return [
        {"premise": r["premise"], "hypothesis": r["hypothesis"], "label": NLI_LABELS[r["label"]]}
        for r in raw
        if r["label"] in NLI_LABELS
    ]


def partition_all_nli_physical(
    raw_dir: Union[str, Path], output_dir: Union[str, Path], dataset_id: str = "ALL-NLI"
) -> PhysicalSplitResult:
    """SNLI + MultiNLI with integer labels mapped to names; unlabeled (-1) rows dropped."""
    raw = Path(raw_dir)
    files = {
        DatasetSplit.TRAIN: "train-00000-of-00001.parquet",
        DatasetSplit.VAL: "dev-00000-of-00001.parquet",
        DatasetSplit.TEST: "test-00000-of-00001.parquet",
    }
    rows = {split: _nli_rows(_read(raw / name)) for split, name in files.items()}
    return _assemble(dataset_id, output_dir, rows, NLI_SCHEMA, _pair_key("premise", "hypothesis"))


def partition_anli_physical(
    raw_dir: Union[str, Path], output_dir: Union[str, Path], dataset_id: str = "ANLI"
) -> PhysicalSplitResult:
    """Adversarial NLI rounds R1-R3 merged under the official train/dev/test names."""
    root = Path(raw_dir) / "anli_v0.1"
    names = {DatasetSplit.TRAIN: "train", DatasetSplit.VAL: "dev", DatasetSplit.TEST: "test"}
    rows: Dict[DatasetSplit, List[Row]] = {}
    for split, name in names.items():
        collected: List[Row] = []
        for rnd in ("R1", "R2", "R3"):
            with open(root / rnd / f"{name}.jsonl", "r", encoding="utf-8") as handle:
                for line in handle:
                    rec = json.loads(line)
                    if rec["label"] in ANLI_LABELS:
                        collected.append(
                            {
                                "premise": rec["context"],
                                "hypothesis": rec["hypothesis"],
                                "label": ANLI_LABELS[rec["label"]],
                            }
                        )
        rows[split] = collected
    return _assemble(dataset_id, output_dir, rows, NLI_SCHEMA, _pair_key("premise", "hypothesis"))


def partition_paws_physical(
    raw_dir: Union[str, Path], output_dir: Union[str, Path], dataset_id: str = "PAWS-WIKI"
) -> PhysicalSplitResult:
    """PAWS-Wiki; a train pair sharing either sentence with val/test is removed."""
    raw = Path(raw_dir)
    files = {
        DatasetSplit.TRAIN: "train-00000-of-00001.parquet",
        DatasetSplit.VAL: "validation-00000-of-00001.parquet",
        DatasetSplit.TEST: "test-00000-of-00001.parquet",
    }
    rows = {split: _read(raw / name) for split, name in files.items()}
    return _assemble(
        dataset_id, output_dir, rows, PAWS_SCHEMA, _sentence_keys("sentence1", "sentence2")
    )


def partition_stsb_physical(
    raw_dir: Union[str, Path], output_dir: Union[str, Path], dataset_id: str = "STSB"
) -> PhysicalSplitResult:
    """STS-B with scores already in [0, 1]; a train pair also in val/test is removed."""
    raw = Path(raw_dir)
    files = {
        DatasetSplit.TRAIN: "train-00000-of-00001.parquet",
        DatasetSplit.VAL: "validation-00000-of-00001.parquet",
        DatasetSplit.TEST: "test-00000-of-00001.parquet",
    }
    rows = {split: _read(raw / name) for split, name in files.items()}
    return _assemble(
        dataset_id, output_dir, rows, STSB_SCHEMA, _pair_key("sentence1", "sentence2")
    )
