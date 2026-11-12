"""Prepare a train-only tokenizer corpus and a fixed development comparison."""

import argparse
import hashlib
import json
import random
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import sentencepiece as spm
from language.benchmarks.fertility import (
    DEFAULT_SOURCES,
    classify_overlap,
    fingerprint_fit_corpus,
    fit_text_key,
    measure_texts,
    read_texts,
    sample_indices,
)
from language.tokenization.trainer import extract_clean_wikipedia_corpus
from language.training.checkpoint import file_sha256

DATA = Path("data/processed")
OUTPUT = Path("artifacts/tokenizer/foundation-r1")
BASELINE = Path("artifacts/tokenizer/laris_spm_32k.model")
BASELINE_CORPUS = Path("data/cache/wikipedia_train_corpus.txt")
F02 = Path("reports/tokenizer/fertility.json")
SEED = 42
TRAIN_ROWS = 80_000
SOURCE_WORD_LIMIT = 1_000_000
VAL_ROWS = 2_000
MAX_LINE_BYTES = 4096
ADAPTIVE_ROWS = False
SOURCE_LIMITS = {}  # per-source word limits overriding SOURCE_WORD_LIMIT


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sample_source(source, split, rows, entries):
    entry = entries[source.manifest_id]
    path = Path(entry["files"][split])
    expected = DATA / source.dataset_dir / f"{split}.parquet"
    if path != expected or not entry["leakage_verified"]:
        raise ValueError(f"Unverified {split} identity for {source.manifest_id}")
    digest = file_sha256(path)
    if digest != entry["sha256"][split]:
        raise ValueError(f"Changed shard {path}")
    indices = sample_indices(pq.ParquetFile(path).metadata.num_rows, rows, SEED)
    return read_texts(path, source.columns, indices), {
        "dataset_id": source.manifest_id,
        "language": source.language,
        "split": split,
        "path": str(path),
        "sha256": digest,
        "rows_sampled": len(indices),
        "row_index_sha256": hashlib.sha256(indices.astype("<i8").tobytes()).hexdigest(),
    }


def _rows_needed(source, entries, word_limit, ceiling, margin=4.0, probe=20_000):
    """Rows to sample so the word limit is reachable, without loading a whole large shard.

    The mean words per row is estimated from the first rows of the shard; `margin` covers
    duplicates and over-long lines. Sources too small to reach the limit keep every row.
    """
    path = Path(entries[source.manifest_id]["files"]["train"])
    parquet = pq.ParquetFile(path)
    total = parquet.metadata.num_rows
    words = rows = 0
    for batch in parquet.iter_batches(batch_size=4096, columns=list(source.columns)):
        for column in source.columns:
            for text in batch.column(column).to_pylist():
                words += len((text or "").split())
        rows += batch.num_rows
        if rows >= probe:
            break
    mean = max(words / max(rows, 1), 1.0)
    return min(total, ceiling, int(word_limit / mean * margin) + 1)


def _measure(path, samples):
    tokenizer = spm.SentencePieceProcessor(model_file=str(path))
    rows = []
    for source, texts in samples.items():
        result = measure_texts(tokenizer, texts, None, SEED)
        result.pop("_bootstrap")
        rows.append({"source": source, **result})
    macro = {}
    for language in ("en", "vi"):
        values = [r for r in rows if r["source"].startswith(f"{language}/")]
        macro[language] = sum(r["fertility"] for r in values) / len(values)
    return {
        "tokenizer_path": str(path),
        "tokenizer_sha256": file_sha256(path),
        "vocab_size": tokenizer.get_piece_size(),
        "macro_fertility": macro,
        "sources": rows,
    }


