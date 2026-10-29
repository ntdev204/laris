"""Learning-rate schedule: linear warmup followed by cosine decay."""

import math
from typing import Any


def warmup_cosine_factor(
    step: int, warmup_steps: int, total_steps: int, min_lr_ratio: float = 0.1
) -> float:
    """Multiplier in (0, 1] applied to the base learning rate at an optimizer step."""
    if total_steps < 1:
        raise ValueError("total_steps must be >= 1")
    if warmup_steps > 0 and step < warmup_steps:
        return (step + 1) / warmup_steps
    decay_span = max(1, total_steps - warmup_steps)
    progress = min(1.0, max(0.0, (step - warmup_steps) / decay_span))
    cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr_ratio + (1.0 - min_lr_ratio) * cosine


def build_warmup_cosine_scheduler(
    optimizer: Any,
    warmup_steps: int,
    total_steps: int,
    min_lr_ratio: float = 0.1,
) -> Any:
    """LambdaLR implementing `warmup_cosine_factor`; call `.step()` once per optimizer step."""
    import torch

    return torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: warmup_cosine_factor(step, warmup_steps, total_steps, min_lr_ratio),
    )
