"""Source- and label-balanced sampling for the NLI and paraphrase tasks (T196).

The plain loader draws a dataset by row count and takes its next record, so each batch carries
the label prior of its sources (FEVER 75 % entailment, SciTail 63 % neutral) and the head can
learn the source instead of the pair. This sampler draws a source per row with the same weights
(rows ** exponent, so source shares are unchanged), then gives every row a label from its source's
own label set (FEVER has no neutral, SciTail no contradiction), so that each label's count in a
batch is within one row of its target: the sum over the batch's rows of 1 / (labels of the row's
source).
"""

import logging
import random
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import pyarrow.compute as pc
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

BALANCEABLE_TASKS = ("nli", "paraphrase")

NLI_LABELS: Dict[Any, int] = {
    "entailment": 0, "0": 0, 0: 0,
    "neutral": 1, "1": 1, 1: 1,
    "contradiction": 2, "2": 2, 2: 2,
}  # fmt: skip


def nli_label(record: Mapping[str, Any]) -> int:
    """Class id of an NLI record (0 entailment, 1 neutral, 2 contradiction); unknown raises."""
    raw = record.get("label") if "label" in record else record.get("gold_label")
    if raw not in NLI_LABELS:
        raise ValueError(f"Unknown NLI label {raw!r}; refusing to guess a class")
    return NLI_LABELS[raw]


def paraphrase_label(record: Mapping[str, Any]) -> int:
    """1 for a paraphrase (duplicate), 0 otherwise; unknown raises."""
    raw = record.get("is_duplicate") if "is_duplicate" in record else record.get("label")
    if raw in (1, True, "1", "duplicate"):
        return 1
    if raw in (0, False, "0", "not_duplicate"):
        return 0
    raise ValueError(f"Unknown paraphrase label {raw!r}; refusing to guess")


# Per task: the label parser and the label columns in the order the parser reads them.
TASK_LABELS: Dict[str, Tuple[Callable[[Mapping[str, Any]], int], Tuple[str, ...]]] = {
    "nli": (nli_label, ("label", "gold_label")),
    "paraphrase": (paraphrase_label, ("is_duplicate", "label")),
}


def label_counts(path: Path, task: str) -> Dict[int, int]:
    """Rows per label class in one shard, read from its label column only."""
    parse, columns = TASK_LABELS[task]
    names = pq.ParquetFile(path).schema_arrow.names
    column = next((c for c in columns if c in names), None)
    if column is None:
        raise ValueError(f"{path} has no {task} label column (looked for {list(columns)})")
    table = pq.read_table(path, columns=[column])
    counts: Dict[int, int] = {}
    for entry in pc.value_counts(table[column]).to_pylist():
        label = parse({column: entry["values"]})
        counts[label] = counts.get(label, 0) + int(entry["counts"])
    return counts


def assign_labels(
    sources: Sequence[str], label_sets: Mapping[str, Sequence[int]], rng: random.Random
) -> List[int]:
    """One label per row from its source's label set, keeping every label near its batch target.

    Rows with the fewest choices go first, and each takes the allowed label with the largest
    remaining deficit (target minus count so far, the target counting all the batch's rows);
    ties are broken at random.
    """
    target = batch_targets(sources, label_sets)
    order = list(range(len(sources)))
    rng.shuffle(order)
    order.sort(key=lambda i: len(label_sets[sources[i]]))
    count = {label: 0 for label in target}
    result = [0] * len(sources)
    for i in order:
        allowed = label_sets[sources[i]]
        best = max(target[label] - count[label] for label in allowed)
        choices = [label for label in allowed if target[label] - count[label] == best]
        label = choices[rng.randrange(len(choices))]
        count[label] += 1
        result[i] = label
    return result


def batch_targets(
    sources: Sequence[str], label_sets: Mapping[str, Sequence[int]]
) -> Dict[int, float]:
    """Expected count of each label in a batch whose rows come from `sources`."""
    target: Dict[int, float] = {}
    for source in sources:
        for label in label_sets[source]:
            target[label] = target.get(label, 0.0) + 1.0 / len(label_sets[source])
    return target


