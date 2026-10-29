"""Unit tests for LanguageArtifactManager, split isolation, and bundle integrity."""

from pathlib import Path

import pytest

from laris.core.errors import (
    DataIntegrityError,
    DataLeakageError,
    ModuleContractViolationError,
)
from laris.language.benchmarks.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.schemas import (
    EncoderCheckpointMetadata,
    LanguageTrainingRunManifest,
    VocabularyContract,
)
from laris.language.tokenization.tokenizer import StemFertilityReport
from laris.language.training.artifacts import (
    BUNDLE_MANIFEST_FILENAME,
    LanguageArtifactBundle,
    LanguageArtifactManager,
)
from laris.retrieval.baseline_comparison import RetrievalComparisonReport


@pytest.fixture
def sample_bundle() -> LanguageArtifactBundle:
    """Fixture providing a complete LanguageArtifactBundle."""
    tokens = get_stem_vocabulary_tokens()
    vocab = VocabularyContract.create(sorted(set(tokens)))

    chk_meta = EncoderCheckpointMetadata(
        checkpoint_id="chk-bundle-01",
        model_id="laris-compact-stem-v1",
        embedding_dim=384,
        vocab_sha256=vocab.vocab_sha256,
        weights_sha256="c" * 64,
        parameter_count=15360000,
        created_at="2026-10-15T12:00:00Z",
        lineage={"seed": 42},
    )

    run_manifest = LanguageTrainingRunManifest(
        run_id="run-bundle-01",
        model_id="laris-compact-stem-v1",
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"peak_vram_gb": 0.85},
        hyperparameters={"vocab_size": vocab.vocab_size},
        dataset_provenance={"test_leakage_overlap_count": 0},
        training_metrics={"loss": 0.05},
        evaluation_metrics={"mrr": 0.85},
        checkpoint_metadata=chk_meta,
    )

    weights = [[0.01 * (i % 10)] * 384 for i in range(10)]

    fert_report = StemFertilityReport(
        benchmark_version="1.0.0",
        vocab_size=vocab.vocab_size,
        vocab_sha256=vocab.vocab_sha256,
        num_samples=10,
        total_words=100,
        total_tokens=125,
        average_fertility=1.25,
        max_fertility=1.35,
        min_fertility=1.10,
        domain_fertility={"physics": 1.25},
        report_sha256="d" * 64,
    )

    ret_report = RetrievalComparisonReport(
        benchmark_version="1.0.0",
        num_queries=10,
        num_documents=10,
        dense_mrr=0.85,
        dense_hits_at_1=0.80,
        dense_hits_at_5=0.90,
        bm25_mrr=0.75,
        bm25_hits_at_1=0.70,
        bm25_hits_at_5=0.80,
        avg_dense_latency_ms=12.5,
        peak_memory_mb=65.0,
        report_sha256="e" * 64,
    )

    return LanguageArtifactBundle(
        vocab_contract=vocab,
        checkpoint_metadata=chk_meta,
        weights=weights,
        run_manifest=run_manifest,
        fertility_report=fert_report,
        retrieval_report=ret_report,
    )


def test_split_isolation_success() -> None:
    """Verifies that completely disjoint splits pass isolation validation."""
    train_ids = ["doc-01", "doc-02", "doc-03"]
    val_ids = ["doc-04", "doc-05"]
    test_ids = ["doc-06", "doc-07"]

    # Should execute cleanly without error
    LanguageArtifactManager.verify_split_isolation(train_ids, val_ids, test_ids)


def test_split_isolation_leakage_detection() -> None:
    """Verifies that overlapping splits raise DataLeakageError."""
    # Train-val overlap
    with pytest.raises(DataLeakageError, match="TRAIN and VAL"):
        LanguageArtifactManager.verify_split_isolation(
            train_doc_ids=["doc-01", "doc-02"],
            val_doc_ids=["doc-02", "doc-03"],
            test_doc_ids=["doc-04"],
        )

    # Train-test overlap
    with pytest.raises(DataLeakageError, match="TRAIN and TEST"):
        LanguageArtifactManager.verify_split_isolation(
            train_doc_ids=["doc-01", "doc-02"],
            val_doc_ids=["doc-03"],
            test_doc_ids=["doc-02", "doc-04"],
        )

    # Val-test overlap
    with pytest.raises(DataLeakageError, match="VAL and TEST"):
        LanguageArtifactManager.verify_split_isolation(
            train_doc_ids=["doc-01"],
            val_doc_ids=["doc-02", "doc-03"],
            test_doc_ids=["doc-03", "doc-04"],
        )


def test_bundle_save_and_load_roundtrip(
    sample_bundle: LanguageArtifactBundle,
    tmp_path: Path,
) -> None:
    """Verifies saving and loading an artifact bundle with cryptographic hash verification."""
    manager = LanguageArtifactManager()
    bundle_dir = tmp_path / "model_bundle"

    # Save
    saved_dir = manager.save_bundle(sample_bundle, bundle_dir)
    assert saved_dir.exists()
    assert (saved_dir / BUNDLE_MANIFEST_FILENAME).exists()

    # Load with verification
    loaded_bundle = manager.load_bundle(saved_dir, verify_integrity=True)
    assert loaded_bundle.vocab_contract == sample_bundle.vocab_contract
    assert loaded_bundle.checkpoint_metadata == sample_bundle.checkpoint_metadata
    assert loaded_bundle.weights == sample_bundle.weights
    assert loaded_bundle.run_manifest.run_id == sample_bundle.run_manifest.run_id


def test_bundle_tamper_detection(
    sample_bundle: LanguageArtifactBundle,
    tmp_path: Path,
) -> None:
    """Verifies that tampering with a saved file triggers DataIntegrityError."""
    manager = LanguageArtifactManager()
    bundle_dir = tmp_path / "model_bundle_tamper"
    manager.save_bundle(sample_bundle, bundle_dir)

    # Corrupt weights.json
    weights_path = bundle_dir / "weights.json"
    with open(weights_path, "w", encoding="utf-8") as f:
        f.write("[[9.9999]]")

    with pytest.raises(DataIntegrityError, match="Integrity check failed"):
        manager.load_bundle(bundle_dir, verify_integrity=True)


def test_bundle_missing_file_detection(
    sample_bundle: LanguageArtifactBundle,
    tmp_path: Path,
) -> None:
    """Verifies that a missing bundle file triggers DataIntegrityError."""
    manager = LanguageArtifactManager()
    bundle_dir = tmp_path / "model_bundle_missing"
    manager.save_bundle(sample_bundle, bundle_dir)

    # Remove vocabulary.json
    vocab_path = bundle_dir / "vocabulary.json"
    vocab_path.unlink()

    with pytest.raises(DataIntegrityError, match="missing file"):
        manager.load_bundle(bundle_dir, verify_integrity=True)


def test_bundle_missing_manifest(tmp_path: Path) -> None:
    """Verifies that missing bundle_manifest.json raises ModuleContractViolationError."""
    manager = LanguageArtifactManager()
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    with pytest.raises(ModuleContractViolationError, match="Missing bundle manifest"):
        manager.load_bundle(empty_dir)
