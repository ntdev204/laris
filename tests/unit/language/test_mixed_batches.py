"""Mixed batches (T201): several tasks whose losses are added in one micro-step.

Nothing here runs a backward pass or an optimizer step: the forward and loss path, the sampling,
the loop dispatch, the progress folding and the memory bookkeeping are checked on fixtures. The
one test that takes a real step is skipped unless the owner authorises training.
"""

import random
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from laris.research.language.training import loop as loop_module  # noqa: E402
from laris.research.language.training.loop import (  # noqa: E402
    TrainingRunConfig,
    run_training,
)
from laris.research.language.training.memory_profile import (  # noqa: E402
    GroupMeasurement,
    TaskMeasurement,
    TrainingMemoryProfile,
    estimate_mixed_peak_gb,
    resident_state_gb,
)
from laris.research.language.training.progress import TrainingProgress  # noqa: E402
from laris.research.language.training.trainer import LanguageEncoderTrainer  # noqa: E402
from laris.shared.config.schemas import TrainingConfig  # noqa: E402
from laris.shared.core.authorization import (  # noqa: E402
    is_training_authorized,
    temporary_training_authorization,
)
from laris.shared.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.shared.language.loading.dataloader import (  # noqa: E402
    StreamingParquetMultiTaskDataLoader,
    TemperatureSamplingScheduler,
)

from .test_training_loop import _write_tasks  # noqa: E402

COUNTS = {"mlm": 1000, "nli": 500, "paraphrase": 200, "similarity": 20, "qa": 100}


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    _write_tasks(tmp_path, "train")
    return tmp_path


def _loader(data_dir: Path, seed: int = 7) -> StreamingParquetMultiTaskDataLoader:
    return StreamingParquetMultiTaskDataLoader(
        data_dir=data_dir, vocab_size=500, seq_len=32, batch_size=2, return_tensors="pt",
        split="train", fallback_to_synthetic=False, seed=seed,
    )


def _trainer(loader, accumulation: int = 1) -> LanguageEncoderTrainer:
    torch.manual_seed(0)
    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, max_sequence_length=32, vocab_size=500
    )
    return LanguageEncoderTrainer(
        model=PyTorchTransformerEncoder(cfg), config=cfg, dataloader=loader,
        use_8bit_adam=False, grad_accum_steps=accumulation, device="cpu",
    )


# --- sampling -------------------------------------------------------------------------------


def test_one_task_draw_is_the_old_draw() -> None:
    scheduler = TemperatureSamplingScheduler(COUNTS)
    old, new = random.Random(3), random.Random(3)
    assert [scheduler.sample_task(old) for _ in range(50)] == [
        scheduler.sample_tasks(new, 1)[0] for _ in range(50)
    ]
    assert old.getstate() == new.getstate()  # the same RNG use, so the default path is unchanged


def test_tasks_of_a_step_are_different_and_seed_stable() -> None:
    scheduler = TemperatureSamplingScheduler(COUNTS)
    first = [scheduler.sample_tasks(rng, 3) for rng in [random.Random(5)] for _ in range(40)]
    rng_a, rng_b = random.Random(5), random.Random(5)
    run_a = [scheduler.sample_tasks(rng_a, 3) for _ in range(40)]
    run_b = [scheduler.sample_tasks(rng_b, 3) for _ in range(40)]
    assert run_a == run_b == first
    assert all(len(set(step)) == 3 for step in run_a)


def test_all_tasks_can_be_drawn_and_more_is_refused() -> None:
    scheduler = TemperatureSamplingScheduler(COUNTS)
    assert sorted(scheduler.sample_tasks(random.Random(1), 5)) == sorted(COUNTS)
    with pytest.raises(ValueError, match="exceeds"):
        scheduler.sample_tasks(random.Random(1), 6)
    with pytest.raises(ValueError, match=">= 1"):
        scheduler.sample_tasks(random.Random(1), 0)


