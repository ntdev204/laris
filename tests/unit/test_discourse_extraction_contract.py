"""Unit tests for Scientific Discourse Extraction Contract and Coordinate Validation.

Module ID: MOD-SCINLP-001 (Boundary D: Scientific Language Intelligence)
Subtask: M4-SCINLP-001-SUB-02 (Issue #88)
Tests:
- Runtime protocol conformance to DiscourseExtractorContract
- Claims, methods, datasets, metrics, results, limitations, assumptions, and LaTeX formulas
- Exact physical coordinate anchoring and snippet verification
- Provenance preservation and deterministic manifest hashing
- Error handling for malformed spans, invalid types, and out-of-range thresholds
- ExtractionConfidenceBelowThresholdError when threshold is strictly enforced
- Heading-agnostic discourse unit extraction across synthetic scientific texts
"""

import hashlib

import pytest

from laris.core.errors import (
    ExtractionConfidenceBelowThresholdError,
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer3_scinlp import (
    DiscourseExtractionSet,
    DiscourseExtractorContract,
    ScientificDiscourseExtractor,
)


@pytest.fixture
def synthetic_scientific_paper() -> str:
    """Synthetic scientific paper excerpt containing all discourse categories."""
    return (
        "We propose a novel Transformer architecture for scientific literature reasoning. "
        "We evaluate our framework on the GLUE and PubMed benchmark datasets using SGD and AdamW. "
        "Our results show that the proposed model achieves an accuracy of 92.4% "
        "and a Macro-F1 of 0.89. "
        "The model yields a statistically significant improvement with p < 0.01 over the baseline. "
        "The classification loss is defined as:\n"
        "$$\\mathcal{L} = -\\sum_{i=1}^{N} y_i \\log(\\hat{y}_i)$$\n"
        "where $y_i$ denotes ground truth labels and $\\hat{y}_i$ denotes predicted probabilities. "
        "We assume that all training sequences are independent and identically distributed. "
        "A limitation of our approach is that the computational cost is prohibitive on "
        "long documents, and our approach is limited to sequences shorter than 4096 tokens."
    )


def test_extractor_protocol_conformance():
    """Verify that ScientificDiscourseExtractor satisfies DiscourseExtractorContract Protocol."""
    extractor = ScientificDiscourseExtractor()
    assert isinstance(extractor, DiscourseExtractorContract)
    assert hasattr(extractor, "extract")
    assert callable(extractor.extract)


def test_extractor_initialization_bounds():
    """Verify boundary checks on threshold parameters."""
    with pytest.raises(ModuleContractViolationError, match="confidence_threshold must be in"):
        ScientificDiscourseExtractor(confidence_threshold=-0.1)

    with pytest.raises(ModuleContractViolationError, match="confidence_threshold must be in"):
        ScientificDiscourseExtractor(confidence_threshold=1.5)

    with pytest.raises(ModuleContractViolationError, match="min_confidence must be in"):
        ScientificDiscourseExtractor(min_confidence=-0.05)

    with pytest.raises(ModuleContractViolationError, match="min_confidence must be in"):
        ScientificDiscourseExtractor(min_confidence=1.05)


def test_invalid_input_types():
    """Verify type checking on document_id, text, and coordinates."""
    extractor = ScientificDiscourseExtractor()

    # Invalid document_id
    with pytest.raises(
        ModuleContractViolationError, match="document_id must be a non-empty string"
    ):
        extractor.extract("", "Valid text")

    with pytest.raises(
        ModuleContractViolationError, match="document_id must be a non-empty string"
    ):
        extractor.extract(None, "Valid text")  # type: ignore

    # Invalid text
    with pytest.raises(ModuleContractViolationError, match="text must be a string"):
        extractor.extract("doc-1", None)  # type: ignore

    with pytest.raises(ModuleContractViolationError, match="text must be a string"):
        extractor.extract("doc-1", 12345)  # type: ignore


def test_malformed_provided_coordinates():
    """Verify detection of malformed coordinates provided in extract call."""
    extractor = ScientificDiscourseExtractor()

    # Out of bounds offset range (char_end > len(text))
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
        extractor.extract("doc-1", "Short text", coordinates=[bad_coord])

    # Non-EvidenceCoordinate object
    with pytest.raises(ModuleContractViolationError, match="Expected EvidenceCoordinate"):
        extractor.extract("doc-1", "Some valid text", coordinates=["not-a-coord"])  # type: ignore


def test_full_synthetic_extraction(synthetic_scientific_paper: str):
    """Test comprehensive extraction across all 8 discourse entity categories."""
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    doc_id = "doc-synth-42"
    result = extractor.extract(doc_id, synthetic_scientific_paper)

    assert isinstance(result, DiscourseExtractionSet)
    assert result.document_id == doc_id
    assert result.total_entities_count() > 0

    # 1. Claims
    assert len(result.claims) >= 1
    assert any(
        "propose a novel Transformer" in c.text or "results show that" in c.text
        for c in result.claims
    )
    for c in result.claims:
        assert c.confidence >= 0.5
        assert c.coordinate.document_id == doc_id
        # Physical offset verification
        snippet = synthetic_scientific_paper[c.coordinate.char_start:c.coordinate.char_end]
        assert snippet == c.coordinate.verbatim_snippet

    # 2. Methods
    assert len(result.methods) >= 2
    method_names = {m.name for m in result.methods}
    assert "Transformer" in method_names
    assert "AdamW" in method_names or "SGD" in method_names
    for m in result.methods:
        snippet = synthetic_scientific_paper[m.coordinate.char_start:m.coordinate.char_end]
        assert snippet == m.coordinate.verbatim_snippet

    # 3. Datasets
    assert len(result.datasets) >= 2
    ds_names = {d.name.upper() for d in result.datasets}
    assert "GLUE" in ds_names
    assert "PUBMED" in ds_names
    for d in result.datasets:
        snippet = synthetic_scientific_paper[d.coordinate.char_start:d.coordinate.char_end]
        assert snippet == d.coordinate.verbatim_snippet

    # 4. Metrics
    assert len(result.metrics) >= 2
    metric_names = {mtr.name for mtr in result.metrics}
    assert "ACCURACY" in metric_names
    assert "MACRO-F1" in metric_names
    for mtr in result.metrics:
        if mtr.name == "ACCURACY":
            assert mtr.value == 92.4
            assert mtr.unit == "%"
        elif mtr.name == "MACRO-F1":
            assert mtr.value == 0.89

    # 5. Results
    assert len(result.results) >= 1
    for r in result.results:
        assert "p < 0.01" in r.description or "achieves an accuracy" in r.description
        if r.statistically_significant:
            assert r.p_value is not None and r.p_value <= 0.05

    # 6. Limitations
    assert len(result.limitations) >= 1
    for lim in result.limitations:
        assert (
            "computational cost is prohibitive" in lim.description
            or "limited to" in lim.description
        )

    # 7. Assumptions
    assert len(result.assumptions) >= 1
    assert any("identically distributed" in a.statement for a in result.assumptions)

    # 8. Formulas
    assert len(result.formulas) >= 1
    disp_formulas = [f for f in result.formulas if not f.is_inline]
    inline_formulas = [f for f in result.formulas if f.is_inline]
    assert len(disp_formulas) >= 1
    assert len(inline_formulas) >= 1
    # Check symbols
    assert any("\\sum" in f.variables or "\\log" in f.variables for f in disp_formulas)


def test_exact_coordinate_and_provenance_preservation():
    """Verify that coordinates faithfully reconstruct the original text and preserve provenance."""
    text = "We observe that BERT outperforms baseline models by 5.2% on GLUE."
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    doc_id = "doc-prov-001"
    doc_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    extraction = extractor.extract(doc_id, text)

    assert len(extraction.claims) >= 1
    claim = extraction.claims[0]
    assert claim.coordinate.document_id == doc_id
    assert claim.coordinate.document_sha256 == doc_sha256
    assert claim.coordinate.page_number == 1
    assert claim.coordinate.char_start == 0
    assert claim.coordinate.char_end == len(text)
    assert claim.coordinate.verbatim_snippet == text

    # Deterministic manifest hash
    manifest_hash_1 = extraction.compute_manifest_hash()
    manifest_hash_2 = extraction.compute_manifest_hash()
    assert manifest_hash_1 == manifest_hash_2
    assert len(manifest_hash_1) == 64


def test_provided_coordinates_matching():
    """Verify matching of extracted spans when caller provides pre-existing EvidenceCoordinate."""
    text = "We establish that SciBERT yields high F1 on PubMed."
    doc_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    existing_coord = EvidenceCoordinate(
        coordinate_id="sent-coord-1",
        document_id="doc-pre-001",
        document_sha256=doc_sha256,
        page_number=3,
        section_identifier="sec:results",
        paragraph_index=2,
        sentence_index=1,
        char_start=0,
        char_end=len(text),
        verbatim_snippet=text,
        extraction_confidence=0.95,
    )

    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    result = extractor.extract("doc-pre-001", text, coordinates=[existing_coord])

    # All extracted entities contained within [0, len(text)] inherit page 3 and section_id
    assert len(result.claims) >= 1
    for claim in result.claims:
        assert claim.coordinate.page_number == 3
        assert claim.coordinate.section_identifier == "sec:results"
        assert claim.coordinate.coordinate_id == "sent-coord-1"


def test_latex_environments_and_syntax_validation():
    """Verify extraction and syntax validation of complex LaTeX equations."""
    text = (
        "Consider the variational objective:\n"
        "\\begin{equation}\n"
        "\\mathcal{F}(\\theta) = \\mathbb{E}_{q_\\phi(z|x)}[\\log p_\\theta(x|z)] "
        "- D_{KL}(q_\\phi(z|x) || p(z))\n"
        "\\end{equation}\n"
        "where $\\theta$ and $\\phi$ are variational parameters."
    )
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    res = extractor.extract("doc-math-1", text)

    assert len(res.formulas) >= 2
    eq_formula = [f for f in res.formulas if not f.is_inline][0]
    assert "\\mathcal{F}" in eq_formula.latex_source
    assert "\\mathbb" in eq_formula.variables
    assert eq_formula.confidence >= 0.85

    # Test malformed LaTeX (unbalanced brace)
    malformed_text = "Here is an unbalanced equation: $$\\frac{a}{b$$ and valid $x = y$."
    extractor.extract("doc-bad-math", malformed_text)
    raw_res = ScientificDiscourseExtractor(confidence_threshold=0.0).extract(
        "doc-bad-math", malformed_text
    )
    bad_forms = [f for f in raw_res.formulas if "\\frac{a}{b" in f.latex_source]
    assert len(bad_forms) == 1
    assert bad_forms[0].confidence < 0.5


def test_confidence_threshold_filtering():
    """Verify entities below confidence_threshold are omitted when enforce_threshold is False."""
    text = "We observe that BERT achieves 90% accuracy."
    # High threshold filter
    strict_extractor = ScientificDiscourseExtractor(
        confidence_threshold=0.99, enforce_threshold=False
    )
    strict_res = strict_extractor.extract("doc-strict", text)
    # None of the entities should pass 0.99
    assert strict_res.total_entities_count() == 0

    # Normal threshold
    normal_extractor = ScientificDiscourseExtractor(
        confidence_threshold=0.5, enforce_threshold=False
    )
    normal_res = normal_extractor.extract("doc-normal", text)
    assert normal_res.total_entities_count() > 0


def test_confidence_threshold_enforcement_exception():
    """Verify ExtractionConfidenceBelowThresholdError is raised when enforce_threshold is True."""
    text = "Here is an unbalanced equation: $$\\frac{a}{b$$ with bad syntax."
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.8, enforce_threshold=True)

    with pytest.raises(ExtractionConfidenceBelowThresholdError, match="is below threshold"):
        extractor.extract("doc-err", text)


