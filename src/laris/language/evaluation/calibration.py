"""Ratchets acceptance thresholds up to what a trained checkpoint has actually achieved.

Thresholds start deliberately loose because no measurement exists. Once a checkpoint passes on
the `val` split, each task's `min_margin` and `min_absolute` are raised to a fraction (`headroom`)
of the weakest task/language group seen. They are never lowered, and `test` reports are refused so
the held-out split is never used to choose thresholds.
"""

import copy
from typing import Any, Dict, List, Sequence, Tuple

DEFAULT_HEADROOM = 0.9
CALIBRATION_SPLIT = "val"


def calibrate_thresholds(
    thresholds: Dict[str, Any],
    reports: Sequence[Dict[str, Any]],
    headroom: float = DEFAULT_HEADROOM,
) -> Tuple[Dict[str, Any], List[str]]:
    """Returns (new thresholds, human-readable change lines); the input is not modified."""
    if not reports:
        raise ValueError("At least one evaluation report is required")
    if not 0.0 < headroom <= 1.0:
        raise ValueError("headroom must be in (0, 1]")
    for report in reports:
        if report.get("split") != CALIBRATION_SPLIT:
            raise ValueError(
                f"Calibration uses only '{CALIBRATION_SPLIT}' reports (got "
                f"'{report.get('split')}'): the test split must not influence thresholds"
            )
        if not report.get("passed"):
            raise ValueError("Calibration requires reports that passed the current gate")

    updated = copy.deepcopy(thresholds)
    changes: List[str] = []
    for task, cfg in updated["tasks"].items():
        groups = [g for r in reports for g in r.get("groups", []) if g["task"] == task]
        if not groups:
            continue
        margin = round(headroom * min(g["value"] - g["baseline"] for g in groups), 3)
        absolute = round(headroom * min(g["value"] for g in groups), 3)
        for key, proposed in (("min_margin", margin), ("min_absolute", absolute)):
            current = float(cfg[key])
            if proposed > current:
                cfg[key] = proposed
                changes.append(f"{task}.{key}: {current:g} -> {proposed:g}")
    return updated, changes
