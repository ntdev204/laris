#!/usr/bin/env python3
"""Intake of an owner run of the decision network (T170, ADR-024 9.2). Read-only: it trains nothing.

    python scripts/decision_net_intake.py --run RUNDIR --dataset DIR --config FILE [--report FILE]

It checks that the logs, the run record, the exported network and the dataset agree with each other
and with the prepared command, then repeats the validation analysis from the exported weights. It
reads only the ``train`` and ``validation`` splits; the sealed files are hashed (never parsed) to
show they did not change. Exit status 0 when every check passes, 1 otherwise. A pass is an intake
result, not a promotion: gates N1-N8 are measured on the sealed split in T171 and the network stays
NOT QUALIFIED until then.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.model.decision import evaluation as ev  # noqa: E402
from laris.model.decision.network import NetworkError, load  # noqa: E402

TOLERANCE = 1e-6
Check = tuple[str, str, str]  # (status, name, detail)


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= TOLERANCE


def check_run(
    run_dir: Path, dataset: Path, config_path: Path
) -> tuple[list[Check], dict[str, Any]]:
    """Every check as ``(PASS|FAIL|WARN, name, detail)`` and the repeated validation analysis."""
    checks: list[Check] = []

    def add(ok: bool, name: str, detail: str = "", warn: bool = False) -> bool:
        checks.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail))
        return ok

    analysis: dict[str, Any] = {}
    try:
        record = ev.read_json(run_dir / "run.json")
        config = ev.read_json(config_path)
        manifest = ev.read_json(dataset / "manifest.json")
        seal = ev.read_json(dataset / "seal.json")
    except (OSError, ValueError) as error:
        add(False, "inputs readable", str(error))
        return checks, analysis
    add(
        record.get("format") == ev.RUN_FORMAT and record.get("version") == ev.RUN_VERSION,
        "run record format",
    )
    problems = ev.check_config(config)
    add(not problems, "config is complete", "; ".join(problems))
    if problems:
        return checks, analysis

    # the prepared command: the run used this config and this dataset
    add(record.get("config_sha256") == ev.sha256_file(config_path), "run used the prepared config")
    add(
        record.get("dataset_manifest_sha256") == ev.sha256_file(dataset / "manifest.json"),
        "run used this dataset manifest",
    )
    add(
        record.get("seal_sha256") == ev.sha256_file(dataset / "seal.json"),
        "seal unchanged since the run",
    )
    add(
        record.get("splits_read") == list(ev.READABLE_SPLITS),
        "run read only train and validation",
        f"splits_read={record.get('splits_read')}",
    )

    # the seal: written before the run, and the sealed files are what the seal says
    sealed = [
        f"{name}.jsonl:{manifest['files'][name + '.jsonl']['sha256']}"
        for name in ev.SEALED_SPLITS
        if name + ".jsonl" in manifest.get("files", {})
    ]
    add(
        seal.get("files_sha256") == hashlib.sha256("\n".join(sealed).encode()).hexdigest(),
        "seal matches the manifest",
    )
    drift = [
        name
        for name in ev.SEALED_SPLITS
        if name + ".jsonl" in manifest.get("files", {})
        and (
            not (dataset / f"{name}.jsonl").exists()
            or ev.sha256_file(dataset / f"{name}.jsonl")
            != manifest["files"][name + ".jsonl"]["sha256"]
        )
    ]
    add(not drift, "sealed files unchanged", ", ".join(drift))
    started = str(record.get("started_at", ""))[:10]
    add(
        bool(started)
        and str(manifest.get("date", "9999")) <= started
        and str(seal.get("date", "9999")) <= started,
        "dataset sealed before the run started",
        f"manifest {manifest.get('date')}, seal {seal.get('date')}, run {started}",
    )

    # the loop: status, budget and stop rules against the log
    status_ok = add(
        record.get("status") == "complete", "run completed", f"status={record.get('status')}"
    )
    reason = record.get("stop_reason")
    add(reason in ev.STOP_REASONS, "stopped by a budget or patience rule", f"stop_reason={reason}")
    try:
        history = [
            json.loads(line)
            for line in (run_dir / "train-log.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as error:
        add(False, "train log readable", str(error))
        return checks, analysis
    add(
        [row.get("epoch") for row in history] == list(range(1, len(history) + 1))
        and len(history) == record.get("epochs_run"),
        "log has one contiguous line per epoch",
        f"{len(history)} lines, record says {record.get('epochs_run')}",
    )
    finite = all(
        isinstance(row.get(k), int | float) and abs(row[k]) != float("inf") and row[k] == row[k]
        for row in history
        for k in ("train_loss", "validation_loss", "seconds")
    )
    add(finite, "every loss in the log is finite")
    if history and finite:
        add(
            all(a["seconds"] <= b["seconds"] for a, b in zip(history, history[1:], strict=False)),
            "log times do not go backwards",
        )
        add(
            len(history) <= config["max_epochs"],
            "epoch budget respected",
            f"{len(history)} of {config['max_epochs']}",
        )
        longest = max(
            b["seconds"] - a["seconds"]
            for a, b in zip([{"seconds": 0.0}, *history], history, strict=False)
        )
        add(
            history[-1]["seconds"] <= config["max_seconds"] + longest,
            "time budget respected (one epoch of slack)",
            f"{history[-1]['seconds']:.0f} s of {config['max_seconds']} s",
        )
        add(
            record.get("best_epoch") == ev.best_epoch(history, config["min_delta"]),
            "recorded best epoch matches the log",
        )
        replay = next(
            (
                i
                for i in range(1, len(history) + 1)
                if ev.stop_reason(history[:i], config, history[i - 1]["seconds"])
            ),
            None,
        )
        expected = (
            ev.stop_reason(history[:replay], config, history[replay - 1]["seconds"])
            if replay
            else None
        )
        add(
            replay == len(history) and expected == reason,
            "stop rules replayed on the log give the recorded epoch and reason",
            f"replay stops at {replay} for {expected}",
        )
    if not status_ok:
        return checks, analysis

    # the exported network
    net_path = run_dir / "net.json"
    try:
        net = load(ev.read_json(net_path))
    except (OSError, ValueError, NetworkError) as error:
        add(False, "network loads", str(error))
        return checks, analysis
    add(True, "network loads with the feature names of this code")
    add(record.get("net_sha256") == ev.sha256_file(net_path), "network file matches the run record")
    add(
        [layer.weights.shape[0] for layer in net.layers] == [*config["hidden"], 1],
        "architecture matches the config",
    )
    add(
        net.parameter_count() == record.get("parameters") == ev.parameter_count(config["hidden"])
        and net.parameter_count() <= config["max_parameters"],
        "parameter count matches and is within the limit",
        f"{net.parameter_count()} of {config['max_parameters']}",
    )
    embedded = ev.read_json(net_path).get("manifest", {})
    add(
        embedded.get("dataset_manifest_sha256") == record.get("dataset_manifest_sha256")
        and embedded.get("config_sha256") == record.get("config_sha256")
        and embedded.get("seed") == config["seed"],
        "network manifest names the same dataset, config and seed",
    )
    add(
        0.25 <= net.temperature <= 8.0 and 0.0 <= net.threshold <= 1.0 + 1e-9,
        "temperature and threshold in range",
        f"T={net.temperature}, threshold={net.threshold}",
    )

    # the validation analysis, repeated from the exported weights
    train = ev.load_split(dataset, "train")
    validation = ev.load_split(dataset, "validation")
    add(
        record.get("train_sha256") == train.sha256
        and record.get("validation_sha256") == validation.sha256,
        "run read the files that are in the dataset",
    )
    rates = ev.action_rates(train)
    analysis = ev.analyse(net, validation, rates)
    recorded = record.get("validation", {})
    mismatched = [
        key
        for key, value in analysis.items()
        if isinstance(value, float | type(None)) and not _close(value, recorded.get(key))
    ]
    add(
        not mismatched,
        "recorded validation numbers reproduce from the weights",
        ", ".join(mismatched),
    )
    temperature, threshold = ev.fit_calibration(net, validation, config["target_precision"])
    add(
        _close(temperature, net.temperature) and _close(threshold, net.threshold),
        "temperature and threshold are the validation fit",
        f"refit T={temperature}, threshold={threshold}",
    )
    add(
        analysis["scenario_share"] == recorded.get("scenario_share"),
        "scenario share stated",
        f"validation scenario share {analysis['scenario_share']:.2f}",
    )
    # informational: signs of a run that learned nothing or memorised
    add(
        analysis["choice_accuracy"] > analysis["majority_by_action_accuracy"],
        "network beats the majority-by-action baseline on validation",
        f"{analysis['choice_accuracy']:.4f} against {analysis['majority_by_action_accuracy']:.4f}",
        warn=True,
    )
    train_loss = history[record["best_epoch"] - 1]["train_loss"] if history else 0.0
    best_validation = history[record["best_epoch"] - 1]["validation_loss"] if history else 0.0
    add(
        best_validation <= 1.5 * max(train_loss, 1e-9),
        "validation loss is not far above train loss",
        f"train {train_loss:.4f}, validation {best_validation:.4f}",
        warn=True,
    )
    return checks, analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        checks, analysis = check_run(args.run, args.dataset, args.config)
    except (ev.SealedSplitError, ev.DatasetError) as error:
        checks, analysis = [("FAIL", "dataset readable", str(error))], {}
    for status, name, detail in checks:
        print(f"[{status}] {name}" + (f": {detail}" if detail else ""))
    failed = [c for c in checks if c[0] == "FAIL"]
    print(
        f"intake: {'FAIL' if failed else 'PASS'} ({len(failed)} failed, "
        f"{sum(c[0] == 'WARN' for c in checks)} warnings)"
    )
    print(
        "This is an intake of an owner run, not a promotion: "
        "the network is NOT QUALIFIED until T171."
    )
    if args.report:
        args.report.write_text(
            json.dumps(
                {"result": "FAIL" if failed else "PASS", "checks": checks, "validation": analysis},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
