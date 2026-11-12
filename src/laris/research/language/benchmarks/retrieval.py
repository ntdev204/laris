"""Independent foundation retrieval benchmark (formal gate G12 and its diagnostics).

Queries are questions written by human annotators for a source paragraph in an article-disjoint
held-out split (SQuAD, UIT-ViQuAD 2.0); the relevant document is that paragraph and the corpus is
every paragraph of the split. Nothing is generated here: relevance labels are the datasets' own.
Hard negatives are the other paragraphs of the same article.

The query set, relevance and corpus are frozen by SHA-256 digests recorded in
`configs/evaluation/foundation_retrieval.yaml` and are verified before any model is scored.
Systems: BM25 (the baseline), dense (the encoder's L2-normalised [CLS] embedding) and a
reciprocal-rank-fusion hybrid. Ties count against a system (the relevant document is ranked
below every document with an equal score).

A record is emitted under the gate dataset id `stem_retrieval` only for sources the config marks
gate-eligible. General-domain sources are reported under `paragraph_retrieval`, so G12 stays
MISSING until a STEM source with human relevance exists. The module encodes text only; it never
trains or fits anything.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow.parquet as pq
import yaml

from laris.shared.language.loading.checkpoint import current_git_commit, file_sha256
from laris.shared.retrieval.bm25 import BM25Document, BM25RetrievalBaseline

BENCHMARK_VERSION = "foundation-retrieval-1"
RETRIEVAL_PROTOCOL = "held_out_query_relevance"
NON_GATE_DATASET = "paragraph_retrieval"
CUTOFFS = (1, 5, 10, 50)
RRF_K = 60
BOOTSTRAP_RESAMPLES = 1000
_TOKEN = re.compile(r"\w+|[^\s\w]")


@dataclass(frozen=True)
class RetrievalQuery:
    query_id: str
    text: str
    relevant_doc: str
    title: str
    also_relevant: Tuple[str, ...] = ()  # further judged-relevant documents (multi-judgement sets)


@dataclass(frozen=True)
class RetrievalSplit:
    source_id: str
    language: str
    queries: List[RetrievalQuery]
    doc_ids: List[str]
    doc_texts: List[str]
    doc_titles: List[str]


def doc_id_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------- data
def _has_answer(answers: Any) -> bool:
    texts = answers.get("text") if isinstance(answers, dict) else None
    return any(t and str(t).strip() for t in (texts or []))


def load_split(source: Dict[str, Any], data_dir: Path) -> RetrievalSplit:
    """Answerable questions of a held-out split and the paragraphs they were written for."""
    path = Path(data_dir) / source["dataset_dir"] / f"{source['split']}.parquet"
    rows = pq.read_table(path, columns=["id", "title", "context", "question", "answers"])
    docs: Dict[str, Tuple[str, str]] = {}
    queries: List[RetrievalQuery] = []
    for row in rows.to_pylist():
        if not (row["context"] and row["question"] and row["question"].strip()):
            continue
        if source.get("query_filter", "answerable") == "answerable" and not _has_answer(
            row["answers"]
        ):
            continue
        doc_id = doc_id_of(row["context"])
        docs[doc_id] = (row["context"], row["title"])
        queries.append(RetrievalQuery(str(row["id"]), row["question"], doc_id, row["title"]))
    ordered = sorted(docs)
    return RetrievalSplit(
        source_id=source["id"],
        language=source["language"],
        queries=sorted(queries, key=lambda q: q.query_id),
        doc_ids=ordered,
        doc_texts=[docs[d][0] for d in ordered],
        doc_titles=[docs[d][1] for d in ordered],
    )


def load_qrels_split(source: Dict[str, Any], data_dir: Path) -> RetrievalSplit:
    """Queries with human relevance judgements (qrels) over a shared corpus, e.g. SciFact.

    Reads `<data_dir>/../raw/<raw_dir>`; every positively judged document of a query is relevant,
    and the corpus is the complete document collection. Nothing is generated or relabelled.
    """
    base = Path(data_dir).parent / "raw" / source["raw_dir"]
    corpus = pq.read_table(base / source["corpus_file"]).to_pylist()
    texts = {str(r["_id"]): (r["title"] or "", r["text"] or "") for r in corpus}
    query_rows = pq.read_table(base / source["queries_file"]).to_pylist()
    query_text = {str(r["_id"]): r["text"] for r in query_rows}
    judged: Dict[str, List[str]] = {}
    with open(base / source["qrels_file"], encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if float(row["score"]) > 0 and row["corpus-id"] in texts:
                judged.setdefault(row["query-id"], []).append(row["corpus-id"])
    ordered = sorted(texts)
    queries = []
    for query_id in sorted(judged):
        relevant = sorted(set(judged[query_id]))
        if not query_text.get(query_id, "").strip():
            continue
        queries.append(
            RetrievalQuery(query_id, query_text[query_id], relevant[0], "", tuple(relevant[1:]))
        )
    return RetrievalSplit(
        source_id=source["id"],
        language=source["language"],
        queries=queries,
        doc_ids=ordered,
        doc_texts=[(texts[d][0] + ". " + texts[d][1]).strip(". ") for d in ordered],
        doc_titles=[texts[d][0] for d in ordered],
    )


def load_parallel_split(source: Dict[str, Any], data_dir: Path) -> RetrievalSplit:
    """Cross-lingual alignment diagnostic over translation pairs (e.g. ViPubmed en/vi).

    A seeded sample of rows is drawn; the query is a row's `query_column` text and its only
    relevant document is that same row's `doc_column` text. Relevance holds by construction, no
    judgement is made, and the translation is machine-made, so this is never human relevance.
    """
    path = Path(data_dir).parent / source["parquet"]
    table = pq.read_table(path, columns=[source["query_column"], source["doc_column"]])
    queries_all = table.column(source["query_column"]).to_pylist()
    docs_all = table.column(source["doc_column"]).to_pylist()
    minimum = int(source.get("min_chars", 0))
    eligible = [
        i
        for i, (q, d) in enumerate(zip(queries_all, docs_all))
        if q and d and len(q) >= minimum and len(d) >= minimum
    ]
    picked = sorted(
        np.random.default_rng(int(source["sample_seed"]))
        .choice(len(eligible), size=min(int(source["sample_size"]), len(eligible)), replace=False)
        .tolist()
    )
    rows = [eligible[i] for i in picked]
    ids = [f"r{i}" for i in rows]
    return RetrievalSplit(
        source_id=source["id"],
        language=source["language"],
        queries=[RetrievalQuery(i, queries_all[r], i, "") for i, r in zip(ids, rows)],
        doc_ids=ids,
        doc_texts=[docs_all[r] for r in rows],
        doc_titles=["" for _ in rows],
    )


def load_any(source: Dict[str, Any], data_dir: Path) -> RetrievalSplit:
    if source.get("kind") == "qrels":
        return load_qrels_split(source, data_dir)
    if source.get("kind") == "parallel":
        return load_parallel_split(source, data_dir)
    return load_split(source, data_dir)


def split_digest(split: RetrievalSplit) -> str:
    """SHA-256 over queries, their relevance and the corpus: the frozen benchmark identity."""
    digest = hashlib.sha256()
    for q in split.queries:
        row: List[Any] = [
            q.query_id,
            hashlib.sha256(q.text.encode("utf-8")).hexdigest(),
            q.relevant_doc,
        ]
        if q.also_relevant:  # keeps the digests of single-judgement sources unchanged
            row.append(list(q.also_relevant))
        digest.update(json.dumps(row).encode("utf-8"))
    for doc_id, title in zip(split.doc_ids, split.doc_titles):
        digest.update(json.dumps([doc_id, title]).encode("utf-8"))
    return digest.hexdigest()


def _column(path: Path, name: str) -> List[Any]:
    return list(pq.read_table(path, columns=[name]).column(name).to_pylist())


def isolation_checks(
    split: RetrievalSplit, source: Dict[str, Any], data_dir: Path
) -> Dict[str, Any]:
    """Overlap with the dataset's training split and exposure through pretraining text."""
    base = Path(data_dir) / source["dataset_dir"]
    train_titles = set(_column(base / "train.parquet", "title"))
    train_docs = {doc_id_of(c) for c in _column(base / "train.parquet", "context") if c}
    test_titles = set(split.doc_titles)
    result: Dict[str, Any] = {
        "train_title_overlap": len(test_titles & train_titles),
        "train_paragraph_overlap": len(set(split.doc_ids) & train_docs),
        "titles": len(test_titles),
        "pretraining_text_exposure": None,
    }
    corpus = source.get("pretraining_corpus")
    if corpus:
        known = set(_column(Path(data_dir) / corpus / "train.parquet", "title"))
        exposed = sorted(t for t in test_titles if t.replace("_", " ") in known)
        result["pretraining_text_exposure"] = {
            "corpus": f"{corpus}/train",
            "matching_titles": len(exposed),
            "of_titles": len(test_titles),
            "titles": exposed,
            "note": "the article text was seen as MLM data; questions and labels were not",
        }
    return result


