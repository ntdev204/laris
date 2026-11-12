"""One GPU queue for the model service (SR-S3).

Every call that touches model weights goes through `GpuQueue`: jobs wait in one priority queue (FIFO
inside a priority), a worker stages the model the job needs into VRAM (`SpecialistLRUCache` with the
`HeadroomBudgetGovernor`, which evicts the least recently used idle model when the budget is
exceeded) and runs the job while that model is pinned. The declared sizes and the budget come from
configuration; the queue never lets the registered allocation pass the budget.
"""

import itertools
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator

from laris.model.execution.headroom_governor import HeadroomBudgetGovernor
from laris.model.execution.weight_staging import (
    SpecialistLRUCache,
    SpecialistWeightDescriptor,
    StorageTier,
)
from laris.shared.core.errors import HardwareBudgetExceededError


class QueueFull(RuntimeError):
    """Too many jobs are waiting; the caller should retry later (HTTP 503)."""


class QueueTimeout(RuntimeError):
    """A job waited longer than the configured limit before it could start (HTTP 504)."""


@dataclass
class ModelSpec:
    """A model the queue may keep in VRAM: its declared size and how to load and release it."""

    model_id: str
    size_bytes: int
    load: Callable[[], None] = lambda: None
    unload: Callable[[], None] = lambda: None


class _CallbackLoader:
    """Weight loader that calls the model's own hooks; durations are measured, not simulated."""

    def __init__(self, models: Dict[str, ModelSpec]) -> None:
        self._models = models

    def load_weights(
        self, descriptor: SpecialistWeightDescriptor, target_tier: StorageTier
    ) -> float:
        started = time.perf_counter()
        self._models[descriptor.specialist_id].load()
        return (time.perf_counter() - started) * 1000.0

    def offload_weights(
        self, descriptor: SpecialistWeightDescriptor, target_tier: StorageTier
    ) -> float:
        started = time.perf_counter()
        self._models[descriptor.specialist_id].unload()
        return (time.perf_counter() - started) * 1000.0


@dataclass
class _Job:
    model_id: str
    run: Callable[[], None]
    fail: Callable[[BaseException], None]
    enqueued: float


_STOP = object()


