"""Training loop: periodic validation, best/last checkpoints, early stopping and resume."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from laris.language.training.checkpoint import load_checkpoint, save_checkpoint
from laris.language.training.progress import TrainingProgress

LAST_DIR = "last"
BEST_DIR = "best"


@dataclass
class TrainingRunConfig:
    """Loop control, in optimizer steps."""

    total_optimizer_steps: int
    eval_interval: int = 200
    eval_batches_per_task: int = 8
    save_interval: int = 500
    patience: int = 5  # evaluations without improvement before stopping; 0 disables
    min_delta: float = 1e-4
    log_interval: int = 10

    def __post_init__(self) -> None:
        if self.total_optimizer_steps < 1:
            raise ValueError("total_optimizer_steps must be >= 1")
        if self.eval_interval < 1 or self.save_interval < 1 or self.log_interval < 1:
            raise ValueError("eval/save/log intervals must be >= 1")


@dataclass
class TrainingRunResult:
    optimizer_steps: int
    best_metric: Optional[float]
    best_step: Optional[int]
    stopped_early: bool
    evaluations: List[Dict[str, Any]] = field(default_factory=list)
    last_dir: Optional[Path] = None
    best_dir: Optional[Path] = None


def run_training(
    trainer: Any,
    train_loader: Any,
    run_config: TrainingRunConfig,
    run_dir: Path,
    *,
    eval_loader: Optional[Any] = None,
    provenance: Optional[Dict[str, Any]] = None,
    resume_from: Optional[Path] = None,
    log: Callable[[str], None] = print,
    progress: Optional[TrainingProgress] = None,
) -> TrainingRunResult:
    """Trains until `total_optimizer_steps` (or early stop), checkpointing under `run_dir`.

    With `progress` the run renders a live bar (or plain lines when not on a terminal) instead
    of the one-line `log`. Validation uses the loader's held-out split only; the test split is
    never read here.
    Resume restores weights, optimizer, scheduler, scaler, RNG and counters; the streaming
    data position is not restored (sampling continues from the restored RNG state).
    """
    run_dir = Path(run_dir)
    if progress is not None:
        log = progress.message
    provenance = dict(provenance or {})
    provenance["run_config"] = asdict(run_config)

    best_metric: Optional[float] = None
    best_step: Optional[int] = None
    stale_evals = 0
    evaluations: List[Dict[str, Any]] = []

    if resume_from is not None:
        loaded = load_checkpoint(
            Path(resume_from),
            model=trainer.model,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            map_location=trainer.device,
        )
        trainer.load_counters(loaded["counters"]["trainer"])
        loop_state = loaded["counters"]["loop"]
        best_metric = loop_state["best_metric"]
        best_step = loop_state["best_step"]
        stale_evals = loop_state["stale_evals"]
        evaluations = list(loop_state["evaluations"])
        rng_state = loaded["extra"].get("loader_rng")
        if rng_state is not None:
            train_loader.rng.setstate(rng_state)
        log(f"[RESUME] {resume_from} at optimizer step {trainer.optimizer_steps}")

    def save(kind: str, metrics: Optional[Dict[str, Any]]) -> Path:
        return save_checkpoint(
            run_dir / kind,
            model=trainer.model,
            optimizer=trainer.optimizer,
            scheduler=trainer.scheduler,
            scaler=trainer.scaler,
            counters={
                "trainer": trainer.counters(),
                "loop": {
                    "best_metric": best_metric,
                    "best_step": best_step,
                    "stale_evals": stale_evals,
                    "evaluations": evaluations,
                },
            },
            provenance=provenance,
            metrics=metrics,
            extra_state={"loader_rng": train_loader.rng.getstate()},
        )

    stopped_early = False
    last_metrics: Optional[Dict[str, Any]] = None
    evaluated_at = -1
    if progress is not None:
        progress.start(trainer.optimizer_steps)
    try:
        while trainer.optimizer_steps < run_config.total_optimizer_steps and not stopped_early:
            before = trainer.optimizer_steps
            snapshot = trainer.execute_training_step(train_loader.generate_batch())
            if progress is not None:
                progress.micro_batch(snapshot)
            steps = trainer.optimizer_steps
            if steps == before:
                continue  # still accumulating gradients

            if progress is not None:
                progress.optimizer_step(steps, snapshot)
            elif steps % run_config.log_interval == 0 or steps == 1:
                vram = f"{snapshot.peak_vram_gb:.2f} GB" if snapshot.peak_vram_gb else "N/A"
                log(
                    f"[Step {steps:06d}/{run_config.total_optimizer_steps}] "
                    f"task={snapshot.task_type:<10} loss={snapshot.loss_value:.4f} "
                    f"lr={snapshot.learning_rate or 0.0:.2e} "
                    f"gnorm={snapshot.grad_norm or 0.0:.2f} vram={vram}"
                )

            if eval_loader is not None and steps % run_config.eval_interval == 0:
                last_metrics = trainer.evaluate(eval_loader, run_config.eval_batches_per_task)
                evaluated_at = steps
                evaluations.append({"step": steps, **last_metrics})
                threshold = None if best_metric is None else best_metric - run_config.min_delta
                improved = threshold is None or last_metrics["mean"] < threshold
                if improved:
                    best_metric, best_step, stale_evals = last_metrics["mean"], steps, 0
                    save(BEST_DIR, last_metrics)
                else:
                    stale_evals += 1
                if progress is not None:
                    progress.evaluation(
                        steps,
                        last_metrics,
                        improved=improved,
                        best_step=best_step,
                        stale=stale_evals,
                        patience=run_config.patience,
                    )
                else:
                    shown = " ".join(f"{k}={v:.4f}" for k, v in last_metrics.items())
                    log(f"[Eval  {steps:06d}] {shown}")
                if not improved and run_config.patience and stale_evals >= run_config.patience:
                    stopped_early = True
                    log(f"[EARLY STOP] no improvement for {stale_evals} evaluations")

            if steps % run_config.save_interval == 0:
                save(LAST_DIR, last_metrics)
    finally:
        if progress is not None:
            progress.close()

    if eval_loader is not None and evaluated_at != trainer.optimizer_steps and not stopped_early:
        last_metrics = trainer.evaluate(eval_loader, run_config.eval_batches_per_task)
        evaluations.append({"step": trainer.optimizer_steps, **last_metrics})
        threshold = None if best_metric is None else best_metric - run_config.min_delta
        if threshold is None or last_metrics["mean"] < threshold:
            best_metric, best_step = last_metrics["mean"], trainer.optimizer_steps
            save(BEST_DIR, last_metrics)
    last_dir = save(LAST_DIR, last_metrics)
    best_dir = run_dir / BEST_DIR
    return TrainingRunResult(
        optimizer_steps=trainer.optimizer_steps,
        best_metric=best_metric,
        best_step=best_step,
        stopped_early=stopped_early,
        evaluations=evaluations,
        last_dir=last_dir,
        best_dir=best_dir if best_dir.exists() else None,
    )
