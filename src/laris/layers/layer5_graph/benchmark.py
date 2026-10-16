"""Benchmark suite for graph persistence, provenance preservation, and anti-conflation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.layers.layer5_graph.schemas import (
    ClaimNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
)
from laris.layers.layer5_graph.sqlite_adapter import SQLiteGraphPersistenceAdapter


@dataclass(frozen=True)
class ProvenancePreservationResult:
    """Evaluation metrics for coordinate roundtrip persistence and bitwise integrity."""
    total_nodes: int
    total_coordinates: int
    perfect_matches: int
    preservation_rate: float
    max_coord_discrepancy: float
    passed: bool


@dataclass(frozen=True)
class ConflationBenchmarkResult:
    """Evaluation metrics verifying separation of author assertions vs inferred edges."""
    total_asserted_edges: int
    total_inferred_edges: int
    conflated_count: int
    conflation_rate: float
    passed: bool


@dataclass(frozen=True)
class PersistenceLatencyResult:
    """Throughput and latency measurements for SQLite persistence operations."""
    node_count: int
    edge_count: int
    save_duration_ms: float
    load_duration_ms: float
    neighborhood_query_ms: float
    passed: bool


@dataclass
class GraphBenchmarkReport:
    """Combined benchmark report summarizing Evidence Graph persistence and integrity."""
    provenance_result: ProvenancePreservationResult
    conflation_result: ConflationBenchmarkResult
    latency_result: PersistenceLatencyResult
    overall_status: bool = True
    metadata: Dict[str, str] = field(default_factory=dict)


def _synthetic_coordinate(doc_idx: int, item_idx: int) -> EvidenceCoordinate:
    return EvidenceCoordinate(
        coordinate_id=f"coord-doc{doc_idx}-p{item_idx}",
        document_id=f"doc-{doc_idx}",
        document_sha256=f"sha{doc_idx:060d}",
        page_number=(item_idx % 10) + 1,
        section_identifier=f"sec_{(item_idx % 4) + 1}",
        paragraph_index=(item_idx % 5),
        sentence_index=(item_idx % 3),
        char_start=item_idx * 150,
        char_end=(item_idx * 150) + 75,
        verbatim_snippet=f"Synthetic verifiable scientific statement snippet {item_idx}.",
        extraction_confidence=0.99,
    )


class GraphProvenanceBenchmark:
    """Comprehensive benchmark runner auditing graph persistence, provenance, and invariants."""

    def __init__(self, adapter: Optional[SQLiteGraphPersistenceAdapter] = None) -> None:
        self.adapter = adapter or SQLiteGraphPersistenceAdapter(":memory:")

    def run_provenance_preservation(self, num_nodes: int = 100) -> ProvenancePreservationResult:
        """Verifies 100% bitwise coordinate preservation across SQLite save/load roundtrips."""
        graph = EvidenceGraph(graph_id="g-provenance-bench")
        doc = DocumentNode(doc_id="doc-bench-0", title="Benchmark Reference Paper")
        graph.add_node(doc)

        expected_coords: Dict[str, EvidenceCoordinate] = {}

        for i in range(1, num_nodes):
            coord = _synthetic_coordinate(0, i)
            expected_coords[f"claim-{i}"] = coord
            claim = ClaimNode(
                claim_id=f"claim-{i}",
                canonical_text=f"Benchmark empirical claim {i} with bandgap measurement.",
                epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
                confidence_score=0.95,
                provenance=[coord],
            )
            graph.add_node(claim)
            edge = EvidenceEdge(
                edge_id=f"e-assert-{i}",
                source_id="doc-bench-0",
                target_id=f"claim-{i}",
                edge_type=EdgeType.ASSERTS_CLAIM,
                is_inferred=False,
            )
            graph.add_edge(edge)

        self.adapter.save(graph)
        loaded = self.adapter.load("g-provenance-bench")

        matches = 0
        total_coords = len(expected_coords)
        max_discrepancy = 0.0

        for cid, expected in expected_coords.items():
            loaded_node = loaded.get_node(cid)
            if loaded_node and loaded_node.provenance:
                loaded_coord = loaded_node.provenance[0]
                if (
                    loaded_coord.coordinate_id == expected.coordinate_id
                    and loaded_coord.document_id == expected.document_id
                    and loaded_coord.char_start == expected.char_start
                    and loaded_coord.char_end == expected.char_end
                    and loaded_coord.verbatim_snippet == expected.verbatim_snippet
                ):
                    matches += 1
                diff = abs(loaded_coord.extraction_confidence - expected.extraction_confidence)
                if diff > max_discrepancy:
                    max_discrepancy = diff

        rate = (matches / total_coords) if total_coords > 0 else 1.0
        passed = (rate >= 1.0) and (max_discrepancy < 1e-6)

        return ProvenancePreservationResult(
            total_nodes=len(loaded.nodes),
            total_coordinates=total_coords,
            perfect_matches=matches,
            preservation_rate=rate,
            max_coord_discrepancy=max_discrepancy,
            passed=passed,
        )

    def run_anti_conflation_audit(
        self, num_asserted: int = 50, num_inferred: int = 50
    ) -> ConflationBenchmarkResult:
        """Audits that inferred relationships never conflate with author assertions."""
        graph = EvidenceGraph(graph_id="g-conflation-bench")
        doc = DocumentNode(doc_id="doc-bench-1", title="Conflation Audit Paper")
        graph.add_node(doc)

        claims: List[str] = []
        for i in range(num_asserted):
            cid = f"asserted-claim-{i}"
            claims.append(cid)
            graph.add_node(ClaimNode(claim_id=cid, canonical_text=f"Direct author claim {i}"))
            graph.add_edge(
                EvidenceEdge(
                    edge_id=f"e-assert-{i}",
                    source_id="doc-bench-1",
                    target_id=cid,
                    edge_type=EdgeType.ASSERTS_CLAIM,
                    is_inferred=False,
                )
            )

        for j in range(num_inferred):
            cid = f"inferred-claim-{j}"
            graph.add_node(
                ClaimNode(
                    claim_id=cid,
                    canonical_text=f"Model-inferred hypothesis {j}",
                    epistemic_status=EpistemicStatus.HYPOTHESIS,
                )
            )
            src = claims[j % len(claims)]
            coord = _synthetic_coordinate(1, j + 500)
            graph.add_edge(
                EvidenceEdge(
                    edge_id=f"e-inf-{j}",
                    source_id=src,
                    target_id=cid,
                    edge_type=EdgeType.SUPPORTS,
                    is_inferred=True,
                    inference_provenance=coord,
                    confidence_score=0.88,
                    properties={"model": "ThreeWayScientificNLIEngine"},
                )
            )

        self.adapter.save(graph)
        loaded = self.adapter.load("g-conflation-bench")

        author_edges = loaded.get_author_asserted_edges()
        inferred_edges = loaded.get_inferred_edges()

        conflated = 0
        for edge in author_edges:
            # An author asserted edge must not have is_inferred=True or model inference tags
            if edge.is_inferred:
                conflated += 1
            if "model" in edge.properties or edge.properties.get("inferred") is True:
                conflated += 1

        for edge in inferred_edges:
            # An inferred edge must have is_inferred=True
            if not edge.is_inferred:
                conflated += 1

        rate = conflated / (len(author_edges) + len(inferred_edges))
        passed = (
            conflated == 0
            and len(author_edges) == num_asserted
            and len(inferred_edges) == num_inferred
        )

        return ConflationBenchmarkResult(
            total_asserted_edges=len(author_edges),
            total_inferred_edges=len(inferred_edges),
            conflated_count=conflated,
            conflation_rate=rate,
            passed=passed,
        )

    def run_persistence_latency_benchmark(
        self, num_nodes: int = 150, num_edges: int = 200
    ) -> PersistenceLatencyResult:
        """Measures execution latency for SQLite save, load, and neighborhood traversal."""
        graph = EvidenceGraph(graph_id="g-latency-bench")
        doc = DocumentNode(doc_id="doc-latency-0", title="Latency Benchmark Paper")
        graph.add_node(doc)

        for i in range(1, num_nodes):
            graph.add_node(ClaimNode(claim_id=f"node-{i}", canonical_text=f"Claim text {i}"))

        for k in range(num_edges):
            src_idx = (k % (num_nodes - 1)) + 1
            tgt_idx = ((k * 3) % (num_nodes - 1)) + 1
            graph.add_edge(
                EvidenceEdge(
                    edge_id=f"e-lat-{k}",
                    source_id=f"node-{src_idx}",
                    target_id=f"node-{tgt_idx}",
                    edge_type=EdgeType.SUPPORTS if k % 2 == 0 else EdgeType.DERIVED_FROM,
                    is_inferred=False,
                )
            )

        # 1. Measure save
        t0 = time.perf_counter()
        self.adapter.save(graph)
        save_ms = (time.perf_counter() - t0) * 1000.0

        # 2. Measure load
        t1 = time.perf_counter()
        loaded = self.adapter.load("g-latency-bench")
        load_ms = (time.perf_counter() - t1) * 1000.0

        # 3. Measure neighborhood query
        t2 = time.perf_counter()
        subgraph = loaded.get_neighborhood(["node-1", "node-2"], max_depth=2)
        neigh_ms = (time.perf_counter() - t2) * 1000.0

        # Target budgets: save < 500ms, load < 200ms, neighborhood < 50ms
        passed = (
            save_ms < 500.0
            and load_ms < 200.0
            and neigh_ms < 50.0
            and len(subgraph.nodes) > 0
        )

        return PersistenceLatencyResult(
            node_count=len(loaded.nodes),
            edge_count=len(loaded.edges),
            save_duration_ms=save_ms,
            load_duration_ms=load_ms,
            neighborhood_query_ms=neigh_ms,
            passed=passed,
        )


    def run_full_benchmark_suite(self) -> GraphBenchmarkReport:
        """Executes all three benchmarks and returns a unified report."""
        prov = self.run_provenance_preservation(num_nodes=100)
        confl = self.run_anti_conflation_audit(num_asserted=50, num_inferred=50)
        lat = self.run_persistence_latency_benchmark(num_nodes=100, num_edges=150)

        overall = prov.passed and confl.passed and lat.passed
        return GraphBenchmarkReport(
            provenance_result=prov,
            conflation_result=confl,
            latency_result=lat,
            overall_status=overall,
            metadata={"adapter": "SQLiteGraphPersistenceAdapter", "backend": "sqlite3"},
        )
