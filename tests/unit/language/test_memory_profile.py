"""Memory profile bookkeeping and the paraphrase loss under CUDA autocast."""

import pytest

from laris.language.training.memory_profile import TaskMeasurement, TrainingMemoryProfile


def _profile(**overrides) -> TrainingMemoryProfile:
    base = dict(
        gpu_name="test",
        total_vram_gb=16.0,
        limit_gb=14.5,
        steady_state=True,
        tasks=[TaskMeasurement("mlm", 7.0, True)],
        peak_gb=7.0,
    )
    base.update(overrides)
    return TrainingMemoryProfile(**base)


def test_forward_only_fits_but_is_never_certified() -> None:
    profile = _profile(steady_state=False)
    assert profile.fits and not profile.certified


def test_certified_requires_steady_state_within_limit_and_finite_losses() -> None:
    assert _profile().certified
    assert not _profile(peak_gb=14.6).certified
    assert not _profile(error="CUDA out of memory").certified
    assert not _profile(tasks=[TaskMeasurement("mlm", 7.0, False)]).certified
    assert not _profile(tasks=[]).certified


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
