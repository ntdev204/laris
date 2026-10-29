"""Memory profile bookkeeping and the paraphrase loss under CUDA autocast."""

import pytest

from laris.language.training.memory_profile import (
    TaskMeasurement,
    TrainingMemoryProfile,
    optimizer_state_gb,
)


def _profile(**overrides) -> TrainingMemoryProfile:
    base = dict(
        device="cuda",
        gpu_name="test",
        total_vram_gb=16.0,
        param_count=1,
        limit_gb=14.5,
        tasks=[TaskMeasurement("mlm", 7.0, True)],
        measured_peak_gb=7.0,
        optimizer_state_gb=1.0,
    )
    base.update(overrides)
    return TrainingMemoryProfile(**base)


def test_optimizer_state_sizes() -> None:
    assert optimizer_state_gb(1024**3, use_8bit_adam=True) == pytest.approx(2.0)
    assert optimizer_state_gb(1024**3, use_8bit_adam=False) == pytest.approx(8.0)


def test_forward_only_fits_but_is_never_certified() -> None:
    profile = _profile(backward_measured=False)
    assert profile.fits and not profile.certified


def test_certified_requires_backward_and_projected_peak_within_limit() -> None:
    assert _profile(backward_measured=True).certified
    assert not _profile(backward_measured=True, measured_peak_gb=14.0).certified
    assert not _profile(backward_measured=True, error="CUDA out of memory").certified
    assert not _profile(
        backward_measured=True, tasks=[TaskMeasurement("mlm", 7.0, False)]
    ).certified


torch = pytest.importorskip("torch")


@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs CUDA autocast")
def test_paraphrase_loss_runs_under_cuda_bf16_autocast() -> None:
    from laris.language.training.trainer import LanguageEncoderTrainer

    trainer = LanguageEncoderTrainer(
        model=torch.nn.Linear(2, 2), config=None, dataloader=None,
        use_8bit_adam=False, device="cuda", precision="bf16",
    )
    probs = torch.rand(4, 1, device="cuda", requires_grad=True)
    labels = {"para_labels": torch.tensor([0.0, 1.0, 1.0, 0.0])}
    with trainer._autocast():
        loss = trainer._compute_torch_loss("paraphrase", {"paraphrase_prob": probs}, labels)
    assert torch.isfinite(loss)
