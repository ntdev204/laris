"""The decision network code (T169): encoding, export, calibration, parity fixtures.

Nothing trains here: the torch module is only run forward, under ``no_grad``, with seeded untrained
weights."""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from laris.model.decision import calibration, features, network

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "src" / "laris" / "model" / "decision"
FIXTURES = ROOT / "crates" / "laris-brain" / "tests" / "fixtures" / "decision-net"

SIGNALS = {
    "missing_slot": None,
    "coverage": 0.75,
    "best_level": "verified",
    "accepted": 3,
    "below_required": 0,
    "pending_candidates": 1,
    "open_conflicts": 0,
    "retracted_dependencies": 0,
    "acquisition_allowed": True,
    "retrievals": 1,
    "acquisitions": 0,
    "advisor_asks": 2,
    "fresh_since_retrieve": False,
    "call": "legal",
    "repeats": 0,
    "advisor_accept_rate": None,
    "advisor_agreement": 0.5,
    "tool_risk": 1,
    "steps_left": 5,
    "time_left_seconds": 90.0,
    "budget_left": 0.8,
}


def test_the_encoding_has_one_named_slot_per_feature():
    assert len(set(features.FEATURE_NAMES)) == len(features.FEATURE_NAMES) == 36
    x = features.encode(SIGNALS, "verify", 6)
    assert len(x) == 36
    assert all(0.0 <= v <= 1.0 for v in x)
    by_name = dict(zip(features.FEATURE_NAMES, x, strict=True))
    assert by_name["candidate_verify"] == 1.0
    assert (
        sum(v for k, v in by_name.items() if k.startswith("candidate_") and k != "candidate_count")
        == 1.0
    )
    assert by_name["best_level"] == 0.75 and by_name["has_level"] == 1.0
    assert by_name["advisor_accept_rate_known"] == 0.0 and by_name["advisor_accept_rate"] == 0.0
    assert by_name["call_legal"] == 1.0 and by_name["call_none"] == 0.0
    assert by_name["time_left"] == pytest.approx(0.3)
    with pytest.raises(ValueError, match="unknown action"):
        features.encode(SIGNALS, "improvise", 3)


def test_values_outside_their_range_are_clipped_not_passed_on():
    wild = {
        **SIGNALS,
        "coverage": 7.0,
        "accepted": 900,
        "time_left_seconds": -5.0,
        "budget_left": -1.0,
        "steps_left": 99,
    }
    by_name = dict(zip(features.STATE_FEATURES, features.state_vector(wild), strict=True))
    assert by_name["coverage"] == 1.0 and by_name["accepted"] == 1.0
    assert (
        by_name["time_left"] == 0.0
        and by_name["budget_left"] == 0.0
        and by_name["steps_left"] == 1.0
    )


def test_a_dataset_line_becomes_an_input_and_a_label():
    line = {
        "signals": SIGNALS,
        "candidates": ["verify", "answer", "stop"],
        "action": "answer",
        "outcome": {"good": False},
    }
    x, y = features.encode_example(line)
    assert x == features.encode(SIGNALS, "answer", 3) and y == 0.0


def test_export_and_load_round_trip_and_are_canonical():
    net = network.random_net(3)
    text = network.dumps(net, {"run": "x"})
    again = network.load(json.loads(text))
    assert network.dumps(again, {"run": "x"}) == text
    assert net.parameter_count() == 2273
    x = features.encode(SIGNALS, "stop", 4)
    assert again.logit(x) == net.logit(x)


def test_a_malformed_export_is_refused():
    good = network.export(network.random_net(3))

    def broken(change):
        data = json.loads(json.dumps(good))
        change(data)
        return data

    for change in (
        lambda d: d.update(version=2),
        lambda d: d["features"].reverse(),
        lambda d: d["layers"][0]["weights"][0].pop(),
        lambda d: d["layers"][1].update(activation="gelu"),
        lambda d: d["calibration"].update(temperature=0.0),
        lambda d: d["abstention"].update(threshold=-0.1),
        lambda d: d["layers"].pop(),
    ):
        with pytest.raises(network.NetworkError):
            network.load(broken(change))


