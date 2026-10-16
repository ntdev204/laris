"""Comprehensive tests for source-coordinate contract, corruption detection, and audit trail.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010 (Issues #29, #93):
- Test coordinate bounds, page/sentence identifiers, document revision identity
- Detect and reject bitwise tampering, checksum drift, and snippet corruptions
- Verify fail-closed ProvenanceViolationError on missing or invalid provenance
- Test non-fatal audit trail generation (ProvenanceAuditReport)
- End-to-end provenance preservation across multi-channel retrieval and fusion
"""

from __future__ import annotations

import hashlib

import pytest

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer5_graph.schemas import (
    ClaimNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
)
from laris.layers.layer6_retrieval import (
    DenseVectorAdapter,
    DenseVectorItem,
    EvidenceCoordinateValidator,
    GraphRetrievalAdapter,
    HybridRetrievalEngine,
    LexicalBM25Adapter,
    LexicalDocument,
    ProvenanceAuditReport,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


@pytest.fixture
def synthetic_paper() -> tuple[str, str, str]:
    """Synthetic paper fixture: document ID, full text, and SHA-256 hash."""
    doc_id = "paper-syn-042"
    text = (
        "Superconducting transmon qubits achieve microsecond coherence times through "
        "large Josephson junctions shunted by an external capacitance. Quantum error "
        "correction suppresses logical phase-flip errors below threshold."
    )
    doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return doc_id, text, doc_hash


@pytest.fixture
def valid_coord(synthetic_paper: tuple[str, str, str]) -> EvidenceCoordinate:
    """Fixture providing a verified EvidenceCoordinate matching synthetic_paper."""
    doc_id, text, doc_hash = synthetic_paper
    snippet = "Superconducting transmon qubits"
    start = text.index(snippet)
    end = start + len(snippet)
    return EvidenceCoordinate(
        coordinate_id="coord-042-1",
        document_id=doc_id,
        document_sha256=doc_hash,
        page_number=1,
        section_identifier="sec-introduction",
        paragraph_index=0,
        sentence_index=0,
        char_start=start,
        char_end=end,
        verbatim_snippet=snippet,
        extraction_confidence=0.98,
    )


# ==============================================================================
# 1. Coordinate Bounds & Structural Invariants
# ==============================================================================


def test_coordinate_valid_passes(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """A valid coordinate matching registered document text and hash must pass."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash, revision_id="1.0.0", total_pages=5)
    assert validator.validate_coordinate(valid_coord) is True


def test_coordinate_empty_id(valid_coord: EvidenceCoordinate) -> None:
    """Empty or whitespace coordinate_id triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    corrupt = EvidenceCoordinate(
        coordinate_id="   ",
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet=valid_coord.verbatim_snippet,
    )
    with pytest.raises(ProvenanceViolationError, match="coordinate_id must not be empty"):
        validator.validate_coordinate(corrupt)


def test_coordinate_empty_document_id(valid_coord: EvidenceCoordinate) -> None:
    """Empty or whitespace document_id triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id="  ",
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet=valid_coord.verbatim_snippet,
    )
    with pytest.raises(ProvenanceViolationError, match="document_id must not be empty"):
        validator.validate_coordinate(corrupt)


def test_coordinate_empty_section_identifier(valid_coord: EvidenceCoordinate) -> None:
    """Empty section_identifier triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier="",
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet=valid_coord.verbatim_snippet,
    )
    with pytest.raises(ProvenanceViolationError, match="section_identifier must not be empty"):
        validator.validate_coordinate(corrupt)


def test_coordinate_empty_snippet(valid_coord: EvidenceCoordinate) -> None:
    """Empty or all-whitespace verbatim_snippet triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet="   \t",
    )
    with pytest.raises(ProvenanceViolationError, match="verbatim_snippet must not be empty"):
        validator.validate_coordinate(corrupt)


def test_coordinate_char_end_exceeds_doc_length(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """char_end exceeding document physical length triggers ProvenanceViolationError."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash)

    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=0,
        char_end=len(text) + 50,
        verbatim_snippet="any",
    )
    with pytest.raises(ProvenanceViolationError, match="exceeds document length"):
        validator.validate_coordinate(corrupt)


# ==============================================================================
# 2. Page and Sentence Identifiers
# ==============================================================================


def test_coordinate_page_number_bounds(valid_coord: EvidenceCoordinate) -> None:
    """Page number < 1 or exceeding max_pages triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    validator.register_document(
        valid_coord.document_id,
        "dummy text",
        valid_coord.document_sha256,
        total_pages=3,
    )

    # Page number exceeding total_pages
    corrupt_high = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=4,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    with pytest.raises(ProvenanceViolationError, match="exceeds document max_pages"):
        validator.validate_coordinate(corrupt_high)


def test_coordinate_sentence_and_paragraph_indices(valid_coord: EvidenceCoordinate) -> None:
    """Negative sentence or paragraph indices trigger ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()

    # Negative paragraph index
    corrupt_para = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=-1,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    with pytest.raises(ProvenanceViolationError, match="paragraph_index must be >= 0"):
        validator.validate_coordinate(corrupt_para)

    # Negative sentence index
    corrupt_sent = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=-2,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    with pytest.raises(ProvenanceViolationError, match="sentence_index must be >= 0"):
        validator.validate_coordinate(corrupt_sent)


