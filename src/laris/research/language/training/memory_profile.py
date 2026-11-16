"""Measured GPU memory and latency profile of the real model on real batches.

Batches come from the real train split through the real tokenizer, so shapes, padding and
labels are exactly what training sees. Without authorization only the forward pass of every
task is measured, without gradients. When the owner has authorized training, two full
accumulation windows are run: window one ends in a real optimizer step so the optimizer state
is allocated, window two is measured with that state resident (the steady-state peak). The
model is randomly initialised and discarded; nothing is saved.

With `tasks_per_step` > 1 (T201) the profile also runs every combination of that many different
tasks as one mixed step (the losses are added and one backward pass covers them, as in
training), each with its own peak counter, so the worst group is measured and not estimated.
"""

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple

TASKS = ("mlm", "nli", "paraphrase", "similarity", "qa")
_GIB = 1024.0**3


@dataclass
class TaskMeasurement:
    task_type: str
    peak_allocated_gb: float
    loss_finite: bool


@dataclass
class GroupMeasurement:
    """One mixed step (T201): different tasks whose losses were added before the backward."""

    tasks: Tuple[str, ...]
    peak_allocated_gb: float
    loss_finite: bool


def resident_state_gb(parameters: int, eight_bit_optimizer: bool = False) -> float:
    """Weights, gradients and AdamW state that stay allocated between steps (GiB).

    fp32 master weights and gradients (4 B each) plus two fp32 moments (8 B), or two 8-bit
    moments (2 B) with the 8-bit optimiser; activations are not included.
    """
    return parameters * (4 + 4 + (2 if eight_bit_optimizer else 8)) / _GIB


def estimate_mixed_peak_gb(
    single_task_peaks_gb: Mapping[str, float], resident_gb: float, tasks_per_step: int
) -> float:
    """Worst-case peak of a mixed step from single-task peaks (an estimate, not a measurement).

    Each task's activation memory is its single-task peak minus the resident state; the graphs
    of all tasks of a step are alive at the backward pass, so the activations of the
    `tasks_per_step` most expensive tasks add up on top of the resident state. A single-task peak
    that is a running maximum (as in the T184 log) overstates the later tasks: the estimate then
    errs high. Allocator fragmentation is not modelled.
    """
    if tasks_per_step < 1 or tasks_per_step > len(single_task_peaks_gb):
        raise ValueError(f"tasks_per_step must be 1 to {len(single_task_peaks_gb)}")
    activations = sorted(
        (max(peak - resident_gb, 0.0) for peak in single_task_peaks_gb.values()), reverse=True
    )
    return resident_gb + sum(activations[:tasks_per_step])


@dataclass
class TrainingMemoryProfile:
    gpu_name: str
    total_vram_gb: float
    limit_gb: float
    steady_state: bool
    tasks: List[TaskMeasurement] = field(default_factory=list)
    peak_gb: float = 0.0
    seconds_per_micro_batch: float = 0.0
    seconds_per_optimizer_update: Optional[float] = None
    optimizer_steps: int = 0
    error: Optional[str] = None
    tasks_per_step: int = 1
    groups: List[GroupMeasurement] = field(default_factory=list)
    seconds_per_group_step: Optional[float] = None

    @property
    def fits(self) -> bool:
        return (
            self.error is None
            and bool(self.tasks)
            and all(t.loss_finite for t in self.tasks)
            and all(g.loss_finite for g in self.groups)
            and self.peak_gb <= self.limit_gb
        )

    @property
    def certified(self) -> bool:
        """Training memory is certified only by a measured steady-state window."""
        return self.fits and self.steady_state