def test_heading_agnostic_extraction():
    """Verify that extraction operates identically on texts without section headings."""
    unstructured_text = (
        "We hypothesize that deep residual representations generalise across biological sequences. "
        "We train a ResNet model on UniProt. "
        "The model achieves an AUC of 0.94. "
        "A limitation of this approach is sensitivity to label noise."
    )
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    res = extractor.extract("doc-unstructured", unstructured_text)

    assert len(res.claims) >= 1
    assert len(res.methods) >= 1
    assert len(res.datasets) >= 1
    assert len(res.metrics) >= 1
    assert len(res.limitations) >= 1


def test_empty_and_whitespace_documents():
    """Verify safe handling of empty and whitespace documents."""
    extractor = ScientificDiscourseExtractor()
    empty_res = extractor.extract("doc-empty", "")
    assert empty_res.total_entities_count() == 0

    ws_res = extractor.extract("doc-ws", "   \n\n\t   ")
    assert ws_res.total_entities_count() == 0


def test_serialization_roundtrip_integrity(synthetic_scientific_paper: str):
    """Verify JSON and dict serialization/deserialization lossless round-trip."""
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.5)
    original = extractor.extract("doc-ser-1", synthetic_scientific_paper)

    json_str = original.to_json()
    reconstructed = DiscourseExtractionSet.from_json(json_str)

    assert reconstructed.document_id == original.document_id
    assert reconstructed.extraction_id == original.extraction_id
    assert reconstructed.total_entities_count() == original.total_entities_count()
    assert reconstructed.compute_manifest_hash() == original.compute_manifest_hash()

    # Verify coordinate fields preserved
    for orig_c, recon_c in zip(original.claims, reconstructed.claims):
        assert orig_c.claim_id == recon_c.claim_id
        assert orig_c.coordinate.coordinate_id == recon_c.coordinate.coordinate_id
        assert orig_c.coordinate.char_start == recon_c.coordinate.char_start
        assert orig_c.coordinate.char_end == recon_c.coordinate.char_end
        assert orig_c.coordinate.verbatim_snippet == recon_c.coordinate.verbatim_snippet


def test_latex_syntax_delimiter_mismatches():
    """Verify delimiter mismatch detection in LaTeX formulas."""
    from laris.layers.layer3_scinlp.extractor import _validate_latex_syntax

    # Negative brace, bracket, paren depth
    assert not _validate_latex_syntax("}")
    assert not _validate_latex_syntax("]")
    assert not _validate_latex_syntax(")")
    assert not _validate_latex_syntax("{a + b}}")
    assert not _validate_latex_syntax("[x]]")
    assert not _validate_latex_syntax("(y))")
    assert _validate_latex_syntax("\\{ escaped brace \\}")


def test_nested_formula_spans_deduplication():
    """Verify formulas in LaTeX environments do not create duplicate inline/display formulas."""
    text = (
        "\\begin{equation}\n"
        "$$x = 1$$\n"
        "$y = 2$\n"
        "\\end{equation}"
    )
    extractor = ScientificDiscourseExtractor(confidence_threshold=0.0)
    result = extractor.extract("doc-nested", text)
    # The outer environment covers the inner spans, preventing duplicate entries
    assert len(result.formulas) == 1
    assert result.formulas[0].latex_source.startswith("\\begin{equation}")

