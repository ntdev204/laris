"""Features of the decision network (T169, ADR-024 5.3).

The network scores a pair (state, candidate action). Everything it reads is a number or a category
the system
measured, never free text and never the advisor's own stated confidence. The encoding is fixed here
and written
again, formula for formula, in ``crates/laris-brain/src/network.rs``; ``FEATURE_NAMES`` is stored in
every exported
network and the Rust side refuses a file whose names differ, so the two cannot drift apart
unnoticed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ACTIONS: tuple[str, ...] = (
    "retrieve",
    "ask_advisor",
    "run_tool",
    "acquire",
    "verify",
    "answer",
    "ask_user",
    "abstain",
    "stop",
)
LEVELS: Mapping[str, int] = {
    "candidate": 0,
    "sourced": 1,
    "corroborated": 2,
    "verified": 3,
    "reviewed": 4,
}
CALLS: tuple[str, ...] = ("none", "legal", "refused")

STATE_FEATURES: tuple[str, ...] = (
    "coverage",
    "best_level",
    "has_level",
    "accepted",
    "below_required",
    "pending_candidates",
    "open_conflicts",
    "retracted_dependencies",
    "acquisition_allowed",
    "retrievals",
    "acquisitions",
    "advisor_asks",
    "fresh_since_retrieve",
    "call_none",
    "call_legal",
    "call_refused",
    "repeats",
    "advisor_accept_rate_known",
    "advisor_accept_rate",
    "advisor_agreement_known",
    "advisor_agreement",
    "tool_risk",
    "steps_left",
    "time_left",
    "budget_left",
    "missing_slot",
)
FEATURE_NAMES: tuple[str, ...] = (
    *STATE_FEATURES,
    *(f"candidate_{a}" for a in ACTIONS),
    "candidate_count",
)


def _unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _capped(value: int, cap: int) -> float:
    return float(min(max(int(value), 0), cap)) / float(cap)


def state_vector(signals: Mapping[str, Any]) -> list[float]:
    """The state features of one ``Signals`` JSON object (as ``Signals::to_json`` writes it)."""
    level = signals.get("best_level")
    rate = signals.get("advisor_accept_rate")
    agreement = signals.get("advisor_agreement")
    call = signals["call"]
    return [
        _unit(signals["coverage"]),
        LEVELS[level] / 4.0 if level is not None else 0.0,
        1.0 if level is not None else 0.0,
        _capped(signals["accepted"], 8),
        _capped(signals["below_required"], 4),
        _capped(signals["pending_candidates"], 4),
        _capped(signals["open_conflicts"], 4),
        _capped(signals["retracted_dependencies"], 4),
        1.0 if signals["acquisition_allowed"] else 0.0,
        _capped(signals["retrievals"], 4),
        _capped(signals["acquisitions"], 4),
        _capped(signals["advisor_asks"], 8),
        1.0 if signals["fresh_since_retrieve"] else 0.0,
        *(1.0 if call == name else 0.0 for name in CALLS),
        _capped(signals["repeats"], 8),
        1.0 if rate is not None else 0.0,
        _unit(rate) if rate is not None else 0.0,
        1.0 if agreement is not None else 0.0,
        _unit(agreement) if agreement is not None else 0.0,
        _capped(signals["tool_risk"], 3),
        _capped(signals["steps_left"], 10),
        min(max(float(signals["time_left_seconds"]), 0.0), 300.0) / 300.0,
        _unit(signals["budget_left"]),
        1.0 if signals.get("missing_slot") is not None else 0.0,
    ]


def encode(signals: Mapping[str, Any], action: str, candidate_count: int) -> list[float]:
    """The input of the network for ``action`` among ``candidate_count`` legal candidates."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    vector = state_vector(signals)
    vector.extend(1.0 if action == a else 0.0 for a in ACTIONS)
    vector.append(_capped(candidate_count, len(ACTIONS)))
    assert len(vector) == len(FEATURE_NAMES)
    return vector


def encode_example(example: Mapping[str, Any]) -> tuple[list[float], float]:
    """One dataset line (T168) as ``(input, label)``: the label is 1 when the outcome was good."""
    candidates: Sequence[str] = example["candidates"]
    return (
        encode(example["signals"], example["action"], len(candidates)),
        1.0 if example["outcome"]["good"] else 0.0,
    )
