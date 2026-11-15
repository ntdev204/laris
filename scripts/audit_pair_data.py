#!/usr/bin/env python3
"""Pair-task data audit by counting (T193). No model, no training, no optimizer step.

Reads the processed pair-task splits (the sources the loader feeds today), the raw candidate
sources acquired in T192 and the MLM shards, and writes one JSON of counts:

* per source and split: rows, label prior, token length of each segment and the share the
  loader cuts at each sequence length (the `build_sequence` rule: first segment at most
  (L - 3) // 2 tokens, second segment the rest);
* exact duplicates within and across sources, overlap of training rows with every held-out
  split of the task, segment-level overlap (premise or sentence) and sentence overlap with
  STS-B validation and test; VitaminC against FEVER through `FEVER_id`;
* shortcut measures without a neural model: word-overlap AUC against the paraphrase label,
  word-overlap Spearman against the similarity score, source-only and hypothesis-only
  (count-based naive Bayes) NLI baselines, and for QA the share of rows that are unanswerable
  or whose answer lies outside the window;
* supply for the new objectives: MLM documents with at least two passages and consecutive
  passage pairs (T194), NLI and paraphrase positives and hard negatives (T197), sentence
  pairs within one passage.

Usage (tokenizer encoding only, no fitting):
    .venv/bin/python -I scripts/audit_pair_data.py \
        --tokenizer artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model \
        --out reports/verification/T193-pair-data-audit.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from laris.shared.language.loading.dataloader import TASK_DATASET_DIRS  # noqa: E402

SPLITS = ("train", "val", "test")
HELD_OUT = ("val", "test")
NLI_CLASSES = ("entailment", "neutral", "contradiction")
VITAMINC_LABELS = {
    "SUPPORTS": "entailment",
    "REFUTES": "contradiction",
    "NOT ENOUGH INFO": "neutral",
}
NEGATION = frozenset(
    {"not", "no", "never", "nobody", "nothing", "none", "nowhere", "cannot", "n't"}
)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_WORD = re.compile(r"[a-z0-9]+|n't")
# Sentence boundary inside an MLM passage (RE2 syntax for pyarrow.compute).
SENTENCE_BOUNDARY = r"[.!?][\"'\)\]\x{201D}\x{2019}]*\s+[\"'\x{201C}]?[A-Z]"
PARAGRAPH_BOUNDARY = r"\n\s*\n"


# --------------------------------------------------------------------------- text keys


def normalise(text: str) -> str:
    """Lower-case, keep letters and digits only (same rule as scripts/check_sts_leakage.py)."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def words(text: str) -> List[str]:
    return _WORD.findall((text or "").lower().replace("’", "'"))


def digest(text: str) -> int:
    """Stable 63-bit hash of a normalised string (deterministic across runs)."""
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big") >> 1


def pair_key(a: str, b: str, ordered: bool) -> int:
    x, y = normalise(a), normalise(b)
    if not ordered and y < x:
        x, y = y, x
    return digest(f"{x}\x1f{y}")


def jaccard(a: str, b: str) -> float:
    sa, sb = set(words(a)), set(words(b))
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


# --------------------------------------------------------------------------- statistics


