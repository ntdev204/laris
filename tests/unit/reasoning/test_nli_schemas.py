"""Unit tests for Layer 2 Semantic Intelligence and NLI schemas and error semantics.

Task ID: M3-SEM-001-SUB-01 (Issue #53)
"""

import math

import pytest

from laris.core.errors import (
    InvalidNLIInputError,
    ProbabilityValidationError,
    UncertaintyCeilingExceededError,
)
from laris.reasoning import (
    LN_3,
    NLILabel,
    NLIOutput,
    NLIProbabilities,
    SentencePairInput,
)


def test_nli_label_from_str_variants() -> None:
    assert NLILabel.from_str("entailment") == NLILabel.ENTAILMENT
    assert NLILabel.from_str("Entailment ") == NLILabel.ENTAILMENT
    assert NLILabel.from_str("contradiction") == NLILabel.CONTRADICTION
    assert NLILabel.from_str(" neutral\n") == NLILabel.NEUTRAL

    with pytest.raises(InvalidNLIInputError):
        NLILabel.from_str("INVALID")


def test_sentence_pair_input_edge_cases() -> None:
    # Context span None or string
    p1 = SentencePairInput(
        premise="E = mc^2",
        hypothesis="Mass and energy are equivalent.",
        context_span=None,
    )
    assert p1.context_span is None

    p2 = SentencePairInput(
        premise="E = mc^2",
        hypothesis="Mass and energy are equivalent.",
        context_span="Einstein 1905 paper",
    )
    assert p2.context_span == "Einstein 1905 paper"

    # Whitespace stripping behavior
    with pytest.raises(InvalidNLIInputError):
        SentencePairInput(premise="\t\n  ", hypothesis="Valid")

    with pytest.raises(InvalidNLIInputError):
        SentencePairInput(premise="Valid", hypothesis="\t  ")


def test_nli_probabilities_boundary_tolerances() -> None:
    tol = 1e-5
    # Just within upper boundary
    p_valid_upper = NLIProbabilities(
        entailment=0.5,
        contradiction=0.3,
        neutral=0.2 + (tol * 0.9),
        tolerance=tol,
    )
    assert p_valid_upper is not None

    # Just within lower boundary
    p_valid_lower = NLIProbabilities(
        entailment=0.5,
        contradiction=0.3,
        neutral=0.2 - (tol * 0.9),
        tolerance=tol,
    )
    assert p_valid_lower is not None

    # Just exceeding upper boundary
    with pytest.raises(ProbabilityValidationError):
        NLIProbabilities(
            entailment=0.5,
            contradiction=0.3,
            neutral=0.2 + (tol * 1.5),
            tolerance=tol,
        )

    # Just exceeding lower boundary
    with pytest.raises(ProbabilityValidationError):
        NLIProbabilities(
            entailment=0.5,
            contradiction=0.3,
            neutral=0.2 - (tol * 1.5),
            tolerance=tol,
        )


def test_nli_probabilities_margin_and_predicted_label() -> None:
    # Clear winner
    p1 = NLIProbabilities(entailment=0.7, contradiction=0.2, neutral=0.1)
    assert p1.predicted_label() == NLILabel.ENTAILMENT
    assert math.isclose(p1.margin(), 0.5, abs_tol=1e-6)

    # Contradiction winner
    p2 = NLIProbabilities(entailment=0.15, contradiction=0.75, neutral=0.10)
    assert p2.predicted_label() == NLILabel.CONTRADICTION
    assert math.isclose(p2.margin(), 0.60, abs_tol=1e-6)

    # Neutral winner
    p3 = NLIProbabilities(entailment=0.20, contradiction=0.20, neutral=0.60)
    assert p3.predicted_label() == NLILabel.NEUTRAL
    assert math.isclose(p3.margin(), 0.40, abs_tol=1e-6)

    # Exact tie between Entailment and Neutral
    p4 = NLIProbabilities(entailment=0.45, contradiction=0.10, neutral=0.45)
    assert p4.predicted_label() == NLILabel.ENTAILMENT
    assert math.isclose(p4.margin(), 0.0, abs_tol=1e-6)


def test_nli_probabilities_entropy_properties() -> None:
    # Perfectly deterministic distribution -> entropy = 0.0
    p_det = NLIProbabilities(entailment=0.0, contradiction=1.0, neutral=0.0)
    assert math.isclose(p_det.normalized_entropy(), 0.0, abs_tol=1e-6)

    # Uniform distribution (1/3, 1/3, 1/3) -> entropy = 1.0
    p_unif = NLIProbabilities(
        entailment=1.0 / 3.0, contradiction=1.0 / 3.0, neutral=1.0 / 3.0
    )
    assert math.isclose(p_unif.normalized_entropy(), 1.0, abs_tol=1e-6)

    # Two equal classes, third zero -> H = -2*(0.5*ln(0.5)) / ln(3) = ln(2)/ln(3) ~ 0.6309
    p_two = NLIProbabilities(entailment=0.5, contradiction=0.5, neutral=0.0)
    expected_two = math.log(2.0) / LN_3
    assert math.isclose(p_two.normalized_entropy(), expected_two, abs_tol=1e-5)


def test_nli_output_validation_errors() -> None:
    probs = {"ENTAILMENT": 0.6, "CONTRADICTION": 0.2, "NEUTRAL": 0.2}

    # Invalid prediction type
    with pytest.raises(InvalidNLIInputError):
        NLIOutput(
            prediction=123,  # type: ignore[arg-type]
            probabilities=probs,
            uncertainty_score=0.2,
        )

    # Invalid probabilities type
    with pytest.raises(ProbabilityValidationError):
        NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities="not_a_dict",  # type: ignore[arg-type]
            uncertainty_score=0.2,
        )

    # NaN uncertainty score
    with pytest.raises(UncertaintyCeilingExceededError):
        NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities=probs,
            uncertainty_score=float("nan"),
        )

    # Out of bounds uncertainty score
    with pytest.raises(UncertaintyCeilingExceededError):
        NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities=probs,
            uncertainty_score=-0.001,
        )

    with pytest.raises(UncertaintyCeilingExceededError):
        NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities=probs,
            uncertainty_score=1.001,
        )

    # NaN topical similarity
    with pytest.raises(InvalidNLIInputError):
        NLIOutput(
            prediction=NLILabel.ENTAILMENT,
            probabilities=probs,
            uncertainty_score=0.2,
            topical_similarity=float("nan"),
        )
