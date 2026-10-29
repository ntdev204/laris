"""Vietnamese STS (ViSTS): test-only release sub-split by connected sentence components."""

import json
from pathlib import Path
from typing import Dict, List, Union

import pyarrow as pa

from laris.corpus.partition import _DisjointSetUnion
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import bucket_split, write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult

SPLIT_ORDER = (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST)
SCHEMA = pa.schema(
    [
        ("sentence1", pa.string()),
        ("sentence2", pa.string()),
        ("score", pa.float32()),
        ("source", pa.string()),
    ]
)


def partition_vists_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "VISTS",
    seed: str = "laris-vists-partition-seed-v1",
) -> PhysicalSplitResult:
    """Splits pairs so that no sentence occurs in more than one split.

    Pairs are linked through shared sentences (union-find); each connected component is assigned
    to a split by hash. Scores are rescaled from [0, 5] to [0, 1].
    """
    pairs: List[dict] = []
    for path in sorted(Path(raw_dir).glob("*.jsonl")):
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                s1, s2 = (rec.get("sentence1") or "").strip(), (rec.get("sentence2") or "").strip()
                if not s1 or not s2 or rec.get("score") is None:
                    continue
                pairs.append(
                    {
                        "sentence1": s1,
                        "sentence2": s2,
                        "score": min(1.0, max(0.0, float(rec["score"]) / 5.0)),
                        "source": path.stem.split("__")[0],
                    }
                )

    dsu = _DisjointSetUnion()
    for rec in pairs:
        dsu.union(rec["sentence1"], rec["sentence2"])

    rows: Dict[DatasetSplit, List[dict]] = {s: [] for s in SPLIT_ORDER}
    for rec in pairs:
        rows[bucket_split(dsu.find(rec["sentence1"]), seed)].append(rec)
    tables = {s: pa.Table.from_pylist(r, schema=SCHEMA) for s, r in rows.items()}
    return write_split_tables(dataset_id, Path(output_dir), tables)

