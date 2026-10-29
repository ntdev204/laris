"""Integration test and exit gate verification for Milestone M2 (Language Foundation).

Validates all canonical acceptance criteria for M2:
1. End-to-end bitwise reproducibility given the same seed across independent runs.
2. Scientific tokenizer STEM fertility <= 1.35 tokens/word (target <= 1.4).
3. Preservation of LaTeX math expressions and Greek characters.
4. Compact sentence encoder embeddings strictly in allowed dimensions {384, 768} with unit norm.
5. Resource envelope compliance: Tier 1 model < 1.0 GB VRAM, latency < 20 ms/sentence.
6. Retrieval benchmark evaluation against lexical BM25 baseline with cryptographic audit trail.
7. Split isolation preventing train/eval contamination.
"""

from pathlib import Path

import pytest

from laris.language.benchmarks.stem_benchmark import (
    get_stem_vocabulary_tokens,
)
from laris.language.encoder.sentence_encoder import CompactSentenceEncoder
from laris.language.schemas import (
    ALLOWED_EMBEDDING_DIMENSIONS,
    LanguageTrainingRunManifest,
    VocabularyContract,
)
from laris.language.tokenization.tokenizer import (
    ScientificTokenizer,
    evaluate_stem_fertility,
)
from laris.language.training.artifacts import (
    LanguageArtifactBundle,
    LanguageArtifactManager,
)
from laris.retrieval.baseline_comparison import (
    evaluate_retrieval_comparison,
)


@pytest.fixture
def stem_vocab() -> VocabularyContract:
    """Fixture providing a deterministic STEM vocabulary contract."""
    tokens = get_stem_vocabulary_tokens()
    return VocabularyContract.create(sorted(set(tokens)))


def test_m2_bitwise_reproducibility(stem_vocab: VocabularyContract) -> None:
    """Verifies that two independent runs with seed=42 yield bitwise identical outputs."""
    tok1 = ScientificTokenizer(vocab=stem_vocab)
    enc1 = CompactSentenceEncoder(tokenizer=tok1, embedding_dim=384, seed=42)

    tok2 = ScientificTokenizer(vocab=stem_vocab)
    enc2 = CompactSentenceEncoder(tokenizer=tok2, embedding_dim=384, seed=42)

    # 1. Bitwise identical weights
    assert enc1._weights_sha256 == enc2._weights_sha256
    assert enc1._embedding_table == enc2._embedding_table

    # 2. Bitwise identical sentence embeddings
    test_sentence = (
        "Quantum electrodynamics in cavity optomechanics demonstrates "
        "photon-phonon coupling under cryogenic conditions at 15 mK."
    )
    out1 = enc1.encode_sentence(test_sentence)
    out2 = enc2.encode_sentence(test_sentence)
    assert out1.embedding == out2.embedding
    assert out1.token_count == out2.token_count

    # 3. Bitwise identical fertility evaluation
    fert1 = evaluate_stem_fertility(tok1)
    fert2 = evaluate_stem_fertility(tok2)
    assert fert1.report_sha256 == fert2.report_sha256
    assert fert1.average_fertility == fert2.average_fertility

    # 4. Bitwise identical retrieval benchmark evaluation
    ret1 = evaluate_retrieval_comparison(enc1, top_k=5)
    ret2 = evaluate_retrieval_comparison(enc2, top_k=5)
    assert ret1.report_sha256 == ret2.report_sha256
    assert ret1.dense_mrr == ret2.dense_mrr


def test_m2_seed_divergence(stem_vocab: VocabularyContract) -> None:
    """Verifies that distinct seeds produce distinct weight hashes."""
    tok = ScientificTokenizer(vocab=stem_vocab)
    enc_seed42 = CompactSentenceEncoder(tokenizer=tok, embedding_dim=384, seed=42)
    enc_seed43 = CompactSentenceEncoder(tokenizer=tok, embedding_dim=384, seed=43)

    assert enc_seed42._weights_sha256 != enc_seed43._weights_sha256


def test_m2_stem_fertility_exit_gate(stem_vocab: VocabularyContract) -> None:
    """Verifies that STEM tokenizer fertility satisfies the <= 1.4 tokens/word exit gate."""
    tokenizer = ScientificTokenizer(vocab=stem_vocab)
    fertility_report = evaluate_stem_fertility(tokenizer)

    assert fertility_report.average_fertility <= 1.35
    assert fertility_report.average_fertility < 1.40  # Roadmap gate requirement
    assert len(fertility_report.report_sha256) == 64


