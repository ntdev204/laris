"""Tests for the training loop: schedule, step counting, evaluation, checkpoints, early stop."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

torch = pytest.importorskip("torch")

from laris.core.authorization import temporary_training_authorization  # noqa: E402
from laris.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.training.checkpoint import (  # noqa: E402
    MODEL_FILE,
    load_checkpoint,
    read_manifest,
)
from laris.language.training.dataloader import StreamingParquetMultiTaskDataLoader  # noqa: E402
from laris.language.training.loop import (  # noqa: E402
    TrainingRunConfig,
    run_training,
)
from laris.language.training.schedule import warmup_cosine_factor  # noqa: E402
from laris.language.training.trainer import LanguageEncoderTrainer  # noqa: E402

TEXT = "Quantum computing uses superposition and entanglement for computation."


def _write_tasks(root: Path, split: str) -> None:
    def put(name: str, table: pa.Table) -> None:
        (root / name).mkdir(parents=True, exist_ok=True)
        pq.write_table(table, root / name / f"{split}.parquet")

    put("wikipedia_en", pa.table({"id": ["a", "b", "c"], "text": [TEXT] * 3}))
    put(
        "all_nli",
        pa.table(
            {"premise": [TEXT] * 3, "hypothesis": ["Computers exist."] * 3, "label": [0, 1, 2]}
        ),
    )
    put(
        "quora",
        pa.table(
            {"question1": [TEXT] * 2, "question2": ["What is a qubit?"] * 2, "is_duplicate": [1, 0]}
        ),
    )
    put(
        "stsb",
        pa.table(
            {"sentence1": [TEXT] * 2, "sentence2": ["Qubits compute."] * 2, "score": [0.9, 0.2]}
        ),
    )
    put(
        "squad",
        pa.table(
            {
                "context": [TEXT] * 2,
                "question": ["What does quantum computing use?"] * 2,
                "answers": [
                    {"text": ["superposition"], "answer_start": [TEXT.index("superposition")]}
                ]
                * 2,
            }
        ),
    )


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    for split in ("train", "val"):
        _write_tasks(tmp_path, split)
    return tmp_path


def _config() -> LanguageEncoderConfig:
    return LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, max_sequence_length=32, vocab_size=500
    )


def _loader(data_dir: Path, split: str = "train", batch: int = 2):
    return StreamingParquetMultiTaskDataLoader(
        data_dir=data_dir,
        vocab_size=500,
        seq_len=32,
        batch_size=batch,
        return_tensors="pt",
        split=split,
        fallback_to_synthetic=False,
    )


def _trainer(loader, **kwargs) -> LanguageEncoderTrainer:
    torch.manual_seed(0)
    cfg = _config()
    defaults = dict(
        model=PyTorchTransformerEncoder(cfg),
        config=cfg,
        dataloader=loader,
        use_8bit_adam=False,
        learning_rate=1e-3,
        grad_accum_steps=1,
        device="cpu",
    )
    defaults.update(kwargs)
    return LanguageEncoderTrainer(**defaults)


def test_warmup_cosine_factor_shape() -> None:
    assert warmup_cosine_factor(0, 10, 100) == pytest.approx(0.1)
    assert warmup_cosine_factor(9, 10, 100) == pytest.approx(1.0)
    assert warmup_cosine_factor(10, 10, 100) == pytest.approx(1.0)
    assert warmup_cosine_factor(100, 10, 100) == pytest.approx(0.1)
    values = [warmup_cosine_factor(s, 10, 100) for s in range(10, 101)]
    assert values == sorted(values, reverse=True)


def test_optimizer_steps_count_accumulation_windows_and_follow_schedule(data_dir: Path) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader, grad_accum_steps=2, warmup_steps=2, total_optimizer_steps=10)
    lrs = []
    with temporary_training_authorization(True):
        for _ in range(4):
            snap = trainer.execute_training_step(loader.generate_batch())
            lrs.append(snap.learning_rate)
    assert trainer.optimizer_steps == 2
    assert len(trainer.step_history) == 4
    assert lrs[0] == lrs[1] and lrs[2] == lrs[3] and lrs[2] != lrs[1]


def test_evaluate_reports_every_task_without_touching_weights(data_dir: Path) -> None:
    trainer = _trainer(_loader(data_dir))
    before = {k: v.clone() for k, v in trainer.model.state_dict().items()}
    metrics = trainer.evaluate(_loader(data_dir, "val"), batches_per_task=2)
    assert {"mlm", "nli", "paraphrase", "similarity", "qa", "mean"} <= set(metrics)
    assert all(v == v and v > 0 for v in metrics.values())
    assert all(torch.equal(before[k], v) for k, v in trainer.model.state_dict().items())


def test_bf16_autocast_step_is_finite(data_dir: Path) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader, precision="bf16")
    with temporary_training_authorization(True):
        snap = trainer.execute_training_step(loader.generate_batch("mlm"))
    assert snap.loss_value == snap.loss_value and snap.loss_value > 0


def test_non_finite_gradients_skip_the_update(data_dir: Path, monkeypatch) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    before = {k: v.clone() for k, v in trainer.model.state_dict().items()}
    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", lambda *a, **k: float("nan"))
    with temporary_training_authorization(True), pytest.warns(RuntimeWarning):
        trainer.execute_training_step(loader.generate_batch("mlm"))
    assert trainer.skipped_steps == 1 and trainer.optimizer_steps == 0
    assert all(torch.equal(before[k], v) for k, v in trainer.model.state_dict().items())


def test_run_training_writes_checkpoints_and_resumes(data_dir: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    loader = _loader(data_dir)
    trainer = _trainer(loader, total_optimizer_steps=4, warmup_steps=1)
    config = TrainingRunConfig(
        total_optimizer_steps=2, eval_interval=1, eval_batches_per_task=1, save_interval=1
    )
    with temporary_training_authorization(True):
        result = run_training(
            trainer,
            loader,
            config,
            run_dir,
            eval_loader=_loader(data_dir, "val"),
            provenance={"seed": 0},
            log=lambda _: None,
        )
    assert result.optimizer_steps == 2 and result.best_dir is not None
    manifest = read_manifest(run_dir / "last")
    assert manifest["counters"]["trainer"]["optimizer_steps"] == 2
    assert manifest["provenance"]["seed"] == 0 and manifest["metrics"]["mean"] > 0

    fresh_loader = _loader(data_dir)
    fresh = _trainer(fresh_loader, total_optimizer_steps=4, warmup_steps=1)
    fresh.model.apply(lambda m: None)
    with temporary_training_authorization(True):
        result2 = run_training(
            fresh,
            fresh_loader,
            TrainingRunConfig(
                total_optimizer_steps=3, eval_interval=1, eval_batches_per_task=1, save_interval=1
            ),
            run_dir,
            eval_loader=_loader(data_dir, "val"),
            resume_from=run_dir / "last",
            log=lambda _: None,
        )
    assert result2.optimizer_steps == 3
    assert len(result2.evaluations) == 3  # two restored + one new


def test_checkpoint_restores_exact_weights_and_detects_corruption(
    data_dir: Path, tmp_path: Path
) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    run_dir = tmp_path / "run"
    with temporary_training_authorization(True):
        run_training(
            trainer,
            loader,
            TrainingRunConfig(total_optimizer_steps=1, eval_interval=5, save_interval=1),
            run_dir,
            log=lambda _: None,
        )
    other = _trainer(_loader(data_dir))
    load_checkpoint(run_dir / "last", model=other.model, optimizer=other.optimizer)
    assert all(
        torch.equal(v, other.model.state_dict()[k]) for k, v in trainer.model.state_dict().items()
    )
    with open(run_dir / "last" / MODEL_FILE, "r+b") as handle:
        handle.seek(100)
        handle.write(b"\x00\x01\x02\x03")
    with pytest.raises(ValueError, match="corrupt"):
        load_checkpoint(run_dir / "last", model=other.model)


def test_early_stopping_after_patience(data_dir: Path, tmp_path: Path, monkeypatch) -> None:
    loader = _loader(data_dir)
    trainer = _trainer(loader)
    scores = iter([1.0, 1.1, 1.2, 1.3, 1.4])
    monkeypatch.setattr(trainer, "evaluate", lambda *a, **k: {"mean": next(scores)})
    with temporary_training_authorization(True):
        result = run_training(
            trainer,
            loader,
            TrainingRunConfig(
                total_optimizer_steps=50, eval_interval=1, save_interval=50, patience=2
            ),
            tmp_path / "run",
            eval_loader=_loader(data_dir, "val"),
            log=lambda _: None,
        )
    assert result.stopped_early and result.best_step == 1
    assert result.optimizer_steps == 3


def test_run_training_renders_progress_and_validation_table(
    data_dir: Path, tmp_path: Path
) -> None:
    import io

    from laris.language.training.progress import TrainingProgress

    out = io.StringIO()
    loader = _loader(data_dir)
    trainer = _trainer(loader, grad_accum_steps=2, total_optimizer_steps=4, warmup_steps=1)
    progress = TrainingProgress(
        4, grad_accum_steps=2, log_interval=1, mode="lines", stream=out
    )
    config = TrainingRunConfig(
        total_optimizer_steps=4, eval_interval=2, eval_batches_per_task=1, save_interval=2,
        log_interval=1,
    )
    with temporary_training_authorization(True):
        result = run_training(
            trainer, loader, config, tmp_path / "run",
            eval_loader=_loader(data_dir, "val"), progress=progress,
        )
    text = out.getvalue()
    assert result.optimizer_steps == 4
    assert text.count("[Step ") == 4 and "eta " in text and "gn=" in text and "lr=" in text
    assert text.count("Validation (val split)") == 1  # one header, then a row per evaluation
    assert "* step 2" in text
