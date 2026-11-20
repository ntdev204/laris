#!/usr/bin/env python3
"""Owner run of T170: trains the decision network on the ``train`` split of a decision dataset.

THE AGENT NEVER RUNS THIS FILE (SR-M3, AGENTS.md). The owner runs it, on the owner's machine:

    LARIS_TRAINING_AUTHORIZED=1 python scripts/train_decision_net.py \
        --config configs/decision-net-training.json --dataset DIR --out RUNDIR

``DIR`` is the dataset of ``cargo xtask decision-data`` (verify it first); ``RUNDIR`` must be new.
The run reads only ``train.jsonl`` and ``validation.jsonl``; the sealed held-out splits are never
opened. Every tunable comes from the config file (no defaults). The budget and the stop rules are in
the config: ``max_epochs``, ``max_seconds``, ``patience`` with ``min_delta``, ``divergence_factor``
and ``max_parameters``. Outputs in ``RUNDIR``: ``net.json`` (the best epoch, calibrated on the
validation split), ``train-log.jsonl`` (one line per epoch) and ``run.json`` (the record that
``scripts/decision_net_intake.py`` checks). Nothing is written under Git-tracked paths.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from laris.model.decision import evaluation as ev  # noqa: E402
from laris.model.decision.network import torch_module  # noqa: E402
from laris.shared.core.authorization import assert_training_authorized  # noqa: E402


def read_inputs(config_path: Path, dataset: Path) -> tuple[dict, ev.Split, ev.Split, dict]:
    """The checked config, the two readable splits and the checksums that the run record needs."""
    config = ev.read_json(config_path)
    problems = ev.check_config(config)
    if problems:
        raise SystemExit("config: " + "; ".join(problems))
    if ev.parameter_count(config["hidden"]) > config["max_parameters"]:
        raise SystemExit("config: the architecture has more parameters than max_parameters")
    train = ev.load_split(dataset, "train")
    validation = ev.load_split(dataset, "validation")
    if not len(train) or not len(validation):
        raise SystemExit("dataset: train and validation must not be empty")
    meta = {
        "dataset_manifest_sha256": ev.sha256_file(dataset / "manifest.json"),
        "seal_sha256": ev.sha256_file(dataset / "seal.json"),
        "config_sha256": ev.sha256_file(config_path),
    }
    return config, train, validation, meta


def descend(config: dict, train: ev.Split, validation: ev.Split, log: Path):
    """The loop that changes the weights. Returns ``(best_net, history, stop_reason, seconds)``.

    Binary cross-entropy on (state, candidate) pairs, Adam with weight decay, mini-batches in the
    seeded order of ``epoch_order``; after every epoch the validation loss is measured without
    gradients, and the weights of the best epoch (by ``best_epoch``) are kept.
    """
    import numpy as np
    import torch
    from torch.nn import functional

    torch.manual_seed(config["seed"])
    torch.set_num_threads(config["threads"])
    model = torch_module(tuple(config["hidden"]))
    optimizer = torch.optim.Adam(
        model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"]
    )
    x = torch.tensor(train.x, dtype=torch.float32)
    y = torch.tensor(train.y, dtype=torch.float32)
    vx = torch.tensor(validation.x, dtype=torch.float32)
    vy = torch.tensor(validation.y, dtype=torch.float32)
    history: list[dict[str, float]] = []
    best_state = copy.deepcopy(model.state_dict())
    best_number = 0
    started = time.monotonic()
    stop: str | None = None
    while stop is None:
        epoch = len(history) + 1
        order = torch.from_numpy(ev.epoch_order(len(train), config["seed"], epoch))
        model.train()
        total = 0.0
        for start in range(0, len(train), config["batch_size"]):
            batch = order[start : start + config["batch_size"]]
            optimizer.zero_grad()
            loss = functional.binary_cross_entropy_with_logits(model(x[batch]), y[batch])
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(batch)
        model.eval()
        with torch.no_grad():
            validation_loss = float(functional.binary_cross_entropy_with_logits(model(vx), vy))
        history.append(
            {
                "epoch": epoch,
                "seconds": time.monotonic() - started,
                "train_loss": total / len(train),
                "validation_loss": validation_loss,
            }
        )
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history[-1], sort_keys=True) + "\n")
        number = ev.best_epoch(history, config["min_delta"])
        if number != best_number and np.isfinite(validation_loss):
            best_number, best_state = number, copy.deepcopy(model.state_dict())
        stop = ev.stop_reason(history, config, time.monotonic() - started)
    model.load_state_dict(best_state)
    return model.to_net(), history, stop, time.monotonic() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    assert_training_authorized("decision network training (T170)")
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; a run never overwrites another run")
    config, train, validation, meta = read_inputs(args.config, args.dataset)
    args.out.mkdir(parents=True)
    log = args.out / "train-log.jsonl"
    log.write_text("", encoding="utf-8")
    started_at = datetime.now(UTC).isoformat(timespec="seconds")

    import numpy
    import torch

    versions = {
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "torch": torch.__version__,
    }
    net, history, stop, seconds = descend(config, train, validation, log)
    meta.update({"started_at": started_at, "seconds": seconds, "versions": versions})
    if stop in ev.STOP_REASONS:
        net_json, record = ev.finish_run(net, train, validation, config, history, stop, meta)
        (args.out / "net.json").write_text(net_json, encoding="utf-8")
    else:  # the run failed; no network is exported
        record = {
            "format": ev.RUN_FORMAT,
            "version": ev.RUN_VERSION,
            "status": "failed",
            "stop_reason": stop,
            "splits_read": list(ev.READABLE_SPLITS),
            "epochs_run": len(history),
            **{
                k: meta[k]
                for k in (
                    "dataset_manifest_sha256",
                    "seal_sha256",
                    "config_sha256",
                    "started_at",
                    "seconds",
                    "versions",
                )
            },
        }
    (args.out / "run.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"stopped: {stop} after {len(history)} epochs, {seconds:.1f} s; "
        f"run record in {args.out}/run.json"
    )
    return 0 if stop in ev.STOP_REASONS else 1


if __name__ == "__main__":
    raise SystemExit(main())
