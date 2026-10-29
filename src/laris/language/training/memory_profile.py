"""Measured GPU memory and latency profile of the real model (no optimizer step).

Always runs the forward pass of every task on the target device at the real micro-batch and
sequence length without gradients, which needs no authorization. When the owner has
authorized training it also runs backward, with gradients kept across tasks as under
gradient accumulation. The optimizer is never stepped, so no weight is updated; its state
size is added analytically.
"""

import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from laris.language.training.dataloader import SyntheticMultiTaskDataLoader

TASKS = ("mlm", "nli", "paraphrase", "similarity", "qa")
_GIB = 1024.0**3


@dataclass
class TaskMeasurement:
    task_type: str
    peak_allocated_gb: float
    loss_finite: bool


@dataclass
class TrainingMemoryProfile:
    device: str
    gpu_name: str
    total_vram_gb: float
    param_count: int
    limit_gb: float
    tasks: List[TaskMeasurement] = field(default_factory=list)
    measured_peak_gb: float = 0.0
    optimizer_state_gb: float = 0.0
    seconds_per_micro_batch: float = 0.0
    backward_measured: bool = False
    error: Optional[str] = None

    @property
    def projected_peak_gb(self) -> float:
        return self.measured_peak_gb + self.optimizer_state_gb

    @property
    def fits(self) -> bool:
        """True when everything measured is finite and within the limit."""
        peak = self.projected_peak_gb if self.backward_measured else self.measured_peak_gb
        return (
            self.error is None
            and bool(self.tasks)
            and all(t.loss_finite for t in self.tasks)
            and peak <= self.limit_gb
        )

    @property
    def certified(self) -> bool:
        """Training memory is only certified once backward has been measured."""
        return self.fits and self.backward_measured


def optimizer_state_gb(param_count: int, use_8bit_adam: bool) -> float:
    """bitsandbytes AdamW8bit keeps two 1-byte states per parameter; AdamW two fp32 states."""
    return param_count * (2 if use_8bit_adam else 8) / _GIB


def profile_training_memory(
    trainer: Any,
    param_count: int,
    batch_size: int,
    seq_len: int,
    vocab_size: int,
    use_8bit_adam: bool,
    limit_gb: float,
    seed: int = 42,
    with_backward: bool = False,
) -> TrainingMemoryProfile:
    """Measures peak CUDA memory per task, forward and optionally backward; no optimizer step."""
    import torch

    props = torch.cuda.get_device_properties(0)
    profile = TrainingMemoryProfile(
        device="cuda",
        gpu_name=props.name,
        total_vram_gb=props.total_memory / _GIB,
        param_count=param_count,
        limit_gb=limit_gb,
        optimizer_state_gb=optimizer_state_gb(param_count, use_8bit_adam),
        backward_measured=with_backward,
    )
    loader = SyntheticMultiTaskDataLoader(
        vocab_size=vocab_size, seq_len=seq_len, batch_size=batch_size, seed=seed
    )
    model = trainer.model
    model.train(with_backward)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    def step(task: str) -> Any:
        batch = loader.generate_batch(task)
        token_ids, attention_mask = trainer._to_device(batch)
        grad = torch.enable_grad() if with_backward else torch.no_grad()
        with grad, trainer._autocast():
            outputs = model(
                token_ids, attention_mask=attention_mask, training_pass=with_backward
            )
            loss = trainer._compute_torch_loss(task, outputs, batch.labels)
        if with_backward:
            loss.backward()
        torch.cuda.synchronize()
        return loss.detach()

    try:
        for task in TASKS:
            loss = step(task)
            profile.tasks.append(
                TaskMeasurement(
                    task_type=task,
                    peak_allocated_gb=torch.cuda.max_memory_allocated() / _GIB,
                    loss_finite=bool(torch.isfinite(loss.float()).item()),
                )
            )
        profile.measured_peak_gb = torch.cuda.max_memory_allocated() / _GIB

        start = time.perf_counter()  # timed pass, kernels already warm
        step("mlm")
        profile.seconds_per_micro_batch = time.perf_counter() - start
    except torch.cuda.OutOfMemoryError as exc:
        profile.error = f"CUDA out of memory at batch {batch_size} x seq {seq_len}: {exc}"
    finally:
        model.zero_grad(set_to_none=True)
        torch.cuda.empty_cache()
    return profile
