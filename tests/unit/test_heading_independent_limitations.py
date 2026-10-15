"""Unit tests for Heading-Independent Limitation and Assumption Detection.

Module ID: MOD-SCINLP-002 (Boundary D: Scientific Language Intelligence)
Subtask: M4-SCINLP-002-SUB-01 (Issue #57)
Parent Task: #25
Tests:
- Extraction of limitations, boundary conditions, negative findings, and assumptions without headers
- Explicit epistemic uncertainty scoring and distribution
- Fine-grained categorization across computational, data, generalization, scope, and method types
- Stripped-heading benchmark evaluation verifying recall >= 80%
- Coordinate anchoring and provenance preservation
- Error handling for invalid inputs and malformed coordinate spans
- Serialization and round-trip consistency
"""

import pytest

from laris.core.errors import (
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer3_scinlp import (
    HeadingIndependentLimitationDetector,
    LimitationCategory,
    LimitationDetectionResult,
    compute_uncertainty_score,
    strip_headings,
)


@pytest.fixture
def synthetic_paper_with_headings() -> str:
    """Synthetic paper containing numbered and Markdown headings and diverse discourse units."""
    return (
        "# 1. Introduction\n"
        "We propose an efficient algorithm for molecular graph representation.\n\n"
        "## 2. Theoretical Assumptions\n"
        "We assume that the underlying physical system satisfies energy conservation. "
        "Under the assumption of convex potential surfaces, convergence is guaranteed.\n\n"
        "## 3. Experimental Results\n"
        "Our model achieves an accuracy of 94.1% on standard benchmarks. "
        "However, no statistically significant improvement was observed on dense crystal lattices. "
        "Moreover, our model fails to outperform the baseline on macromolecules.\n\n"
        "# 4. Discussion and Limitations\n"
        "A major computational cost is prohibitive GPU memory during 3D conformation generation. "
        "Furthermore, our approach suffers from data scarcity on rare organic compounds. "
        "Our model fails to generalize to unseen protein targets due to distribution shift. "
        "This work is restricted to 2D topological graphs, "
        "and we leave 3D dynamics for future work. "
        "The first-order approximation error may introduce bias in molecular force calculations."
    )


def test_detector_initialization():
    """Verify threshold boundary validation on detector initialization."""
    with pytest.raises(
        ModuleContractViolationError, match="confidence_threshold must be in range"
    ):
        HeadingIndependentLimitationDetector(confidence_threshold=-0.1)

    with pytest.raises(
        ModuleContractViolationError, match="confidence_threshold must be in range"
    ):
        HeadingIndependentLimitationDetector(confidence_threshold=1.1)

    detector = HeadingIndependentLimitationDetector(confidence_threshold=0.6)
    assert detector.confidence_threshold == 0.6


def test_input_validation():
    """Verify input argument type checking."""
    detector = HeadingIndependentLimitationDetector()

    with pytest.raises(
        ModuleContractViolationError, match="document_id must be a non-empty string"
    ):
        detector.detect("Valid text", "")

    with pytest.raises(
        ModuleContractViolationError, match="document_id must be a non-empty string"
    ):
        detector.detect("Valid text", None)  # type: ignore

    with pytest.raises(ModuleContractViolationError, match="text must be a string"):
        detector.detect(1234, "doc-1")  # type: ignore


def test_malformed_coordinates():
    """Verify rejection of malformed EvidenceCoordinate inputs."""
    detector = HeadingIndependentLimitationDetector()

    bad_coord = EvidenceCoordinate(
        coordinate_id="c-bad",
        document_id="doc-1",
        document_sha256="abc",
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=9999,  # exceeds text length
        verbatim_snippet="text",
        extraction_confidence=0.9,
    )
    with pytest.raises(MalformedDiscourseSpanError, match="Invalid coordinate offsets"):
        detector.detect("Short text", "doc-1", coordinates=[bad_coord])

    with pytest.raises(ModuleContractViolationError, match="Expected EvidenceCoordinate"):
        detector.detect("Short text", "doc-1", coordinates=["not-a-coord"])  # type: ignore


def test_strip_headings():
    """Verify heading stripper removes Markdown and numbered section headers."""
    text = (
        "# Title\n"
        "Sentence one.\n"
        "## Subtitle\n"
        "Sentence two.\n"
        "3. Methods Section\n"
        "Sentence three."
    )
    stripped = strip_headings(text)
    assert "# Title" not in stripped
    assert "## Subtitle" not in stripped
    assert "3. Methods Section" not in stripped
    assert "Sentence one." in stripped
    assert "Sentence two." in stripped
    assert "Sentence three." in stripped


def test_epistemic_uncertainty_scoring():
    """Verify uncertainty scores for assertive vs hedged statements."""
    assertive = "Our approach fails when the input sequence exceeds 2048 tokens."
    assert compute_uncertainty_score(assertive) <= 0.20

    single_hedge = "The method could potentially suffer from numerical instability."
    score_single = compute_uncertainty_score(single_hedge)
    assert 0.35 <= score_single <= 0.70

    multi_hedge = "It seems plausible that the model might possibly fail under extreme noise."
    score_multi = compute_uncertainty_score(multi_hedge)
    assert score_multi >= 0.65


def test_heading_independent_detection(synthetic_paper_with_headings: str):
    """Test detection on text after completely removing all section headers."""
    detector = HeadingIndependentLimitationDetector(confidence_threshold=0.5)
    doc_id = "doc-mol-001"

    # Run on stripped text
    result = detector.detect(synthetic_paper_with_headings, doc_id, strip_headers=True)

    assert isinstance(result, LimitationDetectionResult)
    assert result.document_id == doc_id
    assert result.total_count() >= 6

    # 1. Limitations & Categorization
    categories = {lim.category for lim in result.limitations}
    assert LimitationCategory.COMPUTATIONAL_RESOURCE.value in categories
    assert LimitationCategory.DATA_SPARSITY.value in categories
    assert LimitationCategory.GENERALIZATION_BOUND.value in categories
    assert LimitationCategory.SCOPE_RESTRICTION.value in categories
    assert LimitationCategory.METHODOLOGICAL.value in categories

    for lim in result.limitations:
        assert lim.coordinate.char_start >= 0
        assert lim.coordinate.char_end > lim.coordinate.char_start
        assert lim.confidence >= 0.5
        assert 0.0 <= lim.uncertainty_score <= 1.0

    # 2. Negative / Null Findings
    assert len(result.negative_findings) >= 2
    neg_descriptions = " ".join(nf.description for nf in result.negative_findings)
    assert "no statistically significant improvement" in neg_descriptions
    assert "fails to outperform" in neg_descriptions

    # 3. Model Assumptions
    assert len(result.assumptions) >= 2
    assump_statements = " ".join(a.statement for a in result.assumptions)
    assert "energy conservation" in assump_statements
    assert "convex potential surfaces" in assump_statements

    # 4. Uncertainty distribution
    assert "low" in result.uncertainty_distribution
    assert "medium" in result.uncertainty_distribution
    assert "high" in result.uncertainty_distribution
    assert sum(result.uncertainty_distribution.values()) == result.total_count()


def test_stripped_heading_recall_gate(synthetic_paper_with_headings: str):
    """Verify limitation recall on stripped-heading text achieves >= 80% (M4-SCINLP-002 gate)."""
    ground_truth = [
        "computational cost is prohibitive",
        "data scarcity on rare organic compounds",
        "fails to generalize to unseen protein targets",
        "restricted to 2D topological graphs",
        "first-order approximation error may introduce bias",
    ]

    detector = HeadingIndependentLimitationDetector(confidence_threshold=0.5)
    report = detector.evaluate_stripped_heading_recall(ground_truth, synthetic_paper_with_headings)

    assert report["ground_truth_count"] == 5
    assert report["recall"] >= 0.80, f"Expected recall >= 0.80, got {report['recall']}"
    assert report["detected_count"] >= 5


def test_empty_ground_truth_recall():
    """Verify evaluation behavior when ground truth list is empty."""
    detector = HeadingIndependentLimitationDetector()
    report = detector.evaluate_stripped_heading_recall([], "Some text without limitations.")
    assert report["recall"] == 1.0
    assert report["ground_truth_count"] == 0


def test_empty_and_neutral_documents():
    """Verify detection on empty text and text without limitations."""
    detector = HeadingIndependentLimitationDetector()
    empty_res = detector.detect("", "doc-empty")
    assert empty_res.total_count() == 0

    neutral_text = (
        "We describe the synthesis of novel peptides. "
        "The reaction proceeded at room temperature for 12 hours. "
        "Crystals were isolated by filtration."
    )
    neutral_res = detector.detect(neutral_text, "doc-neutral")
    assert neutral_res.total_count() == 0


def test_serialization_roundtrip(synthetic_paper_with_headings: str):
    """Verify JSON serialization preserves all records, coordinates, and uncertainty."""
    detector = HeadingIndependentLimitationDetector(confidence_threshold=0.5)
    original = detector.detect(synthetic_paper_with_headings, "doc-ser-test", strip_headers=True)

    json_data = original.to_json()
    restored = LimitationDetectionResult.from_json(json_data)

    assert restored.document_id == original.document_id
    assert restored.total_count() == original.total_count()
    assert restored.uncertainty_distribution == original.uncertainty_distribution
    assert restored.category_counts == original.category_counts

    for orig_lim, rest_lim in zip(original.limitations, restored.limitations):
        assert orig_lim.limitation_id == rest_lim.limitation_id
        assert orig_lim.description == rest_lim.description
        assert orig_lim.category == rest_lim.category
        assert orig_lim.uncertainty_score == rest_lim.uncertainty_score
        assert orig_lim.coordinate.coordinate_id == rest_lim.coordinate.coordinate_id

    for orig_nf, rest_nf in zip(original.negative_findings, restored.negative_findings):
        assert orig_nf.finding_id == rest_nf.finding_id
        assert orig_nf.description == rest_nf.description
        assert orig_nf.uncertainty_score == rest_nf.uncertainty_score


def test_schema_uncertainty_score_bounds():
    """Verify uncertainty_score range validation across schema records."""
    from laris.layers.layer3_scinlp.schemas import (
        AssumptionRecord,
        LimitationRecord,
        NegativeFindingRecord,
    )

    coord = EvidenceCoordinate(
        coordinate_id="c-test",
        document_id="doc-1",
        document_sha256="abc",
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=10,
        verbatim_snippet="0123456789",
        extraction_confidence=0.9,
    )

    with pytest.raises(ModuleContractViolationError, match="uncertainty_score must be in range"):
        LimitationRecord(
            limitation_id="lim-1",
            description="A limitation",
            confidence=0.8,
            coordinate=coord,
            uncertainty_score=-0.1,
        )

    with pytest.raises(ModuleContractViolationError, match="uncertainty_score must be in range"):
        AssumptionRecord(
            assumption_id="asm-1",
            statement="An assumption",
            confidence=0.8,
            coordinate=coord,
            uncertainty_score=1.5,
        )

    with pytest.raises(ModuleContractViolationError, match="uncertainty_score must be in range"):
        NegativeFindingRecord(
            finding_id="neg-1",
            description="A negative finding",
            confidence=0.8,
            coordinate=coord,
            uncertainty_score=2.0,
        )


def test_uncertainty_score_extreme_hedges_and_no_tokens():
    """Verify uncertainty calculation with empty tokens and 3+ hedges."""
    assert compute_uncertainty_score("12345 !@#$%") == 0.10

    extreme_hedge = "It seems tentative and could potentially, plausibly and might fail."
    score = compute_uncertainty_score(extreme_hedge)
    assert score >= 0.75


def test_provided_coordinate_matching_in_limitations():
    """Verify that supplied EvidenceCoordinates are matched when extracting limitations."""
    text = "A key limitation of our model is poor generalization on unseen datasets."
    doc_id = "doc-match-1"
    supplied_coord = EvidenceCoordinate(
        coordinate_id="user-coord-42",
        document_id=doc_id,
        document_sha256="sha-test",
        page_number=5,
        section_identifier="discussion",
        paragraph_index=1,
        sentence_index=0,
        char_start=0,
        char_end=len(text),
        verbatim_snippet=text,
        extraction_confidence=0.95,
    )
    detector = HeadingIndependentLimitationDetector()
    res = detector.detect(text, doc_id, coordinates=[supplied_coord])
    assert len(res.limitations) >= 1
    assert res.limitations[0].coordinate.coordinate_id == "user-coord-42"
    assert res.limitations[0].coordinate.page_number == 5


def test_general_limitation_and_zero_match_recall():
    """Verify general category limitation classification and zero-match recall evaluation."""
    text = "One drawback is sensitivity to initialization."
    detector = HeadingIndependentLimitationDetector()
    res = detector.detect(text, "doc-gen")
    assert len(res.limitations) == 1
    assert res.limitations[0].category == LimitationCategory.GENERAL.value

    # Zero match recall
    report = detector.evaluate_stripped_heading_recall(
        ["completely unmentioned limitation statement"], text
    )
    assert report["recall"] == 0.0
    assert report["ground_truth_count"] == 1

