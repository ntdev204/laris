"""Sentence-order head and loss (T195): shapes, loss at initialisation, checkpoint loading.

Forward passes only: no backward step, no optimizer step, no training authorization.
"""

import math
import zlib
from pathlib import Path
from types import SimpleNamespace
from typing import List

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import torch

from laris.research.language.evaluation.evaluator import EvaluationReport, report_to_dict
from laris.research.language.evaluation.sentence_order import (
    CHANCE_LOSS,
    order_metrics,
    score_sentence_order,
)
from laris.research.language.training.objectives import sentence_order_loss
from laris.research.language.training.trainer import LanguageEncoderTrainer
from laris.shared.config.schemas import TrainingConfig
from laris.shared.language.encoder.transformer import (
    ORDER_CLASS_COUNT,
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
    RandomlyInitializedTransformerEncoder,
)
from laris.shared.language.loading.checkpoint import (
    load_checkpoint,
    load_model_weights,
    save_checkpoint,
)
from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader
from laris.shared.language.loading.segments import IGNORE_INDEX

VOCAB = 200


def _config() -> LanguageEncoderConfig:
    return LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=VOCAB,
        max_sequence_length=64,
    )  # fmt: skip


class _Tok:
    """Stable word ids inside a small vocabulary."""

    def encode_as_ids(self, text: str) -> List[int]:
        return [10 + zlib.crc32(w.encode()) % (VOCAB - 10) for w in text.split()]