class GpuQueue:
    def __init__(
        self,
        models: Dict[str, ModelSpec],
        budget_bytes: int,
        margin_bytes: int = 0,
        workers: int = 1,
        max_waiting: int = 64,
        wait_timeout_s: float = 60.0,
        stream_buffer: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if workers < 1 or max_waiting < 1:
            raise ValueError("workers and max_waiting must be at least 1")
        self.models = models
        self.governor = HeadroomBudgetGovernor(
            vram_ceiling_bytes=budget_bytes, vram_safety_margin_bytes=margin_bytes
        )
        self.cache = SpecialistLRUCache(self.governor, _CallbackLoader(models))
        for spec in models.values():
            if spec.size_bytes > budget_bytes:
                raise ValueError(f"model '{spec.model_id}' is larger than the VRAM budget")
            self.cache.register_specialist(
                SpecialistWeightDescriptor(
                    spec.model_id, max(1, spec.size_bytes // 2), max(1, spec.size_bytes)
                )
            )
        self.max_waiting = max_waiting
        self.wait_timeout_s = wait_timeout_s
        self.stream_buffer = stream_buffer
        self._clock = clock
        self._jobs: "queue.PriorityQueue[Any]" = queue.PriorityQueue()
        self._seq = itertools.count()
        self._waiting = 0
        self._users: Dict[str, int] = {}
        self._lock = threading.Lock()  # counters and the stage-then-pin step
        self._freed = threading.Condition(self._lock)  # signalled when a job releases its model
        self.peak_bytes = 0
        self.order: list = []  # model ids in the order jobs started (for tests and metrics)
        self._threads = [
            threading.Thread(target=self._work, daemon=True, name=f"gpu-queue-{i}")
            for i in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    # -- submission ------------------------------------------------------------------------
    def _enqueue(self, job: _Job, priority: int) -> None:
        with self._lock:
            if self._waiting >= self.max_waiting:
                raise QueueFull(f"{self._waiting} jobs are already waiting")
            self._waiting += 1
        self._jobs.put((priority, next(self._seq), job))

    def _known(self, model_id: str) -> None:
        if model_id not in self.models:
            raise KeyError(f"model '{model_id}' is not declared in the queue")

    def call(self, model_id: str, fn: Callable[[], Any], priority: int = 0) -> Any:
        """Run `fn` on the GPU with `model_id` resident; blocks until it is done."""
        self._known(model_id)
        future: "Future[Any]" = Future()

        def run() -> None:
            try:
                future.set_result(fn())
            except BaseException as exc:  # reported to the caller, never lost in the worker
                future.set_exception(exc)

        self._enqueue(_Job(model_id, run, future.set_exception, self._clock()), priority)
        return future.result()

    def stream(
        self, model_id: str, factory: Callable[[], Iterator[Any]], priority: int = 0
    ) -> Iterator[Any]:
        """Run a generator on the GPU and hand its items to the caller as they appear. The model
        stays resident until the generator ends or the caller stops reading."""
        self._known(model_id)
        items: "queue.Queue[Any]" = queue.Queue(maxsize=self.stream_buffer)
        done = object()
        closed = threading.Event()

        def put(item: Any) -> bool:
            while not closed.is_set():
                try:
                    items.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    continue
            return False

        def run() -> None:
            generator = None
            try:
                generator = factory()
                for item in generator:
                    if not put(item):
                        break
            except BaseException as exc:
                put(exc)
            finally:
                if generator is not None and hasattr(generator, "close"):
                    generator.close()
                put(done)

        def fail(exc: BaseException) -> None:
            put(exc)
            put(done)

        self._enqueue(_Job(model_id, run, fail, self._clock()), priority)

        def consume() -> Iterator[Any]:
            try:
                while True:
                    item = items.get()
                    if item is done:
                        return
                    if isinstance(item, BaseException):
                        raise item
                    yield item
            finally:
                closed.set()  # the reader left: the worker stops and frees the model

        return consume()

    # -- worker ----------------------------------------------------------------------------
    def _work(self) -> None:
        while True:
            entry = self._jobs.get()
            if entry[2] is _STOP:
                return
            job: _Job = entry[2]
            with self._lock:
                self._waiting -= 1
            if self._clock() - job.enqueued > self.wait_timeout_s:
                job.fail(QueueTimeout(f"waited more than {self.wait_timeout_s:g} s for the GPU"))
                continue
            try:
                self._run(job)
            except BaseException as exc:  # staging failed (budget, loader): tell the caller
                job.fail(exc)

    def _run(self, job: _Job) -> None:
        with self._freed:  # staging and pinning are one step: no one evicts the model in between
            while True:
                try:
                    self.cache.request_specialist(job.model_id)
                    break
                except HardwareBudgetExceededError:
                    # the budget is full of models other jobs are using: wait for one to finish
                    if not any(self._users.values()):
                        raise  # nothing is in use, so this model can never fit
                    if self._clock() - job.enqueued > self.wait_timeout_s:
                        raise QueueTimeout("waited too long for VRAM to be released") from None
                    self._freed.wait(timeout=0.05)
            total = self.governor.get_total_registered_allocation()
            self.peak_bytes = max(self.peak_bytes, total)
            self._users[job.model_id] = self._users.get(job.model_id, 0) + 1
            self.cache.pin_specialist(job.model_id)
            self.order.append(job.model_id)
        try:
            job.run()
        finally:
            with self._freed:
                self._users[job.model_id] -= 1
                if self._users[job.model_id] == 0:
                    self.cache.unpin_specialist(job.model_id)
                self._freed.notify_all()

    def close(self) -> None:
        for _ in self._threads:
            self._jobs.put((float("inf"), next(self._seq), _STOP))
        for thread in self._threads:
            thread.join(timeout=5)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "budget_bytes": self.governor.vram_ceiling_bytes,
                "resident_bytes": self.governor.get_total_registered_allocation(),
                "resident": sorted(self.governor.get_active_allocations()),
                "waiting": self._waiting,
                "peak_bytes": self.peak_bytes,
                "evictions": self.cache.evictions,
            }

    def wait_idle(self, timeout_s: float = 5.0) -> bool:
        """For tests: true when no job is waiting or running."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if self._waiting == 0 and not any(self._users.values()):
                    return True
            time.sleep(0.01)
        return False