class LabelBalancedSampler:
    """Draws batches of one task's records: a source per row, then a label within that source.

    `sources` maps a source name (the dataset directory) to its shards. Each source is read as
    its own endless stream; records are routed into per-label queues of at most `queue_limit`
    rows, and a record arriving at a full queue is skipped (counted in `skipped`), which is how a
    majority label is undersampled. Memory stays bounded by sources x labels x queue_limit.
    """

    def __init__(
        self,
        task: str,
        sources: Mapping[str, Sequence[Path]],
        stream_factory: Callable[[List[Path]], Iterator[Dict[str, Any]]],
        rng: random.Random,
        dataset_exponent: float = 1.0,
        queue_limit: int = 256,
        max_scan: int = 100_000,
        label_counts_by_source: Optional[Mapping[str, Mapping[int, int]]] = None,
    ) -> None:
        if task not in TASK_LABELS:
            raise ValueError(f"label balancing supports {list(BALANCEABLE_TASKS)}, not '{task}'")
        if not sources:
            raise ValueError(f"label balancing for '{task}' needs at least one source")
        if queue_limit < 1 or max_scan < 1:
            raise ValueError("queue_limit and max_scan must be positive")
        self.task = task
        self._parse = TASK_LABELS[task][0]
        self.rng = rng
        self.queue_limit = queue_limit
        self.max_scan = max_scan
        self.label_counts: Dict[str, Dict[int, int]] = {}
        for name, paths in sources.items():
            if label_counts_by_source is not None and name in label_counts_by_source:
                counts = dict(label_counts_by_source[name])
            else:
                counts = {}
                for path in paths:
                    for label, n in label_counts(path, task).items():
                        counts[label] = counts.get(label, 0) + n
            if not counts:
                raise ValueError(f"source '{name}' of '{task}' has no labelled rows")
            self.label_counts[name] = counts
        self.sources = sorted(sources)
        self.label_sets = {name: sorted(self.label_counts[name]) for name in self.sources}
        self.weights = [
            sum(self.label_counts[name].values()) ** dataset_exponent for name in self.sources
        ]
        self._streams = {name: stream_factory(list(sources[name])) for name in self.sources}
        self._queues: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            name: {label: [] for label in self.label_sets[name]} for name in self.sources
        }
        self.drawn: Dict[str, Dict[int, int]] = {
            name: {label: 0 for label in self.label_sets[name]} for name in self.sources
        }
        self.skipped: Dict[str, int] = {name: 0 for name in self.sources}
        self.batches = 0
        self.max_batch_deviation = 0.0
        self.batch_label_share: Dict[int, List[float]] = {}

    def source_shares(self) -> Dict[str, float]:
        """Share of rows each source is drawn with (rows ** exponent, normalised)."""
        total = sum(self.weights)
        return {name: w / total for name, w in zip(self.sources, self.weights)}

    def _next_of(self, source: str, label: int) -> Dict[str, Any]:
        queue = self._queues[source][label]
        if queue:
            return queue.pop(0)
        for _ in range(self.max_scan):
            record = next(self._streams[source])
            got = self._parse(record)
            if got not in self._queues[source]:
                raise ValueError(f"source '{source}' yielded label {got} absent from its counts")
            if got == label:
                return record
            if len(self._queues[source][got]) < self.queue_limit:
                self._queues[source][got].append(record)
            else:
                self.skipped[source] += 1
        raise RuntimeError(
            f"no '{self.task}' record with label {label} in {self.max_scan} rows of '{source}'"
        )

    def draw_batch(self, size: int) -> List[Dict[str, Any]]:
        """`size` records: sources by weight, labels balanced within the batch."""
        sources = self.rng.choices(self.sources, weights=self.weights, k=size)
        labels = assign_labels(sources, self.label_sets, self.rng)
        records = [self._next_of(s, lab) for s, lab in zip(sources, labels)]
        target = batch_targets(sources, self.label_sets)
        for source, label in zip(sources, labels):
            self.drawn[source][label] += 1
        for label, expected in target.items():
            got = labels.count(label)
            self.max_batch_deviation = max(self.max_batch_deviation, abs(got - expected))
            self.batch_label_share.setdefault(label, []).append(got / size)
        self.batches += 1
        return records

    def report(self) -> Dict[str, Any]:
        """Label share per source and per batch among the records drawn so far."""
        rows = {name: sum(self.drawn[name].values()) for name in self.sources}
        total_rows = sum(rows.values())
        all_labels = sorted({lab for labels in self.label_sets.values() for lab in labels})
        per_batch = {}
        for label in all_labels:
            shares = self.batch_label_share.get(label, [])
            per_batch[str(label)] = {
                "mean": sum(shares) / len(shares) if shares else 0.0,
                "min": min(shares) if shares else 0.0,
                "max": max(shares) if shares else 0.0,
            }
        return {
            "task": self.task,
            "batches": self.batches,
            "rows": total_rows,
            "max_batch_label_deviation_rows": self.max_batch_deviation,
            "per_batch_label_share": per_batch,
            "sources": {
                name: {
                    "label_set": self.label_sets[name],
                    "data_label_prior": {
                        str(lab): n / sum(self.label_counts[name].values())
                        for lab, n in sorted(self.label_counts[name].items())
                    },
                    "target_source_share": self.source_shares()[name],
                    "drawn_source_share": rows[name] / total_rows if total_rows else 0.0,
                    "drawn_label_share": {
                        str(lab): (n / rows[name] if rows[name] else 0.0)
                        for lab, n in sorted(self.drawn[name].items())
                    },
                    "skipped_at_full_queue": self.skipped[name],
                }
                for name in self.sources
            },
        }
