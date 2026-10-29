"""FEVER claims as premise/hypothesis NLI pairs, split without claim leakage.

Each SUPPORTS/REFUTES claim is paired with the text of its first complete evidence set
(`evidence_sentences.parquet`, resolved at acquisition). SUPPORTS maps to entailment and REFUTES
to contradiction. NOT ENOUGH INFO claims carry no evidence and are dropped, so FEVER teaches the
entailment/contradiction boundary and contributes no neutral examples. The official train split is
kept (minus claims that also occur in labelled dev); labelled dev is sub-split by claim id.
"""

import glob
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pyarrow as pa
import pyarrow.parquet as pq

from laris.corpus.acquisition.fever_evidence import EVIDENCE_FILENAME
from laris.corpus.schemas import DatasetSplit
from laris.corpus.splits.partitioners.common import bucket_dev_split, write_split_tables
from laris.corpus.splits.physical import PhysicalSplitResult

LABEL_MAP = {"SUPPORTS": "entailment", "REFUTES": "contradiction"}
SCHEMA = pa.schema(
    [("premise", pa.string()), ("hypothesis", pa.string()), ("label", pa.string())]
)


def _load_evidence(in_dir: Path) -> Dict[Tuple[str, int], str]:
    table = pq.read_table(in_dir / EVIDENCE_FILENAME)
    return {
        (page, int(sid)): text
        for page, sid, text in zip(
            table.column("page").to_pylist(),
            table.column("sentence_id").to_pylist(),
            table.column("text").to_pylist(),
        )
    }


def build_pairs(
    claims: pa.Table, evidence: Dict[Tuple[str, int], str]
) -> Dict[str, Optional[Dict[str, str]]]:
    """Maps claim id -> NLI pair (None when no complete evidence set can be resolved)."""
    meta: Dict[str, Tuple[str, str]] = {}
    sets: Dict[str, Dict[int, List[Tuple[str, int]]]] = defaultdict(lambda: defaultdict(list))
    for cid, label, claim, evidence_id, page, sid in zip(
        claims.column("id").to_pylist(),
        claims.column("label").to_pylist(),
        claims.column("claim").to_pylist(),
        claims.column("evidence_id").to_pylist(),
        claims.column("evidence_wiki_url").to_pylist(),
        claims.column("evidence_sentence_id").to_pylist(),
    ):
        key = str(cid)
        meta[key] = (label, claim)
        if page and sid is not None and sid >= 0:
            sets[key][int(evidence_id)].append((page, int(sid)))

    pairs: Dict[str, Optional[Dict[str, str]]] = {}
    for key, (label, claim) in meta.items():
        mapped = LABEL_MAP.get(label)
        pair = None
        if mapped is not None:
            for evidence_id in sorted(sets.get(key, {})):
                found = [evidence.get(ref) for ref in sets[key][evidence_id]]
                sentences = [text for text in found if text]
                if sentences and len(sentences) == len(found):
                    pair = {"premise": " ".join(sentences), "hypothesis": claim, "label": mapped}
                    break
        pairs[key] = pair
    return pairs


def _table(pairs: Dict[str, Optional[Dict[str, str]]], ids: List[str]) -> pa.Table:
    rows = [pairs[i] for i in ids if pairs.get(i)]
    return pa.Table.from_pylist([r for r in rows if r], schema=SCHEMA)


def partition_fever_physical(
    raw_dir: Union[str, Path],
    output_dir: Union[str, Path],
    dataset_id: str = "FEVER",
    seed: str = "laris-fever-partition-seed-v1",
) -> PhysicalSplitResult:
    in_dir = Path(raw_dir)
    evidence = _load_evidence(in_dir)
    train = pa.concat_tables(
        [pq.read_table(p) for p in sorted(glob.glob(str(in_dir / "*__train__*.parquet")))]
    )
    dev = pa.concat_tables(
        [pq.read_table(p) for p in sorted(glob.glob(str(in_dir / "*__labelled_dev__*.parquet")))]
    )
    train_pairs = build_pairs(train, evidence)
    dev_pairs = build_pairs(dev, evidence)

    held: Dict[DatasetSplit, List[str]] = {DatasetSplit.VAL: [], DatasetSplit.TEST: []}
    for claim_id in dev_pairs:
        held[bucket_dev_split(claim_id, seed)].append(claim_id)
    held_texts = {
        (p["premise"], p["hypothesis"]) for p in dev_pairs.values() if p is not None
    }
    train_ids = [
        cid
        for cid, pair in train_pairs.items()
        if cid not in dev_pairs
        and pair is not None
        and (pair["premise"], pair["hypothesis"]) not in held_texts
    ]
    tables = {
        DatasetSplit.TRAIN: _table(train_pairs, train_ids),
        DatasetSplit.VAL: _table(dev_pairs, held[DatasetSplit.VAL]),
        DatasetSplit.TEST: _table(dev_pairs, held[DatasetSplit.TEST]),
    }
    return write_split_tables(dataset_id, Path(output_dir), tables)
