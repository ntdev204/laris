"""Skipping padding and unused heads must not change the loss, only the work done."""

from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

torch = pytest.importorskip("torch")

from laris.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.training.dataloader import (  # noqa: E402
    StreamingParquetMultiTaskDataLoader,
    _text_length,
)
from laris.language.training.trainer import LanguageEncoderTrainer  # noqa: E402


class _Tok:
    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + (ord(c) % 50) for c in text][:60]


def _loader(tmp_path: Path, rows: List[Dict[str, Any]], **kwargs: Any):
    path = tmp_path / "mlm" / "train.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return StreamingParquetMultiTaskDataLoader(
        task_paths={"mlm": [path]}, tokenizer=_Tok(), vocab_size=200, seq_len=64,
        batch_size=4, seed=3, return_tensors="pt", **kwargs,
    )  # fmt: skip


def _trainer() -> LanguageEncoderTrainer:
    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=200, max_sequence_length=64
    )
    return LanguageEncoderTrainer(
        PyTorchTransformerEncoder(cfg), config=None, dataloader=None, use_8bit_adam=False,
        device="cpu",
    )  # fmt: skip


ROWS = [{"text": "w" * n} for n in (3, 5, 8, 12, 4, 6, 9, 11)]


def test_trimmed_batch_has_the_same_loss_as_the_padded_one(tmp_path: Path) -> None:
    trainer = _trainer()
    padded = _loader(tmp_path / "a", ROWS).generate_batch("mlm")
    trimmed = _loader(tmp_path / "b", ROWS, trim_padding=True).generate_batch("mlm")
    assert padded.token_ids.shape[1] == 64 and trimmed.token_ids.shape[1] < 64
    assert trimmed.token_ids.shape[1] % 8 == 0
    losses = []
    for batch in (padded, trimmed):
        ids, mask = batch.token_ids, batch.attention_mask
        out = trainer.model(ids, attention_mask=mask)
        losses.append(trainer._compute_torch_loss("mlm", out, batch.labels, mask).item())
    assert losses[0] == pytest.approx(losses[1], rel=1e-4)


def test_masked_only_head_matches_the_full_head(tmp_path: Path) -> None:
    trainer = _trainer()
    batch = _loader(tmp_path, ROWS).generate_batch("mlm")
    ids, mask = batch.token_ids, batch.attention_mask
    full = trainer.model(ids, attention_mask=mask)
    fast = trainer._forward("mlm", ids, mask, batch.labels)
    assert fast["mlm_logits"].dim() == 2 and set(fast) == {"hidden_states", "cls_embedding",
                                                          "mlm_logits"}  # fmt: skip
    full_loss = trainer._compute_torch_loss("mlm", full, batch.labels, mask)
    fast_loss = trainer._compute_torch_loss("mlm", fast, batch.labels, mask)
    assert fast_loss.item() == pytest.approx(full_loss.item(), rel=1e-5)


def test_other_tasks_do_not_compute_the_vocabulary_projection() -> None:
    model = _trainer().model
    ids = torch.randint(5, 100, (2, 16))
    out = model(ids, task="nli")
    assert "nli_logits" in out and "mlm_logits" not in out and "qa_logits" not in out
    with pytest.raises(ValueError, match="Unknown task"):
        model(ids, task="bogus")


def test_length_pool_groups_similar_lengths(tmp_path: Path) -> None:
    rows = [{"text": "w" * n} for n in ([2, 60] * 16)]
    plain = _loader(tmp_path / "a", rows)
    pooled = _loader(tmp_path / "b", rows, length_pool_batches=8)
    def spread(batch: List[Dict[str, Any]]) -> int:
        sizes = [_text_length(r) for r in batch]
        return max(sizes) - min(sizes)

    assert max(spread(plain._next_records("mlm")) for _ in range(4)) > 0
    widths = [spread(pooled._next_records("mlm")) for _ in range(8)]
    assert sum(1 for w in widths if w == 0) >= 6


def test_datasets_of_a_task_are_interleaved_not_read_one_after_another(tmp_path: Path) -> None:
    paths = []
    for name, n in (("a", 400), ("b", 200)):
        path = tmp_path / name / "train.parquet"
        path.parent.mkdir()
        pq.write_table(pa.Table.from_pylist([{"text": name}] * n), path)
        paths.append(path)
    loader = StreamingParquetMultiTaskDataLoader(
        task_paths={"mlm": paths}, tokenizer=_Tok(), vocab_size=200, seq_len=64, batch_size=4,
        seed=1,
    )  # fmt: skip
    first = [next(loader._task_iterators["mlm"])["text"] for _ in range(90)]
    assert 45 <= first.count("a") <= 75 and first.count("b") >= 15  # roughly 2:1, both present


def test_reset_makes_every_pass_the_same_records(tmp_path: Path) -> None:
    rows = [{"text": "w" * (n % 9 + 1)} for n in range(200)]
    loader = _loader(tmp_path, rows)
    first = loader.generate_batch("mlm").token_ids.tolist()
    loader.generate_batch("mlm")
    loader.reset()
    assert loader.generate_batch("mlm").token_ids.tolist() == first
