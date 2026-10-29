"""Initial state of the PyTorch encoder (issue #293)."""

import math

import pytest

torch = pytest.importorskip("torch")

from laris.language.encoder.transformer import (  # noqa: E402
    LanguageEncoderConfig,
    PyTorchTransformerEncoder,
)


def _config(**overrides) -> LanguageEncoderConfig:
    base = dict(
        vocab_size=2000, max_sequence_length=32, d_model=384, num_layers=4, num_heads=6, d_ff=1536
    )
    base.update(overrides)
    return LanguageEncoderConfig(**base)


def test_fresh_model_starts_near_uniform_prediction_not_huge_logits() -> None:
    """A tied N(0,1) embedding gave logit std ~28 and an initial MLM loss ~540."""
    model = PyTorchTransformerEncoder(_config()).eval()
    ids = torch.randint(10, 2000, (4, 32))
    with torch.no_grad():
        logits = model(ids)["mlm_logits"].float()
    assert float(model.token_embeddings.weight.detach().std()) == pytest.approx(0.02, abs=0.005)
    assert float(logits.std()) < 1.0
    # targets independent of the input, as for a masked position
    targets = torch.randint(10, 2000, (4, 32))
    loss = torch.nn.functional.cross_entropy(logits.view(-1, 2000), targets.view(-1))
    assert abs(float(loss) - math.log(2000)) < 0.5


def test_residual_projections_are_scaled_down_and_biases_are_zero() -> None:
    model = PyTorchTransformerEncoder(_config(num_layers=8))
    layer = model.layers[0]
    plain, residual = float(layer.q_proj.weight.std()), float(layer.o_proj.weight.std())
    assert residual == pytest.approx(plain / math.sqrt(16), rel=0.35)
    assert float(model.para_head.bias.abs().max()) == 0.0
    assert float(model.mlm_bias.abs().max()) == 0.0


def test_the_model_seeds_its_own_initialisation() -> None:
    cfg = _config(vocab_size=500, num_layers=2)
    torch.manual_seed(1)
    first = PyTorchTransformerEncoder(cfg)
    torch.manual_seed(2)  # a different outer seed must not change the initial weights
    second = PyTorchTransformerEncoder(cfg)
    for (name, a), (_, b) in zip(first.named_parameters(), second.named_parameters()):
        assert torch.equal(a, b), name
