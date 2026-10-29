"""Benchmark suite for multi-channel retrieval, ranking determinism, and depth limits.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, ADR-008, and ADR-010:
- Deterministic ranking evaluation across repeated trials and tie-breakers
- Metadata filter accuracy verification (0% filter leakage rate)
- Depth escalation bound enforcement ($N \\le 5$) preventing context explosion
- Graceful degradation and fallback behavior when dense backend is absent
- Comparative evaluation of multi-channel hybrid RRF against single-modality baselines
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from laris.core.errors import RetrievalDepthExceededError
from laris.core.schemas import EvidenceCoordinate
from laris.graph.schemas import (
    ClaimNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    MethodNode,
)
from laris.language.benchmarks.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.encoder.sentence_encoder import CompactSentenceEncoder
from laris.language.schemas import VocabularyContract
from laris.language.tokenization.tokenizer import ScientificTokenizer
from laris.retrieval.dense_adapter import (
    DenseVectorAdapter,
    DenseVectorItem,
)
from laris.retrieval.engine import HybridRetrievalEngine
from laris.retrieval.graph_adapter import GraphRetrievalAdapter
from laris.retrieval.lexical_adapter import (
    LexicalBM25Adapter,
    LexicalDocument,
)
from laris.retrieval.schemas import (
    MAX_RETRIEVAL_DEPTH,
    MetadataFilter,
    RetrievalChannel,
    RetrievalQuery,
)


@dataclass(frozen=True)
class RetrievalModalityResult:
    """Evaluation metrics for a specific retrieval channel or hybrid engine."""

    modality: str
    query_count: int
    mrr: float
    precision_at_1: float
    precision_at_3: float
    avg_latency_ms: float
    passed: bool


@dataclass(frozen=True)
class DeterministicRankingResult:
    """Evaluation metrics for ranking determinism across repeated executions."""

    total_trials: int
    identical_order_trials: int
    determinism_rate: float
    passed: bool


@dataclass(frozen=True)
class DepthBoundBenchmarkResult:
    """Evaluation metrics for traversal depth limit enforcement."""

    max_depth_tested: int
    depth_ceiling: int
    violations_detected: int
    graceful_rejections: int
    passed: bool


@dataclass(frozen=True)
class FilterAccuracyResult:
    """Evaluation metrics for metadata predicate filter precision."""

    total_filtered_queries: int
    filter_leakage_count: int
    filter_precision: float
    passed: bool


@dataclass(frozen=True)
class FallbackRobustnessResult:
    """Evaluation metrics for graceful degradation upon channel failure."""

    dense_backend_missing_handled: bool
    unregistered_channel_handled: bool
    passed: bool


@dataclass
class RetrievalBenchmarkReport:
    """Comprehensive evaluation report for Layer 6 Hybrid Retrieval."""

    modality_results: Dict[str, RetrievalModalityResult]
    determinism_result: DeterministicRankingResult
    depth_bound_result: DepthBoundBenchmarkResult
    filter_result: FilterAccuracyResult
    fallback_result: FallbackRobustnessResult
    overall_status: bool = True
    metadata: Dict[str, str] = field(default_factory=dict)


class RetrievalEvaluationBenchmark:
    """Standardized benchmark runner for Layer 6 retrieval components."""

    def __init__(self) -> None:
        # Initialize deterministic tokenizer and encoder
        tokens = get_stem_vocabulary_tokens()
        vocab_contract = VocabularyContract.create(sorted(set(tokens)))
        self.tokenizer = ScientificTokenizer(vocab=vocab_contract)
        self.encoder = CompactSentenceEncoder(
            tokenizer=self.tokenizer,
            embedding_dim=384,
            seed=42,
        )

    def build_synthetic_corpus(
        self,
    ) -> Tuple[
        List[LexicalDocument],
        List[DenseVectorItem],
        EvidenceGraph,
        List[EvidenceCoordinate],
    ]:
        """Constructs synthetic STEM multi-channel documents, vectors, and graph fixtures."""
        coords = [
            EvidenceCoordinate(
                coordinate_id="coord-phys-01",
                document_id="doc-phys-01",
                document_sha256="1" * 64,
                page_number=1,
                section_identifier="sec-1",
                paragraph_index=0,
                sentence_index=0,
                char_start=0,
                char_end=75,
                verbatim_snippet=(
                    "Quantum electrodynamics in cavity optomechanics demonstrates photon coupling."
                ),
            ),
            EvidenceCoordinate(
                coordinate_id="coord-chem-01",
                document_id="doc-chem-01",
                document_sha256="2" * 64,
                page_number=2,
                section_identifier="sec-2",
                paragraph_index=1,
                sentence_index=1,
                char_start=0,
                char_end=80,
                verbatim_snippet=(
                    "Zeolite catalyzed cracking of polyolefin oligomers yields high-octane fuels."
                ),
            ),
            EvidenceCoordinate(
                coordinate_id="coord-bio-01",
                document_id="doc-bio-01",
                document_sha256="3" * 64,
                page_number=3,
                section_identifier="sec-3",
                paragraph_index=0,
                sentence_index=0,
                char_start=0,
                char_end=72,
                verbatim_snippet=(
                    "CRISPR Cas9 ribonucleoprotein complexes mediate targeted endonuclease cuts."
                ),
            ),
            EvidenceCoordinate(
                coordinate_id="coord-cs-01",
                document_id="doc-cs-01",
                document_sha256="4" * 64,
                page_number=4,
                section_identifier="sec-4",
                paragraph_index=2,
                sentence_index=1,
                char_start=0,
                char_end=78,
                verbatim_snippet=(
                    "Graph convolutional message-passing networks compute equivariant embeddings."
                ),
            ),
            EvidenceCoordinate(
                coordinate_id="coord-math-01",
                document_id="doc-math-01",
                document_sha256="5" * 64,
                page_number=5,
                section_identifier="sec-5",
                paragraph_index=0,
                sentence_index=2,
                char_start=0,
                char_end=82,
                verbatim_snippet=(
                    "Cohomological operations on differentiable symplectic manifolds govern "
                    "invariants."
                ),
            ),

        ]

        lex_docs = [
            LexicalDocument(
                doc_id=c.document_id,
                text=c.verbatim_snippet,
                metadata={
                    "year": 2020 + idx,
                    "domain": ["physics", "chemistry", "biology", "cs", "math"][idx],
                    "is_inferred": False,
                },
                coordinates=[c],
            )
            for idx, c in enumerate(coords)
        ]

        dense_items = [
            DenseVectorItem(
                item_id=c.document_id,
                text=c.verbatim_snippet,
                metadata={
                    "year": 2020 + idx,
                    "domain": ["physics", "chemistry", "biology", "cs", "math"][idx],
                    "is_inferred": False,
                },
                coordinates=[c],
            )
            for idx, c in enumerate(coords)
        ]

        graph = EvidenceGraph(graph_id="benchmark-evidence-graph")
        for idx, c in enumerate(coords):
            doc_node = DocumentNode(
                doc_id=c.document_id,
                title=c.verbatim_snippet[:50],
                publication_year=2020 + idx,
                properties={"domain": ["physics", "chemistry", "biology", "cs", "math"][idx]},
            )
            claim_node = ClaimNode(
                claim_id=f"claim-{c.document_id}",
                canonical_text=c.verbatim_snippet,
                provenance=[c],
                properties={
                    "year": 2020 + idx,
                    "domain": ["physics", "chemistry", "biology", "cs", "math"][idx],
                    "document_id": c.document_id,
                },
            )
            method_node = MethodNode(
                method_id=f"method-{c.document_id}",
                name=f"Method for {c.document_id}",
                properties={"document_id": c.document_id},
            )
            graph.add_node(doc_node)
            graph.add_node(claim_node)
            graph.add_node(method_node)

            graph.add_edge(
                EvidenceEdge(
                    edge_id=f"e-doc-claim-{idx}",
                    source_id=c.document_id,
                    target_id=f"claim-{c.document_id}",
                    edge_type=EdgeType.ASSERTS_CLAIM,
                    is_inferred=False,
                )
            )
            graph.add_edge(
                EvidenceEdge(
                    edge_id=f"e-claim-method-{idx}",
                    source_id=f"claim-{c.document_id}",
                    target_id=f"method-{c.document_id}",
                    edge_type=EdgeType.USES_METHOD,
                    is_inferred=False,
                )
            )

        return lex_docs, dense_items, graph, coords

    def setup_engine(self) -> HybridRetrievalEngine:
        """Configures a populated HybridRetrievalEngine with lexical, dense, and graph adapters."""
        lex_docs, dense_items, graph, _ = self.build_synthetic_corpus()

        lex_adapter = LexicalBM25Adapter(tokenizer=self.tokenizer)
        lex_adapter.add_documents(lex_docs)

        dense_adapter = DenseVectorAdapter(encoder=self.encoder)
        dense_adapter.add_items(dense_items)

        graph_adapter = GraphRetrievalAdapter(graph=graph)

        engine = HybridRetrievalEngine()
        engine.register_adapter(lex_adapter)
        engine.register_adapter(dense_adapter)
        engine.register_adapter(graph_adapter)
        return engine

    def benchmark_modalities(
        self,
        engine: HybridRetrievalEngine,
    ) -> Dict[str, RetrievalModalityResult]:
        """Evaluates MRR, Precision, and latency across single-modality and hybrid channels."""
        queries = [
            ("cavity optomechanics photon coupling", "doc-phys-01"),
            ("zeolite catalyzed cracking polyolefin", "doc-chem-01"),
            ("crispr cas9 ribonucleoprotein endonuclease", "doc-bio-01"),
            ("graph convolutional message passing equivariant", "doc-cs-01"),
            ("cohomological operations symplectic manifolds", "doc-math-01"),
        ]

        results: Dict[str, RetrievalModalityResult] = {}
        modalities = [
            ("lexical", RetrievalChannel.LEXICAL),
            ("dense", RetrievalChannel.DENSE),
            ("graph", RetrievalChannel.GRAPH),
            ("hybrid", None),
        ]

        for mod_name, channel in modalities:
            reciprocal_ranks: List[float] = []
            p1_hits = 0
            p3_hits = 0
            latencies: List[float] = []

            for query_text, expected_doc in queries:
                q = RetrievalQuery(text=query_text, top_k=5)
                start_t = time.perf_counter()

                if channel is not None:
                    candidates = engine.retrieve_channel(channel, q)
                else:
                    candidates = engine.retrieve(q)

                elapsed_ms = (time.perf_counter() - start_t) * 1000.0
                latencies.append(elapsed_ms)

                rank_found = 0
                for r, cand in enumerate(candidates, start=1):
                    # For graph nodes, check candidate_id directly or document_id property
                    cand_doc = cand.metadata.get("document_id") or cand.candidate_id
                    if cand_doc == expected_doc or cand.candidate_id == expected_doc:
                        rank_found = r
                        break

                if rank_found > 0:
                    reciprocal_ranks.append(1.0 / float(rank_found))
                    if rank_found == 1:
                        p1_hits += 1
                    if rank_found <= 3:
                        p3_hits += 1
                else:
                    reciprocal_ranks.append(0.0)

            mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
            p1 = p1_hits / len(queries)
            p3 = p3_hits / len(queries)
            avg_lat = sum(latencies) / len(latencies)

            results[mod_name] = RetrievalModalityResult(
                modality=mod_name,
                query_count=len(queries),
                mrr=mrr,
                precision_at_1=p1,
                precision_at_3=p3,
                avg_latency_ms=avg_lat,
                passed=mrr >= 0.5,
            )

        return results

    def benchmark_ranking_determinism(
        self,
        engine: HybridRetrievalEngine,
        trials: int = 10,
    ) -> DeterministicRankingResult:
        """Verifies bitwise deterministic ranking across repeated query executions."""
        query = RetrievalQuery(text="optomechanics quantum electrodynamics", top_k=5)
        reference_order: Optional[List[str]] = None
        identical_trials = 0

        for _ in range(trials):
            results = engine.retrieve(query)
            order = [c.candidate_id for c in results]
            if reference_order is None:
                reference_order = order
                identical_trials += 1
            elif order == reference_order:
                identical_trials += 1

        determinism_rate = identical_trials / trials
        return DeterministicRankingResult(
            total_trials=trials,
            identical_order_trials=identical_trials,
            determinism_rate=determinism_rate,
            passed=determinism_rate == 1.0,
        )

    def benchmark_depth_bounds(
        self,
        engine: HybridRetrievalEngine,
    ) -> DepthBoundBenchmarkResult:
        """Verifies graph traversal depth limit and graceful rejection of runaway depths."""
        violations = 0
        rejections = 0

        # Valid depths 1 through 5 must succeed
        for d in range(1, MAX_RETRIEVAL_DEPTH + 1):
            q = RetrievalQuery(text="optomechanics", max_depth=d, top_k=5)
            try:
                candidates = engine.retrieve_channel(RetrievalChannel.GRAPH, q)
                assert isinstance(candidates, list)
            except Exception:
                violations += 1

        # Depths > MAX_RETRIEVAL_DEPTH must be rejected
        for d in [MAX_RETRIEVAL_DEPTH + 1, MAX_RETRIEVAL_DEPTH + 5]:
            try:
                RetrievalQuery(text="optomechanics", max_depth=d)
                violations += 1
            except RetrievalDepthExceededError:
                rejections += 1

        passed = violations == 0 and rejections == 2
        return DepthBoundBenchmarkResult(
            max_depth_tested=MAX_RETRIEVAL_DEPTH + 5,
            depth_ceiling=MAX_RETRIEVAL_DEPTH,
            violations_detected=violations,
            graceful_rejections=rejections,
            passed=passed,
        )

    def benchmark_filter_accuracy(
        self,
        engine: HybridRetrievalEngine,
    ) -> FilterAccuracyResult:
        """Verifies 100% metadata filter compliance with 0% filter leakage."""
        queries_with_filters = [
            (
                RetrievalQuery(
                    text="quantum",
                    filter=MetadataFilter(min_year=2023),
                    top_k=5,
                ),
                lambda meta: meta.get("year", 0) >= 2023,
            ),
            (
                RetrievalQuery(
                    text="zeolite",
                    filter=MetadataFilter(custom_attributes={"domain": "chemistry"}),
                    top_k=5,
                ),
                lambda meta: meta.get("domain") == "chemistry",
            ),
            (
                RetrievalQuery(
                    text="complex",
                    filter=MetadataFilter(document_ids=["doc-bio-01"]),
                    top_k=5,
                ),
                lambda meta: (meta.get("document_id") or meta.get("node_id")) == "doc-bio-01",
            ),
        ]

        leakage_count = 0
        for q, predicate in queries_with_filters:
            candidates = engine.retrieve(q)
            for c in candidates:
                if not predicate(c.metadata):
                    leakage_count += 1

        precision = 1.0 if leakage_count == 0 else 0.0
        return FilterAccuracyResult(
            total_filtered_queries=len(queries_with_filters),
            filter_leakage_count=leakage_count,
            filter_precision=precision,
            passed=leakage_count == 0,
        )

    def benchmark_fallback_robustness(self) -> FallbackRobustnessResult:
        """Verifies graceful degradation when dense backend or channels fail."""
        lex_docs, _, graph, _ = self.build_synthetic_corpus()

        # Engine configured with lexical and graph, and a dense adapter that has no encoder
        lex_adapter = LexicalBM25Adapter(tokenizer=self.tokenizer)
        lex_adapter.add_documents(lex_docs)

        dense_adapter = DenseVectorAdapter(expected_dim=2)  # No encoder configured
        dense_adapter.add_items(
            [DenseVectorItem(item_id="dummy-1", text="dummy text", embedding=[0.1, 0.2])]
        )
        graph_adapter = GraphRetrievalAdapter(graph=graph)


        engine = HybridRetrievalEngine()
        engine.register_adapter(lex_adapter)
        engine.register_adapter(dense_adapter)
        engine.register_adapter(graph_adapter)

        query = RetrievalQuery(text="quantum electrodynamics cavity", top_k=5)

        # Strict mode: retrieve without fallback raises ModuleContractViolationError
        dense_error_raised = False
        try:
            engine.retrieve(query, fallback_on_channel_failure=False)
        except Exception:
            dense_error_raised = True

        # Fallback mode: retrieve with fallback gracefully survives and returns
        # lexical and graph candidates
        fallback_candidates = engine.retrieve(query, fallback_on_channel_failure=True)

        dense_handled = dense_error_raised and len(fallback_candidates) > 0

        # Unregistered channel handled
        engine.unregister_adapter(RetrievalChannel.GRAPH)
        unreg_handled = not engine.has_adapter(RetrievalChannel.GRAPH)

        passed = dense_handled and unreg_handled
        return FallbackRobustnessResult(
            dense_backend_missing_handled=dense_handled,
            unregistered_channel_handled=unreg_handled,
            passed=passed,
        )

    def run_all(self) -> RetrievalBenchmarkReport:
        """Executes full benchmark suite and returns consolidated report."""
        engine = self.setup_engine()
        modality_results = self.benchmark_modalities(engine)
        determinism = self.benchmark_ranking_determinism(engine)
        depth_bounds = self.benchmark_depth_bounds(engine)
        filter_acc = self.benchmark_filter_accuracy(engine)
        fallback = self.benchmark_fallback_robustness()

        overall = (
            all(m.passed for m in modality_results.values())
            and determinism.passed
            and depth_bounds.passed
            and filter_acc.passed
            and fallback.passed
        )

        return RetrievalBenchmarkReport(
            modality_results=modality_results,
            determinism_result=determinism,
            depth_bound_result=depth_bounds,
            filter_result=filter_acc,
            fallback_result=fallback,
            overall_status=overall,
            metadata={
                "benchmark_version": "1.0.0",
                "hardware_target": "RTX 5070 Ti / local-first",
            },
        )