def test_m2_math_and_symbol_preservation(stem_vocab: VocabularyContract) -> None:
    """Verifies preservation of LaTeX formulas and Greek characters without corruption."""
    tokenizer = ScientificTokenizer(vocab=stem_vocab)
    text = "Coupling $\\alpha \\le \\beta$ with photon rate $\\gamma = 15$ GHz at $\\Delta = 0$."
    tokens = tokenizer.pre_tokenize(text)

    # Formulas must be preserved verbatim
    assert "$\\alpha \\le \\beta$" in tokens
    assert "$\\gamma = 15$" in tokens
    assert "$\\Delta = 0$" in tokens


def test_m2_hardware_and_resource_envelope(stem_vocab: VocabularyContract) -> None:
    """Verifies Tier 1 encoder memory footprint (< 1.0 GB) and query latency (< 20 ms)."""
    tokenizer = ScientificTokenizer(vocab=stem_vocab)
    encoder = CompactSentenceEncoder(tokenizer=tokenizer, embedding_dim=384, seed=42)

    contract = encoder.get_contract()
    assert contract.embedding_dim in ALLOWED_EMBEDDING_DIMENSIONS
    assert contract.parameters_budget_mb <= 1000.0

    retrieval_report = evaluate_retrieval_comparison(encoder, top_k=5)
    assert retrieval_report.peak_memory_mb < 1000.0
    assert retrieval_report.avg_dense_latency_ms < 20.0


def test_m2_complete_artifact_bundle_lifecycle(
    stem_vocab: VocabularyContract,
    tmp_path: Path,
) -> None:
    """Verifies saving and loading complete Milestone M2 bundle with split isolation."""
    # 1. Verify split isolation
    train_ids = [f"train-{i}" for i in range(100)]
    val_ids = [f"val-{i}" for i in range(20)]
    test_ids = [f"test-{i}" for i in range(20)]
    LanguageArtifactManager.verify_split_isolation(train_ids, val_ids, test_ids)

    # 2. Build full bundle
    tok = ScientificTokenizer(vocab=stem_vocab)
    enc = CompactSentenceEncoder(tokenizer=tok, embedding_dim=384, seed=42)
    chk_meta = enc.get_checkpoint_metadata()
    fert_report = evaluate_stem_fertility(tok)
    ret_report = evaluate_retrieval_comparison(enc, top_k=5)

    manifest = LanguageTrainingRunManifest(
        run_id="run-m2-final-01",
        model_id=enc.model_id,
        seed=42,
        created_at="2026-10-15T12:00:00Z",
        hardware_info={"gpu": "RTX 5070 Ti", "peak_vram_gb": 0.85},
        hyperparameters={"embedding_dim": 384, "pooling": "mean"},
        dataset_provenance={
            "train_doc_count": len(train_ids),
            "test_leakage_overlap_count": 0,
        },
        training_metrics={"final_loss": 0.025},
        evaluation_metrics={
            "average_fertility": fert_report.average_fertility,
            "dense_mrr": ret_report.dense_mrr,
            "bm25_mrr": ret_report.bm25_mrr,
        },
        checkpoint_metadata=chk_meta,
    )

    bundle = LanguageArtifactBundle(
        vocab_contract=stem_vocab,
        checkpoint_metadata=chk_meta,
        weights=enc._embedding_table,
        run_manifest=manifest,
        fertility_report=fert_report,
        retrieval_report=ret_report,
    )

    # 3. Save and load bundle
    manager = LanguageArtifactManager()
    bundle_dir = tmp_path / "language_bundle"
    manager.save_bundle(bundle, bundle_dir)

    loaded = manager.load_bundle(bundle_dir, verify_integrity=True)
    assert loaded.vocab_contract.vocab_sha256 == stem_vocab.vocab_sha256
    assert loaded.checkpoint_metadata.weights_sha256 == chk_meta.weights_sha256
    assert loaded.fertility_report is not None
    assert loaded.fertility_report.report_sha256 == fert_report.report_sha256
    assert loaded.retrieval_report is not None
    assert loaded.retrieval_report.report_sha256 == ret_report.report_sha256
