"""Conversion and partitioning of the NER fine-tune sources to one BIO scheme (T187, Phase 42).

Each source becomes ``data/processed/<dir>/{train,val,test}.parquet`` with columns ``id``,
``tokens``,
``labels`` (BIO over the unified label set), ``source_labels`` (BIO over the source's own types) and
``source``. Rules (config-driven, ``configs/data/english_partition.yaml``, section ``ner``):

* The publishers' official train / validation / test splits are kept; nothing is re-split, so the
  test split stays the one the publisher sealed.
* Few-NERD labels one type per token without B/I marks; a run of tokens of the same type becomes one
  entity (``B-`` on its first token). Two adjacent entities of the same type cannot be told apart in
  that format and merge; the count of runs is reported, the merge is not guessable.
* A token tagged ``I-x`` that does not continue an ``x`` entity is repaired to ``B-x`` and counted.
* Held-out text is protected from the train split only: a train sentence that equals a validation or
  test sentence of any NER source (letters and digits, lower case), or shares an eight-word window
  with one, is dropped from train. Validation and test rows are never dropped.

Reads files and writes files; nothing trains.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from laris.research.corpus.splits.partitioners.retrieval import Blocklist, normalise
from laris.research.corpus.splits.physical import PhysicalSplitResult, _compute_file_sha256

NER_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("tokens", pa.list_(pa.string())),
        ("labels", pa.list_(pa.string())),
        ("source_labels", pa.list_(pa.string())),
        ("source", pa.string()),
    ]
)
# Official split name found in the raw file name -> processed file name.
RAW_SPLITS = {"train": "train", "validation": "val", "dev": "val", "test": "test"}
OUTSIDE = "O"


def raw_split(path: Path) -> str:
    """Processed split of a raw file, from its name prefix (``train-0000``, ``test__0000``)."""
    prefix = path.name.replace("__", "-").split("-", 1)[0].split(".", 1)[0]
    if prefix not in RAW_SPLITS:
        raise ValueError(f"cannot tell the official split of {path.name}")
    return RAW_SPLITS[prefix]


def types_to_bio(types: List[Optional[str]]) -> Tuple[List[str], int]:
    """BIO tags from one type (or None for outside) per token, plus the number of entities."""
    tags: List[str] = []
    previous: Optional[str] = None
    entities = 0
    for entity_type in types:
        if entity_type is None:
            tags.append(OUTSIDE)
        else:
            tags.append(f"{'I' if entity_type == previous else 'B'}-{entity_type}")
            entities += entity_type != previous
        previous = entity_type
    return tags, entities


def repair_bio(tags: List[str]) -> Tuple[List[str], int]:
    """Turns an orphan ``I-x`` (one that continues no ``x`` entity) into ``B-x``; counts repairs."""
    fixed: List[str] = []
    repairs = 0
    previous = OUTSIDE
    for tag in tags:
        if tag.startswith("I-") and previous[2:] != tag[2:]:
            tag = "B-" + tag[2:]
            repairs += 1
        fixed.append(tag)
        previous = tag
    return fixed, repairs


def decode_tags(tag_ids: List[int], names: List[str], where: str) -> List[str]:
    try:
        return [names[i] for i in tag_ids]
    except (IndexError, TypeError) as error:
        raise ValueError(f"{where}: tag id outside the declared {len(names)} names") from error


def _check_names(path: Path, column: str, names: List[str]) -> None:
    """Config label names must equal the ones the parquet carries, when it carries any."""
    import json

    metadata = (pq.ParquetFile(path).schema_arrow.metadata or {}).get(b"huggingface")
    if not metadata:
        return
    feature = json.loads(metadata)["info"]["features"].get(column, {})
    declared = feature.get("feature", {}).get("names")
    if declared is not None and declared != names:
        raise ValueError(f"{path.name}: label names of '{column}' differ from the configuration")


def convert_source(
    spec: Dict[str, Any], raw_dir: Path
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    """Official splits of one source as BIO rows, plus per-split statistics."""
    names: List[str] = spec["tag_names"]
    mapping: Dict[str, str] = spec["type_map"]
    unified = set(mapping.values())
    files = sorted(p for p in raw_dir.iterdir() if p.suffix == ".parquet")
    if not files:
        raise FileNotFoundError(f"no parquet files for {spec['id']} in {raw_dir}")
    rows: Dict[str, List[Dict[str, Any]]] = {"train": [], "val": [], "test": []}
    stats: Dict[str, Any] = {
        s: {"sentences": 0, "tokens": 0, "entities": 0, "repaired": 0} for s in rows
    }
    for path in files:
        split = raw_split(path)
        _check_names(path, "ner_tags", names)
        for row in pq.read_table(path, columns=["id", "tokens", "ner_tags"]).to_pylist():
            where = f"{spec['id']} {split} id {row['id']}"
            tokens, ids = row["tokens"], row["ner_tags"]
            if len(tokens) != len(ids):
                raise ValueError(f"{where}: {len(tokens)} tokens but {len(ids)} tags")
            decoded = decode_tags(ids, names, where)
            repairs = 0
            if spec["tag_style"] == "type":  # one type per token (Few-NERD)
                native, entities = types_to_bio([None if t == OUTSIDE else t for t in decoded])
            else:  # B-/I- tags (WNUT-17)
                native, repairs = repair_bio(decoded)
                entities = sum(t.startswith("B-") for t in native)
            labels = []
            for tag in native:
                if tag == OUTSIDE:
                    labels.append(OUTSIDE)
                    continue
                prefix, entity_type = tag[:2], tag[2:]
                if entity_type not in mapping:
                    raise ValueError(f"{where}: type '{entity_type}' has no entry in type_map")
                labels.append(prefix + mapping[entity_type])
            assert {t[2:] for t in labels if t != OUTSIDE} <= unified
            rows[split].append(
                {
                    "id": f"{spec['id']}:{split}:{row['id']}",
                    "tokens": list(tokens),
                    "labels": labels,
                    "source_labels": native,
                    "source": spec["id"],
                }
            )
            counters = stats[split]
            counters["sentences"] += 1
            counters["tokens"] += len(tokens)
            counters["entities"] += entities
            counters["repaired"] += repairs
    return rows, stats


def sentence_text(row: Dict[str, Any]) -> str:
    return " ".join(row["tokens"])


def build_heldout_blocklist(all_rows: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> Blocklist:
    """Validation and test sentences of every NER source, exact and as eight-word windows."""
    block = Blocklist()
    for rows in all_rows.values():
        for split in ("val", "test"):
            for row in rows[split]:
                block.add_passage(f"ner_{split}_sentence", sentence_text(row))
    return block


def _write(
    spec_id: str, out_dir: Path, rows: Dict[str, List[Dict[str, Any]]]
) -> PhysicalSplitResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = PhysicalSplitResult(dataset_id=spec_id)
    for split, split_rows in rows.items():
        if not split_rows:
            continue
        path = out_dir / f"{split}.parquet"
        pq.write_table(
            pa.Table.from_pylist(split_rows, schema=NER_SCHEMA), path, compression="snappy"
        )
        result.files[split] = path
        result.counts[split] = len(split_rows)
        result.bytes[split] = path.stat().st_size
        result.sha256[split] = _compute_file_sha256(path)
    return result


def partition_ner(
    specs: List[Dict[str, Any]], raw_root: Path, processed_root: Path
) -> List[Tuple[PhysicalSplitResult, Dict[str, Any]]]:
    """Converts every NER source, drops train sentences that repeat held-out text, writes files."""
    converted = {
        s["id"]: convert_source(s, raw_root / s["id"].lower().replace("-", "_")) for s in specs
    }
    block = build_heldout_blocklist({sid: rows for sid, (rows, _) in converted.items()})
    results: List[Tuple[PhysicalSplitResult, Dict[str, Any]]] = []
    for spec in specs:
        rows, stats = converted[spec["id"]]
        kept: List[Dict[str, Any]] = []
        dropped: Dict[str, int] = {}
        for row in rows["train"]:
            norm = normalise(sentence_text(row))
            reason = block.exact_hit(norm) if norm else None
            reason = reason or (block.overlap_hit(norm) if norm else None)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
            else:
                kept.append(row)
        rows["train"] = kept
        label_counts: Dict[str, Dict[str, int]] = {}
        for split, split_rows in rows.items():
            counts: Dict[str, int] = {}
            for row in split_rows:
                for tag in row["labels"]:
                    if tag.startswith("B-"):
                        counts[tag[2:]] = counts.get(tag[2:], 0) + 1
            label_counts[split] = dict(sorted(counts.items()))
        out_dir = processed_root / spec["id"].lower().replace("-", "_")
        result = _write(spec["id"], out_dir, rows)
        results.append(
            (
                result,
                {
                    "official": stats,
                    "train_dropped_heldout": dropped,
                    "entities_per_type": label_counts,
                    "counts": result.counts,
                },
            )
        )
    return results
