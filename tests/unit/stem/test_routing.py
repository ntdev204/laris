"""T287: routing labels, the rule router's choices, the network at inference and its gates. No
test trains anything: the network here is written by hand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from laris.research.stem import routing as rt
from laris.research.stem.router import route

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "configs/stem-benchmarks.json").read_text(encoding="utf-8"))
GATES = json.loads((ROOT / "configs/stem-router-gates.json").read_text(encoding="utf-8"))


def _rec(correct: bool, final_from: str = "draft", cls: str = "computable") -> Dict[str, Any]:
    return {"correct": correct, "final_from": final_from, "cls": cls}


def test_labels_count_a_deterministic_path_only_when_it_answered() -> None:
    label = rt.labels(
        {"a": _rec(True, "model_free"), "b": _rec(False, ""), "c": _rec(False, "brain_only")},
        {"a": _rec(False), "b": _rec(True), "c": _rec(True)},
        {"a": _rec(True), "b": _rec(False), "c": _rec(False)},
        {"a": _rec(False), "b": _rec(True)},
    )
    assert set(label) == {"a", "b"}  # c has no bare-model record
    assert label["a"] == {
        "model_free": True,
        "brain_only": False,
        "notes_model": False,
        "model_solver": True,
        "bare_model": False,
    }
    assert not label["b"]["model_free"] and label["b"]["notes_model"]


def test_rule_choice_and_the_routing_table() -> None:
    assert rt.rule_choice(_rec(True, "model_free")) == "model_free"
    assert rt.rule_choice(_rec(True, "draft", "computable")) == "model_solver"
    assert rt.rule_choice(_rec(True, "draft", "knowledge")) == "notes_model"
    label = {
        "a": dict.fromkeys(rt.PATHS, False) | {"model_solver": True},
        "b": dict.fromkeys(rt.PATHS, False) | {"notes_model": True},
        "c": dict.fromkeys(rt.PATHS, False),
    }
    choice = {"a": "model_solver", "b": "model_solver", "c": "notes_model"}
    table = rt.routing_table(
        label, choice, {"a": "computable", "b": "computable", "c": "knowledge"}
    )
    assert table["answerable"] == 2 and table["oracle_correct"] == 2
    assert table["routing_accuracy"] == 0.5 and table["choice_correct"] == 1
    assert table["confusion"]["computable"]["right"]["notes_model"] == 1
    assert table["confusion"]["knowledge"]["none_right"] == 1


def test_every_route_records_its_features() -> None:
    item = {"question": "Which is it ?", "options": ["1 m", "2 m", "red", "blue"]}
    decided = route(item, CONFIG["harness"]["router"])
    assert decided.rule == "numeric_options"
    assert decided.features == {"options": 4, "numeric_option_share": 0.5, "question_words": 4}


def _net(bias: Dict[str, float]) -> rt.RouterNetwork:
    n = len(rt.FEATURES)
    return rt.RouterNetwork.from_json(
        {
            "features": list(rt.FEATURES),
            "mean": [0.0] * n,
            "std": [1.0] * n,
            "weights": {p: [0.0] * n for p in rt.MODEL_PATHS},
            "bias": bias,
        }
    )


def test_decide_abstains_and_never_overrides_a_deterministic_answer() -> None:
    x = [0.0] * len(rt.FEATURES)
    sure = _net({"notes_model": 3.0, "model_solver": -3.0, "bare_model": -3.0})
    assert rt.decide(sure, x, "model_solver", 0.6) == rt.Decision(
        "notes_model", pytest.approx(0.9526, abs=1e-4), "network"
    )
    unsure = _net({"notes_model": 0.0, "model_solver": 0.0, "bare_model": 0.0})
    assert rt.decide(unsure, x, "model_solver", 0.6).by == "rule"
    assert rt.decide(sure, x, "model_free", 0.6) == rt.Decision("model_free", 1.0, "rule")
    assert rt.decide(None, x, "notes_model", 0.6).by == "rule"


def test_a_network_with_the_wrong_features_is_refused() -> None:
    with pytest.raises(ValueError):
        rt.RouterNetwork.from_json(
            {"features": ["x"], "mean": [0], "std": [1], "weights": {}, "bias": {}}
        )


def _rows(n: int, right: str, rule: str = "model_solver") -> list:
    x = [0.0] * len(rt.FEATURES)
    return [
        {"x": x, "labels": dict.fromkeys(rt.PATHS, False) | {right: True}, "rule_path": rule}
        for _ in range(n)
    ]


def test_gates_without_a_network_are_not_verified() -> None:
    report = rt.gates(_rows(5, "notes_model"), None, GATES)
    assert set(report["gates"].values()) == {"NOT VERIFIED"}
    assert report["verdict"].startswith("NOT VERIFIED")


def test_gates_pass_only_for_a_real_gain_and_fail_without_one() -> None:
    better = _net({"notes_model": 3.0, "model_solver": -3.0, "bare_model": -3.0})
    rows = _rows(40, "notes_model") + _rows(2, "model_solver")
    report = rt.gates(rows, better, GATES)
    assert report["gates"]["N1"] == "PASS" and report["gain_points"] > 1.0
    assert report["bootstrap"][0] > 0
    assert report["gates"]["N2"] == "PASS" and report["gates"]["N4"] == "PASS"
    same = rt.gates(_rows(40, "model_solver"), _net(dict.fromkeys(rt.MODEL_PATHS, 0.0)), GATES)
    assert same["gain_points"] == 0.0 and same["gates"]["N1"] == "FAIL"
    assert same["verdict"].startswith("NOT PROMOTED")


def test_calibration_error() -> None:
    assert rt.ece([(0.9, True)] * 9 + [(0.9, False)], 10) == pytest.approx(0.0)
    assert rt.ece([(0.9, False)] * 10, 10) == pytest.approx(0.9)


def test_the_split_is_seeded_and_label_free() -> None:
    ids = [f"item/{i}" for i in range(2000)]
    held = [i for i in ids if rt.is_heldout(i, 287, 0.30)]
    assert 0.27 < len(held) / len(ids) < 0.33
    assert held == [i for i in ids if rt.is_heldout(i, 287, 0.30)]
    assert {rt.fold_of(i, 287, 5) for i in ids} == set(range(5))


def test_training_refuses_without_the_owner_flag(tmp_path: Path) -> None:
    out = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/train_stem_router.py"),
            "--dataset",
            str(tmp_path),
            "--config",
            "configs/stem-router-training.json",
            "--out",
            str(tmp_path / "n.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0 and "owner" in out.stderr
    assert not (tmp_path / "n.json").exists()


def test_path_overrides_merge() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import stem_benchmarks as sb

    merged = sb.merge_path(CONFIG["harness"], CONFIG["router_paths"]["plain_retrieval"])
    assert merged["draft"]["max_retries"] == 0 and merged["formalise"]["classes"] == []
    assert merged["retrieval"]["k"] == CONFIG["harness"]["retrieval"]["k"]
    assert CONFIG["harness"]["draft"]["max_retries"] == 1


def test_a_chosen_path_runs_with_its_own_settings() -> None:
    from laris.research.stem import harness as h

    sys.path.insert(0, str(ROOT / "scripts"))
    import stem_benchmarks as sb

    from .test_harness import t278_harness

    calls = []

    def model(prompt: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        calls.append("formalise" if "Translate the problem" in prompt else "draft")
        return {
            "text": "Answer: B",
            "prompt_tokens": 1,
            "generated_tokens": 1,
            "truncated": False,
            "seconds": 0.0,
        }

    def solve(problem: Dict[str, Any]):
        return None, "refused:x"

    item = {"id": "c/1", "question": "How far?", "options": ["1 m", "2 m"], "answer": "B"}
    item["category"] = "physics"
    notes_cfg = sb.merge_path(t278_harness(), CONFIG["router_paths"]["notes_model"])

    def choose(it: Dict[str, Any], trace: h.Trace) -> Dict[str, Any]:
        trace.steps.append({"step": "route", "path": "notes_model", "by": "network"})
        return notes_cfg

    base = CONFIG["baseline"]
    rule = h.Harness(t278_harness(), base, model, solve, CONFIG["equivalence"])
    rule.answer(item, 1, notes=["a passage"])
    assert calls == ["draft", "formalise"]  # computable: the rule router formalises
    calls.clear()
    net = h.Harness(t278_harness(), base, model, solve, CONFIG["equivalence"], None, choose)
    trace = net.answer(item, 1, notes=["a passage"])
    assert calls == ["draft"] and trace.notes == 1 and trace.cls == "computable"
    assert trace.steps[0] == {"step": "route", "path": "notes_model", "by": "network"}