def test_first_draw_keeps_the_scheduler_distribution() -> None:
    scheduler = TemperatureSamplingScheduler(COUNTS)
    rng = random.Random(11)
    draws = 6000
    firsts = [scheduler.sample_tasks(rng, 2)[0] for _ in range(draws)]
    for task in COUNTS:
        assert firsts.count(task) / draws == pytest.approx(
            scheduler.get_task_probability(task), abs=0.03
        )


def test_loader_step_of_one_is_a_plain_batch(data_dir: Path) -> None:
    plain, mixed = _loader(data_dir), _loader(data_dir)
    for _ in range(6):
        expected = plain.generate_batch()
        (got,) = mixed.generate_step_batches(1)
        assert got.task_type == expected.task_type
        assert torch.equal(torch.as_tensor(got.token_ids), torch.as_tensor(expected.token_ids))


def test_loader_mixed_step_carries_different_tasks_and_is_seed_stable(data_dir: Path) -> None:
    runs = []
    for _ in range(2):
        loader = _loader(data_dir)
        runs.append([[b.task_type for b in loader.generate_step_batches(3)] for _ in range(8)])
    assert runs[0] == runs[1]
    assert all(len(set(step)) == 3 for step in runs[0])
    with pytest.raises(ValueError, match="exceeds"):
        _loader(data_dir).generate_step_batches(9)


# --- loss sum and logging -------------------------------------------------------------------


def test_step_loss_is_the_sum_of_the_task_losses(data_dir: Path) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    batches = [loader.generate_batch("nli"), loader.generate_batch("qa")]
    with torch.no_grad():  # the inference path: no gradients, so no training authorisation
        loss, per_task, order = trainer._step_loss(batches, training_pass=False)
        singles = []
        for batch in batches:
            ids, mask = trainer._to_device(batch)
            outputs = trainer._forward(batch.task_type, ids, mask, batch.labels)
            singles.append(
                trainer._compute_torch_loss(batch.task_type, outputs, batch.labels, mask)
            )
    assert set(per_task) == {"nli", "qa"} and order is None
    assert per_task["nli"] == pytest.approx(float(singles[0]), rel=1e-5)
    assert per_task["qa"] == pytest.approx(float(singles[1]), rel=1e-5)
    assert float(loss) == pytest.approx(float(singles[0] + singles[1]), rel=1e-5)


def test_step_loss_of_one_batch_is_the_single_task_loss(data_dir: Path) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    batch = loader.generate_batch("mlm")
    with torch.no_grad():
        loss, per_task, _ = trainer._step_loss([batch], training_pass=False)
        ids, mask = trainer._to_device(batch)
        outputs = trainer._forward("mlm", ids, mask, batch.labels)
        reference = trainer._compute_torch_loss("mlm", outputs, batch.labels, mask)
    assert float(loss) == float(reference) == per_task["mlm"]


def test_a_mixed_step_needs_different_tasks(data_dir: Path) -> None:
    loader = _loader(data_dir)
    nli = loader.generate_batch("nli")
    with pytest.raises(ValueError, match="different tasks"):
        LanguageEncoderTrainer._as_batches([nli, nli])
    with pytest.raises(ValueError, match="at least one"):
        LanguageEncoderTrainer._as_batches([])
    assert LanguageEncoderTrainer._as_batches(nli) == [nli]


@pytest.mark.skipif(
    not is_training_authorized(), reason="runs optimizer steps: needs owner-authorised training"
)
def test_a_real_mixed_step_logs_every_task(data_dir: Path) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    with temporary_training_authorization(True):
        snapshot = trainer.execute_training_step(loader.generate_step_batches(2))
    assert "+" in snapshot.task_type and set(snapshot.task_losses) == set(
        snapshot.task_type.split("+")
    )
    assert snapshot.loss_value == pytest.approx(sum(snapshot.task_losses.values()), rel=1e-5)
    assert trainer.optimizer_steps == 1


# --- loop, progress, configuration ----------------------------------------------------------


