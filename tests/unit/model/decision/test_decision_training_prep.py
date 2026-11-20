"""Preparation of the decision network's owner run (T170): config, data access, stop rules, run
record and intake.

Nothing here trains. The loop that changes weights is in ``scripts/train_decision_net.py``; these
tests only exercise the code around it, with a seeded untrained network and a fabricated log."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from laris.model.decision import evaluation as ev
from laris.model.decision.network import dumps, random_net
from laris.shared.core.errors import TrainingExecutionProhibitedError

ROOT = Path(__file__).resolve().parents[4]
CONFIG = ROOT / "configs" / "decision-net-training.json"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INTAKE = _load_script("decision_net_intake")
TRAINER = _load_script("train_decision_net")

SIGNALS = {
    "missing_slot": None,
    "coverage": 0.5,
    "best_level": "sourced",
    "accepted": 1,
    "below_required": 0,
    "pending_candidates": 0,
    "open_conflicts": 0,
    "retracted_dependencies": 0,
    "acquisition_allowed": True,
    "retrievals": 0,
    "acquisitions": 0,
    "advisor_asks": 0,
    "fresh_since_retrieve": True,
    "call": "none",
    "repeats": 0,
    "advisor_accept_rate": None,
    "advisor_agreement": None,
    "tool_risk": 0,
    "steps_left": 6,
    "time_left_seconds": 100.0,
    "budget_left": 1.0,
}
ACTIONS = ["retrieve", "answer", "abstain"]


def _line(group: int, action: str, split: str) -> str:
    coverage = (group % 10) / 10.0
    good = (action == "answer") == (coverage >= 0.6)
    example = {
        "group": f"g{group}",
        "origin": "scenario",
        "advisor": None,
        "signals": {**SIGNALS, "coverage": coverage},
        "candidates": ACTIONS,
        "action": action,
        "outcome": {"good": good, "evidence": "scenario_oracle"},
        "provenance": {"index": group},
        "schema": 1,
        "id": f"{group}-{action}",
        "split": split,
    }
    return json.dumps(example, sort_keys=True)


def make_dataset(root: Path, date: str = "2026-11-01") -> Path:
    """A tiny dataset in the format of ``cargo xtask decision-data``."""
    root.mkdir(parents=True)
    ranges = {"train": range(0, 40), "validation": range(40, 50), "heldout": range(50, 60)}
    files = {}
    for split, groups in ranges.items():
        body = "\n".join(sorted(_line(g, a, split) for g in groups for a in ACTIONS)) + "\n"
        (root / f"{split}.jsonl").write_text(body)
        files[f"{split}.jsonl"] = {
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "examples": len(groups) * len(ACTIONS),
        }
    (root / "manifest.json").write_text(json.dumps({"schema": 1, "date": date, "files": files}))
    sealed = f"heldout.jsonl:{files['heldout.jsonl']['sha256']}"
    seal = {"date": date, "files_sha256": hashlib.sha256(sealed.encode()).hexdigest()}
    (root / "seal.json").write_text(json.dumps(seal))
    return root


CONFIG_TEXT = {**json.loads(CONFIG.read_text()), "patience": 3, "max_epochs": 50}


def make_run(
    tmp_path: Path, dataset: Path, started: str = "2026-11-20T10:00:00+00:00"
) -> tuple[Path, Path]:
    """A fabricated, internally consistent run: untrained weights, a log that ends by patience."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG_TEXT, indent=2))
    train, validation = ev.load_split(dataset, "train"), ev.load_split(dataset, "validation")
    losses = [0.9, 0.8, 0.7, 0.71, 0.72, 0.73]
    history = [
        {"epoch": i, "seconds": 2.0 * i, "train_loss": v - 0.05, "validation_loss": v}
        for i, v in enumerate(losses, start=1)
    ]
    assert ev.stop_reason(history, CONFIG_TEXT, history[-1]["seconds"]) == "patience"
    meta = {
        "dataset_manifest_sha256": ev.sha256_file(dataset / "manifest.json"),
        "seal_sha256": ev.sha256_file(dataset / "seal.json"),
        "config_sha256": ev.sha256_file(config_path),
        "started_at": started,
        "seconds": history[-1]["seconds"],
        "versions": {"python": "x"},
    }
    net_json, record = ev.finish_run(
        random_net(7), train, validation, CONFIG_TEXT, history, "patience", meta
    )
    run = tmp_path / "run"
    run.mkdir()
    (run / "net.json").write_text(net_json)
    (run / "run.json").write_text(json.dumps(record, indent=2))
    (run / "train-log.jsonl").write_text("".join(json.dumps(h) + "\n" for h in history))
    return run, config_path


