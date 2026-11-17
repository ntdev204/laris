"""T203: inclusion probabilities of mixed steps and the stage-2 / control configs (no data)."""

import random
from pathlib import Path

import pytest
import yaml

from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.loading.dataloader import (
    TemperatureSamplingScheduler,
    task_inclusion_probabilities,
)

CONFIGS = Path(__file__).resolve().parents[3] / "configs" / "language_encoder"
# Train-split row counts of 2026-11-17 (scripts/plan_stage2_schedule.py), fixed so no data is read.
COUNTS = {
    "mlm": 15_500_570, "nli": 1_670_892, "paraphrase": 1_039_794, "similarity": 23_163,
    "qa": 442_809, "retrieval": 6_373_045, "contrastive_sim": 1_410_056,
}  # fmt: skip


def _training(name: str) -> TrainingConfig:
    return TrainingConfig(**yaml.safe_load((CONFIGS / name).read_text())["training"])


def _scheduler(hyper: TrainingConfig, tasks: list[str]) -> TemperatureSamplingScheduler:
    return TemperatureSamplingScheduler(
        {t: COUNTS[t] for t in tasks}, alpha=hyper.task_sampling_alpha,
        floors=hyper.task_sampling_floor,
    )  # fmt: skip


def test_inclusion_of_one_task_per_step_is_the_probability() -> None:
    probs = [0.5, 0.3, 0.2]
    out = task_inclusion_probabilities(["a", "b", "c"], probs, 1)
    assert out == pytest.approx({"a": 0.5, "b": 0.3, "c": 0.2})


def test_inclusion_of_two_tasks_matches_the_closed_form_and_sums_to_two() -> None:
    probs = [0.5, 0.3, 0.2]
    out = task_inclusion_probabilities(["a", "b", "c"], probs, 2)
    assert sum(out.values()) == pytest.approx(2.0)
    # P(a drawn) = p_a + p_b * p_a/(1-p_b) + p_c * p_a/(1-p_c)
    expected = 0.5 + 0.3 * 0.5 / 0.7 + 0.2 * 0.5 / 0.8
    assert out["a"] == pytest.approx(expected)
    assert out["a"] < 1.0 and out["c"] > 0.2  # large tasks are capped, small ones gain


def test_inclusion_matches_the_scheduler_sampling() -> None:
    sched = _scheduler(_training("english_r1_stage2.yaml"), list(COUNTS))
    exact = task_inclusion_probabilities(sched.tasks, sched.probabilities, 2)
    rng = random.Random(7)
    hits = {t: 0 for t in sched.tasks}
    trials = 30_000
    for _ in range(trials):
        for t in sched.sample_tasks(rng, 2):
            hits[t] += 1
    for task in sched.tasks:
        assert hits[task] / trials == pytest.approx(exact[task], abs=0.01)


@pytest.mark.parametrize("bad", [0, 4])
def test_inclusion_rejects_bad_count(bad: int) -> None:
    with pytest.raises(ValueError):
        task_inclusion_probabilities(["a", "b", "c"], [0.5, 0.3, 0.2], bad)


def test_stage2_config_proposal() -> None:
    hyper = _training("english_r1_stage2.yaml")
    assert hyper.tasks_per_step == 2  # T202 decision
    assert hyper.mlm_pair_fraction > 0 and hyper.order_task and hyper.contrastive_sim_task
    assert hyper.similarity_head == "bi_encoder"
    assert hyper.dataset_sampling_weights["nli"] == {"vitaminc_en": 0.375}  # T207
    sched = _scheduler(hyper, list(COUNTS))
    share = dict(zip(sched.tasks, sched.probabilities))
    assert sum(share.values()) == pytest.approx(1.0)
    for task, floor in hyper.task_sampling_floor.items():
        assert share[task] == pytest.approx(floor)  # every floor binds exactly
    pairs = [share[t] for t in ("nli", "paraphrase", "qa", "similarity", "contrastive_sim")]
    assert sum(pairs) == pytest.approx(0.66)
    draws = task_inclusion_probabilities(sched.tasks, sched.probabilities, 2)
    mlm_draw_share = draws["mlm"] / 2
    assert 0.18 <= mlm_draw_share <= 0.25  # "MLM kept near 20 %"
    assert all(draws[t] / 2 > 0.07 for t in sched.tasks)  # no task is starved


def test_control_is_the_original_mixture_with_the_same_compute() -> None:
    stage2 = _training("english_r1_stage2.yaml")
    control = _training("english_r1_stage2_control.yaml")
    original = _training("english_r1.yaml")
    for field in (
        "max_steps", "warmup_steps", "learning_rate", "batch_size", "micro_batch_size",
        "gradient_accumulation_steps", "tasks_per_step", "max_grad_norm",
    ):  # fmt: skip
        if hasattr(stage2, field):
            assert getattr(control, field) == getattr(stage2, field), field
    # the control keeps the original mixture and heads
    assert control.task_sampling_floor == {"similarity": 0.03}
    assert control.similarity_head == "cross"
    assert not control.order_task and not control.contrastive_sim_task
    assert control.mlm_pair_fraction == 0 and not control.dataset_sampling_weights
    assert control.label_balanced_tasks == []
    for field in ("loss_lambda_mlm", "loss_lambda_nli", "loss_lambda_para", "loss_lambda_sim",
                  "loss_lambda_qa", "loss_lambda_retrieval", "task_sampling_alpha"):  # fmt: skip
        assert getattr(control, field) == getattr(original, field), field


def test_stage2_gives_each_pair_task_more_draws_than_the_control() -> None:
    stage2 = _training("english_r1_stage2.yaml")
    control = _training("english_r1_stage2_control.yaml")
    tasks_control = [t for t in COUNTS if t != "contrastive_sim"]
    s2 = _scheduler(stage2, list(COUNTS))
    c = _scheduler(control, tasks_control)
    d2 = task_inclusion_probabilities(s2.tasks, s2.probabilities, 2)
    dc = task_inclusion_probabilities(c.tasks, c.probabilities, 2)
    for task in ("nli", "paraphrase", "qa", "similarity"):
        assert d2[task] > dc[task]
    assert d2["mlm"] < dc["mlm"]
