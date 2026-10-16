"""Unit tests for VocabularyContract serialization and manifest validation.

Tests:
- Serialization to dict, JSON, and file
- Deserialization roundtrip
- Validation against Layer 0 CorpusManifest
- Rejection of validation and test split documents in tokenizer training spec
"""

from pathlib import Path

import pytest

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.layers.layer0_corpus.pipeline import Layer0Pipeline
from laris.layers.layer0_corpus.schemas import DatasetSplit
from laris.layers.layer1_language.schemas import (
    TokenizerTrainingInputSpec,
    VocabularyContract,
)
from tests.fixtures.synthetic_corpus import get_standard_synthetic_corpus


def test_vocabulary_contract_serialization_roundtrip(tmp_path: Path) -> None:
    """Verifies that VocabularyContract survives file serialization without bit rot."""
    tokens = [f"word_{i}" for i in range(150)]
    vocab = VocabularyContract.create(
        tokens=tokens,
        metadata={"created_by": "unit-test", "model": "laris-bpe"},
    )

    vocab_file = tmp_path / "vocab.json"
    vocab.to_file(vocab_file)

    loaded_vocab = VocabularyContract.from_file(vocab_file)
    assert loaded_vocab.vocab_size == vocab.vocab_size
    assert loaded_vocab.vocab_sha256 == vocab.vocab_sha256
    assert loaded_vocab.token_to_id == vocab.token_to_id
    assert loaded_vocab.id_to_token == vocab.id_to_token
    assert loaded_vocab.metadata == vocab.metadata


def test_vocabulary_contract_from_file_missing_raises(tmp_path: Path) -> None:
    """Verifies that attempting to load a missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        VocabularyContract.from_file(tmp_path / "nonexistent_vocab.json")


def test_tokenizer_training_spec_manifest_validation_success() -> None:
    """Verifies valid TRAIN document IDs pass manifest validation."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)

    train_doc_ids = [
        item.corpus_id for item in output.partitioned_items[DatasetSplit.TRAIN]
    ]
    assert len(train_doc_ids) > 0

    spec = TokenizerTrainingInputSpec(
        source_split=DatasetSplit.TRAIN,
        source_manifest_id=output.corpus_manifest.manifest_id,
        document_ids=train_doc_ids,
    )
    # Must succeed without error
    spec.validate_against_manifest(output.corpus_manifest)


def test_tokenizer_training_spec_manifest_validation_catches_leakage() -> None:
    """Verifies that including a VAL or TEST document ID raises DataLeakageError."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)

    val_doc_ids = [
        item.corpus_id for item in output.partitioned_items[DatasetSplit.VAL]
    ]
    test_doc_ids = [
        item.corpus_id for item in output.partitioned_items[DatasetSplit.TEST]
    ]
    non_train_ids = val_doc_ids + test_doc_ids
    assert len(non_train_ids) > 0, "Expected at least one non-train document in partition"

    # Creating a spec with a document that is actually in VAL/TEST
    spec = TokenizerTrainingInputSpec(
        source_split=DatasetSplit.TRAIN,
        source_manifest_id=output.corpus_manifest.manifest_id,
        document_ids=[non_train_ids[0]],
    )

    with pytest.raises(DataLeakageError, match="causing leakage"):
        spec.validate_against_manifest(output.corpus_manifest)


def test_tokenizer_training_spec_manifest_validation_unknown_doc_id() -> None:
    """Verifies that a document ID not present in manifest raises ModuleContractViolationError."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)

    spec = TokenizerTrainingInputSpec(
        source_split=DatasetSplit.TRAIN,
        source_manifest_id=output.corpus_manifest.manifest_id,
        document_ids=["non-existent-doc-id"],
    )

    with pytest.raises(ModuleContractViolationError, match="not found in manifest"):
        spec.validate_against_manifest(output.corpus_manifest)
