"""Live training display: a progress bar with running metrics, or plain lines when piped.

The bar shows elapsed time, ETA and rate (from tqdm); a second line under it shows the
running loss of every task, learning rate, gradient norm, GPU memory and the accumulation
position. Losses are the trainer's task losses (weighted by their lambda), smoothed with an
exponential average so the single-task micro-batches do not make the numbers jump. When the
output is not a terminal (nohup, redirected logs) or tqdm is missing it prints one plain line
every `log_interval`.
"""

import sys
import time
from typing import Any, Dict, Optional, TextIO

ABBREVIATIONS = {
    "mlm": "mlm",
    "nli": "nli",
    "paraphrase": "para",
    "similarity": "sim",
    "qa": "qa",
}
BAR_FORMAT = "{l_bar}{bar:30}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"


def format_duration(seconds: float) -> str:
    """Compact duration such as 4m12s, 3h05m or 5d03h."""
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s"


def format_metrics(
    losses: Dict[str, float],
    learning_rate: Optional[float],
    grad_norm: Optional[float],
    vram_gb: Optional[float],
    accumulated: int,
    accum_steps: int,
) -> str:
    """One compact metrics string, e.g. `mlm=3.21 nli=0.54 lr=1.0e-04 gn=0.83 mem=11.1G`."""
    parts = [
        f"{ABBREVIATIONS.get(task, task)}={value:.3f}" for task, value in sorted(losses.items())
    ]
    if learning_rate is not None:
        parts.append(f"lr={learning_rate:.1e}")
    if grad_norm is not None:
        parts.append(f"gn={grad_norm:.2f}")
    if vram_gb:
        parts.append(f"mem={vram_gb:.1f}G")
    if accum_steps > 1:
        parts.append(f"acc={accumulated}/{accum_steps}")
    return " ".join(parts)


class TrainingProgress:
    """Receives training events from `run_training` and renders them."""

    def __init__(
        self,
        total_steps: int,
        *,
        grad_accum_steps: int = 1,
        log_interval: int = 10,
        smoothing: float = 0.05,
        stream: Optional[TextIO] = None,
        mode: str = "auto",
    ) -> None:
        if mode not in ("auto", "bar", "lines"):
            raise ValueError(f"mode must be auto, bar or lines, got '{mode}'")
        self.total_steps = total_steps
        self.grad_accum_steps = max(1, grad_accum_steps)
        self.log_interval = max(1, log_interval)
        self.smoothing = smoothing
        self.stream: TextIO = stream if stream is not None else sys.stderr
        self.mode = mode
        self.losses: Dict[str, float] = {}
        self.learning_rate: Optional[float] = None
        self.grad_norm: Optional[float] = None
        self.vram_gb: Optional[float] = None
        self._accumulated = 0
        self._bar: Any = None
        self._info: Any = None
        self._initial = 0
        self._started_at = 0.0
        self._header_printed = False
        self._use_bar = False

    @property
    def uses_bar(self) -> bool:
        return self._use_bar

    def start(self, initial_step: int = 0) -> None:
        """Begins rendering at `initial_step` (non-zero when resuming)."""
        self._initial = initial_step
        self._started_at = time.monotonic()
        want_bar = self.mode == "bar" or (self.mode == "auto" and self.stream.isatty())
        if want_bar:
            try:
                from tqdm import tqdm

                self._bar = tqdm(
                    total=self.total_steps,
                    initial=initial_step,
                    desc="Train",
                    unit="step",
                    dynamic_ncols=True,
                    bar_format=BAR_FORMAT,
                    file=self.stream,
                    smoothing=0.1,
                    position=0,
                )
                self._info = tqdm(
                    total=0,
                    position=1,
                    bar_format="{desc}",
                    dynamic_ncols=True,
                    file=self.stream,
                )
                self._use_bar = True
            except ImportError:
                self.message("[INFO] tqdm is not installed: using plain log lines "
                             "(pip install -e '.[training]')")

    def message(self, text: str) -> None:
        """Prints a line without breaking the bar."""
        if self._bar is not None:
            self._bar.write(text, file=self.stream)
        else:
            print(text, file=self.stream, flush=True)

    def micro_batch(self, snapshot: Any) -> None:
        """Folds one micro-batch loss (a single task) into that task's running average."""
        task, value = snapshot.task_type, float(snapshot.loss_value)
        previous = self.losses.get(task)
        self.losses[task] = value if previous is None else (
            (1.0 - self.smoothing) * previous + self.smoothing * value
        )
        self._accumulated += 1
        if self._bar is not None:
            self._refresh()

    def optimizer_step(self, steps: int, snapshot: Any) -> None:
        """Called once per optimizer update."""
        self.learning_rate = snapshot.learning_rate
        self.grad_norm = snapshot.grad_norm
        self.vram_gb = snapshot.peak_vram_gb
        self._accumulated = 0
        if self._bar is not None:
            self._bar.update(steps - self._bar.n)
            self._refresh()
        elif steps % self.log_interval == 0 or steps == self._initial + 1:
            self.message(self._line(steps))

    def evaluation(
        self,
        steps: int,
        metrics: Dict[str, float],
        *,
        improved: bool,
        best_step: Optional[int],
        stale: int,
        patience: int,
    ) -> None:
        """Prints one validation row; a header precedes the first row."""
        tasks = [t for t in sorted(metrics) if t != "mean"]
        if not self._header_printed:
            names = "".join(f"{ABBREVIATIONS.get(t, t):>9}" for t in tasks)
            self.message(f"\n  Validation (val split)\n{'step':>9}{names}{'mean':>9}  best")
            self._header_printed = True
        values = "".join(f"{metrics[t]:>9.4f}" for t in tasks)
        note = f"* step {best_step}" if improved else (
            f"  stale {stale}/{patience}" if patience else ""
        )
        self.message(f"{steps:>9}{values}{metrics['mean']:>9.4f}  {note}")

    def close(self) -> None:
        for bar in (self._info, self._bar):
            if bar is not None:
                bar.close()
        self._info = self._bar = None

    def _refresh(self) -> None:
        self._info.set_description_str(
            "  "
            + format_metrics(
                self.losses,
                self.learning_rate,
                self.grad_norm,
                self.vram_gb,
                self._accumulated,
                self.grad_accum_steps,
            ),
            refresh=True,
        )

    def _line(self, steps: int) -> str:
        done = steps - self._initial
        elapsed = time.monotonic() - self._started_at
        per_step = elapsed / done if done else 0.0
        remaining = per_step * (self.total_steps - steps)
        metrics = format_metrics(
            self.losses, self.learning_rate, self.grad_norm, self.vram_gb, 0, 1
        )
        return (
            f"[Step {steps:06d}/{self.total_steps}] {metrics} "
            f"{per_step:.1f}s/step elapsed {format_duration(elapsed)} "
            f"eta {format_duration(remaining)}"
        )
