"""Live training display: formatting, line mode, bar mode and the loop integration."""

import io
from types import SimpleNamespace

import pytest

from laris.language.training.progress import (
    TrainingProgress,
    format_duration,
    format_metrics,
)


def _snap(task="mlm", loss=2.0, lr=1e-4, gn=0.5, vram=11.14):
    return SimpleNamespace(
        task_type=task, loss_value=loss, learning_rate=lr, grad_norm=gn, peak_vram_gb=vram
    )


def test_format_duration() -> None:
    assert format_duration(75) == "1m15s"
    assert format_duration(3 * 3600 + 5 * 60) == "3h05m"
    assert format_duration(5 * 86400 + 3 * 3600) == "5d03h"
    assert format_duration(-3) == "0m00s"


def test_format_metrics_lists_tasks_lr_gradnorm_memory_and_accumulation() -> None:
    text = format_metrics(
        {"paraphrase": 0.3, "mlm": 3.2104}, 1e-4, 0.83, 11.14, accumulated=3, accum_steps=8
    )
    assert text == "mlm=3.210 para=0.300 lr=1.0e-04 gn=0.83 mem=11.1G acc=3/8"
    assert format_metrics({"qa": 1.0}, None, None, None, 0, 1) == "qa=1.000"


def test_running_loss_is_smoothed_per_task_not_jumping_with_the_last_batch() -> None:
    progress = TrainingProgress(100, mode="lines", stream=io.StringIO(), smoothing=0.1)
    progress.micro_batch(_snap("mlm", 4.0))
    progress.micro_batch(_snap("nli", 1.0))
    progress.micro_batch(_snap("mlm", 2.0))
    assert progress.losses["mlm"] == pytest.approx(3.8)  # 0.9 * 4.0 + 0.1 * 2.0
    assert progress.losses["nli"] == pytest.approx(1.0)


def test_lines_mode_prints_every_log_interval_with_eta_and_no_carriage_returns() -> None:
    out = io.StringIO()
    progress = TrainingProgress(100, mode="lines", stream=out, log_interval=2)
    progress.start(0)
    for step in range(1, 5):
        progress.micro_batch(_snap())
        progress.optimizer_step(step, _snap())
    lines = out.getvalue().strip().splitlines()
    assert [line[:13] for line in lines] == ["[Step 000001/", "[Step 000002/", "[Step 000004/"]
    assert "mlm=2.000" in lines[-1] and "eta " in lines[-1] and "\r" not in out.getvalue()
    assert not progress.uses_bar


def test_auto_mode_is_lines_when_output_is_not_a_terminal() -> None:
    progress = TrainingProgress(10, mode="auto", stream=io.StringIO())
    progress.start(0)
    assert not progress.uses_bar


def test_evaluation_prints_header_once_then_rows_with_best_marker() -> None:
    out = io.StringIO()
    progress = TrainingProgress(100, mode="lines", stream=out)
    progress.start(0)
    metrics = {"mlm": 3.1, "nli": 0.9, "mean": 2.0}
    progress.evaluation(200, metrics, improved=True, best_step=200, stale=0, patience=5)
    progress.evaluation(400, metrics, improved=False, best_step=200, stale=1, patience=5)
    text = out.getvalue()
    assert text.count("Validation (val split)") == 1
    assert "* step 200" in text and "stale 1/5" in text


def test_bar_mode_renders_a_progress_bar_with_running_metrics() -> None:
    pytest.importorskip("tqdm")
    out = io.StringIO()
    progress = TrainingProgress(10, grad_accum_steps=2, mode="bar", stream=out)
    progress.start(0)
    assert progress.uses_bar
    progress.micro_batch(_snap("mlm", 3.0))
    progress.micro_batch(_snap("nli", 1.0))
    progress.optimizer_step(1, _snap("nli", 1.0))
    progress.message("a message")
    progress.close()
    text = out.getvalue()
    assert "1/10" in text and "mlm=3.000" in text and "nli=1.000" in text
    assert "a message" in text and "lr=1.0e-04" in text


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        TrainingProgress(10, mode="fancy")
