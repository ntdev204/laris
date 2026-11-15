"""Dense-retrieval task (T178).

Covers discovery, in-batch negatives, config validation and the forward-only loss.
"""

from pathlib import Path
from typing import List

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.loading.dataloader import (
    RETRIEVAL_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)


class _Tok:
    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + (ord(c) % 50) for c in text][:60]


def _data(tmp_path: Path, rows: int = 12) -> Path:
    for name in ("gooaq_en", "coco_captions_en"):
        out = tmp_path / name
        out.mkdir()
        table = pa.Table.from_pylist(
            [
                {"query": f"{name} query {i}", "positive": f"passage {i} of {name}", "source": name}
                for i in range(rows)
            ]
        )
        pq.write_table(table, out / "train-00000.parquet")
        pq.write_table(table, out / "val-00000.parquet")
    return tmp_path


def _loader(data: Path, **kwargs) -> StreamingParquetMultiTaskDataLoader:
    return StreamingParquetMultiTaskDataLoader(
        data_dir=data, tokenizer=_Tok(), vocab_size=200, seq_len=64, batch_size=2, seed=1,
        **kwargs,
    )  # fmt: skip


def test_retrieval_task_exists_only_when_enabled(tmp_path):
    data = _data(tmp_path)
    with pytest.raises(FileNotFoundError):  # no other task has data here, and retrieval is off
        _loader(data)
    loader = _loader(data, include_retrieval_task=True)
    assert {p.parent.name for p in loader.task_paths["retrieval"]} == {
        "gooaq_en",
        "coco_captions_en",
    }
    assert {"gooaq_en", "coco_captions_en"} <= set(RETRIEVAL_DATASET_DIRS)
    val = _loader(data, split="val", include_retrieval_task=True)  # validation scores the same task
    assert "retrieval" in val.task_paths


def test_batch_has_in_batch_negatives_and_its_own_size_and_length(tmp_path):
    loader = _loader(
        _data(tmp_path), include_retrieval_task=True, retrieval_batch_size=6,
        retrieval_max_sequence_length=32, trim_padding=True,
    )  # fmt: skip
    batch = loader.generate_batch("retrieval")
    labels = batch.labels
    assert batch.task_type == "retrieval" and batch.batch_size == 6
    assert labels["retrieval_query_ids"].shape[0] == labels["retrieval_passage_ids"].shape[0] == 6
    assert labels["retrieval_passage_ids"].shape[1] <= 32
    positives = labels["retrieval_positives"]
    assert positives.shape == (6, 6) and positives.diagonal().all()
    assert positives.sum() == 6  # distinct queries and passages: every other passage is a negative


def test_known_positives_of_a_repeated_query_are_masked(tmp_path):
    out = tmp_path / "gooaq_en"
    out.mkdir()
    rows = [
        {"query": "same query", "positive": "first passage"},
        {"query": "same query", "positive": "second passage"},
        {"query": "other query", "positive": "third passage"},
        {"query": "another query", "positive": "third passage"},
    ]
    pq.write_table(pa.Table.from_pylist(rows), out / "train-00000.parquet")
    loader = _loader(tmp_path, include_retrieval_task=True, retrieval_batch_size=4)
    positives = loader.generate_batch("retrieval").labels["retrieval_positives"]
    assert positives.shape == (4, 4)
    # rows may be shuffled, so check the structure: a symmetric mask with 2 + 2 + 2 + 2 extra True
    # cells
    assert (positives == positives.T).all() and positives.sum() == 8


def test_bad_retrieval_settings_are_rejected(tmp_path):
    data = _data(tmp_path)
    with pytest.raises(ValueError, match="retrieval_batch_size"):
        _loader(data, include_retrieval_task=True, retrieval_batch_size=1)
    with pytest.raises(ValueError, match="retrieval_max_sequence_length"):
        _loader(data, include_retrieval_task=True, retrieval_max_sequence_length=128)
    with pytest.raises(ValueError, match="retrieval_task needs"):
        TrainingConfig(retrieval_task=True, loss_lambda_retrieval=0.0)
    assert TrainingConfig(retrieval_task=True, loss_lambda_retrieval=0.2).retrieval_task


def test_retrieval_exponent_is_accepted_and_unknown_task_is_not(tmp_path):
    data = _data(tmp_path)
    _loader(data, include_retrieval_task=True, dataset_sampling_exponents={"retrieval": 0.5})
    with pytest.raises(ValueError, match="dataset sampling exponents"):
        _loader(data, dataset_sampling_exponents={"nonsense": 0.5})


def test_forward_only_loss_is_weighted_and_needs_a_weight(tmp_path):
    torch = pytest.importorskip("torch")
    from laris.research.language.training.objectives import contrastive_retrieval_loss
    from laris.research.language.training.trainer import LanguageEncoderTrainer
    from laris.shared.language.encoder.transformer import (
        LanguageEncoderConfig,
        PyTorchTransformerEncoder,
    )

    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=1, num_heads=6, d_ff=768, vocab_size=200, max_sequence_length=64
    )
    model = PyTorchTransformerEncoder(cfg).eval()
    loader = _loader(_data(tmp_path), include_retrieval_task=True, return_tensors="pt",
                     retrieval_batch_size=4, trim_padding=True)  # fmt: skip
    batch = loader.generate_batch("retrieval")

    def make(weight: float) -> LanguageEncoderTrainer:
        return LanguageEncoderTrainer(
            model, config=None, dataloader=None, use_8bit_adam=False, device="cpu",
            retrieval_loss_weight=weight, retrieval_temperature=0.1,
        )  # fmt: skip

    with torch.no_grad():
        trainer = make(0.25)
        ids, mask = trainer._to_device(batch)
        outputs = trainer._forward("retrieval", ids, mask, batch.labels)
        loss = trainer._compute_torch_loss("retrieval", outputs, batch.labels, mask)
        embeddings = [
            model(
                batch.labels[f"retrieval_{k}_ids"],
                attention_mask=batch.labels[f"retrieval_{k}_mask"],
                task="embedding",
            )["cls_embedding"]
            for k in ("query", "passage")
        ]
        expected = contrastive_retrieval_loss(*embeddings, batch.labels["retrieval_positives"], 0.1)
        assert torch.isfinite(loss)
        assert loss.item() == pytest.approx(0.25 * expected.item(), rel=1e-4)
        with pytest.raises(ValueError, match="loss_lambda_retrieval"):
            make(0.0)._forward("retrieval", ids, mask, batch.labels)
