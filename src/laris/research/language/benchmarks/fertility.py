"""Tokenizer fertility on unseen English and Vietnamese text (formal gates G10 and G11).

Definitions (fixed; the report repeats them):

* word  = a whitespace-delimited item of the NFC-normalised text (`str.split()`), punctuation
  attached. In Vietnamese a whitespace item is a *syllable*, not a word-segmented word, so
  Vietnamese values are tokens per syllable and are not comparable with segmented-word figures.
* token = one SentencePiece piece of the raw text, with no special tokens added. [UNK] pieces
  count as tokens and are also reported as an unknown rate.
* fertility = tokens / words.

"Unseen" means held-out text the tokenizer was never fitted on: test partitions that are
disjoint from the fitting corpus. Every sampled text is additionally hashed and compared with
the on-disk tokenizer-fitting corpus; exact matches are excluded and counted.

The module only encodes text with an existing tokenizer. It never fits or trains anything.
"""

import argparse
import hashlib
import json
import statistics
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow.parquet as pq

from laris.shared.corpus.normalizer import normalize_scientific_text
from laris.shared.language.loading.checkpoint import current_git_commit, file_sha256
from laris.shared.language.tokenization.normalized import NORMALIZATION_ID

FERTILITY_PROTOCOL = "unseen_text_tokens_per_word"
REPORT_VERSION = "fertility-1"
UNK_ID = 1
PREFIX_CHARS = 200


@dataclass(frozen=True)
class SourceSpec:
    """One held-out test source: a split file of a partitioned dataset."""

    source_id: str
    language: str
    dataset_dir: str
    manifest_id: str
    columns: Tuple[str, ...]
    domain: str


DEFAULT_SOURCES: Tuple[SourceSpec, ...] = (
    SourceSpec("wikipedia_en_test", "en", "wikipedia_en", "WIKIPEDIA-EN", ("text",), "wiki"),
    SourceSpec("all_nli_test", "en", "all_nli", "ALL-NLI", ("premise", "hypothesis"), "sentences"),
    SourceSpec("wikipedia_vi_test", "vi", "wikipedia_vi", "WIKIPEDIA-VI", ("text",), "wiki"),
    SourceSpec("cc100_vi_test", "vi", "cc100_vi_clean", "CC100-VI-CLEAN", ("text",), "web"),
)  # fmt: skip


# ----------------------------------------------------------------------------- counting
def count_words(text: str) -> int:
    return len(text.split())


def encode_ids(tokenizer: Any, texts: Sequence[str]) -> List[List[int]]:
    """Token ids of each text, batched when the tokenizer supports it."""
    if hasattr(tokenizer, "encode"):
        try:
            return [list(ids) for ids in tokenizer.encode(list(texts), out_type=int)]
        except TypeError:
            pass
    return [list(tokenizer.encode_as_ids(text)) for text in texts]


def fertility(tokens: int, words: int) -> float:
    return tokens / words if words else 0.0


# ----------------------------------------------------------------------------- sampling
def sample_indices(total: int, count: int, seed: int) -> np.ndarray:
    """Sorted row indices of a seeded sample without replacement."""
    if count >= total:
        return np.arange(total)
    return np.sort(np.random.default_rng(seed).choice(total, size=count, replace=False))


def read_texts(path: Path, columns: Sequence[str], indices: np.ndarray) -> List[str]:
    """Texts of the selected rows. Several columns give one text per column value, deduplicated."""
    wanted = set(int(i) for i in indices)
    texts: List[str] = []
    row = 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=4096, columns=list(columns)):
        data = {name: batch.column(name).to_pylist() for name in columns}
        for offset in range(batch.num_rows):
            if row + offset in wanted:
                for name in columns:
                    value = data[name][offset]
                    if value:
                        texts.append(str(value))
        row += batch.num_rows
    return sorted(set(texts)) if len(columns) > 1 else texts


# ----------------------------------------------------------------------------- leakage scan
def _hash64(data: bytes) -> int:
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


def fit_text_key(text: str) -> str:
    """The same normalisation used to build the tokenizer-fitting corpus lines."""
    return " ".join(normalize_scientific_text(text).split())


