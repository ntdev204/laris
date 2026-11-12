"""T54: the GPU queue keeps declared model sizes inside the VRAM budget; order and timeouts hold.
Scripted models with declared sizes only: nothing is loaded onto a real GPU."""

import threading
import time

import pytest

from laris.model.gpu_queue import GpuQueue, ModelSpec, QueueFull, QueueTimeout

GB = 1024**3


class Tracker:
    """Models that report how much 'VRAM' they hold at any moment."""

    def __init__(self, sizes):
        self.sizes = sizes
        self.resident = set()
        self.peak = 0
        self.log = []
        self.lock = threading.Lock()

    def total(self):
        return sum(self.sizes[m] for m in self.resident)

    def spec(self, name):
        def load():
            with self.lock:
                self.resident.add(name)
                self.peak = max(self.peak, self.total())
                self.log.append(("load", name))

        def unload():
            with self.lock:
                self.resident.discard(name)
                self.log.append(("unload", name))

        return ModelSpec(name, self.sizes[name], load, unload)


def queue_for(sizes, budget, **kw):
    t = Tracker(sizes)
    return t, GpuQueue({n: t.spec(n) for n in sizes}, budget, 0, **kw)


def test_declared_sizes_never_exceed_the_budget():
    t, q = queue_for({"chat": 10 * GB, "embed": 6 * GB, "rerank": 5 * GB}, 14 * GB)
    for name in ["chat", "embed", "rerank", "chat", "embed", "chat", "rerank", "embed"]:
        assert q.call(name, lambda n=name: n) == name
        assert t.total() <= 14 * GB and name in t.resident
    assert t.peak <= 14 * GB and q.status()["peak_bytes"] <= 14 * GB
    assert q.status()["evictions"] >= 4  # chat and embed cannot share the budget
    q.close()


def test_models_that_fit_together_stay_resident():
    t, q = queue_for({"chat": 4 * GB, "embed": 2 * GB}, 14 * GB)
    for name in ["chat", "embed", "chat", "embed"]:
        q.call(name, lambda: None)
    assert [e for e in t.log if e[0] == "load"] == [("load", "chat"), ("load", "embed")]
    assert t.resident == {"chat", "embed"} and q.status()["evictions"] == 0
    q.close()


def test_a_model_larger_than_the_budget_is_refused_at_start():
    t = Tracker({"huge": 20 * GB})
    with pytest.raises(ValueError):
        GpuQueue({"huge": t.spec("huge")}, 14 * GB)


def test_jobs_run_in_order_and_priority_goes_first():
    t, q = queue_for({"chat": 1 * GB, "embed": 1 * GB}, 14 * GB)
    gate = threading.Event()
    results = []
    blocker = threading.Thread(target=lambda: q.call("chat", gate.wait))
    blocker.start()
    time.sleep(0.1)  # the single worker is now busy
    threads = []
    for name, priority in [("chat", 5), ("embed", 5), ("chat", 0)]:
        th = threading.Thread(
            target=lambda n=name, p=priority: q.call(n, lambda: results.append((n, p)), p)
        )
        th.start()
        threads.append(th)
        time.sleep(0.05)
    gate.set()
    for th in [blocker, *threads]:
        th.join(timeout=5)
    assert results == [("chat", 0), ("chat", 5), ("embed", 5)]  # priority, then arrival order
    q.close()


def test_waiting_too_long_gives_a_timeout_and_a_full_queue_refuses():
    now = [0.0]
    t, q = queue_for({"chat": 1 * GB}, 14 * GB, max_waiting=2, wait_timeout_s=5.0)
    q._clock = lambda: now[0]
    gate, errors = threading.Event(), []
    busy = threading.Thread(target=lambda: q.call("chat", gate.wait))
    busy.start()
    time.sleep(0.1)

    def late():
        try:
            q.call("chat", lambda: None)
        except Exception as exc:
            errors.append(exc)

    waiters = [threading.Thread(target=late) for _ in range(2)]
    for w in waiters:
        w.start()
        time.sleep(0.05)
    with pytest.raises(QueueFull):
        q.call("chat", lambda: None)  # two are waiting: the third is turned away
    now[0] = 60.0  # the waiters have now waited too long
    gate.set()
    for w in [busy, *waiters]:
        w.join(timeout=5)
    assert len(errors) == 2 and all(isinstance(e, QueueTimeout) for e in errors)
    assert q.call("chat", lambda: "ok") == "ok"  # the queue recovers
    q.close()


def test_a_failing_job_reports_its_error_and_the_worker_survives():
    t, q = queue_for({"chat": 1 * GB}, 14 * GB)
    with pytest.raises(RuntimeError, match="boom"):
        q.call("chat", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert q.call("chat", lambda: 1) == 1
    with pytest.raises(KeyError):
        q.call("unknown", lambda: None)
    q.close()


def test_a_loader_that_fails_fails_only_that_job():
    t = Tracker({"chat": 1 * GB, "bad": 1 * GB})

    def broken():
        raise RuntimeError("cannot load")

    bad = ModelSpec("bad", 1 * GB, broken, lambda: None)
    q = GpuQueue({"chat": t.spec("chat"), "bad": bad}, 14 * GB)
    with pytest.raises(Exception, match="cannot load"):
        q.call("bad", lambda: None)
    assert q.call("chat", lambda: "fine") == "fine"
    q.close()


def test_a_stream_keeps_its_model_resident_until_it_ends_or_the_reader_leaves():
    t, q = queue_for({"chat": 10 * GB, "embed": 10 * GB}, 14 * GB)
    started = threading.Event()

    def gen():
        for i in range(1000):
            started.set()
            yield i

    stream = q.stream("chat", gen)
    assert next(stream) == 0 and started.is_set()
    other = []
    th = threading.Thread(target=lambda: other.append(q.call("embed", lambda: "e")))
    th.start()
    time.sleep(0.2)
    assert not other and "chat" in t.resident  # embed waits: chat is in use and fills the budget
    stream.close()  # the reader leaves: the worker stops, the model is free to be evicted
    th.join(timeout=5)
    assert other == ["e"] and t.peak <= 14 * GB
    assert q.wait_idle()
    q.close()


def test_stream_errors_reach_the_reader():
    t, q = queue_for({"chat": 1 * GB}, 14 * GB)

    def gen():
        yield 1
        raise ValueError("stream broke")

    stream = q.stream("chat", gen)
    assert next(stream) == 1
    with pytest.raises(ValueError, match="stream broke"):
        next(stream)
    q.close()


def test_concurrent_workers_still_respect_the_budget():
    t, q = queue_for({"a": 6 * GB, "b": 6 * GB, "c": 6 * GB}, 14 * GB, workers=3)
    threads = [
        threading.Thread(target=lambda n=name: q.call(n, lambda: time.sleep(0.01)))
        for name in ["a", "b", "c"] * 6
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=20)
    assert t.peak <= 14 * GB and q.status()["peak_bytes"] <= 14 * GB
    q.close()
