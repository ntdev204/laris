import json
from pathlib import Path

import pytest

from laris.cli.main import main
from laris.language.evaluation.calibration import calibrate_thresholds

THRESHOLDS = {
    "tasks": {
        "nli": {"metric": "macro_f1", "baseline": "majority_class", "min_margin": 0.05,
                "min_absolute": 0.0},
        "qa": {"metric": "f1", "baseline": "no_answer_or_first", "min_margin": 0.05,
               "min_absolute": 0.5},
    }
}


def _report(split="val", passed=True, nli=(0.80, 0.20), qa=(0.60, 0.30)):
    return {
        "split": split,
        "passed": passed,
        "groups": [
            {"task": "nli", "language": "en", "value": nli[0], "baseline": nli[1]},
            {"task": "qa", "language": "vi", "value": qa[0], "baseline": qa[1]},
        ],
    }


def test_thresholds_ratchet_up_from_weakest_group_with_headroom() -> None:
    updated, changes = calibrate_thresholds(THRESHOLDS, [_report()], headroom=0.9)
    assert updated["tasks"]["nli"]["min_margin"] == 0.54
    assert updated["tasks"]["nli"]["min_absolute"] == 0.72
    assert updated["tasks"]["qa"]["min_absolute"] == 0.54
    assert THRESHOLDS["tasks"]["nli"]["min_margin"] == 0.05
    assert changes


def test_thresholds_are_never_lowered() -> None:
    weak = _report(qa=(0.52, 0.50))
    updated, _ = calibrate_thresholds(THRESHOLDS, [weak], headroom=0.9)
    assert updated["tasks"]["qa"]["min_margin"] == 0.05
    assert updated["tasks"]["qa"]["min_absolute"] == 0.5


def test_test_split_and_failed_reports_are_refused() -> None:
    with pytest.raises(ValueError, match="test split"):
        calibrate_thresholds(THRESHOLDS, [_report(split="test")])
    with pytest.raises(ValueError, match="passed"):
        calibrate_thresholds(THRESHOLDS, [_report(passed=False)])


def test_cli_writes_calibrated_config(tmp_path: Path) -> None:
    config = Path("configs/evaluation/language_encoder.yaml")
    report = tmp_path / "val.json"
    groups = [
        {"task": t, "language": "en", "value": 0.9, "baseline": 0.2}
        for t in ("mlm", "nli", "paraphrase", "similarity", "qa")
    ]
    report.write_text(json.dumps({"split": "val", "passed": True, "groups": groups}))
    out = tmp_path / "out.yaml"
    code = main(["evaluate", "calibrate", "--reports", str(report), "--config", str(config),
                 "--output", str(out)])
    assert code == 0
    assert "min_margin" in out.read_text()
    assert main(["evaluate", "calibrate", "--reports", str(tmp_path / "none.json")]) == 2