def intake(run: Path, dataset: Path, config: Path) -> dict[str, str]:
    checks, _ = INTAKE.check_run(run, dataset, config)
    return {name: status for status, name, _ in checks}


def failed(result: dict[str, str]) -> set[str]:
    return {name for name, status in result.items() if status == "FAIL"}


def test_the_committed_config_is_complete_and_within_its_own_limit():
    config = json.loads(CONFIG.read_text())
    assert ev.check_config(config) == []
    assert (
        ev.parameter_count(config["hidden"])
        == random_net(1).parameter_count()
        <= config["max_parameters"]
    )
    assert ev.check_config({**config, "oops": 1}) == ["unknown key: oops"]
    assert ev.check_config({k: v for k, v in config.items() if k != "seed"}) == [
        "missing key: seed"
    ]
    assert ev.check_config({**config, "patience": 0}) == ["patience must be at least 1"]


def test_only_train_and_validation_can_be_read(tmp_path):
    dataset = make_dataset(tmp_path / "ds")
    assert len(ev.load_split(dataset, "train")) == 120
    assert ev.load_split(dataset, "validation").groups == 10
    for sealed in ev.SEALED_SPLITS:
        with pytest.raises(ev.SealedSplitError):
            ev.load_split(dataset, sealed)


def test_a_changed_file_or_a_line_in_the_wrong_split_is_refused(tmp_path):
    dataset = make_dataset(tmp_path / "ds")
    with (dataset / "train.jsonl").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ev.DatasetError, match="checksum"):
        ev.load_split(dataset, "train")
    other = make_dataset(tmp_path / "other")
    body = (
        (other / "validation.jsonl")
        .read_text()
        .replace('"split": "validation"', '"split": "train"')
    )
    (other / "validation.jsonl").write_text(body)
    manifest = json.loads((other / "manifest.json").read_text())
    manifest["files"]["validation.jsonl"]["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    (other / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ev.DatasetError, match="belongs to"):
        ev.load_split(other, "validation")


def test_the_training_script_names_no_sealed_split():
    tree = ast.parse((ROOT / "scripts" / "train_decision_net.py").read_text())
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert not {s for s in strings if "heldout" in s and "\n" not in s}


def test_the_script_refuses_to_start_without_the_owners_authorization(tmp_path, monkeypatch):
    monkeypatch.delenv("LARIS_TRAINING_AUTHORIZED", raising=False)
    out = tmp_path / "run"
    with pytest.raises(TrainingExecutionProhibitedError):
        TRAINER.main(["--config", str(CONFIG), "--dataset", str(tmp_path), "--out", str(out)])
    assert not out.exists()


def test_stop_rules_in_order_of_precedence():
    config = {
        "max_epochs": 5,
        "max_seconds": 100.0,
        "patience": 3,
        "min_delta": 0.01,
        "divergence_factor": 2.0,
    }

    def rows(*losses):
        return [{"train_loss": v, "validation_loss": v} for v in losses]

    assert ev.stop_reason([], config, 0.0) is None
    assert ev.stop_reason(rows(1.0, 0.9), config, 1.0) is None
    assert ev.stop_reason(rows(1.0, float("nan")), config, 1.0) == "non_finite_loss"
    assert ev.stop_reason(rows(1.0, 2.5), config, 1.0) == "diverged"
    assert ev.stop_reason(rows(1.0, 0.9, 0.8, 0.7, 0.6), config, 1.0) == "max_epochs"
    assert ev.stop_reason(rows(1.0, 0.9), config, 100.0) == "max_seconds"
    assert (
        ev.stop_reason(rows(1.0, 0.5, 0.5, 0.5, 0.5), {**config, "max_epochs": 9}, 1.0)
        == "patience"
    )
    # a gain smaller than min_delta does not count as progress
    assert ev.best_epoch(rows(1.0, 0.995, 0.994), 0.01) == 1
    assert ev.best_epoch(rows(1.0, 0.9, 0.95), 0.01) == 2


def test_the_visiting_order_is_a_seeded_permutation():
    a, b = ev.epoch_order(50, 3, 1), ev.epoch_order(50, 3, 1)
    assert (a == b).all() and sorted(a.tolist()) == list(range(50))
    assert (a != ev.epoch_order(50, 3, 2)).any() and (a != ev.epoch_order(50, 4, 1)).any()


def test_analysis_numbers_are_consistent(tmp_path):
    dataset = make_dataset(tmp_path / "ds")
    train, validation = ev.load_split(dataset, "train"), ev.load_split(dataset, "validation")
    result = ev.analyse(random_net(3), validation, ev.action_rates(train))
    assert result["groups"] == 10 and result["examples"] == 30 and result["scenario_share"] == 1.0
    assert 0.0 <= result["choice_accuracy"] <= result["ceiling_accuracy"] == 1.0
    assert 0.0 <= result["pair_ece"] <= 1.0 and result["pair_log_loss"] > 0.0
    # "answer" is good exactly when coverage is high, so action rates alone get most right
    assert result["majority_by_action_accuracy"] >= 0.6


def test_a_consistent_run_passes_the_intake(tmp_path):
    dataset = make_dataset(tmp_path / "ds")
    run, config = make_run(tmp_path, dataset)
    result = intake(run, dataset, config)
    assert failed(result) == set(), result
    assert result["run read only train and validation"] == "PASS"
    assert result["recorded validation numbers reproduce from the weights"] == "PASS"
    assert result["temperature and threshold are the validation fit"] == "PASS"


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        ("config", "run used the prepared config"),
        ("sealed", "sealed files unchanged"),
        ("splits", "run read only train and validation"),
        ("late-seal", "dataset sealed before the run started"),
        ("log", "log has one contiguous line per epoch"),
        ("net", "network file matches the run record"),
        ("budget", "epoch budget respected"),
        (
            "reason",
            "stop rules replayed on the log give the recorded epoch and reason",
        ),
        ("failed", "run completed"),
    ],
)
def test_the_intake_rejects_a_run_that_does_not_match(tmp_path, tamper, expected):
    dataset = make_dataset(tmp_path / "ds")
    run, config = make_run(tmp_path, dataset)
    record = json.loads((run / "run.json").read_text())
    if tamper == "config":
        config.write_text(config.read_text().replace('"seed": 170', '"seed": 171'))
    elif tamper == "sealed":
        with (dataset / "heldout.jsonl").open("a") as handle:
            handle.write("\n")
    elif tamper == "splits":
        record["splits_read"] = ["train", "validation", "heldout"]
    elif tamper == "late-seal":
        record["started_at"] = "2026-10-01T00:00:00+00:00"
    elif tamper == "log":
        lines = (run / "train-log.jsonl").read_text().splitlines()
        (run / "train-log.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    elif tamper == "net":
        net = random_net(8)
        (run / "net.json").write_text(dumps(net))
    elif tamper == "budget":
        record["best_epoch"] = 3
        shutil.copy(run / "train-log.jsonl", tmp_path / "log.bak")
        history = [json.loads(x) for x in (run / "train-log.jsonl").read_text().splitlines()]
        history += [{**history[-1], "epoch": 7 + i, "seconds": 20.0 + i} for i in range(50)]
        (run / "train-log.jsonl").write_text("".join(json.dumps(h) + "\n" for h in history))
        record["epochs_run"] = len(history)
    elif tamper == "reason":
        record["stop_reason"] = "max_epochs"
    elif tamper == "failed":
        record["status"] = "failed"
    (run / "run.json").write_text(json.dumps(record))
    assert expected in failed(intake(run, dataset, config))


def test_the_intake_report_and_exit_status(tmp_path, capsys):
    dataset = make_dataset(tmp_path / "ds")
    run, config = make_run(tmp_path, dataset)
    report = tmp_path / "report.json"
    args = [
        "--run",
        str(run),
        "--dataset",
        str(dataset),
        "--config",
        str(config),
        "--report",
        str(report),
    ]
    assert INTAKE.main(args) == 0
    assert json.loads(report.read_text())["result"] == "PASS"
    assert "NOT QUALIFIED" in capsys.readouterr().out
    (dataset / "train.jsonl").write_text("")
    assert INTAKE.main(args) == 1