def test_the_fixtures_on_disk_are_what_the_generator_writes():
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "scripts" / "make_decision_net_fixture.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_reference_forward_reproduces_the_fixture_cases():
    net = network.load(json.loads((FIXTURES / "net.json").read_text()))
    cases = json.loads((FIXTURES / "cases.json").read_text())["cases"]
    assert len(cases) == 40
    for case in cases:
        for action in case["candidates"]:
            x = features.encode(case["signals"], action, len(case["candidates"]))
            assert net.logit(x) == pytest.approx(case["logits"][action], abs=1e-12)
            assert net.probability(x) == pytest.approx(case["probabilities"][action], abs=1e-12)


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="torch is not installed")
def test_the_torch_module_agrees_with_the_numpy_reference_in_float32():
    import torch

    torch.manual_seed(0)
    module = network.torch_module()
    net = module.to_net(temperature=1.3, threshold=0.4)
    network.validate(net)
    assert net.parameter_count() == sum(p.numel() for p in module.parameters()) == 2273
    xs = [features.encode(SIGNALS, a, 5) for a in features.ACTIONS]
    with torch.no_grad():
        got = module(torch.tensor(xs, dtype=torch.float32)).numpy()
    want = np.array([net.logit(x) for x in xs])
    assert np.max(np.abs(got - want)) <= 1e-5
    # the export of a torch network loads back
    assert network.load(network.export(net)).temperature == 1.3


def test_temperature_scaling_recovers_a_known_miscalibration():
    rng = np.random.RandomState(0)  # noqa: NPY002
    truth = 2.0  # the network is overconfident by a factor of two
    logits = rng.standard_normal(4000) * 3.0
    labels = (rng.rand(4000) < 1.0 / (1.0 + np.exp(-logits / truth))).astype(float)
    fitted = calibration.fit_temperature(logits, labels)
    assert 1.6 <= fitted <= 2.5
    raw = 1.0 / (1.0 + np.exp(-logits))
    cal = 1.0 / (1.0 + np.exp(-logits / fitted))
    assert calibration.expected_calibration_error(
        cal, labels
    ) < calibration.expected_calibration_error(raw, labels)
    assert calibration.expected_calibration_error(cal, labels) < 0.05
    assert calibration.log_loss(logits, labels, fitted) <= calibration.log_loss(logits, labels, 1.0)
    with pytest.raises(ValueError):
        calibration.fit_temperature([], [])


def test_the_abstention_threshold_keeps_only_decisions_that_are_right_often_enough():
    rng = np.random.RandomState(1)  # noqa: NPY002
    confidence = rng.rand(3000)
    correct = rng.rand(3000) < confidence  # calibrated by construction
    threshold = calibration.fit_threshold(confidence, correct, 0.9)
    kept = confidence >= threshold
    assert correct[kept].mean() >= 0.9
    assert 0.5 < threshold < 1.0
    # lowering the bar lowers the threshold
    assert calibration.fit_threshold(confidence, correct, 0.7) <= threshold
    # an impossible target sends every decision to the rule decider
    assert calibration.fit_threshold([0.6, 0.7], [False, False], 0.9) > 1.0


def test_this_package_has_no_training_step():
    """T169 prepares code only: training is the owner's run (T170) and is not written here."""
    forbidden = re.compile(r"\.backward\(|optim\.|optimizer|\.step\(|zero_grad|loss\.|\.fit\(")
    for path in PACKAGE.glob("*.py"):
        text = re.sub(r'""".*?"""', "", path.read_text(), flags=re.S)
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert not forbidden.search(code), f"{path.name} contains a training construct"


def test_probabilities_are_finite_for_extreme_logits():
    assert network.sigmoid(1e4) == 1.0 and network.sigmoid(-1e4) == 0.0
    assert math.isfinite(calibration.log_loss([1e4, -1e4], [0.0, 1.0], 1.0))
