"""The real-data loader must raise instead of inventing labels, counts or tokens."""

from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.language.training.dataloader import StreamingParquetMultiTaskDataLoader


class _Tok:
    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + (ord(c) % 50) for c in text][:20]


def _loader(tmp_path: Path, task: str, rows: List[Dict[str, Any]], **kwargs: Any):
    path = tmp_path / task / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return StreamingParquetMultiTaskDataLoader(
        task_paths={task: [path]}, tokenizer=_Tok(), vocab_size=200, seq_len=64, batch_size=2,
        **kwargs,
    )


def test_unknown_nli_label_raises_instead_of_becoming_neutral(tmp_path: Path) -> None:
    rows = [{"premise": "a", "hypothesis": "b", "label": "-"}] * 2
    with pytest.raises(ValueError, match="Unknown NLI label"):
        _loader(tmp_path, "nli", rows).generate_batch("nli")


def test_unknown_paraphrase_label_raises(tmp_path: Path) -> None:
    rows = [{"sentence1": "a", "sentence2": "b", "label": 7}] * 2
    with pytest.raises(ValueError, match="Unknown paraphrase label"):
        _loader(tmp_path, "paraphrase", rows).generate_batch("paraphrase")


def test_missing_similarity_score_raises_instead_of_zero(tmp_path: Path) -> None:
    rows = [{"sentence1": "a", "sentence2": "b", "score": None}] * 2
    with pytest.raises(ValueError, match="without a score"):
        _loader(tmp_path, "similarity", rows).generate_batch("similarity")


def test_qa_offset_mismatch_raises_but_unanswerable_is_a_real_label(tmp_path: Path) -> None:
    good = {"question": "q", "context": "hello world", "answers": {"text": [], "answer_start": []}}
    batch = _loader(tmp_path, "qa", [good] * 2).generate_batch("qa")
    assert batch.labels["qa_start_positions"].tolist() == [0, 0]
    bad = {
        "question": "q", "context": "hello world",
        "answers": {"text": ["world"], "answer_start": [3]},
    }
    with pytest.raises(ValueError, match="does not point at"):
        _loader(tmp_path / "bad", "qa", [bad] * 2).generate_batch("qa")


def test_real_data_mode_requires_a_tokenizer(tmp_path: Path) -> None:
    path = tmp_path / "nli" / "train.parquet"
    path.parent.mkdir()
    pq.write_table(pa.table({"premise": ["a"], "hypothesis": ["b"], "label": ["neutral"]}), path)
    with pytest.raises(ValueError, match="fitted tokenizer"):
        StreamingParquetMultiTaskDataLoader(
            task_paths={"nli": [path]}, require_real_data=True, tokenizer=None
        )


def test_requesting_a_task_without_shards_raises_instead_of_switching(tmp_path: Path) -> None:
    rows = [{"premise": "a", "hypothesis": "b", "label": "neutral"}] * 2
    with pytest.raises(KeyError, match="no data shards"):
        _loader(tmp_path, "nli", rows).generate_batch("qa")
