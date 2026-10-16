"""Unit tests for BM25RetrievalBaseline lexical search engine."""

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer1_language.bm25 import (
    BM25Document,
    BM25RetrievalBaseline,
)
from laris.layers.layer1_language.schemas import VocabularyContract
from laris.layers.layer1_language.stem_benchmark import get_stem_vocabulary_tokens
from laris.layers.layer1_language.tokenizer import ScientificTokenizer


@pytest.fixture
def stem_tokenizer() -> ScientificTokenizer:
    """Fixture providing a ScientificTokenizer initialized with STEM vocabulary."""
    tokens = get_stem_vocabulary_tokens()
    vocab_contract = VocabularyContract.create(sorted(set(tokens)))
    return ScientificTokenizer(vocab=vocab_contract)


@pytest.fixture
def sample_corpus() -> list[BM25Document]:
    """Provides a small corpus of STEM documents for BM25 testing."""
    return [
        BM25Document(
            doc_id="doc-phys-01",
            text="Quantum electrodynamics in cavity optomechanics demonstrates photon coupling.",
            tokens=["quantum", "electrodynamics", "cavity", "optomechanics", "photon", "coupling"],
            metadata={"domain": "physics"},
        ),
        BM25Document(
            doc_id="doc-chem-01",
            text=(
                "Zeolite catalyzed cracking of polyolefin oligomers yields "
                "high-octane hydrocarbons."
            ),
            tokens=["zeolite", "catalyzed", "cracking", "polyolefin", "oligomers", "hydrocarbons"],
            metadata={"domain": "chemistry"},
        ),
        BM25Document(
            doc_id="doc-bio-01",
            text="CRISPR Cas9 ribonucleoprotein complexes mediate targeted endonuclease cleavage.",
            tokens=["crispr", "cas9", "ribonucleoprotein", "endonuclease", "cleavage"],
            metadata={"domain": "biology"},
        ),
        BM25Document(
            doc_id="doc-cs-01",
            text=(
                "Graph convolutional message-passing networks compute "
                "equivariant representations."
            ),
            tokens=["graph", "convolutional", "message", "passing", "equivariant"],
            metadata={"domain": "computer_science"},
        ),
        BM25Document(
            doc_id="doc-math-01",
            text=(
                "Cohomological operations on differentiable symplectic manifolds "
                "characterize invariants."
            ),
            tokens=["cohomological", "symplectic", "manifolds", "topological", "invariants"],
            metadata={"domain": "mathematics"},
        ),
    ]


def test_bm25_index_and_search(
    sample_corpus: list[BM25Document],
    stem_tokenizer: ScientificTokenizer,
) -> None:
    """Verifies that indexing documents and searching returns accurately ranked results."""
    engine = BM25RetrievalBaseline(tokenizer=stem_tokenizer)
    assert engine.doc_count == 0

    engine.index_documents(sample_corpus)
    assert engine.doc_count == 5
    assert engine.has_document("doc-phys-01")
    assert not engine.has_document("non-existent-doc")

    # Search physics query
    results_phys = engine.search("quantum cavity optomechanics", top_k=3)
    assert len(results_phys) > 0
    assert results_phys[0].doc_id == "doc-phys-01"
    assert results_phys[0].rank == 1
    assert results_phys[0].score > 0.0

    # Search biology query
    results_bio = engine.search("CRISPR endonuclease cleavage", top_k=3)
    assert len(results_bio) > 0
    assert results_bio[0].doc_id == "doc-bio-01"

    # Search chemistry query
    results_chem = engine.search("zeolite cracking oligomers", top_k=3)
    assert len(results_chem) > 0
    assert results_chem[0].doc_id == "doc-chem-01"


def test_bm25_parameters_validation() -> None:
    """Verifies validation of BM25 hyperparameters."""
    with pytest.raises(ValueError, match="k1"):
        BM25RetrievalBaseline(k1=-0.5)

    with pytest.raises(ValueError, match="b"):
        BM25RetrievalBaseline(b=1.5)

    with pytest.raises(ValueError, match="b"):
        BM25RetrievalBaseline(b=-0.1)


def test_bm25_edge_cases(sample_corpus: list[BM25Document]) -> None:
    """Verifies edge cases: empty search query, search on empty index, duplicate doc_id."""
    engine = BM25RetrievalBaseline()

    # Search on empty index
    with pytest.raises(ModuleContractViolationError, match="empty BM25 index"):
        engine.search("quantum")

    # Index empty list
    with pytest.raises(ModuleContractViolationError, match="documents list must not be empty"):
        engine.index_documents([])

    engine.index_documents(sample_corpus)

    # Empty queries
    with pytest.raises(ModuleContractViolationError, match="query must not be empty"):
        engine.search("")

    with pytest.raises(ModuleContractViolationError, match="query must not be empty"):
        engine.search("   ")

    with pytest.raises(ValueError, match="top_k"):
        engine.search("quantum", top_k=0)

    # Duplicate doc_id indexing
    duplicate_doc = BM25Document("doc-phys-01", "Text", ["text"])
    with pytest.raises(ValueError, match="Duplicate doc_id"):
        engine.index_documents([duplicate_doc])

    # Query with no matching terms
    no_match = engine.search("astronomy telescope exoplanet")
    assert len(no_match) == 0


def test_bm25_document_invariants() -> None:
    """Verifies BM25Document validation."""
    with pytest.raises(ModuleContractViolationError, match="doc_id"):
        BM25Document(doc_id="", text="Text", tokens=["text"])

    with pytest.raises(ModuleContractViolationError, match="text"):
        BM25Document(doc_id="d1", text="", tokens=["text"])

    with pytest.raises(ModuleContractViolationError, match="tokens"):
        BM25Document(doc_id="d1", text="Text", tokens=[])
