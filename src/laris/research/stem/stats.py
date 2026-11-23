"""Accuracy with a 95 % Wilson interval and per-item cost records (T275, ADR-026 sections 6, 8)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Tuple

Z95 = 1.959963984540054


def wilson_interval(correct: int, total: int, z: float = Z95) -> Tuple[float, float]:
    """The Wilson score interval of `correct / total` (both bounds in [0, 1])."""
    if total <= 0:
        return 0.0, 0.0
    p = correct / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass
class CostRecord:
    """What one item cost: wall seconds of its share of the batch, tokens, calls and peak VRAM."""

    seconds: float
    prompt_tokens: int
    generated_tokens: int
    model_calls: int
    solver_calls: int
    peak_vram_bytes: int

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def percentile(values: List[float], q: float) -> float:
    """The `q` quantile (0..1) by linear interpolation; 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarise(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Accuracy, interval and cost over result records (`correct`, `extracted`, `truncated`,
    `cost`)."""
    rows = list(records)
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    low, high = wilson_interval(correct, total)
    seconds = [r["cost"]["seconds"] for r in rows]
    generated = [float(r["cost"]["generated_tokens"]) for r in rows]
    return {
        "items": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "wilson_low": low,
        "wilson_high": high,
        "unparsed": sum(1 for r in rows if r["extracted"] is None),
        "truncated": sum(1 for r in rows if r.get("truncated")),
        "seconds_median": percentile(seconds, 0.5),
        "seconds_p95": percentile(seconds, 0.95),
        "generated_tokens_median": percentile(generated, 0.5),
        "generated_tokens_p95": percentile(generated, 0.95),
        "generated_tokens_mean": sum(generated) / total if total else 0.0,
        "peak_vram_bytes": max((r["cost"]["peak_vram_bytes"] for r in rows), default=0),
    }
