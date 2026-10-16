"""Unit tests for evidence coordinate validation and fail-closed provenance across retrieval.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010 (Issue #61):
- Bitwise coordinate integrity verification against source text spans
- Provenance checksum auditing matching document SHA-256 hashes
- Fail-closed behavior (ProvenanceViolationError) on missing or invalid coordinates
- End-to-end coordinate preservation from document through graph and retrieval results
"""

import hashlib

import pytest

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.graph.schemas import (
    ClaimNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
)
from laris.retrieval import (
    EvidenceCoordinateValidator,
    GraphRetrievalAdapter,
    HybridRetrievalEngine,
    LexicalBM25Adapter,
    LexicalDocument,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


@pytest.fixture
def sample_raw_document() -> tuple[str, str, str]:
    """Provides a canonical document ID, raw text, and its verified SHA-256 hash."""
    doc_id = "doc-optomechanics-2024"
    text = (
        "Cavity optomechanics enables macroscopic quantum superposition through "
        "radiation pressure coupling between optical photons and mechanical resonators."
    )
    doc_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return doc_id, text, doc_sha256


@pytest.fixture
def valid_coordinate(sample_raw_document: tuple[str, str, str]) -> EvidenceCoordinate:
    """Provides an EvidenceCoordinate anchored to exact offsets in sample_raw_document."""
    doc_id, text, doc_sha256 = sample_raw_document
    snippet = "macroscopic quantum superposition"
    char_start = text.index(snippet)
    char_end = char_start + len(snippet)

    return EvidenceCoordinate(
        coordinate_id="coord-opto-001",
        document_id=doc_id,
        document_sha256=doc_sha256,
        page_number=1,
        section_identifier="sec-abstract",
        paragraph_index=0,
        sentence_index=0,
        char_start=char_start,
        char_end=char_end,
        verbatim_snippet=snippet,
        extraction_confidence=0.99,
    )


# ==============================================================================
# 1. Coordinate Field Invariants & Bitwise Integrity
# ==============================================================================


def test_validator_valid_coordinate(
    sample_raw_document: tuple[str, str, str],
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that a well-anchored coordinate passes validation."""
    doc_id, text, doc_sha256 = sample_raw_document
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_sha256)

    assert validator.validate_coordinate(valid_coordinate) is True


def test_validator_coordinate_field_violations() -> None:
    """Tests that missing or invalid coordinate fields trigger ProvenanceViolationError."""
    validator = EvidenceCoordinateValidator()

    # Empty coordinate_id (bypassing dataclass frozen with object.__setattr__ if needed,
    # or testing the validator's explicit guard)
    coord_empty_id = EvidenceCoordinate(
        coordinate_id="temp",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="hello",
    )
    object.__setattr__(coord_empty_id, "coordinate_id", "")
    with pytest.raises(ProvenanceViolationError, match="coordinate_id must not be empty"):
        validator.validate_coordinate(coord_empty_id)

    # Page number < 1
    coord_bad_page = EvidenceCoordinate(
        coordinate_id="c-page",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="hello",
    )
    object.__setattr__(coord_bad_page, "page_number", 0)
    with pytest.raises(ProvenanceViolationError, match="page_number must be >= 1"):
        validator.validate_coordinate(coord_bad_page)

    # Invalid char range
    coord_bad_range = EvidenceCoordinate(
        coordinate_id="c-range",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="hello",
    )
    object.__setattr__(coord_bad_range, "char_start", -1)
    with pytest.raises(ProvenanceViolationError, match="invalid character range"):
        validator.validate_coordinate(coord_bad_range)


    # Negative paragraph index
    coord_bad_para = EvidenceCoordinate(
        coordinate_id="c1",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=-1,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="hello",
    )
    with pytest.raises(ProvenanceViolationError, match="paragraph_index must be >= 0"):
        validator.validate_coordinate(coord_bad_para)

    # Negative sentence index
    coord_bad_sent = EvidenceCoordinate(
        coordinate_id="c2",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=-1,
        char_start=0,
        char_end=5,
        verbatim_snippet="hello",
    )
    with pytest.raises(ProvenanceViolationError, match="sentence_index must be >= 0"):
        validator.validate_coordinate(coord_bad_sent)

    # Empty verbatim snippet
    coord_empty_snip = EvidenceCoordinate(
        coordinate_id="c3",
        document_id="doc-1",
        document_sha256="hash",
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=5,
        verbatim_snippet="     ",
    )
    with pytest.raises(ProvenanceViolationError, match="verbatim_snippet must not be empty"):
        validator.validate_coordinate(coord_empty_snip)


def test_validator_checksum_and_span_mismatch(
    sample_raw_document: tuple[str, str, str],
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that checksum mismatches or character offset drift trigger fail-closed errors."""
    doc_id, text, doc_sha256 = sample_raw_document
    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_sha256)

    # Checksum mismatch
    with pytest.raises(ProvenanceViolationError, match="document_sha256 mismatch"):
        validator.validate_coordinate(valid_coordinate, expected_sha256="wrong_checksum")

    # Character end exceeding document length
    coord_overflow = EvidenceCoordinate(
        coordinate_id="c-overflow",
        document_id=doc_id,
        document_sha256=doc_sha256,
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=0,
        char_end=len(text) + 100,
        verbatim_snippet="overflow snippet",
    )
    with pytest.raises(ProvenanceViolationError, match="exceeds document length"):
        validator.validate_coordinate(coord_overflow)

    # Tampered verbatim snippet mismatch against physical text at offsets
    coord_tampered = EvidenceCoordinate(
        coordinate_id="c-tampered",
        document_id=doc_id,
        document_sha256=doc_sha256,
        page_number=1,
        section_identifier="sec-1",
        paragraph_index=0,
        sentence_index=0,
        char_start=valid_coordinate.char_start,
        char_end=valid_coordinate.char_end,
        verbatim_snippet="fabricated non-existent text",
    )
    with pytest.raises(ProvenanceViolationError, match="verbatim snippet mismatch at"):
        validator.validate_coordinate(coord_tampered)


# ==============================================================================
# 2. Candidate Provenance Auditing & Fail-Closed Semantics
# ==============================================================================


def test_validator_candidate_fail_closed(
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies fail-closed behavior when a candidate lacks verified coordinates."""
    validator = EvidenceCoordinateValidator()

    # Candidate with valid coordinate
    cand_valid = RetrievalCandidate(
        candidate_id="cand-01",
        content="Valid content",
        score=0.95,
        channel=RetrievalChannel.LEXICAL,
        rank=1,
        coordinates=[valid_coordinate],
    )
    assert validator.validate_candidate(cand_valid, require_coordinates=True) is True

    # Candidate without coordinate fails closed
    cand_unverified = RetrievalCandidate(
        candidate_id="cand-unverified",
        content="Unanchored speculative claim",
        score=0.80,
        channel=RetrievalChannel.HYBRID,
        rank=2,
        coordinates=[],
    )
    with pytest.raises(ProvenanceViolationError, match="lacks verified EvidenceCoordinate"):
        validator.validate_candidate(cand_unverified, require_coordinates=True)

    # When require_coordinates=False, candidate without coordinates is permitted
    assert validator.validate_candidate(cand_unverified, require_coordinates=False) is True


def test_validator_batch_validation_fail_closed_and_filtering(
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Tests validate_candidates under both strict fail-closed and filtering modes."""
    validator = EvidenceCoordinateValidator()

    cand1 = RetrievalCandidate(
        candidate_id="c1",
        content="Verified text 1",
        score=1.0,
        channel=RetrievalChannel.LEXICAL,
        rank=1,
        coordinates=[valid_coordinate],
    )
    cand2 = RetrievalCandidate(
        candidate_id="c2",
        content="Unanchored claim",
        score=0.5,
        channel=RetrievalChannel.DENSE,
        rank=2,
        coordinates=[],
    )

    # Fail closed mode: raises ProvenanceViolationError
    with pytest.raises(ProvenanceViolationError, match="lacks verified EvidenceCoordinate"):
        validator.validate_candidates([cand1, cand2], require_coordinates=True, fail_closed=True)

    # Filter mode: removes unverified candidate and returns only verified candidates
    surviving = validator.validate_candidates(
        [cand1, cand2],
        require_coordinates=True,
        fail_closed=False,
    )
    assert len(surviving) == 1
    assert surviving[0].candidate_id == "c1"


# ==============================================================================
# 3. End-to-End Document -> Graph -> Retrieval Coordinate Preservation
# ==============================================================================


def test_end_to_end_document_to_retrieval_provenance(
    sample_raw_document: tuple[str, str, str],
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies 100% bitwise coordinate preservation from ingestion to retrieval result."""
    doc_id, text, doc_sha256 = sample_raw_document

    # 1. Setup Layer 5 EvidenceGraph
    graph = EvidenceGraph(graph_id="e2e-provenance-graph")
    doc_node = DocumentNode(
        doc_id=doc_id,
        title="Cavity Optomechanics Superposition",
        publication_year=2024,
        document_sha256=doc_sha256,
    )
    claim_node = ClaimNode(
        claim_id="claim-opto-01",
        canonical_text="Cavity optomechanics enables macroscopic quantum superposition.",
        provenance=[valid_coordinate],
        properties={"document_id": doc_id, "year": 2024},
    )
    graph.add_node(doc_node)
    graph.add_node(claim_node)
    graph.add_edge(
        EvidenceEdge(
            edge_id="e-doc-claim-opto",
            source_id=doc_id,
            target_id="claim-opto-01",
            edge_type=EdgeType.ASSERTS_CLAIM,
            is_inferred=False,
        )
    )

    # 2. Setup Layer 6 Adapters and Engine
    lex_doc = LexicalDocument(
        doc_id=doc_id,
        text=text,
        metadata={"document_id": doc_id, "year": 2024},
        coordinates=[valid_coordinate],
    )
    lex_adapter = LexicalBM25Adapter()
    lex_adapter.add_documents([lex_doc])

    graph_adapter = GraphRetrievalAdapter(graph=graph)

    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_sha256)

    engine = HybridRetrievalEngine(coordinate_validator=validator)
    engine.register_adapter(lex_adapter)
    engine.register_adapter(graph_adapter)

    # 3. Execute retrieval requiring verified coordinates
    query = RetrievalQuery(
        text="macroscopic quantum superposition optomechanics",
        target_entities=["claim-opto-01"],
        top_k=5,
        max_depth=1,
        require_coordinates=True,
    )

    candidates = engine.retrieve(query)
    assert len(candidates) > 0

    # 4. Verify 100% of returned candidates have valid coordinates
    for cand in candidates:
        assert len(cand.coordinates) > 0
        for coord in cand.coordinates:
            assert coord.document_id == doc_id
            assert coord.document_sha256 == doc_sha256
            assert coord.page_number == 1
            assert coord.paragraph_index == 0
            assert coord.sentence_index == 0
            # Bitwise match against raw document text
            assert text[coord.char_start : coord.char_end] == coord.verbatim_snippet
            assert coord.verbatim_snippet == "macroscopic quantum superposition"


def test_retrieval_fails_closed_when_coordinate_tampered(
    sample_raw_document: tuple[str, str, str],
    valid_coordinate: EvidenceCoordinate,
) -> None:
    """Verifies that if any retrieved candidate has corrupted coordinates,
    retrieval fails closed.
    """
    doc_id, text, doc_sha256 = sample_raw_document


    # Create a corrupted coordinate (tampered snippet)
    corrupted_coord = EvidenceCoordinate(
        coordinate_id="coord-corrupted",
        document_id=doc_id,
        document_sha256=doc_sha256,
        page_number=1,
        section_identifier="sec-abstract",
        paragraph_index=0,
        sentence_index=0,
        char_start=valid_coordinate.char_start,
        char_end=valid_coordinate.char_end,
        verbatim_snippet="corrupted snippet text",
    )

    lex_doc = LexicalDocument(
        doc_id=doc_id,
        text=text,
        metadata={"document_id": doc_id},
        coordinates=[corrupted_coord],
    )
    lex_adapter = LexicalBM25Adapter()
    lex_adapter.add_documents([lex_doc])

    validator = EvidenceCoordinateValidator()
    validator.register_document(doc_id, text, doc_sha256)

    engine = HybridRetrievalEngine(coordinate_validator=validator)
    engine.register_adapter(lex_adapter)

    query = RetrievalQuery(
        text="quantum optomechanics",
        top_k=5,
        require_coordinates=True,
    )

    with pytest.raises(ProvenanceViolationError, match="verbatim snippet mismatch"):
        engine.retrieve(query)