# ==============================================================================
# 3. Document Revision Identity
# ==============================================================================


def test_document_revision_identity(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """Coordinates audited against mismatched revisions trigger ProvenanceViolationError."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash, revision_id="v1.2.0")

    # Correct revision matches
    assert validator.validate_coordinate(valid_coord, expected_revision="v1.2.0") is True

    # Mismatched revision
    with pytest.raises(ProvenanceViolationError, match="document revision mismatch"):
        validator.validate_coordinate(valid_coord, expected_revision="v2.0.0")

    # Document has no registered revision
    validator_empty = EvidenceCoordinateValidator()
    with pytest.raises(ProvenanceViolationError, match="has no registered revision"):
        validator_empty.validate_coordinate(valid_coord, expected_revision="v1.0.0")


def test_coordinate_extraction_confidence_bounds(valid_coord: EvidenceCoordinate) -> None:
    """Extraction confidence outside [0.0, 1.0] triggers ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet=valid_coord.verbatim_snippet,
        extraction_confidence=0.5,
    )
    object.__setattr__(corrupt, "extraction_confidence", 1.5)
    with pytest.raises(ProvenanceViolationError, match="extraction_confidence must be between"):
        validator.validate_coordinate(corrupt)


def test_document_revision_drift_detection(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """When a document undergoes revision drift, coordinates from older revisions fail."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    # Register initially as v1
    validator.register_document(doc_id, text, doc_hash, revision_id="v1.0")
    assert validator.validate_coordinate(valid_coord) is True

    # Updated document revision with modified text and new hash
    new_text = "Revised: " + text
    new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    validator.register_document(doc_id, new_text, new_hash, revision_id="v2.0")

    # Old coordinate fails due to SHA-256 and text drift
    with pytest.raises(ProvenanceViolationError, match="document_sha256 mismatch"):
        validator.validate_coordinate(valid_coord)


# ==============================================================================
# 4. SHA-256 Format and Tampering Detection
# ==============================================================================


def test_coordinate_sha256_format_violation(valid_coord: EvidenceCoordinate) -> None:
    """Non-hex or wrong-length SHA-256 strings trigger ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()

    # Short hash
    short_hash = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256="abc123",
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    with pytest.raises(ProvenanceViolationError, match="invalid document_sha256 format"):
        validator.validate_coordinate(short_hash)

    # Upper-case or invalid hex characters
    invalid_chars = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256="Z" * 64,
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    with pytest.raises(ProvenanceViolationError, match="invalid document_sha256 format"):
        validator.validate_coordinate(invalid_chars)


def test_coordinate_verbatim_snippet_tampering(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """Altered snippet text triggers ProvenanceViolationError."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash)

    tampered_snippet = valid_coord.verbatim_snippet[:-1] + "X"
    corrupt = EvidenceCoordinate(
        coordinate_id=valid_coord.coordinate_id,
        document_id=valid_coord.document_id,
        document_sha256=valid_coord.document_sha256,
        page_number=valid_coord.page_number,
        section_identifier=valid_coord.section_identifier,
        paragraph_index=valid_coord.paragraph_index,
        sentence_index=valid_coord.sentence_index,
        char_start=valid_coord.char_start,
        char_end=valid_coord.char_end,
        verbatim_snippet=tampered_snippet,
    )
    with pytest.raises(ProvenanceViolationError, match="verbatim snippet mismatch"):
        validator.validate_coordinate(corrupt)


# ==============================================================================
# 5. Missing Provenance Rejection and Filtering
# ==============================================================================


def test_missing_provenance_candidate_rejection() -> None:
    """Retrieval candidates lacking coordinates trigger ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()
    cand_no_coord = RetrievalCandidate(
        candidate_id="cand-orphan-01",
        rank=1,
        score=0.95,
        channel=RetrievalChannel.LEXICAL,
        content="Important empirical result with no coordinate.",
        coordinates=[],
    )

    with pytest.raises(ProvenanceViolationError, match="lacks verified EvidenceCoordinate"):
        validator.validate_candidate(cand_no_coord, require_coordinates=True)


def test_validate_candidates_filtering(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """validate_candidates with fail_closed=False filters out corrupted candidates."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash)

    valid_cand = RetrievalCandidate(
        candidate_id="cand-valid",
        rank=1,
        score=0.88,
        channel=RetrievalChannel.LEXICAL,
        content=valid_coord.verbatim_snippet,
        coordinates=[valid_coord],
    )
    orphan_cand = RetrievalCandidate(
        candidate_id="cand-orphan",
        rank=2,
        score=0.92,
        channel=RetrievalChannel.DENSE,
        content="Unanchored claim.",
        coordinates=[],
    )

    # fail_closed=True raises
    with pytest.raises(ProvenanceViolationError):
        validator.validate_candidates([valid_cand, orphan_cand], fail_closed=True)

    # fail_closed=False returns only valid
    filtered = validator.validate_candidates([valid_cand, orphan_cand], fail_closed=False)
    assert len(filtered) == 1
    assert filtered[0].candidate_id == "cand-valid"


# ==============================================================================
# 6. Audit Trail Generation (ProvenanceAuditReport)
# ==============================================================================


def test_audit_candidates_structured_report(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """audit_candidates produces structured audit report with counts and details."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash)

    valid_cand = RetrievalCandidate(
        candidate_id="cand-1",
        rank=1,
        score=0.9,
        channel=RetrievalChannel.LEXICAL,
        content="content",
        coordinates=[valid_coord],
    )
    orphan_cand = RetrievalCandidate(
        candidate_id="cand-2",
        rank=2,
        score=0.8,
        channel=RetrievalChannel.DENSE,
        content="content",
        coordinates=[],
    )
    corrupted_coord = EvidenceCoordinate(
        coordinate_id="coord-bad",
        document_id=doc_id,
        document_sha256="badhash",
        page_number=1,
        section_identifier="sec",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="dummy",
    )
    corrupted_cand = RetrievalCandidate(
        candidate_id="cand-3",
        rank=3,
        score=0.7,
        channel=RetrievalChannel.GRAPH,
        content="content",
        coordinates=[corrupted_coord],
    )

    report: ProvenanceAuditReport = validator.audit_candidates(
        [valid_cand, orphan_cand, corrupted_cand]
    )
    assert report.total_candidates == 3
    assert report.verified_candidates == 1
    assert report.failed_candidates == 2
    assert report.is_clean is False
    assert len(report.violations) == 2

    # Check violation types
    v_types = {v.violation_type for v in report.violations}
    assert "MISSING_COORDINATES" in v_types
    assert "CORRUPTED_COORDINATE" in v_types


# ==============================================================================
# 7. End-to-End Multi-Channel Retrieval Preservation
# ==============================================================================


def test_end_to_end_coordinate_preservation_across_retrieval(
    synthetic_paper: tuple[str, str, str],
    valid_coord: EvidenceCoordinate,
) -> None:
    """End-to-end multi-channel retrieval preserves coordinates and verifies them."""
    doc_id, text, doc_hash = synthetic_paper
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_hash)

    # 1. Lexical adapter
    lexical_adapter = LexicalBM25Adapter()
    lexical_adapter.add_documents(
        [
            LexicalDocument(
                doc_id=doc_id,
                text=text,
                coordinates=[valid_coord],
            )
        ]
    )

    # 2. Dense adapter
    dense_adapter = DenseVectorAdapter()
    dense_adapter.add_items(
        [
            DenseVectorItem(
                item_id=doc_id,
                text=text,
                embedding=[0.5, 0.5],
                coordinates=[valid_coord],
            )
        ]
    )

    # 3. Graph adapter
    graph = EvidenceGraph(graph_id="graph-042")
    doc_node = DocumentNode(
        doc_id=doc_id,
        title="Superconducting Transmon Qubits",
        publication_year=2024,
        document_sha256=doc_hash,
    )
    claim_node = ClaimNode(
        claim_id="claim-042",
        canonical_text=valid_coord.verbatim_snippet,
        provenance=[valid_coord],
        properties={"document_id": doc_id, "year": 2024},
    )
    graph.add_node(doc_node)
    graph.add_node(claim_node)
    graph.add_edge(
        EvidenceEdge(
            edge_id="e-claim-doc",
            source_id=doc_id,
            target_id="claim-042",
            edge_type=EdgeType.ASSERTS_CLAIM,
            is_inferred=False,
        )
    )
    graph_adapter = GraphRetrievalAdapter(graph=graph)

    engine = HybridRetrievalEngine(
        adapters={
            RetrievalChannel.LEXICAL: lexical_adapter,
            RetrievalChannel.DENSE: dense_adapter,
            RetrievalChannel.GRAPH: graph_adapter,
        },
        coordinate_validator=validator,
    )

    query = RetrievalQuery(
        text="transmon qubits",
        dense_vector=[0.5, 0.5],
        target_entities=["claim-042"],
        top_k=3,
        require_coordinates=True,
    )

    results = engine.retrieve(query)
    assert len(results) > 0
    for cand in results:
        # Every retrieved candidate has valid verified coordinates
        assert len(cand.coordinates) > 0
        for c in cand.coordinates:
            assert c.document_id == doc_id
            assert c.document_sha256 == doc_hash
            assert c.verbatim_snippet == valid_coord.verbatim_snippet
