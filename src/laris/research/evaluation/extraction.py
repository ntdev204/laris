"""Evaluation of the scientific discourse extractor against labelled annotations.

Gold annotations mark a type and a quoted span of the document text. A prediction counts as a true
positive when it has the same type and its character span overlaps a gold span with IoU of at least
`min_iou` (one-to-one matching). Output: per-type precision, recall and F1 plus micro and macro
averages, all rounded and sorted so the report is byte-reproducible. A regression gate compares a
report with a stored baseline.
"""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

TYPES = ("claim", "method", "dataset", "metric", "result", "limitation", "assumption")
Span = Tuple[str, int, int]  # (type, start, end)
MIN_IOU = 0.5


def load_annotations(path: Path) -> List[Dict[str, Any]]:
    """Annotations with `quote` entries resolved to character spans (first occurrence after the
    previous gold span of the same quote, so repeated quotes can be listed in order)."""
    docs = json.loads(Path(path).read_text(encoding="utf-8"))
    for doc in docs:
        cursor: Dict[Tuple[str, str], int] = {}
        spans = []
        for item in doc["gold"]:
            quote = item["quote"]
            key = (item["type"], quote)
            start = doc["text"].find(quote, cursor.get(key, 0))
            if start < 0:
                raise ValueError(f"{doc['id']}: quote not found: {quote!r}")
            cursor[key] = start + 1
            spans.append((item["type"], start, start + len(quote.rstrip())))
        doc["spans"] = spans
    return list(docs)


def extract_spans(text: str) -> List[Span]:
    """The scientific extractor's output as (type, start, end)."""
    from laris.shared.scientific.extractor import ScientificDiscourseExtractor

    found = ScientificDiscourseExtractor().extract("eval", text)
    groups = (
        ("claim", found.claims), ("method", found.methods), ("dataset", found.datasets),
        ("metric", found.metrics), ("result", found.results),
        ("limitation", found.limitations), ("assumption", found.assumptions),
    )  # fmt: skip
    return [
        (kind, r.coordinate.char_start, r.coordinate.char_end)
        for kind, records in groups
        for r in records
    ]


def _iou(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


def match(pred: Sequence[Span], gold: Sequence[Span], min_iou: float = MIN_IOU) -> Dict[str, Any]:
    counts = {t: {"tp": 0, "fp": 0, "fn": 0} for t in TYPES}
    for kind in TYPES:
        p = sorted((s, e) for t, s, e in pred if t == kind)
        g = sorted((s, e) for t, s, e in gold if t == kind)
        used: set = set()
        for ps in p:
            best, best_i = 0.0, -1
            for i, gs in enumerate(g):
                score = _iou(ps, gs)
                if i not in used and score > best:
                    best, best_i = score, i
            if best >= min_iou:
                used.add(best_i)
                counts[kind]["tp"] += 1
            else:
                counts[kind]["fp"] += 1
        counts[kind]["fn"] += len(g) - len(used)
    return counts


def _scores(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def evaluate(
    docs: Sequence[Dict[str, Any]],
    predict: Callable[[str], List[Span]] = extract_spans,
    min_iou: float = MIN_IOU,
) -> Dict[str, Any]:
    totals = {t: {"tp": 0, "fp": 0, "fn": 0} for t in TYPES}
    for doc in docs:
        counts = match(predict(doc["text"]), doc["spans"], min_iou)
        for kind in TYPES:
            for key in ("tp", "fp", "fn"):
                totals[kind][key] += counts[kind][key]
    per_type = {
        kind: {**totals[kind], **_scores(**totals[kind])}
        for kind in TYPES
        if any(totals[kind].values())
    }
    micro = _scores(*(sum(totals[t][k] for t in TYPES) for k in ("tp", "fp", "fn")))
    macro_f1 = (
        round(sum(v["f1"] for v in per_type.values()) / len(per_type), 4) if per_type else 0.0
    )
    return {
        "documents": len(docs),
        "min_iou": min_iou,
        "per_type": per_type,
        "micro": micro,
        "macro_f1": macro_f1,
    }


def gate(report: Dict[str, Any], baseline: Dict[str, Any], tolerance: float = 0.0) -> List[str]:
    """Violations: a type whose F1 fell below the baseline (minus tolerance), or that vanished."""
    problems = []
    for kind, floor in sorted(baseline.get("per_type", {}).items()):
        now = report["per_type"].get(kind, {}).get("f1", 0.0)
        if now + tolerance < floor:
            problems.append(f"{kind}: F1 {now} is below the baseline {floor}")
    if report["macro_f1"] + tolerance < baseline.get("macro_f1", 0.0):
        problems.append(
            f"macro F1 {report['macro_f1']} is below the baseline {baseline['macro_f1']}"
        )
    return problems


def baseline_from(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "per_type": {k: v["f1"] for k, v in sorted(report["per_type"].items())},
        "macro_f1": report["macro_f1"],
    }


def dumps(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