def prepare():
    manifest = DATA / "task_splits_manifest.json"
    entries = {
        row["dataset_id"]: row
        for row in json.loads(manifest.read_text())["partitioned_datasets"]
    }
    previous = json.loads(F02.read_text())
    if (
        file_sha256(BASELINE) != previous["tokenizer_sha256"]
        or file_sha256(BASELINE_CORPUS) != previous["fit_corpus"]["sha256"]
    ):
        raise ValueError("Historical tokenizer or corpus changed since F02")
    OUTPUT.mkdir(parents=True, exist_ok=False)
    corpus = OUTPUT / "train.parquet"
    corpus_text = OUTPUT / "train.txt"
    schema = pa.schema([("text", pa.string())])
    train_receipts = []
    seen = set()
    with pq.ParquetWriter(corpus, schema, compression="zstd") as writer:
        for source in DEFAULT_SOURCES:
            limit = SOURCE_LIMITS.get(source.manifest_id, SOURCE_WORD_LIMIT)
            rows = TRAIN_ROWS
            if ADAPTIVE_ROWS:
                rows = _rows_needed(source, entries, limit, TRAIN_ROWS)
            total = pq.ParquetFile(entries[source.manifest_id]["files"]["train"]).metadata.num_rows
            while True:
                texts, receipt = _sample_source(source, "train", rows, entries)
                random.Random(f"{SEED}:{source.manifest_id}").shuffle(texts)
                selected, words, taken = [], 0, set()
                for text in texts:
                    normalized = fit_text_key(text)
                    if not normalized or len(normalized.encode("utf-8")) > MAX_LINE_BYTES:
                        continue
                    if normalized in seen or normalized in taken:
                        continue
                    count = len(normalized.split())
                    if words + count > limit:
                        continue
                    taken.add(normalized)
                    selected.append(normalized)
                    words += count
                    if words == limit:
                        break
                # Over-long lines are dropped, so a sample can fall short; widen it until the
                # limit is reached or every row has been read.
                if words >= limit * 0.999 or rows >= min(total, TRAIN_ROWS):
                    break
                rows = min(total, TRAIN_ROWS, rows * 2)
            seen.update(taken)
            if not selected:
                raise ValueError(f"No corpus samples for {source.manifest_id}")
            writer.write_table(pa.table({"text": selected}, schema=schema))
            train_receipts.append({**receipt, "texts_written": len(selected), "words": words})
            print(source.manifest_id, len(selected), words, flush=True)
    extract_clean_wikipedia_corpus([corpus], corpus_text)

    old_full, old_prefix, _ = fingerprint_fit_corpus(BASELINE_CORPUS)
    new_full, new_prefix, _ = fingerprint_fit_corpus(corpus_text)
    samples, val_receipts = {}, []
    for source in DEFAULT_SOURCES:
        texts, receipt = _sample_source(source, "val", VAL_ROWS, entries)
        kept = []
        for text in texts:
            if any(classify_overlap(text, old_full, old_prefix)):
                continue
            if any(classify_overlap(text, new_full, new_prefix)):
                continue
            kept.append(text)
        if not kept:
            raise ValueError(f"No isolated development texts for {source.manifest_id}")
        samples[f"{source.language}/{source.manifest_id}"] = kept
        val_receipts.append({
            **receipt, "texts_scored": len(kept),
            "excluded_exact_or_prefix_overlap": len(texts) - len(kept),
        })

    development = OUTPUT / "development.json"
    _write_json(development, samples)
    report = {
        "task": "F05-R1",
        "split": "val",
        "seed": SEED,
        "selection": {
            "train_rows_per_source": TRAIN_ROWS,
            "max_words_per_source": SOURCE_WORD_LIMIT,
            "source_word_limits": SOURCE_LIMITS,
            "max_utf8_bytes_per_line": MAX_LINE_BYTES,
            "validation_rows_per_source": VAL_ROWS,
            "validation_exclusion": "Exact or 200-character-prefix matches to either fit corpus",
        },
        "dataset_manifest_sha256": file_sha256(manifest),
        "train_sources": train_receipts,
        "validation_sources": val_receipts,
        "fit_parquet": {"path": str(corpus), "sha256": file_sha256(corpus)},
        "fit_text": {"path": str(corpus_text), "sha256": file_sha256(corpus_text)},
        "fixed_development_sample": {"path": str(development), "sha256": file_sha256(development)},
        "baseline_fit_corpus_sha256": previous["fit_corpus"]["sha256"],
        "baseline": _measure(BASELINE, samples),
        "tokenizer_fitting_executed": False,
        "training_executed": False,
    }
    _write_json(OUTPUT / "preparation.json", report)
    print("Baseline development fertility", report["baseline"]["macro_fertility"])


def compare(candidate, candidate_fit_corpus, expected_vocab_size=32_000):
    report = json.loads((OUTPUT / "preparation.json").read_text())
    if file_sha256(candidate_fit_corpus) != report["fit_text"]["sha256"]:
        raise ValueError("Candidate fit corpus differs from the prepared train corpus")
    sample = Path(report["fixed_development_sample"]["path"])
    if file_sha256(sample) != report["fixed_development_sample"]["sha256"]:
        raise ValueError("Development sample changed")
    if file_sha256(BASELINE) != report["baseline"]["tokenizer_sha256"]:
        raise ValueError("Baseline tokenizer changed")
    result = _measure(candidate, json.loads(sample.read_text()))
    if result["vocab_size"] != expected_vocab_size:
        raise ValueError(
            f"Candidate vocabulary {result['vocab_size']} differs from the declared "
            f"{expected_vocab_size}; the approved recipe is 32k, other sizes must be declared"
        )
    comparison = {
        "split": "val",
        "fixed_development_sample": report["fixed_development_sample"],
        "fit_corpus_sha256": report["fit_text"]["sha256"],
        "baseline": report["baseline"],
        "candidate": result,
        "approved_recipe_vocab_size": 32_000,
        "declared_vocab_size": expected_vocab_size,
    }
    _write_json(OUTPUT / "comparison.json", comparison)
    print("Development macro fertility", result["macro_fertility"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", type=Path, metavar="CANDIDATE_MODEL")
    parser.add_argument("--fit-corpus", type=Path, metavar="CANDIDATE_FIT_TEXT")
    parser.add_argument("--output-dir", type=Path, help="evidence directory")
    parser.add_argument(
        "--expected-vocab-size", type=int, default=32_000,
        help="vocabulary the candidate must have (the approved recipe is 32000)",
    )
    parser.add_argument("--train-rows", type=int, help="rows sampled per source (default 80000)")
    parser.add_argument("--word-limit", type=int, help="words kept per source (default 1000000)")
    parser.add_argument(
        "--source-limit", action="append", default=[], metavar="ID=WORDS",
        help="per-source word limit, e.g. WIKIPEDIA-EN=80000000",
    )
    parser.add_argument(
        "--adaptive-rows", action="store_true", help="sample only the rows the word limit needs"
    )
    args = parser.parse_args()
    ADAPTIVE_ROWS = args.adaptive_rows
    SOURCE_LIMITS = {k: int(v) for k, v in (x.split('=') for x in args.source_limit)}
    if args.output_dir:
        OUTPUT = args.output_dir
    if args.train_rows:
        TRAIN_ROWS = args.train_rows
    if args.word_limit:
        SOURCE_WORD_LIMIT = args.word_limit
    if args.compare:
        if not args.fit_corpus:
            parser.error("--compare requires --fit-corpus")
        compare(args.compare, args.fit_corpus, args.expected_vocab_size)
    else:
        prepare()
