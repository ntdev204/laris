"""Unit tests for checkpoint lineage, provenance tracking, and tamper detection."""

import json
from pathlib import Path

import pytest

from laris.core.errors import DataIntegrityError
from laris.layers.layer1_language.artifacts import (
    LanguageArtifactBundle,
    LanguageArtifactManager,
)
from laris.layers.layer1_language.encoder import CompactSentenceEncoder
from laris.layers.layer1_language.schemas import (
    LanguageTrainingRunManifest,
    VocabularyContract,
)
from laris.layers.layer1_language.stem_benchmark import get_stem_vocabulary_tokens
from laris.layers.layer1_language.tokenizer import ScientificTokenizer


@pytest.fixture
def stem_vocab() -> VocabularyContract:
    """Fixture providing a deterministic STEM vocabulary contract."""
    tokens = get_stem_vocabulary_tokens()
    return VocabularyContract.create(sorted(set(tokens)))


def test_checkpoint_lineage_traceability(stem_vocab: VocabularyContract) -> None:
    """Verifies that checkpoint metadata and training run manifest record complete lineage."""
    tokenizer = ScientificTokenizer(vocab=stem_vocab)
    encoder = CompactSentenceEncoder(tokenizer=tokenizer, embedding_dim=384, seed=42)

    chk_meta = encoder.get_checkpoint_metadata()
    assert chk_meta.vocab_sha256 == stem_vocab.vocab_sha256
    assert len(chk_meta.weights_sha256) == 64
    assert chk_meta.lineage["seed"] == 42
    assert chk_meta.lineage["vocab_size"] == stem_vocab.vocab_size

    manifest = LanguageTrainingRunManifest(
        run_id="run-lineage-01",
        model_id=encoder.model_id,
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"gpu": "RTX 5070 Ti", "peak_vram_gb": 0.85},
        hyperparameters={"embedding_dim": 384, "pooling": "mean"},
        dataset_provenance={
            "source_manifest_sha256": "f" * 64,
            "train_split_sha256": "e" * 64,
            "test_leakage_overlap_count": 0,
        },
        training_metrics={"loss": 0.012},
        evaluation_metrics={"mrr": 0.88},
        checkpoint_metadata=chk_meta,
    )

    manifest_dict = manifest.to_dict()
    assert manifest_dict["dataset_provenance"]["source_manifest_sha256"] == "f" * 64
    assert manifest_dict["checkpoint_metadata"]["weights_sha256"] == chk_meta.weights_sha256
    assert manifest_dict["manifest_sha256"] == manifest.compute_sha256()


def test_checkpoint_tamper_detection_in_bundle(
    stem_vocab: VocabularyContract,
    tmp_path: Path,
) -> None:
    """Verifies that modifying checkpoint metadata or weights triggers DataIntegrityError."""
    tokenizer = ScientificTokenizer(vocab=stem_vocab)
    encoder = CompactSentenceEncoder(tokenizer=tokenizer, embedding_dim=384, seed=42)
    chk_meta = encoder.get_checkpoint_metadata()

    manifest = LanguageTrainingRunManifest(
        run_id="run-tamper-01",
        model_id=encoder.model_id,
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"peak_vram_gb": 0.85},
        hyperparameters={"embedding_dim": 384},
        dataset_provenance={"test_leakage_overlap_count": 0},
        training_metrics={},
        evaluation_metrics={},
        checkpoint_metadata=chk_meta,
    )

    bundle = LanguageArtifactBundle(
        vocab_contract=stem_vocab,
        checkpoint_metadata=chk_meta,
        weights=encoder._embedding_table,
        run_manifest=manifest,
    )

    manager = LanguageArtifactManager()
    bundle_dir = tmp_path / "saved_bundle"
    manager.save_bundle(bundle, bundle_dir)

    # 1. Tampering with checkpoint.json
    chk_path = bundle_dir / "checkpoint.json"
    with open(chk_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["parameter_count"] = 99999999
    with open(chk_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with pytest.raises(DataIntegrityError, match="Integrity check failed for 'checkpoint.json'"):
        manager.load_bundle(bundle_dir, verify_integrity=True)