def average_ranks(x: Sequence[float]) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """ROC AUC by the Mann-Whitney U statistic with tied scores counted as one half."""
    y = np.asarray(labels, dtype=int)
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if n_pos == 0 or n_neg == 0:
        return None
    r = average_ranks(scores)
    return float((r[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 2:
        return None
    ra, rb = average_ranks(a), average_ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def macro_f1(gold: Sequence[str], pred: Sequence[str], classes: Sequence[str]) -> float:
    scores = []
    for c in classes:
        tp = sum(1 for g, p in zip(gold, pred) if g == c and p == c)
        fp = sum(1 for g, p in zip(gold, pred) if g != c and p == c)
        fn = sum(1 for g, p in zip(gold, pred) if g == c and p != c)
        scores.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(sum(scores) / len(scores))


def accuracy(gold: Sequence[str], pred: Sequence[str]) -> float:
    return float(sum(1 for g, p in zip(gold, pred) if g == p) / len(gold)) if gold else 0.0


def length_summary(lengths: np.ndarray) -> Dict[str, float]:
    if len(lengths) == 0:
        return {}
    return {
        "mean": round(float(lengths.mean()), 1),
        "p50": float(np.percentile(lengths, 50)),
        "p95": float(np.percentile(lengths, 95)),
        "p99": float(np.percentile(lengths, 99)),
        "max": int(lengths.max()),
    }


def prior(labels: Iterable[str]) -> Dict[str, Any]:
    counts = Counter(labels)
    total = sum(counts.values())
    return (
        {k: {"rows": v, "share": round(v / total, 4)} for k, v in sorted(counts.items())}
        if total
        else {}
    )


# --------------------------------------------------------------------------- loader rules


def pair_cut(len_a: np.ndarray, len_b: np.ndarray, seq_len: int) -> Dict[str, float]:
    """Shares the loader truncates under `build_sequence` (first at (L-3)//2, second the rest)."""
    max_inner = max(0, seq_len - 3)
    first_cap = max_inner // 2
    kept_a = np.minimum(len_a, first_cap)
    cut_a = len_a > first_cap
    cut_b = len_b > (max_inner - kept_a)
    n = max(1, len(len_a))
    return {
        "first_cut": round(float(cut_a.sum()) / n, 4),
        "second_cut": round(float(cut_b.sum()) / n, 4),
        "any_cut": round(float((cut_a | cut_b).sum()) / n, 4),
    }


def qa_answer_window(q_len: int, prefix_len: int, answer_len: int, seq_len: int) -> bool:
    """True when the answer span ends inside the window (the `_locate_answer_span` rule)."""
    max_inner = max(0, seq_len - 3)
    question_len = min(q_len, max_inner // 2)
    context_offset = 1 + question_len + 1
    context_limit = min(seq_len - 1, context_offset + (max_inner - question_len))
    end_pos = context_offset + prefix_len + answer_len - 1
    return answer_len > 0 and end_pos < context_limit


# --------------------------------------------------------------------------- NLI baselines


@dataclass
class NaiveBayes:
    """Multinomial naive Bayes on word unigrams with add-one smoothing (a counting baseline)."""

    classes: Tuple[str, ...] = NLI_CLASSES
    class_rows: Counter = field(default_factory=Counter)
    word_counts: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    class_words: Counter = field(default_factory=Counter)
    vocab: set = field(default_factory=set)

    def fit(self, texts: Iterable[List[str]], labels: Iterable[str]) -> "NaiveBayes":
        for toks, lab in zip(texts, labels):
            self.class_rows[lab] += 1
            self.word_counts[lab].update(toks)
            self.class_words[lab] += len(toks)
            self.vocab.update(toks)
        return self

    def predict(self, toks: List[str]) -> str:
        total = sum(self.class_rows.values())
        v = len(self.vocab) + 1
        best, best_score = self.classes[0], -math.inf
        for c in self.classes:
            if not self.class_rows[c]:
                continue
            score = math.log(self.class_rows[c] / total)
            denom = math.log(self.class_words[c] + v)
            wc = self.word_counts[c]
            for t in toks:
                score += math.log(wc.get(t, 0) + 1) - denom
            if score > best_score:
                best, best_score = c, score
        return best


def majority(labels: Iterable[str]) -> str:
    counts = Counter(labels)
    return max(sorted(counts), key=lambda k: counts[k]) if counts else NLI_CLASSES[0]


def nli_baselines(
    train: Dict[str, Tuple[List[str], List[str]]], val: Dict[str, Tuple[List[str], List[str]]]
) -> Dict[str, Any]:
    """`train`/`val` map source -> (hypotheses, labels). Returns per-source and pooled baselines."""
    pooled_train = [lab for _, (_, labs) in sorted(train.items()) for lab in labs]
    global_major = majority(pooled_train)
    pooled_nb = NaiveBayes()
    for src, (hyps, labs) in sorted(train.items()):
        pooled_nb.fit((words(h) for h in hyps), labs)
    with_source = NaiveBayes()
    for src, (hyps, labs) in sorted(train.items()):
        with_source.fit(([f"__source__{src}"] + words(h) for h in hyps), labs)
    out: Dict[str, Any] = {"global_majority_class": global_major, "per_source": {}}
    gold_all, by = [], defaultdict(list)
    for src, (hyps, labs) in sorted(val.items()):
        if src not in train or not labs:
            continue
        src_major = majority(train[src][1])
        own_nb = NaiveBayes().fit((words(h) for h in train[src][0]), train[src][1])
        preds = {
            "global_majority": [global_major] * len(labs),
            "source_majority": [src_major] * len(labs),
            "hypothesis_only_own": [own_nb.predict(words(h)) for h in hyps],
            "hypothesis_only_pooled": [pooled_nb.predict(words(h)) for h in hyps],
            "hypothesis_plus_source_pooled": [
                with_source.predict([f"__source__{src}"] + words(h)) for h in hyps
            ],
        }
        out["per_source"][src] = {
            "val_rows": len(labs),
            "source_majority_class": src_major,
            **{
                name: {
                    "accuracy": round(accuracy(labs, p), 4),
                    "macro_f1": round(macro_f1(labs, p, NLI_CLASSES), 4),
                }
                for name, p in preds.items()
            },
        }
        gold_all.extend(labs)
        for name, p in preds.items():
            by[name].extend(p)
    out["pooled_val"] = {
        "rows": len(gold_all),
        **{
            name: {
                "accuracy": round(accuracy(gold_all, p), 4),
                "macro_f1": round(macro_f1(gold_all, p, NLI_CLASSES), 4),
            }
            for name, p in by.items()
        },
    }
    return out


def negation_cue(hyps: List[str], labels: List[str]) -> Dict[str, Any]:
    flagged = [lab for h, lab in zip(hyps, labels) if NEGATION.intersection(words(h))]
    return {
        "rows_with_negation": len(flagged),
        "share_of_rows": round(len(flagged) / max(1, len(labels)), 4),
        "label_prior_given_negation": prior(flagged),
    }


def nli_triplets(premises: List[str], labels: List[str]) -> Dict[str, int]:
    """Premises with both an entailment and a contradiction hypothesis (SimCSE-style triplets)."""
    seen: Dict[int, set] = defaultdict(set)
    for p, lab in zip(premises, labels):
        seen[digest(normalise(p))].add(lab)
    return {
        "distinct_premises": len(seen),
        "premises_with_entailment_and_contradiction": sum(
            1 for s in seen.values() if "entailment" in s and "contradiction" in s
        ),
    }


# --------------------------------------------------------------------------- MLM supply


def passage_id(row_id: str) -> Tuple[str, int]:
    """`doc#k` -> (doc, k); ids without '#' are one-passage documents."""
    doc, sep, num = str(row_id).rpartition("#")
    if sep and num.isdigit():
        return doc, int(num)
    return str(row_id), 0


class PassageRuns:
    """Streams passage ids in file order and counts documents and consecutive passage pairs."""

    def __init__(self) -> None:
        self.rows = 0
        self.runs = 0
        self.multi_runs = 0
        self.consecutive_pairs = 0
        self._doc: Optional[str] = None
        self._num = -2
        self._run_len = 0
        self._doc_hashes: List[int] = []

    def _close(self) -> None:
        if self._doc is not None:
            self.runs += 1
            self._doc_hashes.append(digest(self._doc))
            if self._run_len >= 2:
                self.multi_runs += 1

    def add(self, row_id: str) -> None:
        doc, num = passage_id(row_id)
        self.rows += 1
        if doc == self._doc:
            self._run_len += 1
            if num == self._num + 1:
                self.consecutive_pairs += 1
        else:
            self._close()
            self._doc, self._run_len = doc, 1
        self._num = num

    def result(self) -> Dict[str, int]:
        self._close()
        self._doc = None
        distinct = (
            int(np.unique(np.asarray(self._doc_hashes, dtype=np.int64)).size)
            if self._doc_hashes
            else 0
        )
        return {
            "passages": self.rows,
            "documents": distinct,
            "documents_contiguous": distinct == self.runs,
            "documents_with_two_or_more_passages": self.multi_runs,
            "consecutive_passage_pairs": self.consecutive_pairs,
        }


def mlm_text_counts(texts: pa.Array) -> Dict[str, int]:
    sentences = pc.count_substring_regex(texts, SENTENCE_BOUNDARY).to_numpy(zero_copy_only=False)
    paragraphs = pc.count_substring_regex(texts, PARAGRAPH_BOUNDARY).to_numpy(zero_copy_only=False)
    return {
        "passages_with_two_or_more_sentences": int((sentences >= 1).sum()),
        "adjacent_sentence_pairs": int(sentences.sum()),
        "passages_with_two_or_more_paragraphs": int((paragraphs >= 1).sum()),
    }


def audit_mlm_source(files: Dict[str, Path], text_scan: bool, batch_rows: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for split, path in files.items():
        runs = PassageRuns()
        text: Counter = Counter()
        columns = ["id", "text"] if text_scan else ["id"]
        for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_rows, columns=columns):
            for rid in batch.column("id").to_pylist():
                runs.add(rid)
            if text_scan:
                text.update(mlm_text_counts(batch.column("text")))
        out[split] = {**runs.result(), **dict(text)}
    return out


# --------------------------------------------------------------------------- sources


@dataclass
class PairRows:
    a: List[str]
    b: List[str]
    labels: List[Any]
    extra: Dict[str, List[Any]] = field(default_factory=dict)


@dataclass
class QARows:
    questions: List[str]
    contexts: List[str]
    answers: List[Optional[str]]
    starts: List[Optional[int]]  # None: no offset in the source, located by search


def read_table(path: Path, columns: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if path.suffix == ".parquet":
        return pq.read_table(path, columns=columns).to_pylist()
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
        return [json.loads(line) for line in handle if line.strip()]


def nli_from_rows(rows: List[Dict[str, Any]]) -> PairRows:
    a, b, labels = [], [], []
    for r in rows:
        a.append(r.get("premise") or r.get("sentence1") or "")
        b.append(r.get("hypothesis") or r.get("sentence2") or "")
        labels.append(str(r.get("label")))
    return PairRows(a, b, labels)


def vitaminc_from_rows(rows: List[Dict[str, Any]]) -> PairRows:
    a, b, labels, fever_ids = [], [], [], []
    for r in rows:
        a.append(r.get("evidence") or "")
        b.append(r.get("claim") or "")
        labels.append(VITAMINC_LABELS[r["label"]])
        fever_ids.append(str(r.get("FEVER_id") or ""))
    return PairRows(a, b, labels, {"fever_id": fever_ids})


def para_from_rows(rows: List[Dict[str, Any]]) -> PairRows:
    a, b, labels = [], [], []
    for r in rows:
        a.append(r.get("sentence1") or r.get("question1") or "")
        b.append(r.get("sentence2") or r.get("question2") or "")
        labels.append(int(str(r.get("label") if "label" in r else r.get("is_duplicate"))))
    return PairRows(a, b, labels)


def sim_from_rows(rows: List[Dict[str, Any]]) -> PairRows:
    a, b, labels = [], [], []
    for r in rows:
        score = float(r.get("score") if "score" in r else r.get("similarity_score"))
        a.append(r.get("sentence1") or "")
        b.append(r.get("sentence2") or "")
        labels.append(score / 5.0 if score > 1.0 else score)
    return PairRows(a, b, labels)


def _first(seq: Any) -> Optional[Any]:
    return seq[0] if isinstance(seq, (list, tuple)) and seq else None


def squad_from_rows(rows: List[Dict[str, Any]]) -> QARows:
    q, c, ans, st = [], [], [], []
    for r in rows:
        a = r.get("answers") or {}
        q.append(r.get("question") or "")
        c.append(r.get("context") or "")
        ans.append(_first(a.get("text")) or None)
        s = _first(a.get("answer_start"))
        st.append(int(s) if s is not None else None)
    return QARows(q, c, ans, st)


def ropes_from_rows(rows: List[Dict[str, Any]]) -> QARows:
    q, c, ans = [], [], []
    for r in rows:
        q.append(r.get("question") or "")
        c.append(f"{r.get('background') or ''}\n{r.get('situation') or ''}")
        ans.append(_first((r.get("answers") or {}).get("text")) or None)
    return QARows(q, c, ans, [None] * len(q))


def duorc_from_rows(rows: List[Dict[str, Any]]) -> QARows:
    q, c, ans = [], [], []
    for r in rows:
        q.append(r.get("question") or "")
        c.append(r.get("plot") or "")
        ans.append(None if r.get("no_answer") else (_first(list(r.get("answers") or [])) or None))
    return QARows(q, c, ans, [None] * len(q))


def drop_from_rows(rows: List[Dict[str, Any]]) -> QARows:
    q, c, ans = [], [], []
    for r in rows:
        spans = r.get("answers_spans") or {}
        q.append(r.get("question") or "")
        c.append(r.get("passage") or "")
        ans.append(_first(spans.get("spans")) or None)
    return QARows(q, c, ans, [None] * len(q))


@dataclass
class Source:
    name: str
    task: str  # nli | paraphrase | similarity | qa
    files: Dict[str, List[Path]]
    adapter: Callable[[List[Dict[str, Any]]], Any]
    status: str  # "in_mixture" (fed by the loader today) or "candidate" (raw, T192)
    note: str = ""


TASK_ADAPTERS = {
    "nli": nli_from_rows,
    "paraphrase": para_from_rows,
    "similarity": sim_from_rows,
    "qa": squad_from_rows,
}


def processed_sources(processed: Path) -> List[Source]:
    out = []
    for task in ("nli", "paraphrase", "similarity", "qa"):
        for d in TASK_DATASET_DIRS[task]:
            files = {
                s: [processed / d / f"{s}.parquet"]
                for s in SPLITS
                if (processed / d / f"{s}.parquet").exists()
            }
            if files:
                out.append(Source(d, task, files, TASK_ADAPTERS[task], "in_mixture"))
    return out


def candidate_sources(raw: Path) -> List[Source]:
    def f(*names: str) -> List[Path]:
        return [raw / n for n in names if (raw / n).exists()]

    specs = [
        Source(
            "vitaminc_en",
            "nli",
            {
                "train": f("vitaminc_en/train.jsonl"),
                "val": f("vitaminc_en/dev.jsonl"),
                "test": f("vitaminc_en/test.jsonl"),
            },
            vitaminc_from_rows,
            "candidate",
            "claim = second segment, evidence = first; carries the BIG-bench canary",
        ),
        Source(
            "paws_swap_en",
            "paraphrase",
            {"train": f("paws_swap_en/train-00000-of-00001.parquet")},
            para_from_rows,
            "candidate",
        ),
        Source(
            "paws_unlabeled_en",
            "paraphrase",
            {
                "train": f("paws_unlabeled_en/train-00000-of-00001.parquet"),
                "val": f("paws_unlabeled_en/validation-00000-of-00001.parquet"),
            },
            para_from_rows,
            "candidate",
            "labels assigned by a classifier (label_source: model)",
        ),
        Source(
            "quoref_en",
            "qa",
            {
                "train": f("quoref_en/train__0000.parquet"),
                "val": f("quoref_en/validation__0000.parquet"),
            },
            squad_from_rows,
            "candidate",
        ),
        Source(
            "ropes_en",
            "qa",
            {
                "train": f("ropes_en/train-00000-of-00001.parquet"),
                "val": f("ropes_en/validation-00000-of-00001.parquet"),
                "test": f("ropes_en/test-00000-of-00001.parquet"),
            },
            ropes_from_rows,
            "candidate",
            "context = background + situation; no offsets, located by search",
        ),
        Source(
            "drop_en",
            "qa",
            {
                "train": f("drop_en/train-00000-of-00001.parquet"),
                "val": f("drop_en/validation-00000-of-00001.parquet"),
            },
            drop_from_rows,
            "candidate",
            "first gold span; numbers and dates are often not verbatim in the passage",
        ),
    ]
    for part in ("ParaphraseRC", "SelfRC"):
        specs.append(
            Source(
                f"duorc_{part.lower()}_en",
                "qa",
                {
                    "train": f(f"duorc_en/{part}__train-00000-of-00001.parquet"),
                    "val": f(f"duorc_en/{part}__validation-00000-of-00001.parquet"),
                    "test": f(f"duorc_en/{part}__test-00000-of-00001.parquet"),
                },
                duorc_from_rows,
                "candidate",
                "no offsets, located by search; no_answer rows count as unanswerable",
            )
        )
    return [s for s in specs if any(s.files.values())]


# --------------------------------------------------------------------------- tokenizer


class Encoder:
    """Token lengths from a SentencePiece model (encoding only) or any batch `encode`."""

    def __init__(self, encode: Callable[[List[str]], List[List[int]]], chunk: int = 20000) -> None:
        self._encode = encode
        self._chunk = chunk

    @classmethod
    def sentencepiece(cls, model: Path) -> "Encoder":
        import sentencepiece as spm

        sp = spm.SentencePieceProcessor(model_file=str(model))
        return cls(lambda texts: sp.encode(texts, out_type=int, num_threads=-1))

    def lengths(self, texts: List[str]) -> np.ndarray:
        out = np.zeros(len(texts), dtype=np.int64)
        for i in range(0, len(texts), self._chunk):
            piece = texts[i : i + self._chunk]
            out[i : i + len(piece)] = [
                len(t) if s else 0 for s, t in zip(piece, self._encode(piece))
            ]
        return out


# --------------------------------------------------------------------------- audits


def audit_pairs(
    task: str, rows: PairRows, enc: Encoder, seq_lens: Sequence[int], neg_threshold: float
) -> Dict[str, Any]:
    la, lb = enc.lengths(rows.a), enc.lengths(rows.b)
    out: Dict[str, Any] = {
        "rows": len(rows.labels),
        "first_segment_tokens": length_summary(la),
        "second_segment_tokens": length_summary(lb),
        "cut": {str(L): pair_cut(la, lb, L) for L in seq_lens},
        "empty_segment_rows": int(
            sum(1 for x, y in zip(rows.a, rows.b) if not x.strip() or not y.strip())
        ),
    }
    if task == "similarity":
        y = np.asarray(rows.labels, dtype=float)
        out["label"] = {
            "mean": round(float(y.mean()), 4),
            "std": round(float(y.std()), 4),
            "histogram_0_to_1_by_0.2": np.histogram(y, bins=5, range=(0, 1))[0].tolist(),
        }
        out["word_overlap_spearman"] = _round(
            spearman([jaccard(a, b) for a, b in zip(rows.a, rows.b)], y)
        )
    else:
        out["label_prior"] = prior(str(v) for v in rows.labels)
    if task == "paraphrase":
        overlap = [jaccard(a, b) for a, b in zip(rows.a, rows.b)]
        out["word_overlap_auc"] = _round(auc(overlap, rows.labels))
        out["supply"] = {
            "positives": int(sum(rows.labels)),
            "negatives": int(len(rows.labels) - sum(rows.labels)),
            f"hard_negatives_jaccard_ge_{neg_threshold}": int(
                sum(1 for o, lab in zip(overlap, rows.labels) if lab == 0 and o >= neg_threshold)
            ),
        }
    if task == "nli":
        out["negation_cue"] = negation_cue(rows.b, rows.labels)
        out["supply"] = {
            "entailment_positives": rows.labels.count("entailment"),
            "contradiction_negatives": rows.labels.count("contradiction"),
            **nli_triplets(rows.a, rows.labels),
        }
    return out


def locate(context: str, answer: Optional[str], start: Optional[int]) -> Tuple[str, int]:
    """('none'|'offset'|'found'|'not_found'|'bad_offset', char start)."""
    if not answer:
        return "none", -1
    if start is not None:
        return (
            ("offset", start)
            if context[start : start + len(answer)] == answer
            else ("bad_offset", -1)
        )
    pos = context.find(answer)
    return ("found", pos) if pos >= 0 else ("not_found", -1)


def audit_qa(rows: QARows, enc: Encoder, seq_lens: Sequence[int]) -> Dict[str, Any]:
    n = len(rows.questions)
    kinds, char_starts = (
        zip(*[locate(c, a, s) for c, a, s in zip(rows.contexts, rows.answers, rows.starts)])
        if n
        else ((), ())
    )
    lq = enc.lengths(rows.questions)
    lc = enc.lengths(rows.contexts)
    usable = [i for i, k in enumerate(kinds) if k in ("offset", "found")]
    prefix = enc.lengths([rows.contexts[i][: char_starts[i]] for i in usable])
    alen = enc.lengths([rows.answers[i] or "" for i in usable])
    k = Counter(kinds)
    answer_in_question = sum(
        1
        for i, kind in enumerate(kinds)
        if kind == "not_found" and rows.answers[i] and rows.answers[i] in rows.questions[i]
    )
    windows = {}
    for L in seq_lens:
        inside = sum(
            1
            for j, i in enumerate(usable)
            if qa_answer_window(int(lq[i]), int(prefix[j]), int(alen[j]), L)
        )
        windows[str(L)] = {
            "answer_outside_window": len(usable) - inside,
            "share_of_rows_outside_window": round((len(usable) - inside) / max(1, n), 4),
            "share_of_rows_trained_on_cls": round((n - inside) / max(1, n), 4),
            **pair_cut(lq, lc, L),
        }
    return {
        "rows": n,
        "question_tokens": length_summary(lq),
        "context_tokens": length_summary(lc),
        "unanswerable": k["none"],
        "unanswerable_share": round(k["none"] / max(1, n), 4),
        "answer_by_offset": k["offset"],
        "answer_located_by_search": k["found"],
        "answer_not_in_context": k["not_found"],
        "answer_not_in_context_but_in_question": answer_in_question,
        "bad_offset": k["bad_offset"],
        "window": windows,
        "empty_answer_baseline_f1": round(k["none"] / max(1, n), 4),
    }


def _round(x: Optional[float], d: int = 4) -> Optional[float]:
    return None if x is None else round(x, d)


# --------------------------------------------------------------------------- overlap


def unique(a: Iterable[int]) -> np.ndarray:
    return np.unique(np.fromiter(a, dtype=np.int64))


def overlap_counts(
    keys: Dict[Tuple[str, str], np.ndarray],
    segments: Dict[Tuple[str, str], Dict[str, np.ndarray]],
    status: Dict[str, str],
) -> Dict[str, Any]:
    """Row counts of exact-pair and segment overlap within a task.

    `keys[(source, split)]` holds one pair hash per row; `segments[(source, split)][name]` one
    hash per row for a segment (e.g. premise).
    Held-out = val and test of the sources in the mixture.
    """
    uniq = {k: np.unique(v) for k, v in keys.items()}
    held = [k for k in keys if k[1] in HELD_OUT and status[k[0]] == "in_mixture"]
    held_union = (
        np.unique(np.concatenate([uniq[k] for k in held])) if held else np.array([], dtype=np.int64)
    )
    out: Dict[str, Any] = {}
    for (src, split), v in sorted(keys.items()):
        entry: Dict[str, Any] = {
            "rows": int(v.size),
            "duplicate_rows_within_split": int(v.size - uniq[(src, split)].size),
        }
        if split == "train" or status[src] == "candidate":
            entry["rows_in_any_held_out_split"] = int(np.isin(v, held_union).sum())
            entry["rows_by_held_out_split"] = {
                f"{h[0]}/{h[1]}": c
                for h in held
                if h != (src, split) and (c := int(np.isin(v, uniq[h]).sum()))
            }
        others = [uniq[k] for k in keys if k[0] != src]
        entry["rows_in_other_sources"] = (
            int(np.isin(v, np.unique(np.concatenate(others))).sum()) if others else 0
        )
        seg = segments.get((src, split), {})
        if seg and (split == "train" or status[src] == "candidate"):
            entry["segment_rows_in_held_out"] = {}
            for name, hv in seg.items():
                pool = [
                    np.unique(segments[h][name])
                    for h in held
                    if h != (src, split) and name in segments.get(h, {})
                ]
                if pool:
                    entry["segment_rows_in_held_out"][name] = int(
                        np.isin(hv, np.unique(np.concatenate(pool))).sum()
                    )
        out[f"{src}/{split}"] = entry
    return out


def sentence_hashes(texts: Iterable[str]) -> np.ndarray:
    return np.fromiter((digest(normalise(t)) for t in texts), dtype=np.int64)


# --------------------------------------------------------------------------- driver


def load(source: Source) -> Dict[str, Any]:
    return {
        split: source.adapter([r for p in paths for r in read_table(p)])
        for split, paths in source.files.items()
        if paths
    }


def fever_crosscheck(
    vitaminc: Dict[str, PairRows], fever_raw: Path, fever_processed: Dict[str, PairRows]
) -> Dict[str, Any]:
    """VitaminC rows with a FEVER_id, mapped to FEVER claims and matched to processed FEVER."""
    claims: Dict[str, str] = {}
    for path in sorted(fever_raw.glob("v1.0__*.parquet")):
        for r in pq.read_table(path, columns=["id", "claim"]).to_pylist():
            claims.setdefault(str(r["id"]), r["claim"])
    fever_hyp = {s: set(normalise(h) for h in rows.b) for s, rows in fever_processed.items()}
    out: Dict[str, Any] = {"fever_claims_with_id": len(claims)}
    for split, rows in vitaminc.items():
        ids = rows.extra["fever_id"]
        with_id = [i for i, f in enumerate(ids) if f]
        mapped = [i for i in with_id if ids[i] in claims]
        claim_norm = [normalise(rows.b[i]) for i in range(len(rows.b))]
        entry = {
            "rows": len(ids),
            "rows_with_fever_id": len(with_id),
            "fever_id_found_in_raw_fever": len(mapped),
            "fever_claim_equals_vitaminc_claim": sum(
                1 for i in mapped if normalise(claims[ids[i]]) == claim_norm[i]
            ),
        }
        for fs, hyp in fever_hyp.items():
            entry[f"fever_claim_in_processed_fever_{fs}"] = sum(
                1 for i in mapped if normalise(claims[ids[i]]) in hyp
            )
            entry[f"vitaminc_claim_in_processed_fever_{fs}"] = sum(
                1 for c in claim_norm if c in hyp
            )
        out[split] = entry
    return out


def run(args: argparse.Namespace, enc: Encoder) -> Dict[str, Any]:
    processed, raw = Path(args.processed), Path(args.raw)
    sources = processed_sources(processed) + ([] if args.no_candidates else candidate_sources(raw))
    status = {s.name: s.status for s in sources}
    report: Dict[str, Any] = {
        "task": "T193",
        "generated": time.strftime("%Y-%m-%d"),
        "tokenizer": str(args.tokenizer),
        "seq_lens": args.seq_len,
        "sources": {
            s.name: {
                "task": s.task,
                "status": s.status,
                "note": s.note,
                "files": {k: [str(p) for p in v] for k, v in s.files.items()},
            }
            for s in sources
        },
        "tasks": {},
    }
    loaded: Dict[str, Dict[str, Any]] = {}
    for task in ("nli", "paraphrase", "similarity", "qa"):
        task_sources = [s for s in sources if s.task == task]
        per: Dict[str, Any] = {}
        keys: Dict[Tuple[str, str], np.ndarray] = {}
        segs: Dict[Tuple[str, str], Dict[str, np.ndarray]] = {}
        for s in task_sources:
            t0 = time.time()
            data = load(s)
            loaded[s.name] = data
            per[s.name] = {}
            for split, rows in data.items():
                if task == "qa":
                    per[s.name][split] = audit_qa(rows, enc, args.seq_len)
                    keys[(s.name, split)] = np.fromiter(
                        (pair_key(q, c, True) for q, c in zip(rows.questions, rows.contexts)),
                        dtype=np.int64,
                    )
                    segs[(s.name, split)] = {
                        "question": sentence_hashes(rows.questions),
                        "context": sentence_hashes(rows.contexts),
                    }
                else:
                    per[s.name][split] = audit_pairs(
                        task, rows, enc, args.seq_len, args.hard_negative_jaccard
                    )
                    keys[(s.name, split)] = np.fromiter(
                        (pair_key(a, b, task == "nli") for a, b in zip(rows.a, rows.b)),
                        dtype=np.int64,
                    )
                    names = (
                        ("premise", "hypothesis") if task == "nli" else ("sentence1", "sentence2")
                    )
                    segs[(s.name, split)] = {
                        names[0]: sentence_hashes(rows.a),
                        names[1]: sentence_hashes(rows.b),
                    }
            print(
                f"[audit] {task}/{s.name}: {len(data)} splits in {time.time() - t0:.0f}s",
                flush=True,
            )
        report["tasks"][task] = {"sources": per, "overlap": overlap_counts(keys, segs, status)}
        if task == "nli":
            train = {
                s: (d["train"].b, d["train"].labels)
                for s, d in loaded.items()
                if status[s] == "in_mixture"
                and "train" in d
                and isinstance(d["train"], PairRows)
                and sources_task(sources, s) == "nli"
            }
            val = {
                s: (d["val"].b, d["val"].labels)
                for s, d in loaded.items()
                if status[s] == "in_mixture"
                and "val" in d
                and isinstance(d["val"], PairRows)
                and sources_task(sources, s) == "nli"
            }
            report["tasks"]["nli"]["baselines_mixture"] = nli_baselines(train, val)
            if "vitaminc_en" in loaded:
                train_v = dict(
                    train,
                    vitaminc_en=(
                        loaded["vitaminc_en"]["train"].b,
                        loaded["vitaminc_en"]["train"].labels,
                    ),
                )
                val_v = dict(
                    val,
                    vitaminc_en=(
                        loaded["vitaminc_en"]["val"].b,
                        loaded["vitaminc_en"]["val"].labels,
                    ),
                )
                report["tasks"]["nli"]["baselines_with_vitaminc"] = nli_baselines(train_v, val_v)
                if "fever" in loaded:
                    report["tasks"]["nli"]["vitaminc_fever"] = fever_crosscheck(
                        loaded["vitaminc_en"], raw / "fever", loaded["fever"]
                    )
    report["stsb_heldout_sentence_overlap"] = stsb_overlap(loaded, sources)
    if not args.no_mlm:
        report["mlm"] = {}
        for d in TASK_DATASET_DIRS["mlm"]:
            files = {
                s: processed / d / f"{s}.parquet"
                for s in ("train", "val")
                if (processed / d / f"{s}.parquet").exists()
            }
            if files:
                t0 = time.time()
                report["mlm"][d] = audit_mlm_source(
                    files, not args.no_mlm_text, args.mlm_batch_rows
                )
                print(f"[audit] mlm/{d} in {time.time() - t0:.0f}s", flush=True)
    return report


def sources_task(sources: List[Source], name: str) -> str:
    return next(s.task for s in sources if s.name == name)


def stsb_overlap(loaded: Dict[str, Dict[str, Any]], sources: List[Source]) -> Dict[str, Any]:
    """Rows of each pair source with a sentence in STS-B val or test (the G05 gate data)."""
    if "stsb" not in loaded:
        return {}
    gate = set()
    for split in HELD_OUT:
        rows = loaded["stsb"].get(split)
        if rows is not None:
            gate.update(normalise(t) for t in rows.a + rows.b)
    out: Dict[str, Any] = {"stsb_heldout_sentences": len(gate)}
    for s in sources:
        if s.task == "qa" or s.name == "stsb":
            continue
        for split, rows in loaded[s.name].items():
            hits = sum(
                1 for a, b in zip(rows.a, rows.b) if normalise(a) in gate or normalise(b) in gate
            )
            if hits or split == "train":
                out[f"{s.name}/{split}"] = hits
    return out


def default_seq_len() -> int:
    cfg = yaml.safe_load(
        (REPO_ROOT / "configs/language_encoder/english_r1.yaml").read_text(encoding="utf-8")
    )
    return int(cfg["model"]["max_sequence_length"])


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--tokenizer", required=True, type=Path, help="SentencePiece model (encoding only)"
    )
    p.add_argument("--processed", default=str(REPO_ROOT / "data/processed"))
    p.add_argument("--raw", default=str(REPO_ROOT / "data/raw"))
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--seq-len",
        type=int,
        nargs="+",
        default=None,
        help="window lengths for the cut shares (default: english_r1 max_sequence_length and 512)",
    )
    p.add_argument(
        "--hard-negative-jaccard",
        type=float,
        default=0.5,
        help="word-overlap threshold above which a paraphrase negative counts as hard",
    )
    p.add_argument(
        "--no-candidates", action="store_true", help="skip the raw T192 candidate sources"
    )
    p.add_argument("--no-mlm", action="store_true", help="skip the MLM shard scan")
    p.add_argument(
        "--no-mlm-text", action="store_true", help="count passages by id only (no sentence scan)"
    )
    p.add_argument("--mlm-batch-rows", type=int, default=65536)
    args = p.parse_args(argv)
    if args.seq_len is None:
        args.seq_len = sorted({default_seq_len(), 512}, reverse=True)
    report = run(args, Encoder.sentencepiece(args.tokenizer))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"[audit] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
