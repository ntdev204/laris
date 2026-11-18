"""Batches prepared by background processes (T213).

The multi-task loader tokenizes, masks and collates in one Python thread, so on a fast GPU the
training step waits for the CPU (T212: one core at 100 %, GPU about 32 % busy, 1.4 s per optimizer
step). A `PrefetchingLoader` runs `workers` copies of the loader in forked processes; each fills a
bounded queue with ready micro-steps and the training loop only takes them. `workers == 0` never
builds this class and the single-process path is unchanged.

What changes: every worker draws its own tasks and rows from its own seeded streams, so the mixture
holds in expectation (the same scheduler in every worker), the order of batches depends on process
timing, and a run is not bit-reproducible; the loader position was never restored on resume.
Workers must not touch CUDA (they only build CPU tensors).
"""

from __future__ import annotations

import atexit
import queue as queue_module
import random
import traceback
from typing import Any, Callable, Dict, List

try:  # shared-memory tensor transfer when PyTorch is present
    import torch.multiprocessing as _mp
except ImportError:  # pragma: no cover - the CPU-only path
    import multiprocessing as _mp  # type: ignore[no-redef]

_POLL_SECONDS = 0.5


def _worker(
    factory: Callable[[int], Any],
    index: int,
    tasks_per_step: int,
    out: Any,
    stop: Any,
) -> None:
    """Fill `out` with micro-steps until `stop` is set; a failure is sent to the parent."""
    try:
        loader = factory(index)
        while not stop.is_set():
            if tasks_per_step == 1:
                step: List[Any] = [loader.generate_batch()]
            else:
                step = loader.generate_step_batches(tasks_per_step)
            while not stop.is_set():
                try:
                    out.put(("ok", step), timeout=_POLL_SECONDS)
                    break
                except queue_module.Full:
                    continue
    except BaseException:  # noqa: BLE001 - everything must reach the parent
        try:
            out.put(("error", traceback.format_exc()), timeout=5)
        except Exception:  # pragma: no cover
            pass


class PrefetchingLoader:
    """Same calls as the training loop uses on the loader, served from worker processes."""

    def __init__(
        self,
        factory: Callable[[int], Any],
        reference: Any,
        workers: int,
        tasks_per_step: int = 1,
        depth: int = 4,
        seed: int = 0,
    ) -> None:
        if workers < 1:
            raise ValueError("PrefetchingLoader needs at least one worker")
        if tasks_per_step < 1 or depth < 1:
            raise ValueError("tasks_per_step and depth must be >= 1")
        self.tasks_per_step = tasks_per_step
        self.workers = workers
        # The loop saves and restores `rng` with the checkpoint; the data position never was.
        self.rng = random.Random(seed)
        self.task_paths: Dict[str, Any] = reference.task_paths
        self.stats = reference.stats
        ctx = _mp.get_context("fork")
        self._stop = ctx.Event()
        self._queue = ctx.Queue(maxsize=workers * depth)
        self._processes = [
            ctx.Process(
                target=_worker,
                args=(factory, i + 1, tasks_per_step, self._queue, self._stop),
                daemon=True,
            )
            for i in range(workers)
        ]
        for process in self._processes:
            process.start()
        self._closed = False
        atexit.register(self.close)

    def _next(self) -> List[Any]:
        while True:
            try:
                kind, payload = self._queue.get(timeout=_POLL_SECONDS)
            except queue_module.Empty:
                if not any(p.is_alive() for p in self._processes):
                    raise RuntimeError("all loader workers have stopped") from None
                continue
            if kind == "error":
                self.close()
                raise RuntimeError(f"loader worker failed:\n{payload}")
            return payload  # type: ignore[no-any-return]

    def generate_batch(self, task_type: Any = None) -> Any:
        if task_type is not None or self.tasks_per_step != 1:
            raise ValueError("a prefetching loader serves the draws it was built for")
        return self._next()[0]

    def generate_step_batches(self, tasks_per_step: int = 1) -> List[Any]:
        if tasks_per_step != self.tasks_per_step:
            raise ValueError(
                f"built for {self.tasks_per_step} tasks per step, asked for {tasks_per_step}"
            )
        return self._next()

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self._stop.set()
        try:
            while True:
                self._queue.get_nowait()
        except Exception:  # noqa: BLE001 - the queue is being torn down
            pass
        for process in self._processes:
            process.join(timeout=3)
            if process.is_alive():
                process.terminate()
        atexit.unregister(self.close)
