"""Regression tests for training data integrity (Issue #246)."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.language.dataloader import StreamingParquetMultiTaskDataLoader
from laris.language.schemas import SpecialTokenConfig
from laris.language.tokenizer_trainer import TokenizerTrainerConfig, TokenizerTrainingPipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _write_split(task_dir: Path, name: str, table: pa.Table) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, task_dir / f"{name}.parquet")


def _mlm_table(prefix: str) -> pa.Table:
    return pa.table({"id": [f"{prefix}1"], "text": [f"{prefix} alpha beta gamma delta"]})


def test_loader_reads_only_train_split(tmp_path: Path) -> None:
    for split in ("train", "val", "test"):
        _write_split(tmp_path / "wikipedia_en", split, _mlm_table(split))
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path, vocab_size=500, seq_len=16, batch_size=1, fallback_to_synthetic=False
    )
    assert [p.name for p in loader.task_paths["mlm"]] == ["train.parquet"]
    eval_loader = StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path,
        vocab_size=500,
        seq_len=16,
        batch_size=1,
        split="val",
        fallback_to_synthetic=False,
    )
    assert [p.name for p in eval_loader.task_paths["mlm"]] == ["val.parquet"]


def test_empty_data_dir_fails_fast_by_default(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        StreamingParquetMultiTaskDataLoader(data_dir=tmp_path, vocab_size=500, seq_len=16)


def test_fallback_tokenizer_is_process_independent(tmp_path: Path) -> None:
    code = (
        "import sys;"
        "from laris.language.dataloader import StreamingParquetMultiTaskDataLoader as L;"
        "l = L(data_dir=sys.argv[1], vocab_size=500, seq_len=16, fallback_to_synthetic=True);"
        "print(l._tokenize('quantum entanglement spooky'))"
    )
    outs = set()
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
        res = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outs.add(res.stdout.strip())
    assert len(outs) == 1


def _qa_loader(tmp_path: Path, rows: dict) -> StreamingParquetMultiTaskDataLoader:
    _write_split(tmp_path / "squad", "train", pa.table(rows))
    return StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path, vocab_size=500, seq_len=64, batch_size=1, fallback_to_synthetic=False
    )


def test_qa_labels_point_at_the_real_answer(tmp_path: Path) -> None:
    context = "The speed of light is 299792458 meters per second in vacuum."
    answer = "299792458 meters"
    loader = _qa_loader(
        tmp_path,
        {
            "context": [context],
            "question": ["What is the speed of light?"],
            "answers": [{"text": [answer], "answer_start": [context.index(answer)]}],
        },
    )
    batch = loader.generate_batch(task_type="qa")
    start = int(batch.labels["qa_start_positions"][0])
    end = int(batch.labels["qa_end_positions"][0])
    ids = [int(t) for t in batch.token_ids[0]]
    assert ids[start : end + 1] == loader._tokenize(answer)


def test_qa_unanswerable_points_at_cls(tmp_path: Path) -> None:
    loader = _qa_loader(
        tmp_path,
        {"context": ["Some context here."], "question": ["Unanswerable?"], "answers": [None]},
    )
    batch = loader.generate_batch(task_type="qa")
    assert int(batch.labels["qa_start_positions"][0]) == 0
    assert int(batch.labels["qa_end_positions"][0]) == 0


def test_corrupt_shard_is_skipped_with_warning(tmp_path: Path, caplog) -> None:
    task_dir = tmp_path / "wikipedia_en"
    _write_split(task_dir, "train", _mlm_table("good"))
    (task_dir / "train-bad.parquet").write_bytes(b"not a parquet file")
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path, vocab_size=500, seq_len=16, batch_size=1, fallback_to_synthetic=False
    )
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            loader.generate_batch(task_type="mlm")
    assert any("train-bad.parquet" in r.message for r in caplog.records)


def test_all_corrupt_shards_raise_instead_of_hanging(tmp_path: Path) -> None:
    task_dir = tmp_path / "wikipedia_en"
    task_dir.mkdir()
    (task_dir / "train.parquet").write_bytes(b"not a parquet file")
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=tmp_path, vocab_size=500, seq_len=16, batch_size=1, fallback_to_synthetic=False
    )
    with pytest.raises(RuntimeError):
        loader.generate_batch(task_type="mlm")


def test_sentencepiece_args_reserve_mask_before_other_symbols(tmp_path: Path) -> None:
    pipeline = TokenizerTrainingPipeline(TokenizerTrainerConfig(output_dir=tmp_path))
    args = pipeline.build_sentencepiece_args(input_file="x.txt")
    symbols = next(a for a in args if a.startswith("--user_defined_symbols=")).split("=", 1)[1]
    special = SpecialTokenConfig()
    ordered = symbols.split(",")[:4]
    assert ordered == [
        special.mask_token,
        special.math_token,
        special.greek_token,
        special.unit_token,
    ]