def test_loop_asks_the_loader_for_mixed_steps_only_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(loop_module, "save_checkpoint", lambda *a, **k: tmp_path)
    calls = []

    class Loader:
        rng = random.Random(0)

        def generate_batch(self):
            calls.append("single")
            return "batch"

        def generate_step_batches(self, count):
            calls.append(("step", count))
            return ["a", "b"][:count]

    class Trainer:
        optimizer_steps = 0
        model = optimizer = scheduler = scaler = None
        device = "cpu"

        def execute_training_step(self, batch):
            calls.append(batch)
            self.optimizer_steps += 1
            return SimpleNamespace(
                task_type="x", loss_value=1.0, learning_rate=0.0, grad_norm=0.0,
                peak_vram_gb=None, task_losses=None,
            )

        def counters(self):
            return {}

    for tasks_per_step, expected in ((1, ["single", "batch"]), (2, [("step", 2), ["a", "b"]])):
        calls.clear()
        run_training(
            Trainer(), Loader(),
            TrainingRunConfig(total_optimizer_steps=1, tasks_per_step=tasks_per_step),
            tmp_path, log=lambda _: None,
        )
        Trainer.optimizer_steps = 0
        assert calls == expected


def test_configuration_defaults_to_one_task_and_validates() -> None:
    assert TrainingConfig().tasks_per_step == 1
    assert TrainingConfig(tasks_per_step=3).tasks_per_step == 3
    with pytest.raises(ValueError):
        TrainingConfig(tasks_per_step=0)
    with pytest.raises(ValueError, match="tasks_per_step"):
        TrainingRunConfig(total_optimizer_steps=1, tasks_per_step=0)
    assert TrainingRunConfig(total_optimizer_steps=1).tasks_per_step == 1


def test_progress_folds_each_task_of_a_mixed_step() -> None:
    progress = TrainingProgress(10, grad_accum_steps=2, log_interval=1)
    progress.micro_batch(
        SimpleNamespace(task_type="mlm+nli", loss_value=3.0, task_losses={"mlm": 1.0, "nli": 2.0})
    )
    assert progress.losses == {"mlm": 1.0, "nli": 2.0}
    progress.micro_batch(SimpleNamespace(task_type="qa", loss_value=4.0, task_losses=None))
    assert progress.losses["qa"] == 4.0


# --- memory ---------------------------------------------------------------------------------

# peak per task from the T184 profile (large model, micro-batch 8 x 4, bf16, checkpointing)
T184_PEAKS = {"mlm": 8.85, "nli": 10.32, "paraphrase": 10.33, "similarity": 10.33,
              "qa": 10.91, "retrieval": 11.39}


def test_resident_state_of_the_large_model() -> None:
    assert resident_state_gb(543_991_751) == pytest.approx(8.106, abs=0.001)
    assert resident_state_gb(543_991_751, eight_bit_optimizer=True) < resident_state_gb(
        543_991_751
    )


def test_estimate_adds_the_most_expensive_activations() -> None:
    resident = resident_state_gb(543_991_751)
    one = estimate_mixed_peak_gb(T184_PEAKS, resident, 1)
    two = estimate_mixed_peak_gb(T184_PEAKS, resident, 2)
    three = estimate_mixed_peak_gb(T184_PEAKS, resident, 3)
    assert one == pytest.approx(11.39)  # the measured maximum
    assert two == pytest.approx(resident + (11.39 - resident) + (10.91 - resident))
    assert two < 14.5 < three
    with pytest.raises(ValueError):
        estimate_mixed_peak_gb(T184_PEAKS, resident, 7)


def test_a_group_that_is_not_finite_or_too_large_does_not_fit() -> None:
    base = dict(
        gpu_name="t", total_vram_gb=16.0, limit_gb=14.5, steady_state=True,
        tasks=[TaskMeasurement("mlm", 7.0, True)], peak_gb=7.0,
    )
    ok = TrainingMemoryProfile(**base, groups=[GroupMeasurement(("mlm", "nli"), 9.0, True)])
    bad = TrainingMemoryProfile(**base, groups=[GroupMeasurement(("mlm", "nli"), 9.0, False)])
    assert ok.certified and not bad.fits
