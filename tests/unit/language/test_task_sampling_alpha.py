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


def _shares(**kwargs):
    sched = TemperatureSamplingScheduler(COUNTS, alpha=0.7, **kwargs)
    return {t: sched.get_task_probability(t) for t in COUNTS}


def test_floor_lifts_a_small_task_and_keeps_the_others_proportional() -> None:
    base = _shares()
    assert base["similarity"] < 0.03
    lifted = _shares(floors={"similarity": 0.03})
    assert lifted["similarity"] == pytest.approx(0.03)
    assert sum(lifted.values()) == pytest.approx(1.0)
    ratio = lifted["mlm"] / base["mlm"]
    for task in ("mlm", "nli", "paraphrase", "qa"):
        assert lifted[task] / base[task] == pytest.approx(ratio)


def test_floor_below_the_natural_share_changes_nothing() -> None:
    assert _shares(floors={"mlm": 0.01}) == pytest.approx(_shares())


def test_two_floors_hold_together() -> None:
    lifted = _shares(floors={"similarity": 0.05, "qa": 0.10})
    assert lifted["similarity"] == pytest.approx(0.05)
    assert lifted["qa"] == pytest.approx(0.10)
    assert sum(lifted.values()) == pytest.approx(1.0)


def test_floor_of_an_inactive_task_is_ignored() -> None:
    assert _shares(floors={"retrieval": 0.2}) == pytest.approx(_shares())


@pytest.mark.parametrize(
    "floors", [{"qa": 1.0}, {"qa": -0.1}, {"qa": float("nan")}, {"qa": 0.6, "nli": 0.5}]
)
def test_invalid_floors_are_rejected(floors) -> None:
    with pytest.raises(ValueError):
        TemperatureSamplingScheduler(COUNTS, alpha=0.7, floors=floors)


def test_floor_is_a_training_setting_empty_by_default() -> None:
    assert TrainingConfig().task_sampling_floor == {}
    config = TrainingConfig(task_sampling_floor={"similarity": 0.03})
    assert config.task_sampling_floor == {"similarity": 0.03}
