"""The task-sampling temperature is a recorded training setting, default 0.7 as in R1 and R2."""

import pytest
from pydantic import ValidationError

from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.loading.dataloader import (
    StreamingParquetMultiTaskDataLoader,
    TemperatureSamplingScheduler,
)

COUNTS = {
    "mlm": 5_414_554,
    "nli": 1_200_353,
    "paraphrase": 379_753,
    "qa": 196_620,
    "similarity": 25_174,
}


def test_default_alpha_is_the_value_the_earlier_rounds_used() -> None:
    assert TrainingConfig().task_sampling_alpha == 0.7


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, float("nan"), float("inf")])
def test_alpha_outside_zero_to_one_is_rejected(bad: float) -> None:
    with pytest.raises(ValidationError):
        TrainingConfig(task_sampling_alpha=bad)


def test_lower_alpha_gives_the_small_tasks_a_larger_share() -> None:
    def share(alpha: float) -> dict:
        sched = TemperatureSamplingScheduler(COUNTS, alpha=alpha)
        return dict(zip(sched.tasks, sched.probabilities))

    high, low = share(0.7), share(0.4)
    assert high["similarity"] == pytest.approx(0.0143, abs=5e-4)
    assert low["similarity"] > high["similarity"] * 2
    assert low["mlm"] < high["mlm"]


def test_loader_uses_the_configured_alpha(tmp_path) -> None:
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path, fallback_to_synthetic=True, alpha=0.4
    )
    assert loader.scheduler.alpha == pytest.approx(0.4)
