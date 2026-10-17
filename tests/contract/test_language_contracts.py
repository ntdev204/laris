"""Boundary B (MOD-LANG-001) Language Foundation contract tests.

Verifies:
- NormalizedSentenceInput preconditions and postconditions
- TokenizedSentenceOutput dimensions, sequence limits, and errors
- SpecialTokenConfig canonical allocations
- VocabularyContract integrity, bijective mapping, and size constraints
- TokenizerTrainingInputSpec zero-leakage enforcement
"""

import pytest

from laris.core.errors import (
    DataLeakageError,
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
    SequenceLengthExceededError,
    VocabularyMismatchError,
)
from laris.corpus.schemas import DatasetSplit
from laris.language.schemas import (
    CANONICAL_SPECIAL_TOKENS,
    CLS_TOKEN,
    GREEK_TOKEN,
    MASK_TOKEN,
    MATH_TOKEN,
    PAD_TOKEN,
    SEP_TOKEN,
    UNIT_TOKEN,
    UNK_TOKEN,
    NormalizedSentenceInput,
    SpecialTokenConfig,
    TokenizedSentenceOutput,
    TokenizerTrainingInputSpec,
    VocabularyContract,
)


def test_normalized_sentence_input_contract() -> None:
    """Verifies NormalizedSentenceInput contract validation."""
    valid_input = NormalizedSentenceInput(
        text="Quantum states exhibit entanglement.",
        language="en",
        metadata={"domain": "physics"},
    )
    assert valid_input.text == "Quantum states exhibit entanglement."
    assert valid_input.language == "en"

    # Empty text raises ModuleContractViolationError
    with pytest.raises(ModuleContractViolationError, match="text must be non-empty"):
        NormalizedSentenceInput(text="   ")

    # Invalid language raises ModuleContractViolationError
    with pytest.raises(ModuleContractViolationError, match="language must be valid"):
        NormalizedSentenceInput(text="Valid text", language="x")


def test_tokenized_sentence_output_contract() -> None:
    """Verifies TokenizedSentenceOutput contract validation and error handling."""
    tokens = ["[CLS]", "quantum", "states", "[SEP]"]
    token_ids = [2, 101, 102, 3]

    output = TokenizedSentenceOutput(
        token_ids=token_ids,
        tokens=tokens,
        embedding=[0.1] * 384,
        max_sequence_length=512,
    )
    assert len(output.token_ids) == 4
    assert output.embedding is not None and len(output.embedding) == 384

    # Length mismatch raises ModuleContractViolationError
    with pytest.raises(ModuleContractViolationError, match="tokens length"):
        TokenizedSentenceOutput(token_ids=[1, 2], tokens=["only_one"])

    # Sequence length exceeded raises SequenceLengthExceededError
    with pytest.raises(SequenceLengthExceededError, match="exceeds capacity"):
        TokenizedSentenceOutput(
            token_ids=[1, 2, 3],
            tokens=["a", "b", "c"],
            max_sequence_length=2,
        )

    # Invalid embedding dimension raises EmbeddingDimensionMismatchError
    with pytest.raises(EmbeddingDimensionMismatchError, match="not in allowed"):
        TokenizedSentenceOutput(
            token_ids=[1],
            tokens=["a"],
            embedding=[0.1] * 256,  # 256 is not 384 or 768
        )

    # 768 dimension is accepted
    output_768 = TokenizedSentenceOutput(
        token_ids=[1],
        tokens=["a"],
        embedding=[0.1] * 768,
    )
    assert output_768.embedding is not None and len(output_768.embedding) == 768


