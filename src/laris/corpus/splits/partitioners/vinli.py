"""Vietnamese NLI (ViNLI): official splits renamed to the project convention."""

from pathlib import Path
from typing import Dict, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult

THREE_WAY_LABELS = {"entailment", "neutral", "contradiction"}
SCHEMA = pa.schema(
    [("premise", pa.string()), ("hypothesis", pa.string()), ("label", pa.string())]
)
OFFICIAL_FILES = {
    DatasetSplit.TRAIN: "train-00000-of-00001.parquet",
    DatasetSplit.VAL: "dev-00000-of-00001.parquet",
    DatasetSplit.TEST: "test-00000-of-00001.parquet",
}


def partition_vinli_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "VINLI",
) -> PhysicalSplitResult:
    """Keeps the official train/dev/test splits and prepares 3-way NLI records.

    ViNLI ships a fourth label, `other`, which the 3-way NLI head cannot represent; those
    rows are dropped. Any pair that also occurs in val/test is removed from train.
    """
    in_dir = Path(raw_dir)
    tables: Dict[DatasetSplit, pa.Table] = {}
    held_out_pairs = set()
    for split in (DatasetSplit.TEST, DatasetSplit.VAL, DatasetSplit.TRAIN):
        raw = pq.read_table(in_dir / OFFICIAL_FILES[split]).to_pylist()
        rows = []
        for rec in raw:
            label = rec["gold_label"]
            pair = (rec["sentence1"], rec["sentence2"])
            if label not in THREE_WAY_LABELS or pair in held_out_pairs:
                continue
            rows.append({"premise": pair[0], "hypothesis": pair[1], "label": label})
            if split != DatasetSplit.TRAIN:
                held_out_pairs.add(pair)
        tables[split] = pa.Table.from_pylist(rows, schema=SCHEMA)
    return write_split_tables(dataset_id, Path(output_dir), tables)
