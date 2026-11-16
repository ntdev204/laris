#!/usr/bin/env python3
"""QA formatters and word-order paraphrase sources (T200). Reads raw data, writes train splits.

Nothing trains.

QA (DuoRC, ROPES, Quoref, DROP) goes to the loader's QA schema through
`laris.research.corpus.splits.partitioners.pair_sources`; PAWS-Wiki swap and unlabeled become
`paws_swap_en` and `paws_unlabeled_en` with a `label_source` column (`human`, `model`).

Every source is written as `train.parquet` only. A validation or test file would enter the gate
averages of the evaluator (they weight datasets by rows), so the new sources never get one; their
raw validation splits stay untouched. Rows are dropped when their context (QA) or a sentence
(paraphrase) overlaps held-out data: normalised exact match or an eight-word window, against the
held-out splits of the gate sources and of the sources the mixture already evaluates on.

Usage (tokenizer encoding only, no fitting):
    .venv/bin/python -I scripts/build_qa_paraphrase_data.py \
        --tokenizer artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model [--apply]
Without --apply nothing is written; the counts and the report are still produced.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.research.corpus.splits.partitioners import pair_sources as P  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "processed"
RAW = REPO_ROOT / "data" / "raw"
REPORT = REPO_ROOT / "reports" / "verification" / "T200-paraphrase-qa-data.json"

# Held-out contexts a QA row may not share an eight-word window with: the G06/G07 sources and every
# other QA source the evaluator scores.
QA_HELD_OUT = ("squad", "squad_v2_en", "adversarial_qa_en", "hotpotqa")
# Held-out sentences a paraphrase row may not contain: PAWS, Quora, MRPC, STS-B (G05) val and test.
PARA_HELD_OUT = {
    "paws": ("sentence1", "sentence2"),
    "quora_duplicates": ("sentence1", "sentence2"),
    "mrpc_en": ("sentence1", "sentence2"),
    "stsb": ("sentence1", "sentence2"),
}
QA_SEQ_LENS = (1024, 512)


def batches(path: Path, columns: Optional[List[str]] = None) -> Iterator[Dict[str, Any]]:
    for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=columns):
        yield from batch.to_pylist()


def held_out_texts(dirs: Dict[str, Sequence[str]]) -> Iterator[str]:
    for name, columns in dirs.items():
        for split in ("val", "test"):
            path = PROCESSED / name / f"{split}.parquet"
            if path.exists():
                for row in batches(path, list(columns)):
                    for column in columns:
                        yield row[column] or ""


def qa_raw_rows() -> Iterator[Tuple[str, Dict[str, Any], str]]:
    """(source, raw row, variant) of every training row of the four QA sources."""
    for variant in ("ParaphraseRC", "SelfRC"):
        path = RAW / "duorc_en" / f"{variant}__train-00000-of-00001.parquet"
        for row in batches(path):
            yield "duorc_en", row, variant
    for row in batches(RAW / "ropes_en" / "train-00000-of-00001.parquet"):
        yield "ropes_en", row, ""
    for row in batches(RAW / "quoref_en" / "train__0000.parquet"):
        yield "quoref_en", row, ""
    for row in batches(RAW / "drop_en" / "train-00000-of-00001.parquet"):
        yield "drop_en", row, ""


def format_qa(index: P.WindowIndex) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    outcomes: Dict[str, Counter] = {}
    leaked: Dict[str, Counter] = {}
    seen: Dict[str, set] = {}
    cache: Dict[str, Optional[str]] = {}
    for source, raw, variant in qa_raw_rows():
        formatter = {
            "duorc_en": lambda r: P.format_duorc(r, variant),
            "ropes_en": P.format_ropes,
            "quoref_en": P.format_quoref,
            "drop_en": P.format_drop,
        }[source]
        row, outcome = formatter(raw)
        counter = outcomes.setdefault(source, Counter())
        if row is None:
            counter[outcome] += 1
            continue
        if row["id"] in seen.setdefault(source, set()):
            counter["dropped_duplicate_id"] += 1
            continue
        context = row["context"]
        if context not in cache:
            cache[context] = index.hit(context)
        if cache[context]:
            leaked.setdefault(source, Counter())[cache[context]] += 1
            counter["dropped_held_out_overlap"] += 1
            continue
        seen[source].add(row["id"])
        counter[outcome] += 1
        rows.setdefault(source, []).append(row)
    stats = {
        s: {"outcomes": dict(sorted(c.items())), "held_out_overlap": dict(leaked.get(s, {}))}
        for s, c in outcomes.items()
    }
    return rows, stats


def format_paraphrase(
    index: P.WindowIndex,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    sources = {
        "paws_swap_en": (
            RAW / "paws_swap_en" / "train-00000-of-00001.parquet",
            P.LABEL_SOURCE_HUMAN,
        ),
        "paws_unlabeled_en": (
            RAW / "paws_unlabeled_en" / "train-00000-of-00001.parquet",
            P.LABEL_SOURCE_MODEL,
        ),
    }
    seen = {
        P.pair_key(r["sentence1"], r["sentence2"])
        for r in batches(PROCESSED / "paws" / "train.parquet", ["sentence1", "sentence2"])
    }
    out: Dict[str, List[Dict[str, Any]]] = {}
    stats: Dict[str, Any] = {}
    for name, (path, label_source) in sources.items():
        counter: Counter = Counter()
        held: Counter = Counter()
        kept: List[Dict[str, Any]] = []
        for raw in batches(path):
            row = P.paws_row(raw, label_source)
            if row is None:
                counter["dropped_bad_row"] += 1
                continue
            key = P.pair_key(row["sentence1"], row["sentence2"])
            if key in seen:
                counter["dropped_duplicate_pair"] += 1
                continue
            hits = [index.hit(row["sentence1"]), index.hit(row["sentence2"])]
            if any(hits):
                held["exact" if "exact" in hits else "window"] += 1
                counter["dropped_held_out_overlap"] += 1
                continue
            seen.add(key)
            counter["kept"] += 1
            kept.append(row)
        out[name] = kept
        labels = Counter(r["label"] for r in kept)
        stats[name] = {
            "label_source": label_source,
            "outcomes": dict(sorted(counter.items())),
            "held_out_overlap": dict(held),
            "label_counts": {str(k): v for k, v in sorted(labels.items())},
        }
    return out, stats


def rescan_qa(rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Independent count over the written rows, with a second hash function."""
    import hashlib

    def grams(text: str) -> set:
        words = P.normalise(text).split()
        return {
            hashlib.sha256(" ".join(words[i : i + P.WINDOW]).encode()).digest()[:12]
            for i in range(len(words) - P.WINDOW + 1)
        }

    held = set()
    for text in held_out_texts({name: ("context",) for name in QA_HELD_OUT}):
        held |= grams(text)
    result = {}
    for source, items in rows.items():
        contexts = {r["context"] for r in items}
        result[source] = {
            "contexts_checked": len(contexts),
            "window_hits": sum(1 for c in contexts if grams(c) & held),
        }
    return result


