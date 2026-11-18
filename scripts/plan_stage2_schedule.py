#!/usr/bin/env python3
"""Expected draws, updates and passes per task for a stage-2 config (T203). Computed, not measured.

Reads only the Parquet footers of the train split (row counts) and a training YAML; builds the
scheduler exactly as the trainer does (alpha, floors, active tasks) and, for `tasks_per_step`
different tasks per micro-step, the chance that each task is in a micro-step. Nothing trains.

Usage:
    .venv/bin/python -I scripts/plan_stage2_schedule.py \
        --config configs/language_encoder/english_r1_stage2.yaml \
        --config configs/language_encoder/english_r1_stage2_control.yaml \
        --report reports/verification/T203-stage2-schedule.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.shared.config.schemas import TrainingConfig  # noqa: E402
from laris.shared.language.loading.dataloader import (  # noqa: E402
    CONTRASTIVE_SIM_TASK,
    RETRIEVAL_TASK,
    StreamingParquetMultiTaskDataLoader,
    TemperatureSamplingScheduler,
    task_inclusion_probabilities,
)


def plan_config(
    path: Path, steps: List[int], micro_batch: Optional[int], grad_accum: Optional[int]
) -> Dict[str, Any]:
    hyper = TrainingConfig(**yaml.safe_load(path.read_text())["training"])
    micro_batch = micro_batch or hyper.micro_batch_size  # the YAML unless given on the command line
    grad_accum = grad_accum or hyper.gradient_accumulation_steps
    loader = StreamingParquetMultiTaskDataLoader(
        split="train",
        include_retrieval_task=hyper.retrieval_task,
        include_contrastive_sim_task=hyper.contrastive_sim_task,
        fallback_to_synthetic=False,
        alpha=hyper.task_sampling_alpha,
        task_sampling_floor=hyper.task_sampling_floor,
        seed=0,
    )
    counts = loader._count_rows()
    scheduler = TemperatureSamplingScheduler(
        {t: counts[t] for t in loader.task_paths},
        alpha=hyper.task_sampling_alpha,
        floors=hyper.task_sampling_floor,
    )
    k = hyper.tasks_per_step
    inclusion = task_inclusion_probabilities(scheduler.tasks, scheduler.probabilities, k)
    rows_per_draw = {t: micro_batch for t in scheduler.tasks}
    rows_per_draw[RETRIEVAL_TASK] = hyper.retrieval_batch_size or micro_batch
    rows_per_draw[CONTRASTIVE_SIM_TASK] = hyper.contrastive_sim_batch_size or micro_batch
    tasks: Dict[str, Any] = {}
    for task, prob in zip(scheduler.tasks, scheduler.probabilities):
        q = inclusion[task]  # chance the task is in one micro-step
        entry: Dict[str, Any] = {
            "train_rows": counts[task],
            "scheduler_probability": round(prob, 4),
            "draw_share": round(q / k, 4),
            "rows_per_draw": rows_per_draw[task],
        }
        for n in steps:
            micro_steps = n * grad_accum
            draws = micro_steps * q
            entry[f"steps_{n}"] = {
                "draws": round(draws, 1),
                "updates_with_task": round(n * (1 - (1 - q) ** grad_accum), 1),
                "rows_seen": round(draws * rows_per_draw[task]),
                "passes": round(draws * rows_per_draw[task] / counts[task], 3),
            }
        tasks[task] = entry
    return {
        "config": str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        "alpha": hyper.task_sampling_alpha,
        "floors": hyper.task_sampling_floor,
        "tasks_per_step": k,
        "micro_batch_size": micro_batch,
        "grad_accum": grad_accum,
        "draws_per_optimizer_step": grad_accum * k,
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", action="append", required=True, type=Path)
    parser.add_argument("--steps", type=int, nargs="+", default=[5000, 20000])
    parser.add_argument("--micro-batch-size", type=int, default=None, help="default: from the YAML")
    parser.add_argument("--grad-accum-steps", type=int, default=None, help="default: from the YAML")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = [
        plan_config(
            path if path.is_absolute() else REPO_ROOT / path,
            args.steps,
            args.micro_batch_size,
            args.grad_accum_steps,
        )
        for path in args.config
    ]
    for plan in result:
        print(f"\n{plan['config']}  alpha {plan['alpha']}  tasks/step {plan['tasks_per_step']}")
        for task, e in sorted(plan["tasks"].items()):
            cols = "  ".join(
                f"{n}: {e[f'steps_{n}']['draws']:>9.0f} draws "
                f"{e[f'steps_{n}']['passes']:>7.3f} passes"
                for n in args.steps
            )
            head = f"  {task:<16} p {e['scheduler_probability']:.3f} share {e['draw_share']:.3f}"
            print(f"{head}  {cols}")
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
