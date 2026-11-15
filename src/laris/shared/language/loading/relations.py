"""Row sampler for the contrastive similarity task (T199).

The pair file of T197 holds relation pairs (`sentence1`, `sentence2`, `relation`) that are only
partly shuffled and very uneven (PAWS non-paraphrases are 4 % of the rows), so one shared stream
cannot serve every row kind. Each kind reads its own endless stream of the file (the rows of that
relation only, through a bounded shuffle buffer); `simcse` reads the sentences of all rows. A row
kind is drawn per row by the configured shares and turned into a training row:

- `simcse`: the sentence alone; its positive is itself, seen through a second dropout pass.
- a positive relation (entailment, paraphrase duplicate, adjacent sentences): the pair is
  anchor and positive.
- a hard-negative relation (contradiction, PAWS word swap): a SimCSE row whose second sentence is
  also a negative for that anchor.

Order-swapped rows are never read (a symmetric head cannot separate them, T197).
"""

import random
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

import pyarrow.compute as pc
import pyarrow.parquet as pq

from laris.shared.config.schemas import (
    CONTRASTIVE_HARD_NEGATIVE_KINDS,
    CONTRASTIVE_POSITIVE_KINDS,
    CONTRASTIVE_ROW_KINDS,
)

SIMCSE = "simcse"
PAIR_COLUMNS = ("sentence1", "sentence2", "relation")


def relation_stream(
    paths: Sequence[Path], relation: Optional[str], chunk_rows: int = 8192
) -> Iterator[Dict[str, Any]]:
    """Endless stream of the pair rows of one relation (all rows for `None`), in file order.

    A full pass without a single matching row raises instead of spinning.
    """
    while True:
        found = False
        for path in paths:
            for chunk in pq.ParquetFile(path).iter_batches(
                batch_size=chunk_rows, columns=list(PAIR_COLUMNS)
            ):
                if relation is not None:
                    chunk = chunk.filter(pc.equal(chunk.column("relation"), relation))
                for row in chunk.to_pylist():
                    found = True
                    yield row
        if not found:
            names = [str(p) for p in paths]
            raise RuntimeError(f"no pair rows of relation {relation!r} in {names}")


def shuffled(stream: Iterator[Any], size: int, rng: random.Random) -> Iterator[Any]:
    """Local shuffle: fill a buffer of `size`, then emit a random item and refill its slot."""
    buffer: List[Any] = []
    for item in stream:
        if len(buffer) < size:
            buffer.append(item)
            continue
        slot = rng.randrange(size)
        buffer[slot], item = item, buffer[slot]
        yield item


class RelationRowSampler:
    """Draws batches of contrastive rows `{kind, anchor, positive, negative}`.

    `streams` maps each row kind with a positive share to its stream (`simcse` yields rows of any
    relation, of which only `sentence1` is used).
    """

    def __init__(
        self,
        streams: Mapping[str, Iterator[Dict[str, Any]]],
        shares: Mapping[str, float],
        rng: random.Random,
    ) -> None:
        kinds = [k for k in CONTRASTIVE_ROW_KINDS if shares.get(k, 0.0) > 0]
        if not kinds:
            raise ValueError("the contrastive row shares need at least one positive share")
        missing = [k for k in kinds if k not in streams]
        if missing:
            raise ValueError(f"no stream for row kinds {missing}")
        self.kinds = kinds
        self.weights = [float(shares[k]) for k in kinds]
        self.rng = rng
        self._streams = {k: streams[k] for k in kinds}
        self.drawn: Dict[str, int] = {k: 0 for k in kinds}
        self.empty_skipped = 0

    def draw_batch(self, size: int) -> List[Dict[str, Any]]:
        """`size` rows; a record with an empty sentence is skipped and the kind drawn again."""
        rows: List[Dict[str, Any]] = []
        while len(rows) < size:
            kind = self.rng.choices(self.kinds, weights=self.weights, k=1)[0]
            record = next(self._streams[kind])
            first = (record.get("sentence1") or "").strip()
            second = (record.get("sentence2") or "").strip()
            if not first or (kind != SIMCSE and not second):
                self.empty_skipped += 1
                continue
            rows.append(
                {
                    "kind": kind,
                    "anchor": first,
                    "positive": second if kind in CONTRASTIVE_POSITIVE_KINDS else None,
                    "negative": second if kind in CONTRASTIVE_HARD_NEGATIVE_KINDS else None,
                }
            )
            self.drawn[kind] += 1
        return rows

    def report(self) -> Dict[str, Any]:
        total = sum(self.drawn.values())
        return {
            "rows": total,
            "drawn_share": {k: (n / total if total else 0.0) for k, n in self.drawn.items()},
            "target_share": {k: w / sum(self.weights) for k, w in zip(self.kinds, self.weights)},
            "empty_rows_skipped": self.empty_skipped,
        }