def rescan_paraphrase(rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Independent count with word tuples and normalised strings, no hashing."""
    held = list(held_out_texts(PARA_HELD_OUT))
    exact = {P.normalise(s) for s in held if P.normalise(s)}
    grams = set()
    for sentence in held:
        words = P.normalise(sentence).split()
        grams.update(tuple(words[i : i + P.WINDOW]) for i in range(len(words) - P.WINDOW + 1))
    result = {}
    for source, items in rows.items():
        exact_hits = window_hits = 0
        for row in items:
            for sentence in (row["sentence1"], row["sentence2"]):
                words = P.normalise(sentence).split()
                if P.normalise(sentence) in exact:
                    exact_hits += 1
                elif any(
                    tuple(words[i : i + P.WINDOW]) in grams
                    for i in range(len(words) - P.WINDOW + 1)
                ):
                    window_hits += 1
        result[source] = {
            "pairs_checked": len(items),
            "exact_hits": exact_hits,
            "window_hits": window_hits,
        }
    return result


def drop_outside_window(
    rows: Dict[str, List[Dict[str, Any]]], tokenizer: Path, seq_len: int
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    """Drop answerable rows whose answer ends outside the window: the loader would train them on the
    no-answer position, a false label. True unanswerable rows (empty answer) stay."""
    audit = load_audit()
    encoder = audit.Encoder.sentencepiece(tokenizer)
    kept: Dict[str, List[Dict[str, Any]]] = {}
    dropped: Dict[str, int] = {}
    for source, items in rows.items():
        answerable = [i for i, r in enumerate(items) if r["answers"]["text"]]
        lq = encoder.lengths([items[i]["question"] for i in answerable])
        prefix = encoder.lengths(
            [items[i]["context"][: items[i]["answers"]["answer_start"][0]] for i in answerable]
        )
        alen = encoder.lengths([items[i]["answers"]["text"][0] for i in answerable])
        outside = {
            i
            for j, i in enumerate(answerable)
            if not audit.qa_answer_window(int(lq[j]), int(prefix[j]), int(alen[j]), seq_len)
        }
        dropped[source] = len(outside)
        kept[source] = [r for i, r in enumerate(items) if i not in outside]
    return kept, dropped


def load_audit() -> Any:
    if "audit_pair_data" in sys.modules:
        return sys.modules["audit_pair_data"]
    spec = importlib.util.spec_from_file_location(
        "audit_pair_data", REPO_ROOT / "scripts/audit_pair_data.py"
    )
    assert spec and spec.loader
    audit = importlib.util.module_from_spec(spec)
    sys.modules["audit_pair_data"] = audit
    spec.loader.exec_module(audit)
    return audit


def audit_windows(rows: Dict[str, List[Dict[str, Any]]], tokenizer: Path) -> Dict[str, Any]:
    audit = load_audit()
    encoder = audit.Encoder.sentencepiece(tokenizer)
    out = {}
    for source, items in rows.items():
        qa = audit.squad_from_rows(items)
        out[source] = audit.audit_qa(qa, encoder, QA_SEQ_LENS)
    return out


def pool_shares(measured: Dict[str, Any]) -> Dict[str, Any]:
    """Unanswerable share of the QA training pool, before and after the new sources (exponent 1)."""
    existing = {}
    for name in ("squad", "hotpotqa", "squad_v2_en", "adversarial_qa_en"):
        path = PROCESSED / name / "train.parquet"
        table = pq.read_table(path, columns=["answers"])
        texts = table.column("answers").combine_chunks().field("text")
        empty = sum(1 for t in texts.to_pylist() if not t)
        existing[name] = {"rows": len(table), "unanswerable": empty}
    new = {
        s: {
            "rows": m["rows"],
            "unanswerable": m["unanswerable"],
            "trained_on_cls_at_1024": round(
                m["window"]["1024"]["share_of_rows_trained_on_cls"] * m["rows"]
            ),
        }
        for s, m in measured.items()
    }

    def share(parts: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        rows = sum(p["rows"] for p in parts.values())
        empty = sum(p["unanswerable"] for p in parts.values())
        return {
            "rows": rows,
            "unanswerable": empty,
            "unanswerable_share": round(empty / max(1, rows), 4),
        }

    parts = {**existing, **new}
    by_exponent = {}
    for exponent in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        weights = {k: v["rows"] ** exponent for k, v in parts.items()}
        total = sum(weights.values())
        by_exponent[str(exponent)] = round(
            sum(weights[k] * v["unanswerable"] / v["rows"] for k, v in parts.items()) / total, 4
        )
    return {
        "unanswerable_share_by_qa_sampling_exponent": by_exponent,
        "existing_pool": share(existing),
        "new_sources": share(new),
        "pool_with_new_sources": share({**existing, **new}),
        "per_source_existing": existing,
        "per_source_new": new,
    }


def write(rows: Dict[str, List[Dict[str, Any]]], schema: pa.Schema) -> Dict[str, Any]:
    from laris.research.corpus.splits.physical import _compute_file_sha256

    entries = {}
    for source, items in rows.items():
        out = PROCESSED / source
        out.mkdir(parents=True, exist_ok=True)
        path = out / "train.parquet"
        pq.write_table(pa.Table.from_pylist(items, schema=schema), path, compression="snappy")
        entries[source] = {
            "dataset_id": source.upper().replace("_", "-"),
            "counts": {"train": len(items)},
            "bytes": {"train": path.stat().st_size},
            "sha256": {"train": _compute_file_sha256(path)},
            "files": {"train": str(path)},
            "leakage_verified": True,
        }
    return entries


def update_manifest(entries: Dict[str, Any]) -> None:
    path = PROCESSED / "task_splits_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    ids = {e["dataset_id"] for e in entries.values()}
    kept = [r for r in manifest["partitioned_datasets"] if r["dataset_id"] not in ids]
    manifest["partitioned_datasets"] = kept + list(entries.values())
    manifest["total_datasets_partitioned"] = len(manifest["partitioned_datasets"])
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tokenizer", required=True, type=Path, help="SentencePiece model (encoding only)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the train splits and the manifest"
    )
    args = parser.parse_args(argv)

    print("[index] held-out QA contexts", flush=True)
    qa_index = P.WindowIndex(held_out_texts({n: ("context",) for n in QA_HELD_OUT}))
    print(f"        {len(qa_index.hashes):,} windows", flush=True)
    qa_rows, qa_stats = format_qa(qa_index)
    print("[qa]", {s: len(r) for s, r in qa_rows.items()}, flush=True)
    print("[index] held-out sentences", flush=True)
    para_index = P.WindowIndex(held_out_texts(PARA_HELD_OUT))
    para_rows, para_stats = format_paraphrase(para_index)
    print("[paraphrase]", {s: len(r) for s, r in para_rows.items()}, flush=True)

    audit = load_audit()
    seq_len = audit.default_seq_len()
    qa_rows, outside = drop_outside_window(qa_rows, args.tokenizer, seq_len)
    print("[qa] dropped, answer outside the window:", outside, flush=True)
    measured = audit_windows(qa_rows, args.tokenizer)
    report = {
        "task": "T200",
        "applied": bool(args.apply),
        "split_policy": "train.parquet only; raw validation and test splits are untouched",
        "qa": {
            "window_length": seq_len,
            "dropped_answer_outside_window": outside,
            "sources": qa_stats,
            "measured": measured,
            "pool": pool_shares(measured),
        },
        "paraphrase": para_stats,
        "rescan": {"qa": rescan_qa(qa_rows), "paraphrase": rescan_paraphrase(para_rows)},
    }
    if args.apply:
        entries = {**write(qa_rows, P.QA_SCHEMA), **write(para_rows, P.PARAPHRASE_SCHEMA)}
        update_manifest(entries)
        report["written"] = {s: e["counts"]["train"] for s, e in entries.items()}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
