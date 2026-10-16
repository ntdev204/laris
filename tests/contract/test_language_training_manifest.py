"""Contract tests for LanguageTrainingRunManifest and hardware/leakage safety gates."""

import pytest

from laris.core.errors import (
    DataLeakageError,
    HardwareBudgetExceededError,
    ModuleContractViolationError,
)
from laris.layers.layer1_language.schemas import (
    EncoderCheckpointMetadata,
    LanguageTrainingRunManifest,
)


@pytest.fixture
def sample_checkpoint_metadata() -> EncoderCheckpointMetadata:
    """Fixture providing valid EncoderCheckpointMetadata."""
    return EncoderCheckpointMetadata(
        checkpoint_id="chk-stem-01",
        model_id="laris-compact-stem-v1",
        embedding_dim=384,
        vocab_sha256="a" * 64,
        weights_sha256="b" * 64,
        parameter_count=15360000,
        created_at="2026-10-15T12:00:00Z",
        lineage={"seed": 42},
    )


def test_language_training_run_manifest_roundtrip(
    sample_checkpoint_metadata: EncoderCheckpointMetadata,
) -> None:
    """Verifies instantiation, deterministic SHA-256 computation, and JSON roundtrip."""
    manifest = LanguageTrainingRunManifest(
        run_id="run-stem-01",
        model_id="laris-compact-stem-v1",
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"gpu": "RTX 5070 Ti", "peak_vram_gb": 0.85},
        hyperparameters={"vocab_size": 32000, "embedding_dim": 384},
        dataset_provenance={"manifest_id": "man-01", "num_train_docs": 100},
        training_metrics={"final_loss": 0.042},
        evaluation_metrics={"stem_fertility": 1.25, "retrieval_mrr": 0.88},
        checkpoint_metadata=sample_checkpoint_metadata,
    )

    digest = manifest.compute_sha256()
    assert len(digest) == 64

    data_dict = manifest.to_dict()
    assert data_dict["manifest_sha256"] == digest

    json_str = manifest.to_json()
    restored = LanguageTrainingRunManifest.from_json(json_str)

    assert restored.run_id == manifest.run_id
    assert restored.seed == manifest.seed
    assert restored.checkpoint_metadata == sample_checkpoint_metadata
    assert restored.manifest_sha256 == digest


def test_language_training_run_manifest_hardware_budget_guardrail(
    sample_checkpoint_metadata: EncoderCheckpointMetadata,
) -> None:
    """Verifies that exceeding the 14.5 GB safety envelope triggers HardwareBudgetExceededError."""
    # Under 14.5 GB passes
    LanguageTrainingRunManifest(
        run_id="run-safe",
        model_id="laris-compact-stem-v1",
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"peak_vram_gb": 14.0},
        hyperparameters={},
        dataset_provenance={},
        training_metrics={},
        evaluation_metrics={},
        checkpoint_metadata=sample_checkpoint_metadata,
    )

    # Exceeding 14.5 GB raises HardwareBudgetExceededError
    with pytest.raises(HardwareBudgetExceededError, match="exceeds safe threshold"):
        LanguageTrainingRunManifest(
            run_id="run-unsafe",
            model_id="laris-compact-stem-v1",
            seed=42,
            created_at="2026-10-15T12:00:00Z",
            hardware_info={"peak_vram_gb": 15.2},
            hyperparameters={},
            dataset_provenance={},
            training_metrics={},
            evaluation_metrics={},
            checkpoint_metadata=sample_checkpoint_metadata,
        )


def test_language_training_run_manifest_leakage_guardrail(
    sample_checkpoint_metadata: EncoderCheckpointMetadata,
) -> None:
    """Verifies that detected overlap with test split raises DataLeakageError."""
    with pytest.raises(DataLeakageError, match="overlapping documents"):
        LanguageTrainingRunManifest(
            run_id="run-leaked",
            model_id="laris-compact-stem-v1",
            seed=42,
            created_at="2026-10-15T12:00:00Z",
            hardware_info={"peak_vram_gb": 1.0},
            hyperparameters={},
            dataset_provenance={"test_leakage_overlap_count": 3},
            training_metrics={},
            evaluation_metrics={},
            checkpoint_metadata=sample_checkpoint_metadata,
        )


def test_language_training_run_manifest_invariants(
    sample_checkpoint_metadata: EncoderCheckpointMetadata,
) -> None:
    """Verifies field validation on empty identifiers."""
    with pytest.raises(ModuleContractViolationError, match="run_id"):
        LanguageTrainingRunManifest(
            run_id="",
            model_id="model",
            seed=42,
            created_at="2026-10-15T00:00:00Z",
            hardware_info={},
            hyperparameters={},
            dataset_provenance={},
            training_metrics={},
            evaluation_metrics={},
            checkpoint_metadata=sample_checkpoint_metadata,
        )

    with pytest.raises(ModuleContractViolationError, match="model_id"):
        LanguageTrainingRunManifest(
            run_id="run-01",
            model_id="",
            seed=42,
            created_at="2026-10-15T00:00:00Z",
            hardware_info={},
            hyperparameters={},
            dataset_provenance={},
            training_metrics={},
            evaluation_metrics={},
            checkpoint_metadata=sample_checkpoint_metadata,
        )

    with pytest.raises(ValueError, match="created_at"):
        LanguageTrainingRunManifest(
            run_id="run-01",
            model_id="model",
            seed=42,
            created_at="",
            hardware_info={},
            hyperparameters={},
            dataset_provenance={},
            training_metrics={},
            evaluation_metrics={},
            checkpoint_metadata=sample_checkpoint_metadata,
        )