def profile_training_memory(
    trainer: Any,
    loader: Any,
    limit_gb: float,
    with_training_step: bool = False,
    tasks_per_step: int = 1,
) -> TrainingMemoryProfile:
    """Measures peak CUDA memory per task on real batches; see the module docstring."""
    import torch

    props = torch.cuda.get_device_properties(0)
    profile = TrainingMemoryProfile(
        gpu_name=props.name,
        total_vram_gb=props.total_memory / _GIB,
        limit_gb=limit_gb,
        steady_state=with_training_step,
        tasks_per_step=tasks_per_step,
    )
    model = trainer.model
    model.train(with_training_step)
    # the retrieval and contrastive tasks exist only in runs that enable them
    tasks = TASKS + tuple(t for t in ("retrieval", "contrastive_sim") if t in loader.task_paths)

    if not 1 <= tasks_per_step <= len(tasks):
        raise ValueError(f"tasks_per_step must be 1 to {len(tasks)} (the tasks measured)")

    def step(*names: str) -> Any:
        """One micro-step: the losses of `names` are added, one backward covers the sum."""
        grad = torch.enable_grad() if with_training_step else torch.no_grad()
        losses = []
        for task in names:
            batch = loader.generate_batch(task)
            if batch.task_type != task:
                raise RuntimeError(f"Requested task '{task}' but received '{batch.task_type}'")
            token_ids, attention_mask = trainer._to_device(batch)
            with grad, trainer._autocast():
                outputs = trainer._forward(
                    task, token_ids, attention_mask, batch.labels,
                    training_pass=with_training_step,
                )
                losses.append(
                    trainer._compute_torch_loss(task, outputs, batch.labels, attention_mask)
                )
        loss = sum(losses[1:], losses[0])
        if with_training_step:
            scaled = loss / trainer.grad_accum_steps
            if trainer.scaler is not None:  # fp16: the optimizer step unscales these gradients
                scaled = trainer.scaler.scale(scaled)
            scaled.backward()
        torch.cuda.synchronize()
        return loss.detach()

    def window() -> float:
        started = time.perf_counter()
        for task in tasks:
            torch.cuda.reset_peak_memory_stats()  # each task's peak stands alone (T201)
            loss = step(task)
            profile.tasks.append(
                TaskMeasurement(
                    task_type=task,
                    peak_allocated_gb=torch.cuda.max_memory_allocated() / _GIB,
                    loss_finite=bool(torch.isfinite(loss.float()).item()),
                )
            )
        return (time.perf_counter() - started) / len(tasks)

    try:
        if with_training_step:
            window()  # warm-up window: allocates gradients, then the optimizer state
            trainer._optimizer_update()
            profile.optimizer_steps = trainer.optimizer_steps
            if profile.optimizer_steps == 0:
                profile.error = "Optimizer step skipped (non-finite gradients); state not allocated"
                return profile
            profile.tasks.clear()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        profile.seconds_per_micro_batch = window()
        profile.peak_gb = max(t.peak_allocated_gb for t in profile.tasks)
        if tasks_per_step > 1:
            started = time.perf_counter()
            combinations = list(itertools.combinations(tasks, tasks_per_step))
            for names in combinations:
                torch.cuda.reset_peak_memory_stats()
                loss = step(*names)
                profile.groups.append(
                    GroupMeasurement(
                        tasks=names,
                        peak_allocated_gb=torch.cuda.max_memory_allocated() / _GIB,
                        loss_finite=bool(torch.isfinite(loss.float()).item()),
                    )
                )
            profile.seconds_per_group_step = (time.perf_counter() - started) / len(combinations)
            profile.peak_gb = max(profile.peak_gb, max(g.peak_allocated_gb for g in profile.groups))
        if with_training_step:
            started = time.perf_counter()
            trainer._optimizer_update()
            torch.cuda.synchronize()
            profile.seconds_per_optimizer_update = time.perf_counter() - started
            profile.peak_gb = max(profile.peak_gb, torch.cuda.max_memory_allocated() / _GIB)
    except torch.cuda.OutOfMemoryError as exc:
        profile.error = f"CUDA out of memory: {exc}"
    finally:
        model.zero_grad(set_to_none=True)
        torch.cuda.empty_cache()
    return profile