def _shards(tmp_path: Path, docs: int = 10) -> Path:
    path = tmp_path / "val.parquet"
    rows = [
        {"id": f"<urn:val-{d}>#0", "text": " ".join(f"Doc{d} sentence{k} ends." for k in range(4))}
        for d in range(docs)
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _order_batch(tmp_path: Path):
    loader = StreamingParquetMultiTaskDataLoader(
        task_paths={"mlm": [_shards(tmp_path)]}, tokenizer=_Tok(), vocab_size=VOCAB, seq_len=64,
        batch_size=6, seed=3, return_tensors="pt", mlm_pair_fraction=1.0, order_task=True,
    )  # fmt: skip
    return loader.generate_batch("mlm")


def _trainer(model: PyTorchTransformerEncoder, order_weight: float) -> LanguageEncoderTrainer:
    return LanguageEncoderTrainer(
        model, config=None, dataloader=None, use_8bit_adam=False, device="cpu",
        order_loss_weight=order_weight,
    )  # fmt: skip


# ---------------------------------------------------------------- head and shapes
def test_order_head_is_zero_and_gives_three_uniform_logits() -> None:
    model = PyTorchTransformerEncoder(_config())
    assert ORDER_CLASS_COUNT == 3
    assert model.order_head.weight.shape == (3, 384) and model.order_head.bias.shape == (3,)
    assert not model.order_head.weight.any() and not model.order_head.bias.any()
    ids = torch.randint(5, VOCAB, (4, 16))
    out = model(ids, task="order")
    assert out["order_logits"].shape == (4, 3)
    assert set(out) == {"hidden_states", "cls_embedding", "order_logits"}
    assert torch.equal(out["order_logits"], torch.zeros(4, 3))
    assert model(ids)["order_logits"].shape == (4, 3)  # every head without a task


def test_with_order_adds_order_logits_to_a_single_task_pass() -> None:
    model = PyTorchTransformerEncoder(_config())
    ids = torch.randint(5, VOCAB, (2, 16))
    assert "order_logits" not in model(ids, task="mlm")
    out = model(ids, task="mlm", with_order=True)
    assert out["order_logits"].shape == (2, 3) and "mlm_logits" in out


def test_head_parameter_count_matches_the_instantiated_model() -> None:
    cfg = _config()
    model = PyTorchTransformerEncoder(cfg)
    assert sum(p.numel() for p in model.parameters()) == cfg.calculate_parameter_count(True)


def test_numpy_reference_model_has_the_same_zero_order_head() -> None:
    model = RandomlyInitializedTransformerEncoder(_config())
    out = model.forward(np.random.default_rng(0).integers(5, VOCAB, (2, 8)))
    assert out["order_logits"].shape == (2, 3) and not out["order_logits"].any()


def test_same_seed_gives_the_same_weights() -> None:
    a = PyTorchTransformerEncoder(_config()).state_dict()
    b = PyTorchTransformerEncoder(_config()).state_dict()
    assert all(torch.equal(a[k], b[k]) for k in a)


# ---------------------------------------------------------------- loss
def test_order_loss_at_zero_logits_is_ln3_and_ignores_unlabelled_rows() -> None:
    logits = torch.zeros(5, 3, requires_grad=True)
    targets = torch.tensor([0, 1, 2, IGNORE_INDEX, 1])
    assert sentence_order_loss(logits, targets).item() == pytest.approx(math.log(3), abs=1e-6)
    none = sentence_order_loss(logits, torch.full((5,), IGNORE_INDEX))
    assert none.item() == 0.0 and none.requires_grad


def test_order_loss_matches_cross_entropy_on_the_labelled_rows() -> None:
    logits = torch.tensor([[2.0, 0.0, -1.0], [0.0, 0.0, 0.0], [1.0, 3.0, 0.0]])
    targets = torch.tensor([0, IGNORE_INDEX, 1])
    expected = torch.nn.functional.cross_entropy(logits[[0, 2]], targets[[0, 2]])
    assert sentence_order_loss(logits, targets).item() == pytest.approx(expected.item())
    with pytest.raises(ValueError):
        sentence_order_loss(logits, torch.tensor([0, 1]))


def test_trainer_adds_weighted_ln3_to_the_mlm_loss_at_initialisation(tmp_path: Path) -> None:
    batch = _order_batch(tmp_path)
    labels = batch.labels
    assert (labels["order_labels"] != IGNORE_INDEX).any()
    model = PyTorchTransformerEncoder(_config())
    plain, weighted = _trainer(model, 0.0), _trainer(model, 0.5)
    losses = []
    for trainer in (plain, weighted):
        with torch.no_grad():
            out = trainer._forward("mlm", batch.token_ids, batch.attention_mask, labels)
            losses.append(
                trainer._compute_torch_loss("mlm", out, labels, batch.attention_mask).item()
            )
    assert "order_logits" in out
    assert weighted._last_order_loss == pytest.approx(math.log(3), abs=1e-6)
    assert losses[1] - losses[0] == pytest.approx(0.5 * math.log(3), abs=1e-5)
    assert plain._last_order_loss is None


def test_trainer_ignores_order_labels_with_zero_weight(tmp_path: Path) -> None:
    batch = _order_batch(tmp_path)
    trainer = _trainer(PyTorchTransformerEncoder(_config()), 0.0)
    out = trainer._forward("mlm", batch.token_ids, batch.attention_mask, batch.labels)
    assert "order_logits" not in out


def test_trainer_rejects_a_negative_or_infinite_order_weight() -> None:
    model = PyTorchTransformerEncoder(_config())
    for bad in (-0.1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            _trainer(model, bad)


def test_training_config_ties_order_task_to_its_weight() -> None:
    TrainingConfig()  # defaults: off
    TrainingConfig(mlm_pair_fraction=0.5, order_task=True, loss_lambda_order=0.1)
    with pytest.raises(ValueError, match="loss_lambda_order"):
        TrainingConfig(mlm_pair_fraction=0.5, order_task=True)
    with pytest.raises(ValueError, match="loss_lambda_order"):
        TrainingConfig(loss_lambda_order=0.1)
    assert TrainingConfig().loss_lambda_order == 0.0


# ---------------------------------------------------------------- checkpoint loading
def _stage1_state(model: PyTorchTransformerEncoder) -> dict:
    """A state dict as a checkpoint written before T195 holds it: no order head."""
    return {k: v.clone() for k, v in model.state_dict().items() if not k.startswith("order_head")}


def test_a_checkpoint_without_order_head_loads_and_keeps_the_head_at_zero() -> None:
    source = PyTorchTransformerEncoder(_config())
    with torch.no_grad():
        source.layers[0].q_proj.weight.add_(1.0)  # weights differ from a fresh model
    target = PyTorchTransformerEncoder(_config())
    missing = load_model_weights(target, _stage1_state(source))
    assert sorted(missing) == ["order_head.bias", "order_head.weight"]
    assert torch.equal(target.layers[0].q_proj.weight, source.layers[0].q_proj.weight)
    assert not target.order_head.weight.any() and not target.order_head.bias.any()


def test_loading_still_refuses_other_missing_and_unexpected_keys() -> None:
    model = PyTorchTransformerEncoder(_config())
    state = _stage1_state(model)
    del state["final_norm.weight"]
    with pytest.raises(RuntimeError, match="final_norm"):
        load_model_weights(model, state)
    state = {**model.state_dict(), "extra_head.weight": torch.zeros(1)}
    with pytest.raises(RuntimeError, match="extra_head"):
        load_model_weights(model, state)
    assert load_model_weights(model, model.state_dict()) == []


def test_load_checkpoint_restores_a_pre_t195_checkpoint(tmp_path: Path) -> None:
    source = PyTorchTransformerEncoder(_config())
    save_checkpoint(
        tmp_path / "ckpt", model=source, optimizer=None, scheduler=None, scaler=None,
        counters={"optimizer_steps": 0}, provenance={},
    )  # fmt: skip
    torch.save(_stage1_state(source), tmp_path / "ckpt" / "model.pt")
    _rewrite_digest(tmp_path / "ckpt")
    target = PyTorchTransformerEncoder(_config())
    restored = load_checkpoint(tmp_path / "ckpt", model=target, restore_rng=False)
    assert restored["counters"] == {"optimizer_steps": 0}
    assert not target.order_head.weight.any()


def test_resuming_optimizer_state_of_a_pre_t195_checkpoint_is_refused(tmp_path: Path) -> None:
    source = PyTorchTransformerEncoder(_config())
    optimizer = torch.optim.AdamW(source.parameters())
    save_checkpoint(
        tmp_path / "ckpt", model=source, optimizer=optimizer, scheduler=None, scaler=None,
        counters={}, provenance={},
    )  # fmt: skip
    torch.save(_stage1_state(source), tmp_path / "ckpt" / "model.pt")
    _rewrite_digest(tmp_path / "ckpt")
    target = PyTorchTransformerEncoder(_config())
    with pytest.raises(ValueError, match="init-from"):
        load_checkpoint(
            tmp_path / "ckpt", model=target, optimizer=torch.optim.AdamW(target.parameters()),
            restore_rng=False,
        )  # fmt: skip


def _rewrite_digest(directory: Path) -> None:
    import json

    from laris.shared.language.loading.checkpoint import MANIFEST_FILE, file_sha256

    manifest_path = directory / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text())
    manifest["model_sha256"] = file_sha256(directory / "model.pt")
    manifest_path.write_text(json.dumps(manifest))


# ---------------------------------------------------------------- evaluator
def test_order_metrics_against_hand_computed_values() -> None:
    logits = np.array([[3, 0, 0], [0, 3, 0], [0, 3, 0], [0, 0, 3], [1, 1, 1]], dtype=float)
    gold = np.array([0, 1, 0, 2, IGNORE_INDEX])
    m = order_metrics(logits, gold)
    assert m["rows"] == 4 and m["accuracy"] == 0.75
    assert m["recall"] == {"in_order": 0.5, "swapped": 1.0, "other_document": 1.0}
    assert m["gold_shares"]["in_order"] == 0.5 and m["majority_baseline_accuracy"] == 0.5
    assert m["predicted_shares"]["swapped"] == 0.5
    expected = -math.log(math.exp(3) / (math.exp(3) + 2))
    lost = -math.log(1 / (math.exp(3) + 2))
    assert m["loss"] == pytest.approx((3 * expected + lost) / 4)
    with pytest.raises(ValueError):
        order_metrics(logits[:1], np.array([IGNORE_INDEX]))


def test_forward_only_order_score_at_initialisation_is_chance(tmp_path: Path) -> None:
    encoder = SimpleNamespace(
        model=PyTorchTransformerEncoder(_config()), tokenizer=_Tok(), config=_config(),
        seq_len=64, device="cpu",
    )  # fmt: skip
    result = score_sentence_order(encoder, [_shards(tmp_path)], rows=10, batch_size=4, seed=1)
    assert result["loss"] == pytest.approx(CHANCE_LOSS, abs=1e-6)
    # a zero head predicts the first class everywhere: accuracy is the in-order share
    assert result["predicted_shares"]["in_order"] == 1.0
    assert result["accuracy"] == pytest.approx(result["gold_shares"]["in_order"])
    assert result["drawn_rows"] == 10 and result["masked_inputs"] is False
    assert not any(p.grad is not None for p in encoder.model.parameters())


def test_report_carries_the_order_diagnostic_without_changing_the_verdict() -> None:
    report = EvaluationReport(split="val", passed=False)
    report.diagnostics["sentence_order"] = {"gate": None, "datasets": []}
    body = report_to_dict(report)
    assert body["passed"] is False and body["diagnostics"]["sentence_order"]["gate"] is None
    assert "diagnostics" not in report_to_dict(EvaluationReport(split="val"))
