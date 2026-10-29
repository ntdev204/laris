"""Train/validation/test ratio configuration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PartitionRatios:
    """Configurable target distribution ratios for dataset splits."""

    train: float = 0.80
    val: float = 0.10
    test: float = 0.10

    def __post_init__(self) -> None:
        if self.train <= 0.0 or self.val <= 0.0 or self.test <= 0.0:
            raise ValueError("All partition ratios must be strictly positive")
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-5:
            raise ValueError(f"Partition ratios must sum to 1.0, got {total:.6f}")
