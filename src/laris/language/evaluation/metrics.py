"""Pure-NumPy metrics used to evaluate the language encoder."""

from typing import Sequence, Tuple, Union

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
