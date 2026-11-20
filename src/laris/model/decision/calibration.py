"""Calibration and abstention of the decision network (T169, ADR-024 5.4 and 5.5).

Temperature scaling here is a search over a fixed grid of one scalar, minimising the log-loss on the
validation
split; there is no gradient, optimizer or backward step. The abstention threshold is the lowest
confidence at which
the decisions the network keeps are right often enough. Both are fitted on validation data only and
sealed with the
model manifest.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .network import sigmoid

TEMPERATURE_GRID: tuple[float, ...] = tuple(
    float(t) for t in np.round(np.geomspace(0.25, 8.0, 61), 6)
)


def log_loss(logits: Sequence[float], labels: Sequence[float], temperature: float) -> float:
    """Mean negative log-likelihood of ``labels`` under ``sigmoid(logit / temperature)``."""
    z = np.asarray(logits, dtype=np.float64) / temperature
    y = np.asarray(labels, dtype=np.float64)
    # log(1 + e^z) - y z, written to stay finite
    return float(np.mean(np.logaddexp(0.0, z) - y * z))


def fit_temperature(
    logits: Sequence[float],
    labels: Sequence[float],
    grid: Sequence[float] = TEMPERATURE_GRID,
) -> float:
    """The grid temperature with the lowest validation log-loss (the lowest temperature wins a
    tie)."""
    if len(logits) != len(labels) or not len(logits):
        raise ValueError("logits and labels must be non-empty and of one length")
    return min(sorted(grid), key=lambda t: log_loss(logits, labels, t))


def expected_calibration_error(
    probabilities: Sequence[float], labels: Sequence[float], bins: int = 10
) -> float:
    """Expected calibration error with equal-width bins (gate N3 asks for at most 0.05)."""
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        mask = (p >= low) & ((p < high) if high < 1.0 else (p <= high))
        if mask.any():
            total += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return float(total)


def fit_threshold(
    confidences: Sequence[float], correct: Sequence[bool], target_precision: float
) -> float:
    """The lowest confidence at which the kept decisions are right at least ``target_precision`` of
    the time.

    ``confidences`` are the calibrated probabilities of the chosen actions and ``correct`` says
    whether each chosen
    action's outcome was good. When no threshold reaches the target the result is above 1, so every
    decision falls
    back to the rule decider.
    """
    if len(confidences) != len(correct) or not len(confidences):
        raise ValueError("confidences and correct must be non-empty and of one length")
    order = sorted(set(float(c) for c in confidences))
    c = np.asarray(confidences, dtype=np.float64)
    ok = np.asarray(correct, dtype=bool)
    for threshold in order:
        kept = c >= threshold
        if ok[kept].mean() >= target_precision:
            return threshold
    return 1.0 + 1e-9


def calibrated(logit: float, temperature: float) -> float:
    """``sigmoid(logit / temperature)``."""
    return sigmoid(logit / temperature)