# ----------------------------------------------------------------------------- scoring
def _tokens(text: str) -> List[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t.strip()]


def bm25_scores(split: RetrievalSplit, k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """(queries x documents) BM25 score matrix from the repository's BM25 baseline."""
    engine = BM25RetrievalBaseline(k1=k1, b=b)
    engine.index_documents(
        [
            BM25Document(doc_id=d, text=t, tokens=_tokens(t) or ["<empty>"])
            for d, t in zip(split.doc_ids, split.doc_texts)
        ]
    )
    index = {d: i for i, d in enumerate(split.doc_ids)}
    scores = np.zeros((len(split.queries), len(split.doc_ids)), dtype=np.float64)
    for row, query in enumerate(split.queries):
        for hit in engine.search(query.text, top_k=len(split.doc_ids)):
            scores[row, index[hit.doc_id]] = hit.score
    return scores


def dense_scores(query_vectors: np.ndarray, doc_vectors: np.ndarray) -> np.ndarray:
    """Cosine scores for L2-normalised vectors."""
    scores: np.ndarray = (
        np.asarray(query_vectors, dtype=np.float64) @ np.asarray(doc_vectors, dtype=np.float64).T
    )
    return scores


def rank_matrix(scores: np.ndarray) -> np.ndarray:
    """1-based rank of every document per query (stable order breaks exact ties)."""
    order = np.argsort(-scores, axis=1, kind="stable")
    ranks = np.empty_like(order)
    rows = np.arange(scores.shape[0])[:, None]
    ranks[rows, order] = np.arange(1, scores.shape[1] + 1)[None, :]
    return ranks


def rrf_scores(score_matrices: Sequence[np.ndarray], k: int = RRF_K) -> np.ndarray:
    """Reciprocal rank fusion of several score matrices."""
    fused = np.zeros_like(score_matrices[0], dtype=np.float64)
    for matrix in score_matrices:
        fused += 1.0 / (k + rank_matrix(matrix))
    return fused


def relevant_ranks(
    scores: np.ndarray, split: RetrievalSplit, same_title_only: bool = False
) -> np.ndarray:
    """Pessimistic rank of the relevant document of each query (ties count against it)."""
    index = {d: i for i, d in enumerate(split.doc_ids)}
    titles = np.asarray(split.doc_titles)
    out = np.empty(len(split.queries), dtype=np.int64)
    for row, query in enumerate(split.queries):
        pool = scores[row] if not same_title_only else scores[row][titles == query.title]
        out[row] = min(
            int((pool >= scores[row, index[doc]]).sum())
            for doc in (query.relevant_doc, *query.also_relevant)
        )
    return out


def ndcg_at_10_values(scores: np.ndarray, split: RetrievalSplit) -> np.ndarray:
    """Per-query binary-gain nDCG@10 over every judged-relevant document (ties pessimistic)."""
    index = {d: i for i, d in enumerate(split.doc_ids)}
    out = np.zeros(len(split.queries), dtype=np.float64)
    for row, query in enumerate(split.queries):
        relevant = (query.relevant_doc, *query.also_relevant)
        ranks = np.asarray([int((scores[row] >= scores[row, index[d]]).sum()) for d in relevant])
        gain = float(np.sum(np.where(ranks <= 10, 1.0 / np.log2(ranks + 1.0), 0.0)))
        ideal = float(np.sum(1.0 / np.log2(np.arange(1, min(len(relevant), 10) + 1) + 1.0)))
        out[row] = gain / ideal
    return out


# ----------------------------------------------------------------------------- metrics
def summarise(
    ranks: np.ndarray,
    cutoffs: Sequence[int] = CUTOFFS,
    ndcg: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    """MRR, nDCG@10 and recall@k from best-relevant-document ranks.

    `ndcg` holds per-query nDCG@10 for multi-judgement sets; by default it is derived from the
    single relevant document's rank.
    """
    if not len(ranks):
        return {"mrr": 0.0, "ndcg_at_10": 0.0, **{f"recall_at_{k}": 0.0 for k in cutoffs}}
    ndcg_values = (
        ndcg if ndcg is not None else np.where(ranks <= 10, 1.0 / np.log2(ranks + 1.0), 0.0)
    )
    out = {
        "mrr": float(np.mean(1.0 / ranks)),
        "ndcg_at_10": float(np.mean(ndcg_values)),
    }
    for k in cutoffs:
        out[f"recall_at_{k}"] = float(np.mean(ranks <= k))
    return out


def _interval(values: np.ndarray) -> List[float]:
    return [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]


def bootstrap_mean(
    values: np.ndarray, seed: int, resamples: int = BOOTSTRAP_RESAMPLES
) -> List[float]:
    if not len(values):
        return [0.0, 0.0]
    pick = np.random.default_rng(seed).integers(0, len(values), size=(resamples, len(values)))
    return _interval(values[pick].mean(axis=1))


# ----------------------------------------------------------------------------- evaluation
def evaluate_split(
    split: RetrievalSplit,
    source: Dict[str, Any],
    config: Dict[str, Any],
    embed: Callable[[Sequence[str]], np.ndarray],
    seed: int = 42,
) -> Dict[str, Any]:
    systems_cfg = config["systems"]
    bm25 = bm25_scores(split, systems_cfg["bm25"]["k1"], systems_cfg["bm25"]["b"])
    query_vectors = embed([q.text for q in split.queries])
    doc_vectors = embed(split.doc_texts)
    dense = dense_scores(query_vectors, doc_vectors)
    matrices = {
        "bm25": bm25,
        "dense": dense,
        "hybrid_rrf": rrf_scores([bm25, dense], systems_cfg["hybrid_rrf"]["k"]),
    }
    titles = np.asarray([q.title for q in split.queries])
    results: Dict[str, Any] = {}
    all_ranks: Dict[str, np.ndarray] = {}
    for name, matrix in matrices.items():
        ranks = relevant_ranks(matrix, split)
        all_ranks[name] = ranks
        results[name] = {
            **summarise(ranks, ndcg=ndcg_at_10_values(matrix, split)),
            "mrr_ci95": bootstrap_mean(1.0 / ranks, seed),
        }
        if any(q.title for q in split.queries):  # same-article negatives need article titles
            same_title = relevant_ranks(matrix, split, same_title_only=True)
            results[name]["hard_negative_same_article"] = {
                "mrr": summarise(same_title)["mrr"],
                "recall_at_1": summarise(same_title)["recall_at_1"],
            }
    baseline = config["baseline_system"]
    paired = {}
    for name in ("dense", "hybrid_rrf"):
        diff = 1.0 / all_ranks[name] - 1.0 / all_ranks[baseline]
        paired[f"{name}_minus_{baseline}_mrr"] = {
            "mean": float(diff.mean()),
            "ci95": bootstrap_mean(diff, seed),
        }
    subsets: Dict[str, Any] = {}
    for subset in config.get("subsets", []):
        if subset.get("source") != source["id"]:
            continue
        mask = np.isin(titles, subset["titles"])
        subsets[subset["id"]] = {
            "queries": int(mask.sum()),
            "gate_eligible": False,
            "note": subset["note"],
            **{n: summarise(r[mask]) for n, r in all_ranks.items()},
        }
    return {
        "systems": results,
        "paired_differences": paired,
        "subsets": subsets,
        "_ranks": all_ranks,
    }


def gate_row(
    split: RetrievalSplit,
    source: Dict[str, Any],
    config: Dict[str, Any],
    evaluation: Dict[str, Any],
) -> Dict[str, Any]:
    """Measurement record shaped for the readiness assessment."""
    gate_system, baseline = config["gate_system"], config["baseline_system"]
    systems = evaluation["systems"]
    eligible = bool(source.get("gate_eligible"))
    return {
        "dataset": config["gate_dataset"] if eligible else NON_GATE_DATASET,
        "language": split.language,
        "samples": len(split.queries),
        "metrics": {
            "mrr": systems[gate_system]["mrr"],
            "ndcg_at_10": systems[gate_system]["ndcg_at_10"],
            "recall_at_10": systems[gate_system]["recall_at_10"],
            "hybrid_mrr": systems["hybrid_rrf"]["mrr"],
        },
        "baseline": {
            "mrr": systems[baseline]["mrr"],
            "ndcg_at_10": systems[baseline]["ndcg_at_10"],
            "recall_at_10": systems[baseline]["recall_at_10"],
        },
        "metric_protocols": {"mrr": RETRIEVAL_PROTOCOL},
        "protocol_details": {
            "source": source["id"],
            "gate_system": gate_system,
            "baseline_system": baseline,
            "gate_eligible": eligible,
            "gate_ineligible_reason": None if eligible else source.get("gate_ineligible_reason"),
        },
    }


def verify_frozen(config: Dict[str, Any], digests: Dict[str, Dict[str, Any]]) -> None:
    frozen = config.get("frozen") or {}
    for source_id, current in digests.items():
        recorded = frozen.get(source_id)
        if not recorded:
            raise ValueError(f"{source_id}: benchmark is not frozen; run the freeze command first")
        if recorded != current:
            raise ValueError(f"{source_id}: queries/relevance/corpus differ from the frozen digest")


def load_config(path: Path) -> Dict[str, Any]:
    config: Dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if config.get("protocol") != RETRIEVAL_PROTOCOL:
        raise ValueError("Retrieval config must declare the held_out_query_relevance protocol")
    return config


def freeze_digests(config: Dict[str, Any], data_dir: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for source in config["sources"]:
        split = load_any(source, data_dir)
        out[source["id"]] = {
            "queries": len(split.queries),
            "documents": len(split.doc_ids),
            "digest": split_digest(split),
        }
    return out


def _qrels_provenance(
    source: Dict[str, Any],
    data_dir: Path,
    partition_entries: Dict[str, Any],
    split: RetrievalSplit,
    verify_hashes: bool,
) -> Tuple[Path, Optional[str], Any, Dict[str, Any]]:
    """Checks a qrels source against the acquisition manifest and its training exposure."""
    data_dir = Path(data_dir)
    acquisition = json.loads((data_dir.parent / "acquisition_manifest.json").read_text("utf-8"))
    entry = next(
        (d for d in acquisition["datasets"] if d["dataset_id"] == source["manifest_id"]), None
    )
    if entry is None or entry.get("acquisition_status") not in ("VERIFIED", "DOWNLOADED"):
        raise ValueError(f"{source['manifest_id']}: dataset is not acquired")
    base = data_dir.parent / "raw" / source["raw_dir"]
    recorded = {f["filename"]: f["sha256"] for f in entry["files"]}
    hashes: Dict[str, str] = {}
    for key in ("corpus_file", "queries_file", "qrels_file"):
        name = source[key]
        hashes[name] = recorded[name]
        if verify_hashes and file_sha256(base / name) != recorded[name]:
            raise ValueError(f"{base / name}: SHA-256 differs from the acquisition manifest")
    train_path = base / source["train_qrels_file"]
    with open(train_path, encoding="utf-8", newline="") as handle:
        train_rows = list(csv.DictReader(handle, delimiter="\t"))
    train_queries = {r["query-id"] for r in train_rows}
    train_docs = {r["corpus-id"] for r in train_rows if float(r["score"]) > 0}
    test_docs = {d for q in split.queries for d in (q.relevant_doc, *q.also_relevant)}
    query_overlap = train_queries & {q.query_id for q in split.queries}
    if query_overlap:
        raise ValueError(f"{source['id']}: test queries also occur in the train qrels")
    if source["manifest_id"] in partition_entries:
        raise ValueError(f"{source['id']}: dataset also appears in the training partitions")
    isolation = {
        "train_query_overlap": 0,
        "train_relevant_document_overlap": len(train_docs & test_docs),
        "test_relevant_documents": len(test_docs),
        "partitioned_for_training": False,
        "note": "claims are disjoint; the corpus is shared by design and is not training data",
    }
    return base / source["qrels_file"], None, hashes[source["qrels_file"]], isolation


def _parallel_provenance(
    source: Dict[str, Any],
    data_dir: Path,
    partition_entries: Dict[str, Any],
    split: RetrievalSplit,
    verify_hashes: bool,
) -> Tuple[Path, Optional[str], Any, Dict[str, Any]]:
    """Checks a translation-pair source against its manifest and its training exposure."""
    data_dir = Path(data_dir)
    path = data_dir.parent / source["parquet"]
    manifest = json.loads((data_dir.parent / source["manifest_file"]).read_text("utf-8"))
    if verify_hashes and file_sha256(path) != manifest["sha256"]:
        raise ValueError(f"{path}: SHA-256 differs from its manifest")
    if source["manifest_id"] in partition_entries:
        raise ValueError(f"{source['id']}: dataset also appears in the training partitions")
    isolation = {
        "partitioned_for_training": False,
        "manifest_status": manifest.get("status"),
        "sampled_rows": len(split.queries),
        "note": "machine-translated pairs; relevance by construction, not human judgement",
    }
    return path, None, manifest["sha256"], isolation


def build_report(
    config: Dict[str, Any],
    data_dir: Path,
    embed: Callable[[Sequence[str]], np.ndarray],
    seed: int = 42,
    verify_hashes: bool = True,
) -> Dict[str, Any]:
    data_dir = Path(data_dir)
    manifest_path = data_dir / "task_splits_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {e["dataset_id"]: e for e in manifest["partitioned_datasets"]}
    splits = {s["id"]: load_any(s, data_dir) for s in config["sources"]}
    digests = {
        sid: {"queries": len(sp.queries), "documents": len(sp.doc_ids), "digest": split_digest(sp)}
        for sid, sp in splits.items()
    }
    verify_frozen(config, digests)  # nothing is scored against an unfrozen or altered benchmark
    rows: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    for source in config["sources"]:
        split = splits[source["id"]]
        if source.get("kind") == "qrels":
            path, actual, file_hash, isolation = _qrels_provenance(
                source, data_dir, entries, split, verify_hashes
            )
        elif source.get("kind") == "parallel":
            path, actual, file_hash, isolation = _parallel_provenance(
                source, data_dir, entries, split, verify_hashes
            )
        else:
            entry = entries.get(source["manifest_id"])
            if entry is None or not entry.get("leakage_verified"):
                raise ValueError(f"{source['manifest_id']}: split isolation is not verified")
            path = data_dir / source["dataset_dir"] / f"{source['split']}.parquet"
            actual = file_sha256(path) if verify_hashes else None
            if actual is not None and actual != entry["sha256"][source["split"]]:
                raise ValueError(f"{path}: SHA-256 differs from the partition manifest")
            file_hash = actual or entry["sha256"][source["split"]]
            isolation = isolation_checks(split, source, data_dir)
            if isolation["train_title_overlap"] or isolation["train_paragraph_overlap"]:
                raise ValueError(f"{source['id']}: held-out split overlaps the training split")
        evaluation = evaluate_split(split, source, config, embed, seed)
        evaluation.pop("_ranks")
        rows.append(gate_row(split, source, config, evaluation))
        sources.append(
            {
                "id": source["id"],
                "language": split.language,
                "domain": source.get("domain"),
                "file": str(path),
                "file_sha256": file_hash,
                "frozen": digests[source["id"]],
                "isolation": isolation,
                **evaluation,
            }
        )
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_id": config["benchmark_id"],
        "split": "test",
        "datasets": rows,
        "sources": sources,
        "relevance": "human-written question for its source paragraph (dataset labels); "
        "no relevance judgment was generated or edited",
        "hard_negatives": "other paragraphs of the same article",
        "tie_policy": "pessimistic: the relevant document ranks below all equal scores",
        "dataset_manifest_sha256": file_sha256(manifest_path),
        "split_isolation_checked": True,
        "seed": seed,
        "config_sha256": None,
    }


# ----------------------------------------------------------------------------- command line
def _embedder(checkpoint: Path, tokenizer_model: Path, device: Optional[str]) -> Tuple[Any, Any]:
    from laris.model.inference.loader import load_encoder
    from laris.model.inference.predictor import LanguageEncoderPredictor

    encoder = load_encoder(checkpoint, tokenizer_model, device=device)
    encoder.model.eval()
    return LanguageEncoderPredictor(encoder).embed, encoder


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Foundation retrieval benchmark")
    parser.add_argument("command", choices=["freeze", "run"])
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument(
        "--config", type=Path, default=Path("configs/evaluation/foundation_retrieval.yaml")
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--tokenizer-model", type=Path)
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("reports/retrieval/foundation.json"))
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "freeze":
        print(yaml.safe_dump({"frozen": freeze_digests(config, args.data_dir)}, sort_keys=False))
        return 0
    if not args.checkpoint or not args.tokenizer_model:
        print("[ERROR] run needs --checkpoint and --tokenizer-model", file=sys.stderr)
        return 2
    embed, encoder = _embedder(args.checkpoint, args.tokenizer_model, args.device)
    report = build_report(config, args.data_dir, embed, args.seed)
    report.update(
        checkpoint=str(args.checkpoint),
        model_sha256=encoder.manifest["model_sha256"],
        tokenizer_sha256=encoder.manifest["provenance"].get("tokenizer_sha256"),
        config_sha256=file_sha256(args.config),
        git_commit=current_git_commit(),
        training_executed=False,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for row in report["datasets"]:
        m, b = row["metrics"], row["baseline"]
        print(
            f"{row['protocol_details']['source']}: dense MRR {m['mrr']:.4f} vs BM25 "
            f"{b['mrr']:.4f}; hybrid {m['hybrid_mrr']:.4f} ({row['samples']} queries)"
        )
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
