"""Contract tests for sentence encoder schemas, dimensions, and checkpoint metadata."""

from pathlib import Path

import pytest

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
)
from laris.layers.layer1_language.schemas import (
    ALLOWED_EMBEDDING_DIMENSIONS,
    EmbeddingBatchOutput,
    EncoderCheckpointMetadata,
    SentenceEmbeddingOutput,
    SentenceEncoderContract,
)


def test_sentence_encoder_contract_allowed_dimensions() -> None:
    """Verifies that allowed embedding dimensions (384, 768) are accepted."""
    for dim in ALLOWED_EMBEDDING_DIMENSIONS:
        contract = SentenceEncoderContract(
            model_id="laris-encoder-test",
            embedding_dim=dim,
        )
        assert contract.embedding_dim == dim
        assert contract.max_sequence_length == 512
        assert contract.pooling_strategy == "mean"
        assert contract.normalize_embeddings is True


def test_sentence_encoder_contract_invalid_dimension() -> None:
    """Verifies that unapproved dimensions raise EmbeddingDimensionMismatchError."""
    for invalid_dim in [64, 128, 256, 512, 1024]:
        with pytest.raises(EmbeddingDimensionMismatchError):
            SentenceEncoderContract(
                model_id="laris-encoder-test",
                embedding_dim=invalid_dim,
            )


def test_sentence_encoder_contract_invalid_fields() -> None:
    """Verifies validation on empty model_id, invalid pooling, and memory budget."""
    with pytest.raises(ModuleContractViolationError, match="model_id"):
        SentenceEncoderContract(model_id="", embedding_dim=384)

    with pytest.raises(ValueError, match="max_sequence_length"):
        SentenceEncoderContract(model_id="test", embedding_dim=384, max_sequence_length=0)

    with pytest.raises(ModuleContractViolationError, match="pooling_strategy"):
        SentenceEncoderContract(model_id="test", embedding_dim=384, pooling_strategy="invalid")

    with pytest.raises(ModuleContractViolationError, match="memory budget"):
        SentenceEncoderContract(model_id="test", embedding_dim=384, parameters_budget_mb=2048.0)


def test_encoder_checkpoint_metadata_roundtrip(tmp_path: Path) -> None:
    """Verifies that EncoderCheckpointMetadata serializes and deserializes cleanly."""
    vocab_hash = "a" * 64
    weights_hash = "b" * 64

    meta = EncoderCheckpointMetadata(
        checkpoint_id="chk-stem-001",
        model_id="laris-stem-encoder-v1",
        embedding_dim=384,
        vocab_sha256=vocab_hash,
        weights_sha256=weights_hash,
        parameter_count=15360000,
        created_at="2026-10-15T12:00:00Z",
        lineage={"training_split": "train", "epochs": 10},
    )

    meta_dict = meta.to_dict()
    restored_from_dict = EncoderCheckpointMetadata.from_dict(meta_dict)
    assert restored_from_dict == meta

    json_path = tmp_path / "metadata.json"
    meta.save_to_file(json_path)
    restored_from_file = EncoderCheckpointMetadata.load_from_file(json_path)
    assert restored_from_file == meta


def test_encoder_checkpoint_metadata_invariants() -> None:
    """Verifies validation on checkpoint hashes, dimensions, and parameter count."""
    valid_hash = "a" * 64

    with pytest.raises(ModuleContractViolationError, match="checkpoint_id"):
        EncoderCheckpointMetadata(
            checkpoint_id="",
            model_id="test",
            embedding_dim=384,
            vocab_sha256=valid_hash,
            weights_sha256=valid_hash,
            parameter_count=1000,
            created_at="2026-10-15T00:00:00Z",
        )

    with pytest.raises(EmbeddingDimensionMismatchError):
        EncoderCheckpointMetadata(
            checkpoint_id="chk-01",
            model_id="test",
            embedding_dim=256,
            vocab_sha256=valid_hash,
            weights_sha256=valid_hash,
            parameter_count=1000,
            created_at="2026-10-15T00:00:00Z",
        )

    with pytest.raises(ValueError, match="vocab_sha256"):
        EncoderCheckpointMetadata(
            checkpoint_id="chk-01",
            model_id="test",
            embedding_dim=384,
            vocab_sha256="short",
            weights_sha256=valid_hash,
            parameter_count=1000,
            created_at="2026-10-15T00:00:00Z",
        )

    with pytest.raises(ValueError, match="parameter_count"):
        EncoderCheckpointMetadata(
            checkpoint_id="chk-01",
            model_id="test",
            embedding_dim=384,
            vocab_sha256=valid_hash,
            weights_sha256=valid_hash,
            parameter_count=0,
            created_at="2026-10-15T00:00:00Z",
        )


def test_sentence_embedding_output_invariants() -> None:
    """Verifies postconditions on SentenceEmbeddingOutput dimensions and finite values."""
    valid_vec = [0.1] * 384
    emb = SentenceEmbeddingOutput(
        text="Quantum state",
        embedding=valid_vec,
        token_count=3,
        embedding_dim=384,
    )
    assert emb.embedding_dim == 384
    assert len(emb.embedding) == 384

    with pytest.raises(ModuleContractViolationError, match="text must not be empty"):
        SentenceEmbeddingOutput(
            text="   ",
            embedding=valid_vec,
            token_count=3,
            embedding_dim=384,
        )

    with pytest.raises(EmbeddingDimensionMismatchError, match="must be in"):
        SentenceEmbeddingOutput(
            text="Quantum state",
            embedding=[0.1] * 256,
            token_count=3,
            embedding_dim=256,
        )

    with pytest.raises(EmbeddingDimensionMismatchError, match="does not match declared"):
        SentenceEmbeddingOutput(
            text="Quantum state",
            embedding=[0.1] * 383,
            token_count=3,
            embedding_dim=384,
        )

    # Non-finite values test
    nan_vec = list(valid_vec)
    nan_vec[10] = float("nan")
    with pytest.raises(ValueError, match="Non-finite value"):
        SentenceEmbeddingOutput(
            text="Quantum state",
            embedding=nan_vec,
            token_count=3,
            embedding_dim=384,
        )


def test_embedding_batch_output_invariants() -> None:
    """Verifies that EmbeddingBatchOutput enforces size and dimension uniformity."""
    valid_vec = [0.1] * 384
    item1 = SentenceEmbeddingOutput("Text 1", valid_vec, 2, 384)
    item2 = SentenceEmbeddingOutput("Text 2", valid_vec, 2, 384)

    batch = EmbeddingBatchOutput(
        embeddings=[item1, item2],
        model_id="test-model",
        embedding_dim=384,
        batch_size=2,
    )
    assert batch.batch_size == 2

    with pytest.raises(ValueError, match="does not match batch_size"):
        EmbeddingBatchOutput(
            embeddings=[item1],
            model_id="test-model",
            embedding_dim=384,
            batch_size=2,
        )
