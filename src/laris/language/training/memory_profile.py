"""Measured GPU memory and latency profile of the real model on real batches.

Batches come from the real train split through the real tokenizer, so shapes, padding and
labels are exactly what training sees. Without authorization only the forward pass of every
task is measured, without gradients. When the owner has authorized training, two full
accumulation windows are run: window one ends in a real optimizer step so the optimizer state
is allocated, window two is measured with that state resident (the steady-state peak). The
model is randomly initialised and discarded; nothing is saved.
"""

import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

TASKS = ("mlm", "nli", "paraphrase", "similarity", "qa")
_GIB = 1024.0**3


@dataclass
class TaskMeasurement:
    task_type: str
    peak_allocated_gb: float
    loss_finite: bool


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

    @property
    def fits(self) -> bool:
        return (
            self.error is None
            and bool(self.tasks)
            and all(t.loss_finite for t in self.tasks)
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
) -> TrainingMemoryProfile:
    """Measures peak CUDA memory per task on real batches; see the module docstring."""
    import torch

    props = torch.cuda.get_device_properties(0)
    profile = TrainingMemoryProfile(
        gpu_name=props.name,
        total_vram_gb=props.total_memory / _GIB,
        limit_gb=limit_gb,
        steady_state=with_training_step,
    )
    model = trainer.model
    model.train(with_training_step)

    def step(task: str) -> Any:
        batch = loader.generate_batch(task)
        if batch.task_type != task:
            raise RuntimeError(f"Requested task '{task}' but received '{batch.task_type}'")
        token_ids, attention_mask = trainer._to_device(batch)
        grad = torch.enable_grad() if with_training_step else torch.no_grad()
        with grad, trainer._autocast():
            outputs = model(
                token_ids, attention_mask=attention_mask, training_pass=with_training_step
            )
            loss = trainer._compute_torch_loss(task, outputs, batch.labels)
        if with_training_step:
            (loss / trainer.grad_accum_steps).backward()
        torch.cuda.synchronize()
        return loss.detach()

    def window() -> float:
        started = time.perf_counter()
        for task in TASKS:
            loss = step(task)
            profile.tasks.append(
                TaskMeasurement(
                    task_type=task,
                    peak_allocated_gb=torch.cuda.max_memory_allocated() / _GIB,
                    loss_finite=bool(torch.isfinite(loss.float()).item()),
                )
            )
        return (time.perf_counter() - started) / len(TASKS)

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
        profile.peak_gb = torch.cuda.max_memory_allocated() / _GIB
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
