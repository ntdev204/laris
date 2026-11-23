"""Cost and response-time levers of the evaluation profile (T279, ADR-026 section 8).

- **Repetition detection**: a generation whose tail repeats one chunk several times is a loop that
  would run to the token cap; `repeating_tail` names it so the engine can stop the request early.
- **Budget forcing**: a thinking generation that reaches its budget without closing its reasoning
  is closed with `FORCE_ANSWER` and the model writes the answer (`forced_prompt`).
- **Lever comparison**: a run against a reference on the same items, paired (McNemar exact),
  with latency percentiles and calls per item (`compare_runs`).

Inference only; nothing here reads a gold answer except the scored records it is given.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from laris.research.stem import stats

THINK_CLOSE = "</think>"
# Qwen's own wording for closing a thinking budget; the answer follows the closing tag
FORCE_ANSWER = (
    "\n\nConsidering the limited time by the user, I have to give the solution based on the "
    "thinking directly now.\n</think>\n\n"
)


def repeating_tail(text: str, min_period: int, max_period: int, repeats: int) -> Optional[int]:
    """The shortest period `p` (min_period..max_period characters) such that the last
    `p * repeats` characters of `text` are one chunk of `p` characters repeated, else None."""
    for period in range(max(1, min_period), max_period + 1):
        width = period * repeats
        if width > len(text):
            return None
        tail = text[-width:]
        if tail[:-period] == tail[period:]:
            return period
    return None


class RepetitionWatch:
    """Feeds streamed text and says when a loop is seen; checks every `every_chars` new
    characters once `min_chars` have arrived (`cfg`: the `repetition` section of the harness)."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.enabled = bool(cfg.get("enabled"))
        self.min_period = int(cfg.get("min_period", 16))
        self.max_period = int(cfg.get("max_period", 512))
        self.repeats = int(cfg.get("repeats", 6))
        self.min_chars = int(cfg.get("min_chars", 1000))
        self.every = int(cfg.get("every_chars", 256))
        self.text = ""
        self._next = self.min_chars
        self.period: Optional[int] = None

    def feed(self, piece: str) -> bool:
        """Add streamed text; True once the tail repeats (then `period` is set)."""
        self.text += piece
        if not self.enabled or len(self.text) < self._next:
            return False
        self._next = len(self.text) + self.every
        self.period = repeating_tail(self.text, self.min_period, self.max_period, self.repeats)
        return self.period is not None


def forced_prompt(raw_prompt: str, thinking: str) -> str:
    """The raw prompt of the answer after a thinking budget ran out: the reasoning so far, then
    the closing sentence and tag."""
    return raw_prompt + thinking + FORCE_ANSWER


# -- comparison --------------------------------------------------------------------------------


def mcnemar_exact(gained: int, lost: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs (binomial, p = 0.5)."""
    n = gained + lost
    if n == 0:
        return 1.0
    k = min(gained, lost)
    tail = float(sum(math.comb(n, i) for i in range(k + 1))) / 2.0**n
    return min(1.0, 2 * tail)


def compare_runs(
    run: Dict[str, Dict[str, Any]], reference: Dict[str, Dict[str, Any]], bench: str
) -> Dict[str, Any]:
    """A run against a reference on the items of `bench` both hold: accuracy of each, items
    gained and lost, McNemar p, and per-item cost (median and p95 seconds, mean generated
    tokens, model calls)."""
    ids = sorted(i for i, r in run.items() if r["bench"] == bench and i in reference)
    rows = [run[i] for i in ids]
    refs = [reference[i] for i in ids]
    gained = sum(1 for a, b in zip(rows, refs) if a["correct"] and not b["correct"])
    lost = sum(1 for a, b in zip(rows, refs) if b["correct"] and not a["correct"])

    def cost(records: List[Dict[str, Any]]) -> Dict[str, float]:
        seconds = [float(r["cost"]["seconds"]) for r in records]
        tokens = [float(r["cost"]["generated_tokens"]) for r in records]
        calls = [float(r["cost"]["model_calls"]) for r in records]
        n = len(records) or 1
        return {
            "seconds_median": stats.percentile(seconds, 0.5),
            "seconds_p95": stats.percentile(seconds, 0.95),
            "generated_tokens_mean": sum(tokens) / n,
            "model_calls_mean": sum(calls) / n,
        }

    right = sum(1 for r in rows if r["correct"])
    ref_right = sum(1 for r in refs if r["correct"])
    low, high = stats.wilson_interval(right, len(rows))
    return {
        "items": len(rows),
        "correct": right,
        "reference_correct": ref_right,
        "wilson_low": low,
        "wilson_high": high,
        "gained": gained,
        "lost": lost,
        "p_mcnemar": mcnemar_exact(gained, lost),
        "cost": cost(rows),
        "reference_cost": cost(refs),
    }


def counterfactual(rows: List[Dict[str, Any]], drop: str) -> int:
    """Right answers had a step not changed the answer, from the records of one run:
    `review` keeps the draft where a solver review gave the final answer; `formalise` also
    drops the solver fallback (no draft read, so no answer)."""
    if drop not in ("review", "formalise"):
        raise ValueError(drop)
    right = 0
    for r in rows:
        source = r.get("final_from")
        if source == "review_solver":
            right += int(bool(r.get("draft_correct")))
        elif source == "solver_fallback" and drop == "formalise":
            continue
        else:
            right += int(bool(r["correct"]))
    return right
