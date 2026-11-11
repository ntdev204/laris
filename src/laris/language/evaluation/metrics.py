"""Pure-NumPy metrics used to evaluate the language encoder."""

import re
import string
import unicodedata
from collections import Counter
from typing import Dict, Optional, Sequence, Tuple, Union

import numpy as np

IntArrayLike = Union[Sequence[int], np.ndarray]


def accuracy(pred: IntArrayLike, gold: IntArrayLike) -> float:
    pred_a, gold_a = np.asarray(pred), np.asarray(gold)
    return float((pred_a == gold_a).mean()) if len(gold_a) else 0.0


def f1_binary(pred: Sequence[int], gold: Sequence[int]) -> float:
    p, g = np.asarray(pred).astype(bool), np.asarray(gold).astype(bool)
    tp = float((p & g).sum())
    denom = 2 * tp + float((p & ~g).sum()) + float((~p & g).sum())
    return 2 * tp / denom if denom else 0.0


def macro_f1(pred: Sequence[int], gold: Sequence[int], num_classes: int) -> float:
    pred_a, gold_a = np.asarray(pred), np.asarray(gold)
    scores = []
    for c in range(num_classes):
        tp = float(((pred_a == c) & (gold_a == c)).sum())
        denom = 2 * tp + float(((pred_a == c) & (gold_a != c)).sum())
        denom += float(((pred_a != c) & (gold_a == c)).sum())
        scores.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(scores))


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    sorted_vals = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc(scores: Sequence[float], gold: Sequence[int]) -> float:
    """Area under the ROC curve via the rank-sum statistic (ties get average rank)."""
    s, g = np.asarray(scores, dtype=np.float64), np.asarray(gold).astype(bool)
    n_pos, n_neg = int(g.sum()), int((~g).sum())
    if n_pos == 0 or n_neg == 0:
        return 0.5
    ranks = _average_ranks(s)
    return float((ranks[g].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


ArrayLike = Union[Sequence[float], np.ndarray]


def pearson(x: ArrayLike, y: ArrayLike) -> float:
    a, b = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if len(a) < 2 or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def spearman(x: ArrayLike, y: ArrayLike) -> float:
    return pearson(
        _average_ranks(np.asarray(x, dtype=np.float64)),
        _average_ranks(np.asarray(y, dtype=np.float64)),
    )


def span_f1(pred: Tuple[int, int], gold: Tuple[int, int]) -> float:
    """Token-overlap F1 between two inclusive spans; (0, 0) means 'no answer'."""
    if pred == (0, 0) or gold == (0, 0):
        return 1.0 if pred == gold else 0.0
    overlap = max(0, min(pred[1], gold[1]) - max(pred[0], gold[0]) + 1)
    if overlap == 0:
        return 0.0
    precision = overlap / (pred[1] - pred[0] + 1)
    recall = overlap / (gold[1] - gold[0] + 1)
    return 2 * precision * recall / (precision + recall)


# ----------------------------------------------------------------------------- answer text QA
ANSWER_TEXT_PROTOCOL = "normalized_answer_text"
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCTUATION = set(string.punctuation)


def normalize_answer(text: str, language: str = "en") -> str:
    """SQuAD-style answer normalisation: NFC, lower-case, strip punctuation, collapse blanks.

    English additionally drops the articles a/an/the. Vietnamese keeps every syllable and every
    tone mark (combining marks are not punctuation), so no information is removed from it.
    """
    text = unicodedata.normalize("NFC", text or "").lower()
    text = "".join(
        ch for ch in text if ch not in _PUNCTUATION and not unicodedata.category(ch).startswith("P")
    )
    if language == "en":
        text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def _answer_f1(pred: str, gold: str) -> float:
    pred_tokens, gold_tokens = pred.split(), gold.split()
    if not pred_tokens or not gold_tokens:
        return float(pred_tokens == gold_tokens)  # both empty (no-answer agreement) or neither
    common = sum((Counter(pred_tokens) & Counter(gold_tokens)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(pred_tokens), common / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def answer_scores(pred: str, golds: Sequence[str], language: str = "en") -> Tuple[float, float]:
    """(exact match, F1) of one prediction against every acceptable gold answer text.

    An empty `golds` (or only blank gold strings) means the question has no answer; the
    prediction is correct only if it is empty too. The best score over the gold answers counts.
    """
    normalised = [normalize_answer(g, language) for g in golds if g and g.strip()] or [""]
    prediction = normalize_answer(pred, language)
    return (
        max(float(prediction == g) for g in normalised),
        max(_answer_f1(prediction, g) for g in normalised),
    )


def select_answer_span(
    start_logits: np.ndarray,
    end_logits: np.ndarray,
    context_start: int,
    context_end: int,
    max_answer_tokens: int = 64,
    null_threshold: float = 0.0,
) -> Optional[Tuple[int, int]]:
    """Best inclusive span inside the context window, or None meaning 'no answer'.

    Only positions in [context_start, context_end] may form an answer, so the question and the
    special tokens can never be decoded as one. The position-0 ([CLS]) score is the no-answer
    score; the span wins only when it exceeds it by more than `null_threshold` (fixed, never
    tuned on held-out data).
    """
    if context_end < context_start:
        return None
    window_start = np.asarray(start_logits[context_start : context_end + 1], dtype=np.float64)
    window_end = np.asarray(end_logits[context_start : context_end + 1], dtype=np.float64)
    n = len(window_start)
    scores = window_start[:, None] + window_end[None, :]
    ones = np.ones((n, n), dtype=bool)
    allowed = np.triu(ones) & ~np.triu(ones, k=max(1, int(max_answer_tokens)))
    scores = np.where(allowed, scores, -np.inf)
    s, e = np.unravel_index(int(np.argmax(scores)), scores.shape)
    null_score = float(start_logits[0]) + float(end_logits[0])
    if scores[s, e] <= null_score + null_threshold:
        return None
    return int(s) + context_start, int(e) + context_start


def answer_text_summary(
    rows: Sequence[Dict[str, float]],
) -> Dict[str, float]:
    """Mean EM/F1 over rows plus the has-answer / no-answer breakdown."""

    def mean(key: str, subset: Sequence[Dict[str, float]]) -> float:
        return float(np.mean([r[key] for r in subset])) if subset else 0.0

    has = [r for r in rows if r["has_answer"]]
    none = [r for r in rows if not r["has_answer"]]
    return {
        "exact_match": mean("em", rows),
        "f1": mean("f1", rows),
        "has_answer_exact_match": mean("em", has),
        "has_answer_f1": mean("f1", has),
        "no_answer_exact_match": mean("em", none),
        "no_answer_f1": mean("f1", none),
    }
