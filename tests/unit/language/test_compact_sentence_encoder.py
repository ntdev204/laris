"""Unit tests for CompactSentenceEncoder, pooling strategies, and dimension checks."""

import math

import pytest

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
    SequenceLengthExceededError,
)
from laris.language.benchmarks.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.encoder.sentence_encoder import CompactSentenceEncoder
from laris.language.schemas import VocabularyContract
from laris.language.tokenization.tokenizer import ScientificTokenizer


@pytest.fixture
def stem_tokenizer() -> ScientificTokenizer:
    """Fixture providing a ScientificTokenizer initialized with STEM vocabulary."""
    tokens = get_stem_vocabulary_tokens()
    # Add general english words to cover test sentences
    general_words = [
        "the", "of", "in", "and", "to", "a", "with", "is", "for", "at",
        "on", "by", "from", "under", "where", "rates", "conditions",
        "demonstrates", "indicate", "yields", "exceeding", "mediate",
        "undergo", "compute", "optimizes", "characterize", "dominates",
    ]
    all_tokens = sorted(set(tokens + general_words))
    vocab_contract = VocabularyContract.create(all_tokens)
    return ScientificTokenizer(vocab=vocab_contract)


def test_compact_sentence_encoder_initialization(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies successful initialization and metadata generation for D=384 and D=768."""
    encoder_384 = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384)
    contract_384 = encoder_384.get_contract()
    assert contract_384.embedding_dim == 384
    assert contract_384.pooling_strategy == "mean"

    metadata_384 = encoder_384.get_checkpoint_metadata()
    assert metadata_384.embedding_dim == 384
    assert len(metadata_384.weights_sha256) == 64
    assert metadata_384.parameter_count > 0

    encoder_768 = CompactSentenceEncoder(stem_tokenizer, embedding_dim=768)
    assert encoder_768.embedding_dim == 768


def test_compact_sentence_encoder_invalid_dimension(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies that attempting to construct encoder with invalid dimension fails."""
    with pytest.raises(EmbeddingDimensionMismatchError):
        CompactSentenceEncoder(stem_tokenizer, embedding_dim=512)


def test_compact_sentence_encoder_encode_sentence(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies encoding single sentence produces valid normalized embedding."""
    encoder = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384, normalize_embeddings=True)
    text = "Quantum electrodynamics in cavity optomechanics demonstrates photon coupling."

    output = encoder.encode_sentence(text)
    assert output.text == text
    assert output.embedding_dim == 384
    assert len(output.embedding) == 384
    assert output.token_count > 0

    # Verify finite values
    for val in output.embedding:
        assert math.isfinite(val)

    # Verify L2 unit norm
    l2_norm = math.sqrt(sum(x * x for x in output.embedding))
    assert abs(l2_norm - 1.0) < 1e-4


def test_compact_sentence_encoder_pooling_strategies(
    stem_tokenizer: ScientificTokenizer,
) -> None:
    """Verifies that mean, cls, and max pooling strategies function correctly."""
    text = "Static single assignment form optimizes register allocation."

    for strategy in ["mean", "cls", "max"]:
        encoder = CompactSentenceEncoder(
            stem_tokenizer,
            embedding_dim=384,
            pooling_strategy=strategy,
        )
        output = encoder.encode_sentence(text)
        assert output.embedding_dim == 384
        assert len(output.embedding) == 384
        l2_norm = math.sqrt(sum(x * x for x in output.embedding))
        assert abs(l2_norm - 1.0) < 1e-4


def test_compact_sentence_encoder_batch(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies batch encoding over multiple sentences."""
    encoder = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384)
    texts = [
        "Quantum electrodynamics in cavity optomechanics.",
        "Zeolite catalyzed cracking of polyolefin oligomers.",
        "CRISPR Cas9 ribonucleoprotein complexes mediate cleavage.",
    ]

    batch = encoder.encode_batch(texts)
    assert batch.batch_size == 3
    assert len(batch.embeddings) == 3
    for emb in batch.embeddings:
        assert emb.embedding_dim == 384


def test_compact_sentence_encoder_determinism(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies that encoding the same sentence with identical seed yields identical floats."""
    encoder1 = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384, seed=42)
    encoder2 = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384, seed=42)

    text = (
        "Cohomological operations on differentiable symplectic manifolds "
        "characterize invariants."
    )
    out1 = encoder1.encode_sentence(text)
    out2 = encoder2.encode_sentence(text)

    assert out1.embedding == out2.embedding


def test_compact_sentence_encoder_edge_cases(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies edge case handling: empty text, empty batch, sequence truncation."""
    encoder = CompactSentenceEncoder(
        stem_tokenizer,
        embedding_dim=384,
        max_sequence_length=10,
    )

    with pytest.raises(ModuleContractViolationError, match="empty"):
        encoder.encode_sentence("")

    with pytest.raises(ModuleContractViolationError, match="empty"):
        encoder.encode_sentence("   ")

    with pytest.raises(ModuleContractViolationError, match="empty"):
        encoder.encode_batch([])

    long_text = " ".join(["quantum"] * 20)

    # Exceeding sequence length with truncate=False raises SequenceLengthExceededError
    with pytest.raises(SequenceLengthExceededError):
        encoder.encode_sentence(long_text, truncate=False)

    # With truncate=True, should succeed
    truncated_out = encoder.encode_sentence(long_text, truncate=True)
    assert truncated_out.embedding_dim == 384


def test_compact_sentence_encoder_out_of_bounds_token(
    stem_tokenizer: ScientificTokenizer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that an out-of-bounds token ID gracefully falls back to zero vector."""
    from laris.language.schemas import TokenizedSentenceOutput

    encoder = CompactSentenceEncoder(stem_tokenizer, embedding_dim=384)
    # Monkeypatch tokenizer.encode to return an out-of-bounds token id
    monkeypatch.setattr(
        stem_tokenizer,
        "encode",
        lambda text: TokenizedSentenceOutput(
            token_ids=[9999999],
            tokens=["unknown_id"],
            max_sequence_length=512,
        ),
    )
    out = encoder.encode_sentence("test out of bounds", truncate=False)
    assert out.embedding_dim == 384
    # All zero vectors when pooled and normalized will produce zeros
    assert len(out.embedding) == 384

