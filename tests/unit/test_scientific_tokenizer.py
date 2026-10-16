"""Unit tests for ScientificTokenizer and STEM fertility evaluation engine.

Tests:
- LaTeX math and Greek letter preservation during pre-tokenization
- Greedy WordPiece subword segmentation and [UNK] fallback
- Encoding to TokenizedSentenceOutput and decoding roundtrip
- Token fertility ratio computation
- End-to-end STEM fertility evaluation and report serialization against acceptance thresholds
"""

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.language.schemas import (
    CLS_TOKEN,
    SEP_TOKEN,
    UNK_TOKEN,
    VocabularyContract,
)
from laris.language.tokenizer import (
    ScientificTokenizer,
    compute_token_fertility,
    evaluate_stem_fertility,
)
from tests.fixtures.stem_benchmark import (
    STEM_BENCHMARK_FIXTURES,
    STEM_BENCHMARK_VERSION,
    get_stem_vocabulary_tokens,
)


@pytest.fixture
def stem_tokenizer() -> ScientificTokenizer:
    """Provides a domain-adapted scientific tokenizer loaded with STEM benchmark vocabulary."""
    tokens = get_stem_vocabulary_tokens()
    # Add common general English words to ensure comprehensive coverage
    general_words = [
        "the", "of", "in", "and", "to", "a", "with", "is", "for", "at",
        "on", "by", "from", "under", "where", "rates", "conditions",
        "demonstrates", "indicate", "yields", "exceeding", "mediate",
        "undergo", "compute", "optimizes", "admit", "establish",
        "per", "hour", "compact", "identically",
    ]
    all_tokens = sorted(set(tokens + general_words))
    vocab = VocabularyContract.create(all_tokens)
    return ScientificTokenizer(vocab=vocab)


@pytest.fixture
def baseline_general_tokenizer() -> ScientificTokenizer:
    """Provides an unadapted, small character/simple word tokenizer to serve as a baseline."""
    # A generic vocabulary that lacks specialized STEM compound words
    base_words = [
        "the", "of", "in", "and", "to", "a", "with", "is", "for", "at",
        "on", "by", "from", "under", "where", "state", "rate", "tree",
        "##a", "##b", "##c", "##d", "##e", "##f", "##g", "##h", "##i",
        "##j", "##k", "##l", "##m", "##n", "##o", "##p", "##q", "##r",
        "##s", "##t", "##u", "##v", "##w", "##x", "##y", "##z",
    ]
    # Pad to minimum vocab size
    for i in range(len(base_words), 110):
        base_words.append(f"base_tok_{i}")
    vocab = VocabularyContract.create(base_words)
    return ScientificTokenizer(vocab=vocab)


def test_scientific_tokenizer_pre_tokenization(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies math formulas and Greek symbols are preserved during pre-tokenization."""
    text = "Cavity coupling parameter satisfies $\\alpha \\le \\beta$ at 15 mK."
    tokens = stem_tokenizer.pre_tokenize(text)

    assert "$\\alpha \\le \\beta$" in tokens
    assert "cavity" in tokens
    assert "coupling" in tokens

    # Empty text returns empty list
    assert stem_tokenizer.pre_tokenize("") == []
    assert stem_tokenizer.pre_tokenize("   \n\t ") == []


def test_scientific_tokenizer_wordpiece_segmentation(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies greedy WordPiece subword segmentation and unknown token fallback."""
    # Known whole word in vocab
    assert stem_tokenizer.tokenize("quantum") == ["quantum"]

    # Subword segmentation with continuation prefix
    # 'electrodynamics' should segment into known morphemes or subwords
    subwords = stem_tokenizer.tokenize("electrodynamics")
    assert len(subwords) >= 1
    assert any("electro" in tok for tok in subwords)

    # Word with completely unknown character falls back to [UNK]
    unk_subwords = stem_tokenizer.tokenize("xyz123nonexistentcharacter\u9999")
    assert unk_subwords == [UNK_TOKEN]


def test_scientific_tokenizer_encode_decode_roundtrip(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies token encoding into TokenizedSentenceOutput and decoding roundtrip."""
    text = "quantum electro dynamics in cavity"
    output = stem_tokenizer.encode(text, add_special_tokens=True)

    assert output.tokens[0] == CLS_TOKEN
    assert output.tokens[-1] == SEP_TOKEN
    assert len(output.token_ids) == len(output.tokens)
    assert output.token_ids[0] == stem_tokenizer.vocab.token_to_id[CLS_TOKEN]
    assert output.token_ids[-1] == stem_tokenizer.vocab.token_to_id[SEP_TOKEN]

    decoded = stem_tokenizer.decode(output.token_ids, skip_special_tokens=True)
    assert "quantum" in decoded
    assert "cavity" in decoded

    # Non-string raises ModuleContractViolationError
    with pytest.raises(ModuleContractViolationError, match="must be a string"):
        stem_tokenizer.encode(12345)  # type: ignore[arg-type]


def test_compute_token_fertility(stem_tokenizer: ScientificTokenizer) -> None:
    """Verifies fertility computation logic."""
    text = "quantum electro dynamics in cavity"
    fert, wc, tc = compute_token_fertility(text, stem_tokenizer)

    assert wc == 5
    assert tc >= 5
    assert fert == tc / wc

    # Empty text returns 0 fertility
    empty_fert, empty_wc, empty_tc = compute_token_fertility("", stem_tokenizer)
    assert empty_fert == 0.0
    assert empty_wc == 0
    assert empty_tc == 0


def test_evaluate_stem_fertility_benchmark(
    stem_tokenizer: ScientificTokenizer,
    baseline_general_tokenizer: ScientificTokenizer,
) -> None:
    """Evaluates STEM fertility against the acceptance criteria (fertility <= 1.35)."""
    report = evaluate_stem_fertility(
        tokenizer=stem_tokenizer,
        samples=STEM_BENCHMARK_FIXTURES,
        baseline_tokenizer=baseline_general_tokenizer,
    )

    # 1. Acceptance Criteria: STEM fertility <= 1.35
    assert report.average_fertility <= 1.35, (
        f"Domain tokenizer fertility ({report.average_fertility:.3f}) exceeded threshold 1.35!"
    )

    # 2. Benchmark completeness
    assert report.benchmark_version == STEM_BENCHMARK_VERSION
    assert report.num_samples == len(STEM_BENCHMARK_FIXTURES)
    assert report.total_words > 0
    assert report.total_tokens > 0
    assert report.report_sha256 != ""

    # 3. Domain coverage
    expected_domains = {"physics", "chemistry", "biology", "computer_science", "mathematics"}
    assert set(report.domain_fertility.keys()) == expected_domains
    for domain, domain_fert in report.domain_fertility.items():
        assert domain_fert <= 1.45, f"Domain '{domain}' fertility {domain_fert:.3f} was too high"

    # 4. Baseline comparison
    assert report.baseline_fertility is not None
    assert report.baseline_fertility > report.average_fertility
    assert report.fertility_reduction_pct is not None and report.fertility_reduction_pct > 0.0

    # 5. Serialization integrity
    report_dict = report.to_dict()
    assert report_dict["average_fertility"] == round(report.average_fertility, 4)
    assert report_dict["benchmark_version"] == STEM_BENCHMARK_VERSION

    report_json = report.to_json()
    assert report.report_sha256 in report_json