def fingerprint_fit_corpus(corpus: Path) -> Tuple[np.ndarray, np.ndarray, int]:
    """Sorted 64-bit hashes of every corpus line and of its first PREFIX_CHARS characters."""
    full, prefix, lines = array("Q"), array("Q"), 0
    with open(corpus, "rb") as handle:
        for line in handle:
            body = line.rstrip(b"\r\n")
            if not body:
                continue
            lines += 1
            full.append(_hash64(body))
            head = body[: PREFIX_CHARS * 4].decode("utf-8", "ignore")[:PREFIX_CHARS]
            prefix.append(_hash64(head.encode("utf-8")))
    return (
        np.sort(np.frombuffer(full, dtype=np.uint64)),
        np.sort(np.frombuffer(prefix, dtype=np.uint64)),
        lines,
    )


def _member(sorted_hashes: np.ndarray, value: int) -> bool:
    if not len(sorted_hashes):
        return False
    position = int(np.searchsorted(sorted_hashes, np.uint64(value)))
    return position < len(sorted_hashes) and int(sorted_hashes[position]) == value


def classify_overlap(text: str, full: np.ndarray, prefix: np.ndarray) -> Tuple[bool, bool]:
    """(exact match with a fitting-corpus line, shares its leading characters with one)."""
    key = fit_text_key(text)
    if not key:
        return False, False
    exact = _member(full, _hash64(key.encode("utf-8")))
    head = _member(prefix, _hash64(key[:PREFIX_CHARS].encode("utf-8")))
    return exact, head


# ----------------------------------------------------------------------------- measurement
def _distribution(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0}
    ordered = sorted(values)
    return {
        "p50": float(statistics.median(ordered)),
        "p95": float(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]),
    }


BOOTSTRAP_RESAMPLES = 1000