def test_special_tokens_canonical_contract() -> None:
    """Verifies canonical special tokens definitions and unique ID allocation."""
    assert CANONICAL_SPECIAL_TOKENS == [
        PAD_TOKEN,
        UNK_TOKEN,
        CLS_TOKEN,
        SEP_TOKEN,
        MASK_TOKEN,
        MATH_TOKEN,
        GREEK_TOKEN,
        UNIT_TOKEN,
    ]

    config = SpecialTokenConfig()
    mapping = config.to_dict()
    assert len(mapping) == 8
    assert len(set(mapping.values())) == 8
    assert mapping[PAD_TOKEN] == 0
    assert mapping[UNK_TOKEN] == 1
    assert mapping[CLS_TOKEN] == 2
    assert mapping[SEP_TOKEN] == 3
    assert mapping[MASK_TOKEN] == 4
    assert mapping[MATH_TOKEN] == 5
    assert mapping[GREEK_TOKEN] == 6
    assert mapping[UNIT_TOKEN] == 7


def test_vocabulary_contract_creation_and_bijection() -> None:
    """Verifies VocabularyContract factory creation and bijective mappings."""
    tokens = [f"token_{i}" for i in range(120)]
    vocab = VocabularyContract.create(tokens)

    assert vocab.vocab_size == 128  # 8 special + 120 standard
    assert len(vocab.token_to_id) == 128
    assert len(vocab.id_to_token) == 128
    assert vocab.vocab_sha256 != ""

    # Check that special tokens are mapped to canonical IDs
    assert vocab.token_to_id[PAD_TOKEN] == 0
    assert vocab.token_to_id[UNIT_TOKEN] == 7

    # Check bijection
    for tok, tid in vocab.token_to_id.items():
        assert vocab.id_to_token[tid] == tok


def test_vocabulary_contract_tamper_detection() -> None:
    """Verifies that tampering with VocabularyContract mappings or hash raises."""
    tokens = [f"subword_{i}" for i in range(100)]
    vocab = VocabularyContract.create(tokens)

    # Corrupting sha256
    with pytest.raises(VocabularyMismatchError, match="SHA-256 mismatch"):
        VocabularyContract(
            vocab_size=vocab.vocab_size,
            token_to_id=vocab.token_to_id,
            id_to_token=vocab.id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256="0" * 64,
        )

    # Corrupting bijection
    corrupt_id_to_token = dict(vocab.id_to_token)
    corrupt_id_to_token[10] = "wrong_token"
    with pytest.raises(VocabularyMismatchError, match="Bijective mismatch"):
        VocabularyContract(
            vocab_size=vocab.vocab_size,
            token_to_id=vocab.token_to_id,
            id_to_token=corrupt_id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256=vocab.vocab_sha256,
        )


def test_tokenizer_training_input_spec_zero_leakage_contract() -> None:
    """Verifies TokenizerTrainingInputSpec prohibits non-TRAIN splits."""
    valid_spec = TokenizerTrainingInputSpec(
        source_split=DatasetSplit.TRAIN,
        source_manifest_id="manifest-train-001",
        document_ids=["doc-001", "doc-002"],
    )
    assert valid_spec.source_split == DatasetSplit.TRAIN

    # Prohibit DatasetSplit.VAL
    with pytest.raises(DataLeakageError, match="strictly prohibited"):
        TokenizerTrainingInputSpec(
            source_split=DatasetSplit.VAL,
            source_manifest_id="manifest-val-001",
            document_ids=["doc-001"],
        )

    # Prohibit DatasetSplit.TEST
    with pytest.raises(DataLeakageError, match="strictly prohibited"):
        TokenizerTrainingInputSpec(
            source_split=DatasetSplit.TEST,
            source_manifest_id="manifest-test-001",
            document_ids=["doc-001"],
        )


def test_special_token_config_validation_errors() -> None:
    """Verifies validation errors on invalid special token configurations."""
    # Duplicate string token
    with pytest.raises(ValueError, match="must be distinct"):
        SpecialTokenConfig(pad_token="[DUP]", unk_token="[DUP]")

    # Duplicate token ID
    with pytest.raises(ValueError, match="must be unique"):
        SpecialTokenConfig(pad_id=0, unk_id=0)

    # Negative token ID
    with pytest.raises(ValueError, match="must be unique"):
        SpecialTokenConfig(pad_id=-1)


