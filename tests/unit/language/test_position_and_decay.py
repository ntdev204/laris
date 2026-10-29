"""The PyTorch backbone must be order-aware and weight decay must spare norms/biases."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from laris.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
    _apply_rope,
    _apply_rope_torch,
)
from laris.language.training.trainer import LanguageEncoderTrainer  # noqa: E402


def _model() -> "PyTorchTransformerEncoder":
    cfg = LanguageEncoderConfig(
        d_model=384, num_layers=2, num_heads=6, d_ff=1536, vocab_size=1000, max_sequence_length=64
    )
    return PyTorchTransformerEncoder(cfg).eval()


def test_reversing_the_tokens_changes_the_representation() -> None:
    model = _model()
    ids = torch.randint(5, 900, (1, 16))
    reversed_ids = torch.cat([ids[:, :1], ids[:, 1:].flip(1)], dim=1)
    original = model(ids)["hidden_states"]
    other = model(reversed_ids)["hidden_states"]
    assert (original[:, 1:].flip(1) - other[:, 1:]).abs().max().item() > 1e-3


def test_torch_rope_matches_the_numpy_reference() -> None:
    rng = np.random.default_rng(0)
    q = rng.normal(size=(2, 8, 3, 16)).astype(np.float32)  # (B, S, H, D)
    expected, _ = _apply_rope(q, q, seq_len=8, head_dim=16)
    got = _apply_rope_torch(torch.from_numpy(q).transpose(1, 2))  # (B, H, S, D)
    np.testing.assert_allclose(got.transpose(1, 2).numpy(), expected, atol=1e-5)


def test_weight_decay_only_on_weight_matrices() -> None:
    model = _model()
    trainer = LanguageEncoderTrainer(
        model, config=None, dataloader=None, use_8bit_adam=False, device="cpu", weight_decay=0.01
    )
    decayed = {id(p) for g in trainer.optimizer.param_groups if g["weight_decay"] > 0
               for p in g["params"]}
    free = {id(p) for g in trainer.optimizer.param_groups if g["weight_decay"] == 0
            for p in g["params"]}
    named = dict(model.named_parameters())
    assert id(named["token_embeddings.weight"]) in free
    assert id(named["final_norm.weight"]) in free
    assert id(named["mlm_bias"]) in free
    assert id(named["layers.0.q_proj.weight"]) in decayed
    assert decayed | free == {id(p) for p in model.parameters()}


def test_qa_loss_ignores_padded_positions_and_empty_mlm_is_finite() -> None:
    model = _model()
    trainer = LanguageEncoderTrainer(
        model, config=None, dataloader=None, use_8bit_adam=False, device="cpu"
    )
    qa_logits = torch.zeros(1, 6, 2)
    qa_logits[0, 4:] = 50.0  # padded positions look very attractive
    labels = {"qa_start_positions": torch.tensor([1]), "qa_end_positions": torch.tensor([2])}
    mask = torch.tensor([[1, 1, 1, 1, 0, 0]])
    masked = trainer._compute_torch_loss("qa", {"qa_logits": qa_logits}, labels, mask)
    unmasked = trainer._compute_torch_loss("qa", {"qa_logits": qa_logits}, labels)
    assert masked.item() < unmasked.item()
    assert abs(masked.item() - 0.15 * np.log(4)) < 1e-4

    none_masked = {"mlm_labels": torch.full((1, 4), -100)}
    loss = trainer._compute_torch_loss("mlm", {"mlm_logits": torch.zeros(1, 4, 10)}, none_masked)
    assert torch.isfinite(loss) and loss.item() == 0.0