def bootstrap_fertility(
    tokens: Sequence[int], words: Sequence[int], seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> np.ndarray:
    """Fertility of `resamples` text-level resamples (ratio of sums), seeded."""
    t, w = np.asarray(tokens, dtype=np.float64), np.asarray(words, dtype=np.float64)
    if not len(t) or w.sum() == 0:
        return np.zeros(resamples)
    pick = np.random.default_rng(seed).integers(0, len(t), size=(resamples, len(t)))
    ratio: np.ndarray = t[pick].sum(axis=1) / np.maximum(w[pick].sum(axis=1), 1.0)
    return ratio


def _interval(values: np.ndarray) -> List[float]:
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def measure_texts(
    tokenizer: Any,
    texts: Sequence[str],
    overlap: Optional[Callable[[str], Tuple[bool, bool]]] = None,
    seed: int = 0,
) -> Dict[str, Any]:
    """Fertility of the texts after excluding exact fitting-corpus matches."""
    kept, exact_matches, prefix_matches = [], 0, 0
    flags: List[bool] = []
    for text in texts:
        exact, head = overlap(text) if overlap else (False, False)
        if exact:
            exact_matches += 1
            continue
        kept.append(text)
        flags.append(head)
        prefix_matches += int(head)
    ids = encode_ids(tokenizer, kept)
    words = [count_words(t) for t in kept]
    tokens = [len(i) for i in ids]
    unknown = sum(1 for row in ids for t in row if t == UNK_ID)
    chars = sum(len(t) for t in kept)
    total_words, total_tokens = sum(words), sum(tokens)
    result: Dict[str, Any] = {
        "texts_scored": len(kept),
        "texts_sampled": len(texts),
        "excluded_exact_fit_corpus_matches": exact_matches,
        "prefix_overlap_texts": prefix_matches,
        "words": total_words,
        "tokens": total_tokens,
        "fertility": fertility(total_tokens, total_words),
        "unknown_token_rate": unknown / total_tokens if total_tokens else 0.0,
        "chars_per_token": chars / total_tokens if total_tokens else 0.0,
        "text_fertility": _distribution([fertility(t, w) for t, w in zip(tokens, words) if w > 0]),
    }
    clean_words = sum(w for w, f in zip(words, flags) if not f)
    clean_tokens = sum(t for t, f in zip(tokens, flags) if not f)
    result["fertility_excluding_prefix_overlap"] = fertility(clean_tokens, clean_words)
    boot = bootstrap_fertility(tokens, words, seed)
    result["fertility_ci95"] = _interval(boot)
    result["_bootstrap"] = boot
    return result


def build_report(
    tokenizer: Any,
    sources: Sequence[SourceSpec],
    data_dir: Path,
    docs_per_source: int,
    seed: int,
    overlap: Optional[Callable[[str], Tuple[bool, bool]]],
    manifest_sha256: Optional[str] = None,
    verify_hashes: bool = True,
) -> Dict[str, Any]:
    manifest_path = Path(data_dir) / "task_splits_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {e["dataset_id"]: e for e in manifest.get("partitioned_datasets", [])}
    per_source: List[Dict[str, Any]] = []
    for spec in sources:
        entry = entries.get(spec.manifest_id)
        if entry is None or not entry.get("leakage_verified"):
            raise ValueError(f"{spec.manifest_id}: split isolation is not verified in the manifest")
        path = Path(data_dir) / spec.dataset_dir / "test.parquet"
        actual = file_sha256(path) if verify_hashes else None
        recorded = entry["sha256"]["test"]
        if actual is not None and actual != recorded:
            raise ValueError(f"{path}: SHA-256 differs from the partition manifest")
        total_rows = pq.ParquetFile(path).metadata.num_rows
        indices = sample_indices(total_rows, docs_per_source, seed)
        texts = read_texts(path, spec.columns, indices)
        record = measure_texts(tokenizer, texts, overlap, seed)
        record.update(
            source_id=spec.source_id,
            language=spec.language,
            domain=spec.domain,
            file=str(path),
            file_sha256=actual or recorded,
            file_sha256_verified=actual is not None,
            split_rows=total_rows,
            rows_sampled=len(indices),
            row_index_digest=hashlib.sha256(indices.astype("<i8").tobytes()).hexdigest(),
        )
        per_source.append(record)

    datasets: List[Dict[str, Any]] = []
    for language in sorted({s.language for s in sources}):
        rows = [r for r in per_source if r["language"] == language]
        macro_boot = np.mean([r["_bootstrap"] for r in rows], axis=0)
        words = sum(r["words"] for r in rows)
        tokens = sum(r["tokens"] for r in rows)
        datasets.append(
            {
                "dataset": "unseen_text",
                "language": language,
                "samples": sum(r["texts_scored"] for r in rows),
                "metrics": {
                    "fertility": float(np.mean([r["fertility"] for r in rows])),
                    "fertility_pooled": fertility(tokens, words),
                    "fertility_worst_source": max(r["fertility"] for r in rows),
                    "unknown_token_rate": float(np.mean([r["unknown_token_rate"] for r in rows])),
                    "fertility_ci95_low": _interval(macro_boot)[0],
                    "fertility_ci95_high": _interval(macro_boot)[1],
                },
                "baseline": {},
                "metric_protocols": {"fertility": FERTILITY_PROTOCOL},
                "protocol_details": {
                    "aggregation": "macro_mean_over_sources",
                    "sources": [r["source_id"] for r in rows],
                },
            }
        )
    for record in per_source:
        record.pop("_bootstrap")
    return {
        "report_version": REPORT_VERSION,
        "split": "test",
        "datasets": datasets,
        "sources": per_source,
        "definitions": {
            "word": "whitespace-delimited item of the text (str.split); Vietnamese items are "
            "syllables, so values are tokens per syllable",
            "token": "SentencePiece piece of the raw text, no special tokens; [UNK] counted",
            "fertility": "tokens / words",
            "primary_aggregation": "macro mean of per-source fertility; pooled and worst "
            "source are reported beside it",
            "sampling": "seeded sample of rows without replacement from each test split",
            "confidence": "95% percentile bootstrap over texts, 1000 resamples, fixed seed; "
            "the gate is judged on the point estimate, the interval is context only",
        },
        "dataset_manifest_sha256": manifest_sha256 or file_sha256(manifest_path),
        "split_isolation_checked": True,
        "docs_per_source": docs_per_source,
        "seed": seed,
    }


# ----------------------------------------------------------------------------- command line
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Tokenizer fertility on unseen EN/VI text")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--tokenizer-model", type=Path, default=None, required=True)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint whose identity the report records; its tokenizer digest must match",
    )
    parser.add_argument(
        "--fit-corpus",
        type=Path,
        default=Path("data/cache/wikipedia_train_corpus.txt"),
        help="Tokenizer-fitting corpus used for the leakage scan",
    )
    parser.add_argument(
        "--normalize-input",
        action="store_true",
        help="Apply the tokenizer-fitting normalisation before encoding, as a model trained "
        "with --normalize-input sees its text",
    )
    parser.add_argument("--docs-per-source", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("reports/tokenizer/fertility.json"))
    args = parser.parse_args(argv)

    try:
        import sentencepiece as spm
    except ImportError:
        print("[ERROR] sentencepiece is required (pip install -e '.[tokenizer]')", file=sys.stderr)
        return 2
    if not args.fit_corpus.is_file():
        print(
            f"[ERROR] fitting corpus {args.fit_corpus} not found; leakage scan impossible",
            file=sys.stderr,
        )
        return 2
    tokenizer: Any = spm.SentencePieceProcessor(model_file=str(args.tokenizer_model))
    if args.normalize_input:
        from laris.shared.language.tokenization.normalized import NormalizedSentencePiece

        tokenizer = NormalizedSentencePiece(tokenizer)
    tokenizer_sha = file_sha256(args.tokenizer_model)
    model_sha: Optional[str] = None
    if args.checkpoint is not None:
        from laris.shared.language.loading.checkpoint import read_manifest

        manifest = read_manifest(args.checkpoint)
        recorded = manifest.get("provenance", {}).get("tokenizer_sha256")
        if recorded and recorded != tokenizer_sha:
            print("[ERROR] checkpoint was trained with a different tokenizer", file=sys.stderr)
            return 2
        model_sha = manifest.get("model_sha256")

    partition = json.loads((args.data_dir / "task_splits_manifest.json").read_text("utf-8"))
    expected_lines = sum(
        e["counts"]["train"]
        for e in partition["partitioned_datasets"]
        if e["dataset_id"] in {"WIKIPEDIA-EN", "WIKIPEDIA-VI"}
    )
    print(f"Fingerprinting fitting corpus {args.fit_corpus} ...")
    full, prefix, lines = fingerprint_fit_corpus(args.fit_corpus)
    report = build_report(
        tokenizer,
        DEFAULT_SOURCES,
        args.data_dir,
        args.docs_per_source,
        args.seed,
        lambda text: classify_overlap(text, full, prefix),
    )
    report.update(
        tokenizer_model=str(args.tokenizer_model),
        tokenizer_sha256=tokenizer_sha,
        text_normalization=NORMALIZATION_ID if args.normalize_input else None,
        model_sha256=model_sha,
        checkpoint=str(args.checkpoint) if args.checkpoint else None,
        identity_scope="fertility depends on the tokenizer only; model_sha256 records the "
        "checkpoint named above and must be regenerated for the final candidate",
        fit_corpus={
            "path": str(args.fit_corpus),
            "sha256": file_sha256(args.fit_corpus),
            "bytes": args.fit_corpus.stat().st_size,
            "lines": lines,
            "note": "on-disk corpus; its use for the recorded tokenizer is not itself proven",
            "lines_match_partition_train_counts": lines == expected_lines,
            "expected_lines_from_manifest": expected_lines,
        },
        git_commit=current_git_commit(),
        training_executed=False,
        tokenizer_fitting_executed=False,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for row in report["datasets"]:
        m = row["metrics"]
        print(
            f"{row['language']}: fertility {m['fertility']:.4f} "
            f"(pooled {m['fertility_pooled']:.4f}, worst {m['fertility_worst_source']:.4f})"
        )
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