def test_tokenized_sentence_output_negative_token_id() -> None:
    """Verifies ValueError when negative token IDs are passed."""
    with pytest.raises(ValueError, match="non-negative integers"):
        TokenizedSentenceOutput(token_ids=[-1], tokens=["invalid"])


def test_vocabulary_contract_size_bounds_and_mismatch() -> None:
    """Verifies validation bounds and size mismatches in VocabularyContract."""
    tokens = [f"tok_{i}" for i in range(120)]
    vocab = VocabularyContract.create(tokens)

    # Vocab size below minimum
    with pytest.raises(ValueError, match=r"vocab_size must be in"):
        VocabularyContract(
            vocab_size=50,  # Below MIN_VOCAB_SIZE (100)
            token_to_id=vocab.token_to_id,
            id_to_token=vocab.id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256=vocab.vocab_sha256,
        )

    # Declared vocab_size != token_to_id length
    with pytest.raises(VocabularyMismatchError, match="token_to_id size"):
        VocabularyContract(
            vocab_size=200,
            token_to_id=vocab.token_to_id,
            id_to_token=vocab.id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256=vocab.vocab_sha256,
        )

    # Declared vocab_size != id_to_token length
    truncated_id_to_token = dict(vocab.id_to_token)
    truncated_id_to_token.pop(0)
    with pytest.raises(VocabularyMismatchError, match="id_to_token size"):
        VocabularyContract(
            vocab_size=vocab.vocab_size,
            token_to_id=vocab.token_to_id,
            id_to_token=truncated_id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256=vocab.vocab_sha256,
        )

    # Special token mapped to non-canonical ID (maintaining bijection)
    corrupt_token_to_id = dict(vocab.token_to_id)
    corrupt_id_to_token = dict(vocab.id_to_token)
    tok_8 = corrupt_id_to_token[8]
    corrupt_token_to_id[PAD_TOKEN] = 8
    corrupt_token_to_id[tok_8] = 0
    corrupt_id_to_token[8] = PAD_TOKEN
    corrupt_id_to_token[0] = tok_8
    with pytest.raises(VocabularyMismatchError, match="Special token"):
        VocabularyContract(
            vocab_size=vocab.vocab_size,
            token_to_id=corrupt_token_to_id,
            id_to_token=corrupt_id_to_token,
            special_tokens=vocab.special_tokens,
            vocab_sha256=vocab.vocab_sha256,
        )


def test_vocabulary_contract_create_with_duplicates() -> None:
    """Verifies VocabularyContract.create deduplicates input tokens cleanly."""
    tokens = [f"tok_{i}" for i in range(100)] + ["tok_0", "tok_1", PAD_TOKEN]
    vocab = VocabularyContract.create(tokens)
    assert vocab.vocab_size == 108  # 8 special + 100 unique tokens


def test_tokenizer_training_spec_validation_bounds() -> None:
    """Verifies boundary checks on TokenizerTrainingInputSpec."""
    # Empty document_ids
    with pytest.raises(ValueError, match="must not be empty"):
        TokenizerTrainingInputSpec(
            source_split=DatasetSplit.TRAIN,
            source_manifest_id="manifest-001",
            document_ids=[],
        )

    # min_frequency < 1
    with pytest.raises(ValueError, match="min_frequency must be >= 1"):
        TokenizerTrainingInputSpec(
            source_split=DatasetSplit.TRAIN,
            source_manifest_id="manifest-001",
            document_ids=["doc-001"],
            min_frequency=0,
        )

    # target_vocab_size out of bounds
    with pytest.raises(ValueError, match="target_vocab_size must be in"):
        TokenizerTrainingInputSpec(
            source_split=DatasetSplit.TRAIN,
            source_manifest_id="manifest-001",
            document_ids=["doc-001"],
            target_vocab_size=50,
        )

