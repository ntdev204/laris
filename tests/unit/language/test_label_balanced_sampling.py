"""Source- and label-balanced sampling for NLI and paraphrase (T196)."""

import random
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.loading.balanced import (
    assign_labels,
    batch_targets,
    label_counts,
    nli_label,
    paraphrase_label,
)
from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader

# Source -> (rows per label) with the label sets of the real sources: FEVER has no neutral,
# SciTail no contradiction, ANLI all three; the priors are skewed on purpose.
NLI_SOURCES: Dict[str, Dict[str, int]] = {
    "fever": {"entailment": 300, "contradiction": 100},
    "scitail_en": {"entailment": 60, "neutral": 140},
    "anli": {"entailment": 500, "neutral": 200, "contradiction": 100},
}
PARA_SOURCES: Dict[str, Dict[int, int]] = {
    "quora_duplicates": {0: 400, 1: 200},
    "mrpc_en": {0: 30, 1: 70},
}
NAME = {"entailment": 0, "neutral": 1, "contradiction": 2}


def _write(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _data(tmp_path: Path) -> Path:
    for source, labels in NLI_SOURCES.items():
        for split in ("train", "val"):
            rows = [
                {"premise": f"{source} {split} p{label}{i}", "hypothesis": f"h {i}", "label": label}
                for label, n in labels.items()
                for i in range(n)
            ]
            random.Random(source).shuffle(rows)
            _write(tmp_path / source / f"{split}.parquet", rows)
    for source, plabels in PARA_SOURCES.items():
        rows = [
            {"sentence1": f"{source} a{label}{i}", "sentence2": f"b {i}", "label": label}
            for label, n in plabels.items()
            for i in range(n)
        ]
        random.Random(source).shuffle(rows)
        _write(tmp_path / source / "train.parquet", rows)
    return tmp_path


def _loader(data: Path, **kwargs: object) -> StreamingParquetMultiTaskDataLoader:
    base: dict = dict(
        data_dir=data, batch_size=8, seed=11, label_balanced_tasks=("nli", "paraphrase")
    )
    base.update(kwargs)
    return StreamingParquetMultiTaskDataLoader(**base)  # type: ignore[arg-type]


def _source(rec: dict) -> str:
    text = rec.get("premise") or rec.get("sentence1")
    return text.split()[0]


def _draw(loader: StreamingParquetMultiTaskDataLoader, task: str, n: int) -> List[List[dict]]:
    return [loader._next_records(task) for _ in range(n)]


def test_label_parsers_and_label_column_counts(tmp_path: Path) -> None:
    data = _data(tmp_path)
    assert nli_label({"gold_label": "neutral"}) == 1 and nli_label({"label": 2}) == 2
    assert paraphrase_label({"is_duplicate": True, "label": 0}) == 1
    with pytest.raises(ValueError):
        nli_label({"label": "maybe"})
    with pytest.raises(ValueError):
        paraphrase_label({"label": 0.5})
    assert label_counts(data / "fever" / "train.parquet", "nli") == {0: 300, 2: 100}
    assert label_counts(data / "mrpc_en" / "train.parquet", "paraphrase") == {0: 30, 1: 70}


def test_each_source_keeps_its_own_label_set(tmp_path: Path) -> None:
    loader = _loader(_data(tmp_path))
    labels_seen: Dict[str, set] = {}
    for batch in _draw(loader, "nli", 200):
        for rec in batch:
            labels_seen.setdefault(_source(rec), set()).add(nli_label(rec))
    assert labels_seen == {"fever": {0, 2}, "scitail_en": {0, 1}, "anli": {0, 1, 2}}
    sampler = loader._balanced["nli"]
    assert sampler.label_sets == {"anli": [0, 1, 2], "fever": [0, 2], "scitail_en": [0, 1]}


@pytest.mark.parametrize("task, parse", [("nli", nli_label), ("paraphrase", paraphrase_label)])
def test_every_batch_carries_each_label_within_one_of_its_target(
    tmp_path: Path, task: str, parse: object
) -> None:
    loader = _loader(_data(tmp_path))
    sets = loader._balanced[task].label_sets
    for batch in _draw(loader, task, 300):
        sources = [_source(r) for r in batch]
        counts = Counter(parse(r) for r in batch)  # type: ignore[operator]
        for label, target in batch_targets(sources, sets).items():
            assert abs(counts[label] - target) <= 1.0
    assert loader.label_balance_report()[task]["max_batch_label_deviation_rows"] <= 1.0


def test_assignment_bound_holds_for_random_batches() -> None:
    sets = {"all": [0, 1, 2], "fever": [0, 2], "scitail": [0, 1], "one": [1]}
    rng = random.Random(0)
    for _ in range(5000):
        sources = [rng.choice(list(sets)) for _ in range(rng.randint(1, 33))]
        labels = assign_labels(sources, sets, rng)
        assert all(lab in sets[s] for s, lab in zip(sources, labels))
        for label, target in batch_targets(sources, sets).items():
            assert abs(labels.count(label) - target) <= 1.0


def test_label_shares_inside_a_source_are_uniform_not_the_prior(tmp_path: Path) -> None:
    loader = _loader(_data(tmp_path), batch_size=16)
    _draw(loader, "nli", 400)
    report = loader.label_balance_report()["nli"]["sources"]
    # FEVER is 75 % entailment in the data; balanced it is half and half.
    assert report["fever"]["data_label_prior"]["0"] == pytest.approx(0.75)
    for name, entry in report.items():
        for share in entry["drawn_label_share"].values():
            assert share == pytest.approx(1 / len(entry["label_set"]), abs=0.06), name


@pytest.mark.parametrize("exponent", [1.0, 0.5])
def test_sources_keep_their_dataset_sampling_share(tmp_path: Path, exponent: float) -> None:
    loader = _loader(_data(tmp_path), batch_size=16, dataset_sampling_exponents={"nli": exponent})
    _draw(loader, "nli", 500)
    rows = {s: sum(v.values()) for s, v in NLI_SOURCES.items()}
    total = sum(n**exponent for n in rows.values())
    report = loader.label_balance_report()["nli"]["sources"]
    for source, n in rows.items():
        assert report[source]["target_source_share"] == pytest.approx(n**exponent / total)
        assert report[source]["drawn_source_share"] == pytest.approx(n**exponent / total, abs=0.03)


def test_seed_stable_and_reset_repeats(tmp_path: Path) -> None:
    data = _data(tmp_path)

    def texts(loader: StreamingParquetMultiTaskDataLoader) -> List[Tuple[str, ...]]:
        return [tuple(r["premise"] for r in b) for b in _draw(loader, "nli", 30)]

    first, second = _loader(data), _loader(data)
    assert texts(first) == texts(second)
    assert texts(_loader(data, seed=12)) != texts(_loader(data))
    first.reset()
    assert texts(first) == texts(_loader(data))


def test_batches_format_and_carry_the_balanced_labels(tmp_path: Path) -> None:
    loader = _loader(_data(tmp_path))
    nli = loader.generate_batch("nli")
    para = loader.generate_batch("paraphrase")
    assert nli.batch_size == 8 and set(nli.labels["nli_labels"].tolist()) <= {0, 1, 2}
    assert para.batch_size == 8 and set(para.labels["para_labels"].tolist()) <= {0.0, 1.0}


def test_default_off_keeps_the_plain_stream(tmp_path: Path) -> None:
    data = _data(tmp_path)
    plain = StreamingParquetMultiTaskDataLoader(data_dir=data, batch_size=8, seed=11)
    explicit = _loader(data, label_balanced_tasks=())
    assert plain._balanced == {} and plain.label_balance_report() == {}
    a = [tuple(r["premise"] for r in b) for b in _draw(plain, "nli", 10)]
    b = [tuple(r["premise"] for r in b) for b in _draw(explicit, "nli", 10)]
    assert a == b
    assert TrainingConfig().label_balanced_tasks == []


def test_options_are_validated(tmp_path: Path) -> None:
    data = _data(tmp_path)
    with pytest.raises(ValueError):
        _loader(data, label_balanced_tasks=("qa",))
    with pytest.raises(ValueError):
        _loader(data, label_balanced_tasks=("nli",), split="val")
    with pytest.raises(ValueError):
        TrainingConfig(label_balanced_tasks=["similarity"])
    assert TrainingConfig(label_balanced_tasks=["nli", "paraphrase"]).label_balanced_tasks


def test_majority_label_is_skipped_at_a_full_queue_with_bounded_memory(tmp_path: Path) -> None:
    loader = _loader(_data(tmp_path), buffer_size=2, batch_size=2)
    _draw(loader, "nli", 300)
    sampler = loader._balanced["nli"]
    assert all(
        len(queue) <= sampler.queue_limit
        for queues in sampler._queues.values()
        for queue in queues.values()
    )
    assert sampler.skipped["anli"] > 0  # anli entailment is 62 % of its rows
