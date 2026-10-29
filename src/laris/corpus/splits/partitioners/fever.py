"""FEVER claims: official train kept, labelled dev sub-split grouped by claim id.

The FEVER release carries evidence *references* (Wikipedia page + sentence id) rather than
evidence text, so these records cannot feed premise/hypothesis NLI training until the evidence
sentences are joined from a Wikipedia dump. They are partitioned (leakage-safe) but the training
data loader does not discover this directory.
"""

import glob
from pathlib import Path
from typing import Dict, List, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import bucket_dev_split, write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult


def partition_fever_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "FEVER",
    seed: str = "laris-fever-partition-seed-v1",
) -> PhysicalSplitResult:
    in_dir = Path(raw_dir)
    train = pa.concat_tables(
        [pq.read_table(p) for p in sorted(glob.glob(str(in_dir / "*__train__*.parquet")))]
    )
    dev = pa.concat_tables(
        [pq.read_table(p) for p in sorted(glob.glob(str(in_dir / "*__labelled_dev__*.parquet")))]
    )
    dev_ids = [str(v) for v in dev.column("id").to_pylist()]
    held: Dict[DatasetSplit, List[int]] = {DatasetSplit.VAL: [], DatasetSplit.TEST: []}
    for idx, claim_id in enumerate(dev_ids):
        held[bucket_dev_split(claim_id, seed)].append(idx)

    dev_claim_ids = set(dev_ids)
    keep = [
        i for i, cid in enumerate(train.column("id").to_pylist()) if str(cid) not in dev_claim_ids
    ]
    tables = {
        DatasetSplit.TRAIN: train.take(pa.array(keep, type=pa.int64())),
        DatasetSplit.VAL: dev.take(pa.array(held[DatasetSplit.VAL], type=pa.int64())),
        DatasetSplit.TEST: dev.take(pa.array(held[DatasetSplit.TEST], type=pa.int64())),
    }
    return write_split_tables(dataset_id, Path(output_dir), tables)
