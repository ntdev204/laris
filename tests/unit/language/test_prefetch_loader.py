"""T213: batches prepared by worker processes. Loader only: no model, no backward step."""

from collections import Counter
from pathlib import Path

import pytest

from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader
from laris.shared.language.loading.prefetch import PrefetchingLoader

from .test_training_loop import _write_tasks


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    _write_tasks(tmp_path, "train")
    return tmp_path


def _factory(data_dir: Path):  # type: ignore[no-untyped-def]
    def build(seed: int) -> StreamingParquetMultiTaskDataLoader:
        return StreamingParquetMultiTaskDataLoader(
            data_dir=data_dir, vocab_size=500, seq_len=32, batch_size=2, return_tensors="pt",
            split="train", fallback_to_synthetic=False, seed=seed,
        )  # fmt: skip

    return build


def test_single_task_steps_have_the_shape_and_mixture_of_the_plain_loader(data_dir: Path) -> None:
    build = _factory(data_dir)
    reference = build(7)
    prefetch = PrefetchingLoader(build, reference, workers=2, tasks_per_step=1, depth=2, seed=7)
    try:
        batches = [prefetch.generate_batch() for _ in range(300)]
    finally:
        prefetch.close()
    assert all(b.token_ids.shape == (2, 32) for b in batches)
    counts = Counter(b.task_type for b in batches)
    assert set(counts) == set(reference.scheduler.tasks)  # every task is served
    expected = dict(zip(reference.scheduler.tasks, reference.scheduler.probabilities))
    for task, p in expected.items():  # the same scheduler in every worker
        assert counts[task] / 300 == pytest.approx(p, abs=0.08)


def test_mixed_steps_hold_different_tasks_and_the_wrong_count_is_refused(data_dir: Path) -> None:
    build = _factory(data_dir)
    prefetch = PrefetchingLoader(build, build(7), workers=2, tasks_per_step=2, depth=2, seed=7)
    try:
        for _ in range(40):
            step = prefetch.generate_step_batches(2)
            assert len(step) == 2 and step[0].task_type != step[1].task_type
        with pytest.raises(ValueError, match="built for 2"):
            prefetch.generate_step_batches(3)
        with pytest.raises(ValueError):
            prefetch.generate_batch()
    finally:
        prefetch.close()


def test_a_failing_worker_reaches_the_caller(data_dir: Path) -> None:
    def broken(seed: int) -> StreamingParquetMultiTaskDataLoader:
        raise RuntimeError("no shards today")

    prefetch = PrefetchingLoader(broken, _factory(data_dir)(7), workers=1, seed=7)
    with pytest.raises(RuntimeError, match="no shards today"):
        prefetch.generate_batch()


def test_close_stops_every_worker_and_is_idempotent(data_dir: Path) -> None:
    build = _factory(data_dir)
    prefetch = PrefetchingLoader(build, build(7), workers=2, seed=7)
    prefetch.generate_batch()
    processes = list(prefetch._processes)
    prefetch.close()
    prefetch.close()
    assert not any(p.is_alive() for p in processes)


def test_rejects_bad_arguments(data_dir: Path) -> None:
    build = _factory(data_dir)
    with pytest.raises(ValueError):
        PrefetchingLoader(build, build(7), workers=0)
    with pytest.raises(ValueError):
        PrefetchingLoader(build, build(7), workers=1, tasks_per_step=0)


def test_commit_falls_back_to_the_environment_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T212: a VM without .git still records the commit it unpacked."""
    from laris.shared.language.loading.checkpoint import current_git_commit

    monkeypatch.setenv("PATH", str(tmp_path))  # no git on the path
    monkeypatch.delenv("LARIS_GIT_COMMIT", raising=False)
    assert current_git_commit(tmp_path) is None
    monkeypatch.setenv("LARIS_GIT_COMMIT", "00f3c6018e4edd8acb753af1de18a6ffd98ebda6")
    assert current_git_commit(tmp_path) == "00f3c6018e4edd8acb753af1de18a6ffd98ebda6"
