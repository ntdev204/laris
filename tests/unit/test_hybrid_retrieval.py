"""Comprehensive unit tests for Layer 6 Hybrid Retrieval engine, adapters, and RRF combiner."""

import pytest

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
    RetrievalDepthExceededError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.graph.interfaces import InMemoryGraphPersistenceAdapter
from laris.graph.schemas import (
    ClaimNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    MethodNode,
)
from laris.language.encoder import CompactSentenceEncoder
from laris.language.schemas import VocabularyContract
from laris.language.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.tokenizer import ScientificTokenizer
from laris.retrieval import (
    DEFAULT_RRF_K,
    MAX_RETRIEVAL_DEPTH,
    DenseVectorAdapter,
    DenseVectorItem,
    GraphRetrievalAdapter,
    HybridRetrievalEngine,
    LexicalBM25Adapter,
    LexicalDocument,
    MetadataFilter,
    ReciprocalRankFusion,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


@pytest.fixture
def sample_coordinate() -> EvidenceCoordinate:
    """Fixture providing a verified EvidenceCoordinate instance."""
    return EvidenceCoordinate(
        coordinate_id="coord-phys-001",
        document_id="doc-phys-01",
        document_sha256="a" * 64,
        page_number=3,
        section_identifier="sec-3.1",
        paragraph_index=2,
        sentence_index=4,
        char_start=120,
        char_end=200,
        verbatim_snippet="Quantum electrodynamics in cavity optomechanics demonstrates coupling.",
        extraction_confidence=0.98,
    )


@pytest.fixture
def stem_tokenizer() -> ScientificTokenizer:
    """Fixture providing a ScientificTokenizer initialized with STEM vocabulary."""
    tokens = get_stem_vocabulary_tokens()
    vocab_contract = VocabularyContract.create(sorted(set(tokens)))
    return ScientificTokenizer(vocab=vocab_contract)


@pytest.fixture
def stem_encoder(stem_tokenizer: ScientificTokenizer) -> CompactSentenceEncoder:
    """Fixture providing a deterministic CompactSentenceEncoder."""
    return CompactSentenceEncoder(
        tokenizer=stem_tokenizer,
        embedding_dim=384,
        seed=42,
    )


@pytest.fixture
def sample_graph(sample_coordinate: EvidenceCoordinate) -> EvidenceGraph:
    """Fixture providing an EvidenceGraph with typed nodes and edges."""
    graph = EvidenceGraph(graph_id="graph-stem-test")

    doc = DocumentNode(
        doc_id="doc-phys-01",
        title="Optomechanical cavity quantum electrodynamics",
        publication_year=2024,
    )
    claim1 = ClaimNode(
        claim_id="claim-01",
        canonical_text="Cavity optomechanics enables macroscopic quantum superposition.",
        provenance=[sample_coordinate],
        properties={"year": 2024, "document_id": "doc-phys-01"},
    )
    method1 = MethodNode(
        method_id="method-01",
        name="Cryogenic laser interferometry",
        properties={"year": 2024, "document_id": "doc-phys-01"},
    )


    graph.add_node(doc)
    graph.add_node(claim1)
    graph.add_node(method1)

    graph.add_edge(
        EvidenceEdge(
            edge_id="e-doc-claim",
            source_id="doc-phys-01",
            target_id="claim-01",
            edge_type=EdgeType.ASSERTS_CLAIM,
            is_inferred=False,
        )
    )
    graph.add_edge(
        EvidenceEdge(
            edge_id="e-claim-method",
            source_id="claim-01",
            target_id="method-01",
            edge_type=EdgeType.USES_METHOD,
            is_inferred=False,
        )
    )

    return graph


# ==============================================================================
# 1. MetadataFilter and Schemas Contract Tests
# ==============================================================================


def test_metadata_filter_validation() -> None:
    """Tests MetadataFilter argument validation."""
    with pytest.raises(ModuleContractViolationError, match="cannot be greater"):
        MetadataFilter(min_year=2025, max_year=2020)

    filt = MetadataFilter(min_year=2020, max_year=2025)
    assert filt.matches({"year": 2022})
    assert not filt.matches({"year": 2019})
    assert not filt.matches({"year": 2026})
    assert not filt.matches({})


def test_metadata_filter_criteria_matching() -> None:
    """Tests multi-criteria filtering across document_ids, node_types, and attributes."""
    filt = MetadataFilter(
        document_ids=["doc-01", "doc-02"],
        node_types=["claim", "method"],
        exclude_inferred=True,
        custom_attributes={"domain": "physics"},
    )

    matching_meta = {
        "document_id": "doc-01",
        "node_type": "CLAIM",
        "domain": "physics",
        "is_inferred": False,
    }
    assert filt.matches(matching_meta)

    # Inferred excluded
    inferred_meta = dict(matching_meta, is_inferred=True)
    assert not filt.matches(inferred_meta)

    # Disallowed document
    other_doc = dict(matching_meta, document_id="doc-99")
    assert not filt.matches(other_doc)

    # Disallowed node type
    other_node = dict(matching_meta, node_type="RESULT")
    assert not filt.matches(other_node)

    # Disallowed attribute
    other_domain = dict(matching_meta, domain="biology")
    assert not filt.matches(other_domain)


def test_retrieval_query_and_candidate_validation() -> None:
    """Tests contract validation on RetrievalQuery and RetrievalCandidate."""
    with pytest.raises(ModuleContractViolationError, match="must not be empty"):
        RetrievalQuery(text="")

    with pytest.raises(ModuleContractViolationError, match="top_k must be > 0"):
        RetrievalQuery(text="test query", top_k=0)

    with pytest.raises(ModuleContractViolationError, match="max_depth must be >= 1"):
        RetrievalQuery(text="test query", max_depth=0)

    with pytest.raises(RetrievalDepthExceededError, match="exceeds ceiling"):
        RetrievalQuery(text="test query", max_depth=MAX_RETRIEVAL_DEPTH + 1)

    with pytest.raises(ModuleContractViolationError, match="candidate_id must not be empty"):
        RetrievalCandidate(
            candidate_id="",
            content="text",
            score=1.0,
            channel=RetrievalChannel.LEXICAL,
            rank=1,
        )

    with pytest.raises(ModuleContractViolationError, match="rank must be >= 1"):
        RetrievalCandidate(
            candidate_id="cand-1",
            content="text",
            score=1.0,
            channel=RetrievalChannel.LEXICAL,
            rank=0,
        )


# ==============================================================================
# 2. LexicalBM25Adapter Unit Tests
# ==============================================================================


def test_lexical_adapter_empty_index() -> None:
    """Tests LexicalBM25Adapter handles empty index gracefully."""
    adapter = LexicalBM25Adapter()
    assert adapter.channel == RetrievalChannel.LEXICAL
    assert adapter.total_items == 0
    assert not adapter.has_item("doc-01")

    query = RetrievalQuery(text="quantum electrodynamics")
    results = adapter.retrieve(query)
    assert results == []


def test_lexical_adapter_input_validation() -> None:
    """Tests LexicalBM25Adapter parameter and document validation."""
    with pytest.raises(ModuleContractViolationError, match="k1 must be >= 0.0"):
        LexicalBM25Adapter(k1=-0.5)

    with pytest.raises(ModuleContractViolationError, match="b must be in"):
        LexicalBM25Adapter(b=1.5)

    with pytest.raises(ModuleContractViolationError, match="max_index_size"):
        LexicalBM25Adapter(max_index_size=0)

    adapter = LexicalBM25Adapter(max_index_size=10)
    with pytest.raises(ModuleContractViolationError, match="documents list must not be empty"):
        adapter.add_documents([])

    with pytest.raises(ModuleContractViolationError, match="doc_id must not be empty"):
        LexicalDocument(doc_id="", text="sample")

    with pytest.raises(ModuleContractViolationError, match="text must not be empty"):
        LexicalDocument(doc_id="d1", text="")

    with pytest.raises(ModuleContractViolationError, match="zero valid tokens"):
        adapter.add_documents([LexicalDocument(doc_id="d1", text="valid", tokens=[])])

    docs = [
        LexicalDocument(doc_id="d1", text="Quantum mechanics."),
        LexicalDocument(doc_id="d2", text="Classical physics."),
    ]
    adapter.add_documents(docs)

    # Test duplicate doc_id
    with pytest.raises(ModuleContractViolationError, match="Duplicate doc_id"):
        adapter.add_documents([LexicalDocument(doc_id="d1", text="Duplicate.")])

    # Test capacity overflow
    small_adapter = LexicalBM25Adapter(max_index_size=1)
    small_adapter.add_documents([LexicalDocument(doc_id="s1", text="Small.")])
    with pytest.raises(ModuleContractViolationError, match="maximum index capacity"):
        small_adapter.add_documents([LexicalDocument(doc_id="s2", text="Overflow.")])



def test_lexical_adapter_retrieval_ranking_and_coordinates(
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Tests exact term matching, score ordering, and coordinate retention in LexicalBM25Adapter."""
    adapter = LexicalBM25Adapter()
    docs = [
        LexicalDocument(
            doc_id="doc-optomechanics",
            text="Optomechanics and cavity quantum electrodynamics in photonics.",
            metadata={"domain": "physics", "year": 2024},
            coordinates=[sample_coordinate],
        ),
        LexicalDocument(
            doc_id="doc-polymer",
            text="Polymer crystallization kinetics under hydrostatic pressure.",
            metadata={"domain": "chemistry", "year": 2021},
        ),
        LexicalDocument(
            doc_id="doc-quantum-superposition",
            text="Quantum superposition of macroscopic optomechanical cantilevers.",
            metadata={"domain": "physics", "year": 2023},
        ),
    ]
    adapter.add_documents(docs)
    assert adapter.total_items == 3
    assert adapter.has_item("doc-optomechanics")

    # Query matching optomechanics
    query = RetrievalQuery(text="optomechanics quantum", top_k=5)
    candidates = adapter.retrieve(query)

    assert len(candidates) == 2
    assert candidates[0].rank == 1
    assert candidates[0].channel == RetrievalChannel.LEXICAL
    assert candidates[0].score > 0.0
    assert "optomechanics" in candidates[0].content.lower()

    # Check coordinate preservation
    opt_cand = next(c for c in candidates if c.candidate_id == "doc-optomechanics")
    assert len(opt_cand.coordinates) == 1
    assert opt_cand.coordinates[0].coordinate_id == "coord-phys-001"
    assert opt_cand.coordinates[0].page_number == 3

    # Test filtering by year
    query_filtered = RetrievalQuery(
        text="quantum optomechanics",
        top_k=5,
        filter=MetadataFilter(min_year=2024),
    )
    filtered_results = adapter.retrieve(query_filtered)
    assert len(filtered_results) == 1
    assert filtered_results[0].candidate_id == "doc-optomechanics"


# ==============================================================================
# 3. DenseVectorAdapter Unit Tests
# ==============================================================================


def test_dense_adapter_empty_index() -> None:
    """Tests DenseVectorAdapter on empty state."""
    adapter = DenseVectorAdapter()
    assert adapter.channel == RetrievalChannel.DENSE
    assert adapter.total_items == 0
    assert not adapter.has_item("item-1")

    query = RetrievalQuery(text="semantic query", dense_vector=[0.1, 0.2])
    assert adapter.retrieve(query) == []


def test_dense_adapter_dimension_mismatch_and_validation() -> None:
    """Tests DenseVectorAdapter dimension checks and item validation."""
    with pytest.raises(ModuleContractViolationError, match="item_id must not be empty"):
        DenseVectorItem(item_id="", text="text")

    with pytest.raises(ModuleContractViolationError, match="text must not be empty"):
        DenseVectorItem(item_id="i1", text="")

    adapter = DenseVectorAdapter(expected_dim=3)
    with pytest.raises(ModuleContractViolationError, match="items list must not be empty"):
        adapter.add_items([])

    with pytest.raises(EmbeddingDimensionMismatchError, match="does not match expected"):
        adapter.add_items(
            [DenseVectorItem(item_id="i1", text="text", embedding=[1.0, 0.0])]  # dim 2 != 3
        )

    adapter.add_items([DenseVectorItem(item_id="i1", text="text", embedding=[1.0, 0.0, 0.0])])

    with pytest.raises(ModuleContractViolationError, match="Duplicate item_id"):
        adapter.add_items([DenseVectorItem(item_id="i1", text="text", embedding=[0.0, 1.0, 0.0])])

    # Query dimension mismatch
    query_bad = RetrievalQuery(text="query", dense_vector=[1.0, 0.0])
    with pytest.raises(EmbeddingDimensionMismatchError, match="does not match expected"):
        adapter.retrieve(query_bad)


def test_dense_adapter_with_compact_encoder(
    stem_encoder: CompactSentenceEncoder,
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Tests DenseVectorAdapter computing representations via CompactSentenceEncoder."""
    adapter = DenseVectorAdapter(encoder=stem_encoder)
    assert adapter.expected_dim == 384

    items = [
        DenseVectorItem(
            item_id="passage-optomechanics",
            text="Optomechanical cavities enable quantum state preparation.",
            metadata={"domain": "physics", "year": 2024},
            coordinates=[sample_coordinate],
        ),
        DenseVectorItem(
            item_id="passage-genomics",
            text="Endonuclease enzyme cleavage sequences for DNA editing.",
            metadata={"domain": "biology", "year": 2022},
        ),
    ]
    adapter.add_items(items)
    assert adapter.total_items == 2

    # Query encoded on the fly
    query = RetrievalQuery(
        text="quantum optomechanical state",
        top_k=2,
    )
    results = adapter.retrieve(query)
    assert len(results) == 2
    assert results[0].candidate_id == "passage-optomechanics"
    assert results[0].channel == RetrievalChannel.DENSE
    assert results[0].coordinates[0].coordinate_id == "coord-phys-001"

    # Filter by domain
    query_filtered = RetrievalQuery(
        text="optomechanical",
        top_k=5,
        filter=MetadataFilter(custom_attributes={"domain": "biology"}),
    )
    bio_results = adapter.retrieve(query_filtered)
    assert len(bio_results) == 1
    assert bio_results[0].candidate_id == "passage-genomics"


# ==============================================================================
# 4. GraphRetrievalAdapter Unit Tests
# ==============================================================================


def test_graph_adapter_empty_graph() -> None:
    """Tests GraphRetrievalAdapter with empty graph."""
    adapter = GraphRetrievalAdapter()
    assert adapter.channel == RetrievalChannel.GRAPH
    assert adapter.total_items == 0

    query = RetrievalQuery(text="quantum claim")
    assert adapter.retrieve(query) == []


def test_graph_adapter_traversal_and_epistemic_filtering(
    sample_graph: EvidenceGraph,
) -> None:
    """Tests bounded BFS traversal, seed resolution, and epistemic filtering."""
    adapter = GraphRetrievalAdapter(graph=sample_graph)
    assert adapter.total_items == 3
    assert adapter.has_item("claim-01")

    # Retrieve with explicit seed entity
    query = RetrievalQuery(
        text="query about optomechanics",
        target_entities=["claim-01"],
        max_depth=1,
        top_k=10,
    )
    candidates = adapter.retrieve(query)

    # claim-01 (depth 0) and its neighbors doc-phys-01, method-01 (depth 1)
    cand_ids = {c.candidate_id for c in candidates}
    assert "claim-01" in cand_ids
    assert "doc-phys-01" in cand_ids
    assert "method-01" in cand_ids

    # claim-01 at depth 0 has higher score than depth 1 nodes
    claim_cand = next(c for c in candidates if c.candidate_id == "claim-01")
    other_cand = next(c for c in candidates if c.candidate_id == "method-01")
    assert claim_cand.score > other_cand.score
    assert len(claim_cand.coordinates) == 1

    # Text-based seed discovery (matching "optomechanical")
    text_query = RetrievalQuery(text="cryogenic laser interferometry", top_k=5, max_depth=1)
    text_cands = adapter.retrieve(text_query)
    assert any(c.candidate_id == "method-01" for c in text_cands)

    # Filter out all nodes except CLAIM
    claim_only_query = RetrievalQuery(
        text="superposition",
        target_entities=["claim-01"],
        max_depth=2,
        filter=MetadataFilter(node_types=["claim"]),
    )
    claim_results = adapter.retrieve(claim_only_query)
    assert len(claim_results) == 1
    assert claim_results[0].candidate_id == "claim-01"


def test_graph_adapter_persistence_loading(sample_graph: EvidenceGraph) -> None:
    """Tests GraphRetrievalAdapter initialization from persistence adapter."""
    persistence = InMemoryGraphPersistenceAdapter()
    persistence.save(sample_graph)

    adapter = GraphRetrievalAdapter(
        persistence_adapter=persistence,
        graph_id="graph-stem-test",
    )
    assert adapter.total_items == 3
    assert adapter.has_item("doc-phys-01")


def test_graph_adapter_depth_limit_enforcement(sample_graph: EvidenceGraph) -> None:
    """Tests GraphRetrievalAdapter enforces maximum depth limit."""
    adapter = GraphRetrievalAdapter(graph=sample_graph, max_allowed_depth=3)
    with pytest.raises(ModuleContractViolationError, match="max_allowed_depth must be >= 1"):
        GraphRetrievalAdapter(max_allowed_depth=0)

    query = RetrievalQuery(text="test", target_entities=["claim-01"], max_depth=4)
    with pytest.raises(RetrievalDepthExceededError, match="exceeds adapter limit"):
        adapter.retrieve(query)


# ==============================================================================
# 5. ReciprocalRankFusion Unit Tests
# ==============================================================================


def test_rrf_validation() -> None:
    """Tests ReciprocalRankFusion parameter validation."""
    with pytest.raises(ModuleContractViolationError, match="k must be > 0.0"):
        ReciprocalRankFusion(k=0.0)

    with pytest.raises(ModuleContractViolationError, match="weight.*must be >= 0.0"):
        ReciprocalRankFusion(weights={RetrievalChannel.LEXICAL: -1.0})

    rrf = ReciprocalRankFusion()
    assert rrf.k == DEFAULT_RRF_K
    with pytest.raises(ModuleContractViolationError, match="top_k must be > 0"):
        rrf.combine({}, top_k=0)



def test_rrf_fusion_arithmetic_and_tie_breaking(
    sample_coordinate: EvidenceCoordinate,
) -> None:
    """Tests mathematical correctness of RRF scoring and deterministic tie-breaking."""
    k = 60.0
    rrf = ReciprocalRankFusion(k=k)

    lex_cands = [
        RetrievalCandidate(
            candidate_id="cand-A",
            content="Alpha content",
            score=10.0,
            channel=RetrievalChannel.LEXICAL,
            rank=1,
            coordinates=[sample_coordinate],
        ),
        RetrievalCandidate(
            candidate_id="cand-B",
            content="Beta content",
            score=5.0,
            channel=RetrievalChannel.LEXICAL,
            rank=2,
        ),
    ]

    dense_cands = [
        RetrievalCandidate(
            candidate_id="cand-B",
            content="Beta content long",
            score=0.9,
            channel=RetrievalChannel.DENSE,
            rank=1,
        ),
        RetrievalCandidate(
            candidate_id="cand-A",
            content="Alpha content",
            score=0.8,
            channel=RetrievalChannel.DENSE,
            rank=2,
        ),
    ]

    # cand-A score: 1/(60+1) + 1/(60+2) = 1/61 + 1/62
    # cand-B score: 1/(60+2) + 1/(60+1) = 1/62 + 1/61
    # Scores are exactly equal! Tie breaker: candidate_id ascending ("cand-A" < "cand-B")
    channel_results = {
        RetrievalChannel.LEXICAL: lex_cands,
        RetrievalChannel.DENSE: dense_cands,
    }

    fused = rrf.combine(channel_results, top_k=5)
    assert len(fused) == 2
    assert fused[0].candidate_id == "cand-A"
    assert fused[1].candidate_id == "cand-B"
    assert fused[0].channel == RetrievalChannel.HYBRID

    expected_score = (1.0 / 61.0) + (1.0 / 62.0)
    assert abs(fused[0].score - expected_score) < 1e-9

    # Check coordinate retention from cand-A
    assert len(fused[0].coordinates) == 1
    assert fused[0].coordinates[0].coordinate_id == "coord-phys-001"
    assert "lexical" in fused[0].source_scores
    assert "dense" in fused[0].source_scores


# ==============================================================================
# 6. HybridRetrievalEngine Integration Tests
# ==============================================================================


def test_hybrid_engine_adapter_management() -> None:
    """Tests adapter registration, unregistration, and inspection in HybridRetrievalEngine."""
    engine = HybridRetrievalEngine()
    assert engine.registered_channels == []

    lex_adapter = LexicalBM25Adapter()
    engine.register_adapter(lex_adapter)

    assert engine.has_adapter(RetrievalChannel.LEXICAL)
    assert engine.registered_channels == [RetrievalChannel.LEXICAL]
    assert engine.get_adapter(RetrievalChannel.LEXICAL) is lex_adapter

    # Unregister
    assert engine.unregister_adapter(RetrievalChannel.LEXICAL)
    assert not engine.has_adapter(RetrievalChannel.LEXICAL)
    assert not engine.unregister_adapter(RetrievalChannel.LEXICAL)

    with pytest.raises(ModuleContractViolationError, match="instance of BaseRetrievalAdapter"):
        engine.register_adapter("not_an_adapter")  # type: ignore[arg-type]


def test_hybrid_engine_end_to_end_multi_channel(
    sample_coordinate: EvidenceCoordinate,
    stem_encoder: CompactSentenceEncoder,
    sample_graph: EvidenceGraph,
) -> None:
    """Tests end-to-end multi-channel retrieval across lexical, dense, and graph adapters."""
    # 1. Lexical Adapter
    lex_adapter = LexicalBM25Adapter()
    lex_adapter.add_documents(
        [
            LexicalDocument(
                doc_id="doc-phys-01",
                text="Quantum electrodynamics and cavity optomechanics.",
                metadata={"year": 2024},
                coordinates=[sample_coordinate],
            ),
            LexicalDocument(
                doc_id="doc-chem-01",
                text="Zeolite catalyzed polyolefin cracking.",
                metadata={"year": 2022},
            ),
        ]
    )

    # 2. Dense Adapter
    dense_adapter = DenseVectorAdapter(encoder=stem_encoder)
    dense_adapter.add_items(
        [
            DenseVectorItem(
                item_id="doc-phys-01",
                text="Quantum electrodynamics in optical microcavities.",
                metadata={"year": 2024},
                coordinates=[sample_coordinate],
            ),
            DenseVectorItem(
                item_id="doc-bio-01",
                text="CRISPR endonuclease targeted genomic cleavage.",
                metadata={"year": 2023},
            ),
        ]
    )

    # 3. Graph Adapter
    graph_adapter = GraphRetrievalAdapter(graph=sample_graph)

    # Setup Engine
    engine = HybridRetrievalEngine()
    engine.register_adapter(lex_adapter)
    engine.register_adapter(dense_adapter)
    engine.register_adapter(graph_adapter)

    assert set(engine.registered_channels) == {
        RetrievalChannel.LEXICAL,
        RetrievalChannel.DENSE,
        RetrievalChannel.GRAPH,
    }

    # Query across all 3 channels
    query = RetrievalQuery(
        text="quantum electrodynamics cavity optomechanics",
        target_entities=["claim-01"],
        top_k=5,
        max_depth=1,
    )

    fused_results = engine.retrieve(query)
    assert len(fused_results) > 0
    top_cand = fused_results[0]
    assert top_cand.channel == RetrievalChannel.HYBRID
    assert top_cand.rank == 1

    # Check single channel execution
    lex_only = engine.retrieve_channel(RetrievalChannel.LEXICAL, query)
    assert len(lex_only) > 0
    assert lex_only[0].channel == RetrievalChannel.LEXICAL

    # Query with channel subset
    dense_only_fused = engine.retrieve(query, channels=[RetrievalChannel.DENSE])
    assert len(dense_only_fused) > 0

    # Unregistered channel error
    engine.unregister_adapter(RetrievalChannel.GRAPH)
    with pytest.raises(ModuleContractViolationError, match="No adapter registered"):
        engine.retrieve_channel(RetrievalChannel.GRAPH, query)


def test_edge_cases_and_branch_coverage(
    stem_encoder: CompactSentenceEncoder,
    sample_graph: EvidenceGraph,
) -> None:
    """Tests edge cases across adapters, engine, and combiner to ensure high branch coverage."""
    # 1. DenseVectorAdapter zero-norm vector
    dense = DenseVectorAdapter()
    assert dense._normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]

    # DenseVectorAdapter dimension mismatch at init with encoder
    with pytest.raises(EmbeddingDimensionMismatchError, match="Specified expected_dim"):
        DenseVectorAdapter(encoder=stem_encoder, expected_dim=128)

    # DenseVectorAdapter item missing embedding and no encoder
    no_enc_adapter = DenseVectorAdapter()
    with pytest.raises(
        ModuleContractViolationError, match="lacks embedding and no sentence encoder"
    ):
        no_enc_adapter.add_items([DenseVectorItem(item_id="i1", text="text without emb")])


    # DenseVectorAdapter sets expected_dim from first item
    no_enc_adapter.add_items([DenseVectorItem(item_id="i1", text="text", embedding=[0.5, 0.5])])
    assert no_enc_adapter.expected_dim == 2

    # DenseVectorAdapter retrieve without dense_vector and no encoder
    with pytest.raises(ModuleContractViolationError, match="Query dense_vector missing"):
        no_enc_adapter.retrieve(RetrievalQuery(text="sample text"))

    # Dense filter rejection
    filtered_results = no_enc_adapter.retrieve(
        RetrievalQuery(
            text="sample text",
            dense_vector=[0.5, 0.5],
            filter=MetadataFilter(document_ids=["non-existent-doc"]),
        )
    )
    assert filtered_results == []

    # 2. Engine constructor with adapters dict
    lex_adapter = LexicalBM25Adapter()
    lex_adapter.add_documents(
        [
            LexicalDocument(
                doc_id="d-tok",
                text="Pretokenized text.",
                tokens=["pretokenized", "text"],
            )
        ]
    )
    engine = HybridRetrievalEngine(adapters={RetrievalChannel.LEXICAL: lex_adapter})
    assert engine.has_adapter(RetrievalChannel.LEXICAL)

    # Empty channels list returns []
    assert engine.retrieve(RetrievalQuery(text="test"), channels=[]) == []

    # Channels not registered returns []
    assert engine.retrieve(RetrievalQuery(text="test"), channels=[RetrievalChannel.DENSE]) == []

    # 3. RRF with channel weight 0.0
    rrf_zero = ReciprocalRankFusion(weights={RetrievalChannel.LEXICAL: 0.0})
    cand = RetrievalCandidate(
        candidate_id="c1",
        content="test",
        score=1.0,
        channel=RetrievalChannel.LEXICAL,
        rank=1,
    )
    fused_empty = rrf_zero.combine({RetrievalChannel.LEXICAL: [cand]}, top_k=5)
    assert fused_empty == []

    # 4. Graph adapter set_graph and seed resolution
    graph_adapter = GraphRetrievalAdapter()
    new_graph = EvidenceGraph(graph_id="new-graph")
    graph_adapter.set_graph(new_graph)
    assert graph_adapter.graph is new_graph

    # Punctuation only query in graph adapter
    graph_adapter.set_graph(sample_graph)
    assert graph_adapter.retrieve(RetrievalQuery(text="... ??? !!!")) == []

    # Unmatched query
    assert graph_adapter.retrieve(RetrievalQuery(text="completely unmatched query term")) == []

    # 5. MetadataFilter missing node_type and year matching
    filt_node = MetadataFilter(node_types=["claim"])
    assert not filt_node.matches({})
    assert not filt_node.matches({"node_type": None})

    filt_year = MetadataFilter(min_year=2020)
    assert not filt_year.matches({})
    filt_max_year = MetadataFilter(max_year=2020)
    assert not filt_max_year.matches({})

    # 6. Empty engine retrieve with default channels
    empty_engine = HybridRetrievalEngine()
    assert empty_engine.retrieve(RetrievalQuery(text="sample")) == []

    # 7. LexicalBM25Adapter with explicit ScientificTokenizer
    tokens = get_stem_vocabulary_tokens()
    tok = ScientificTokenizer(vocab=VocabularyContract.create(sorted(set(tokens))))
    lex_with_tok = LexicalBM25Adapter(tokenizer=tok)
    lex_with_tok.add_documents([LexicalDocument(doc_id="t1", text="Quantum optomechanics.")])
    res_tok = lex_with_tok.retrieve(RetrievalQuery(text="quantum optomechanics"))
    assert len(res_tok) == 1


