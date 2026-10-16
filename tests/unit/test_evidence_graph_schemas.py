"""Unit and contract tests for versioned Evidence Graph schemas, nodes, edges,
and persistence interface.
"""

import unittest

from laris.core.errors import (
    GraphIntegrityError,
    InferredEdgeConflationError,
    SchemaMigrationError,
)
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.layers.layer5_graph import (
    AuthorNode,
    ClaimNode,
    DatasetNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    GraphQueryRequest,
    GraphQueryResult,
    GraphQueryType,
    GraphSchemaMigrationRegistry,
    InMemoryGraphPersistenceAdapter,
    LimitationNode,
    MethodNode,
    MetricNode,
    NodeType,
    ResultNode,
)


def _make_dummy_coordinate(coord_id: str = "coord-1") -> EvidenceCoordinate:
    return EvidenceCoordinate(
        coordinate_id=coord_id,
        document_id="doc-123",
        document_sha256="a" * 64,
        page_number=3,
        section_identifier="sec-results",
        paragraph_index=2,
        sentence_index=1,
        char_start=120,
        char_end=185,
        verbatim_snippet="The measured bandgap was found to be 1.42 eV under ambient conditions.",
        extraction_confidence=0.98,
    )


class TestEvidenceNodeSchemas(unittest.TestCase):
    """Test suite for EvidenceNode base and specialized subclass schemas."""

    def test_document_node_creation_and_attributes(self) -> None:
        doc = DocumentNode(
            doc_id="doc-001",
            title="Transformer Architectures in STEM",
            authors=["Alice Smith", "Bob Jones"],
            doi="10.1000/182",
            publication_year=2024,
            document_sha256="b" * 64,
        )
        self.assertEqual(doc.node_id, "doc-001")
        self.assertEqual(doc.node_type, NodeType.DOCUMENT)
        self.assertEqual(doc.properties["title"], "Transformer Architectures in STEM")
        self.assertEqual(doc.properties["authors"], ["Alice Smith", "Bob Jones"])
        self.assertEqual(doc.properties["publication_year"], 2024)

    def test_author_node_creation(self) -> None:
        author = AuthorNode(
            author_id="author-01",
            name="Alice Smith",
            affiliations=["MIT Physics"],
            orcid="0000-0002-1825-0097",
        )
        self.assertEqual(author.node_id, "author-01")
        self.assertEqual(author.node_type, NodeType.AUTHOR)
        self.assertEqual(author.properties["affiliations"], ["MIT Physics"])

    def test_claim_node_validations(self) -> None:
        coord = _make_dummy_coordinate()
        claim = ClaimNode(
            claim_id="claim-001",
            canonical_text="GaAs exhibits direct bandgap of 1.42 eV.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
            confidence_score=0.95,
            provenance=[coord],
        )
        self.assertEqual(claim.node_type, NodeType.CLAIM)
        self.assertEqual(claim.properties["confidence_score"], 0.95)
        self.assertEqual(len(claim.provenance), 1)

        # Invalid confidence score
        with self.assertRaises(GraphIntegrityError):
            ClaimNode(
                claim_id="claim-err",
                canonical_text="Faulty confidence",
                confidence_score=1.5,
            )

    def test_method_dataset_metric_result_limitation_nodes(self) -> None:
        method = MethodNode(
            method_id="m-1",
            name="Photoluminescence Spectroscopy",
            category="SPECTROSCOPY",
        )
        self.assertEqual(method.node_type, NodeType.METHOD)

        dataset = DatasetNode(
            dataset_id="d-1",
            name="MaterialsProject-2024",
            domain="Materials Science",
        )
        self.assertEqual(dataset.node_type, NodeType.DATASET)

        metric = MetricNode(
            metric_id="met-1",
            name="Energy Bandgap",
            unit="eV",
            dimension="M^1 L^2 T^-2",
        )
        self.assertEqual(metric.node_type, NodeType.METRIC)

        result = ResultNode(
            result_id="res-1",
            metric_name="Energy Bandgap",
            value=1.424,
            uncertainty=0.005,
            unit="eV",
        )
        self.assertEqual(result.node_type, NodeType.RESULT)
        self.assertIn("1.424", result.label)

        limitation = LimitationNode(
            limitation_id="lim-1",
            description="Measurements limited to room temperature (300 K).",
            category="ENVIRONMENTAL",
            is_explicit=True,
        )
        self.assertEqual(limitation.node_type, NodeType.LIMITATION)


    def test_node_empty_id_raises_error(self) -> None:
        with self.assertRaises(GraphIntegrityError):
            EvidenceNode(node_id="", node_type=NodeType.DOCUMENT, label="Invalid")

    def test_node_serialization_roundtrip(self) -> None:
        coord = _make_dummy_coordinate()
        node = EvidenceNode(
            node_id="test-node-1",
            node_type=NodeType.METHOD,
            label="DFT B3LYP",
            properties={"basis_set": "6-31G*"},
            provenance=[coord],
        )
        d = node.to_dict()
        reconstructed = EvidenceNode.from_dict(d)
        self.assertEqual(reconstructed.node_id, node.node_id)
        self.assertEqual(reconstructed.node_type, NodeType.METHOD)
        self.assertEqual(reconstructed.properties["basis_set"], "6-31G*")
        self.assertEqual(len(reconstructed.provenance), 1)
        self.assertEqual(reconstructed.provenance[0].coordinate_id, coord.coordinate_id)


class TestEvidenceEdgeSchemas(unittest.TestCase):
    """Test suite for typed edge invariants and anti-conflation guardrails."""

    def test_author_asserted_edge_creation(self) -> None:
        edge = EvidenceEdge(
            edge_id="e-1",
            source_id="doc-001",
            target_id="claim-001",
            edge_type=EdgeType.ASSERTS_CLAIM,
            is_inferred=False,
            confidence_score=1.0,
        )
        self.assertFalse(edge.is_inferred)
        self.assertEqual(edge.edge_type, EdgeType.ASSERTS_CLAIM)

    def test_inferred_edge_creation_with_provenance(self) -> None:
        coord = _make_dummy_coordinate()
        edge = EvidenceEdge(
            edge_id="e-inf-1",
            source_id="claim-001",
            target_id="claim-002",
            edge_type=EdgeType.SUPPORTS,
            is_inferred=True,
            inference_provenance=coord,
            confidence_score=0.87,
            properties={"inferred_by": "ThreeWayScientificNLIEngine"},
        )
        self.assertTrue(edge.is_inferred)
        self.assertIsNotNone(edge.inference_provenance)
        self.assertEqual(edge.properties["inferred_by"], "ThreeWayScientificNLIEngine")

    def test_anti_conflation_guardrail(self) -> None:
        """Edge asserting is_inferred=False cannot carry inference marker properties."""
        with self.assertRaises(InferredEdgeConflationError):
            EvidenceEdge(
                edge_id="e-bad-1",
                source_id="claim-001",
                target_id="claim-002",
                edge_type=EdgeType.SUPPORTS,
                is_inferred=False,
                properties={"inferred_by": "Model-X"},
            )

        with self.assertRaises(InferredEdgeConflationError):
            EvidenceEdge(
                edge_id="e-bad-2",
                source_id="claim-001",
                target_id="claim-002",
                edge_type=EdgeType.SUPPORTS,
                is_inferred=False,
                properties={"inferred": True},
            )

    def test_edge_validation_errors(self) -> None:
        with self.assertRaises(GraphIntegrityError):
            EvidenceEdge(edge_id="", source_id="a", target_id="b", edge_type=EdgeType.SUPPORTS)
        with self.assertRaises(GraphIntegrityError):
            EvidenceEdge(edge_id="e1", source_id="", target_id="b", edge_type=EdgeType.SUPPORTS)
        with self.assertRaises(GraphIntegrityError):
            EvidenceEdge(edge_id="e1", source_id="a", target_id="", edge_type=EdgeType.SUPPORTS)
        with self.assertRaises(GraphIntegrityError):
            EvidenceEdge(
                edge_id="e1", source_id="a", target_id="b",
                edge_type=EdgeType.SUPPORTS, confidence_score=-0.1,
            )


    def test_edge_serialization_roundtrip(self) -> None:
        coord = _make_dummy_coordinate()
        edge = EvidenceEdge(
            edge_id="e-roundtrip",
            source_id="c-1",
            target_id="c-2",
            edge_type=EdgeType.CONTRADICTS,
            is_inferred=True,
            inference_provenance=coord,
            confidence_score=0.91,
            epistemic_status=EpistemicStatus.CONFLICTING_EVIDENCE,
            properties={"technique": "adversarial_audit"},
        )
        d = edge.to_dict()
        reconstructed = EvidenceEdge.from_dict(d)
        self.assertEqual(reconstructed.edge_id, edge.edge_id)
        self.assertEqual(reconstructed.edge_type, EdgeType.CONTRADICTS)
        self.assertTrue(reconstructed.is_inferred)
        self.assertIsNotNone(reconstructed.inference_provenance)
        self.assertEqual(reconstructed.epistemic_status, EpistemicStatus.CONFLICTING_EVIDENCE)


class TestEvidenceGraphContainer(unittest.TestCase):
    """Test suite for EvidenceGraph indexing, traversal, and integrity validation."""

    def setUp(self) -> None:
        self.graph = EvidenceGraph(graph_id="g-test-01")
        # Add sample nodes
        self.doc = DocumentNode(doc_id="doc-1", title="Paper 1")
        self.c1 = ClaimNode(claim_id="claim-1", canonical_text="Solar efficiency is 24.5%")
        self.c2 = ClaimNode(claim_id="claim-2", canonical_text="Solar efficiency is 18.2%")
        self.c3 = ClaimNode(claim_id="claim-3", canonical_text="Tandem cells achieve 29.1%")
        self.m1 = MethodNode(method_id="m-1", name="IV Curve Tracer")
        self.lim = LimitationNode(limitation_id="lim-1", description="Limited to 1-sun irradiance")

        for n in [self.doc, self.c1, self.c2, self.c3, self.m1, self.lim]:
            self.graph.add_node(n)

        # Add author asserted edges
        self.e1 = EvidenceEdge(
            edge_id="e-1", source_id="doc-1", target_id="claim-1",
            edge_type=EdgeType.ASSERTS_CLAIM, is_inferred=False
        )
        self.e2 = EvidenceEdge(
            edge_id="e-2", source_id="claim-1", target_id="m-1",
            edge_type=EdgeType.USES_METHOD, is_inferred=False
        )
        self.e3 = EvidenceEdge(
            edge_id="e-3", source_id="claim-1", target_id="lim-1",
            edge_type=EdgeType.HAS_LIMITATION, is_inferred=False
        )
        # Inferred edges
        self.e4 = EvidenceEdge(
            edge_id="e-4", source_id="claim-1", target_id="claim-2",
            edge_type=EdgeType.CONTRADICTS, is_inferred=True, confidence_score=0.92
        )
        self.e5 = EvidenceEdge(
            edge_id="e-5", source_id="claim-1", target_id="claim-3",
            edge_type=EdgeType.SUPPORTS, is_inferred=True, confidence_score=0.85
        )

        for e in [self.e1, self.e2, self.e3, self.e4, self.e5]:
            self.graph.add_edge(e)

    def test_referential_integrity_on_edge_addition(self) -> None:
        bad_edge = EvidenceEdge(
            edge_id="e-bad", source_id="non-existent", target_id="claim-1",
            edge_type=EdgeType.SUPPORTS, is_inferred=True
        )
        with self.assertRaises(GraphIntegrityError):
            self.graph.add_edge(bad_edge, validate_endpoints=True)

    def test_node_removal_cascades_to_incident_edges(self) -> None:
        self.assertIsNotNone(self.graph.get_node("m-1"))
        self.assertIsNotNone(self.graph.get_edge("e-2"))

        deleted = self.graph.remove_node("m-1")
        self.assertTrue(deleted)
        self.assertIsNone(self.graph.get_node("m-1"))
        self.assertIsNone(self.graph.get_edge("e-2"))
        self.assertNotIn("e-2", [e.edge_id for e in self.graph.get_outgoing_edges("claim-1")])

    def test_edge_filtering_and_separation(self) -> None:
        asserted = self.graph.get_author_asserted_edges()
        inferred = self.graph.get_inferred_edges()

        self.assertEqual(len(asserted), 3)
        self.assertEqual(len(inferred), 2)
        # Assert they are mutually exclusive
        asserted_ids = {e.edge_id for e in asserted}
        inferred_ids = {e.edge_id for e in inferred}
        self.assertTrue(asserted_ids.isdisjoint(inferred_ids))

    def test_neighborhood_subgraph_extraction(self) -> None:
        subgraph_1 = self.graph.get_neighborhood(["claim-1"], max_depth=1)
        # Depth 1 from claim-1 reaches: doc-1 (in), m-1 (out), lim-1 (out), claim-2/3 (out)
        self.assertIn("claim-1", subgraph_1.nodes)
        self.assertIn("m-1", subgraph_1.nodes)
        self.assertIn("claim-2", subgraph_1.nodes)
        self.assertEqual(len(subgraph_1.nodes), 6)

        subgraph_0 = self.graph.get_neighborhood(["claim-1"], max_depth=0)
        self.assertEqual(list(subgraph_0.nodes.keys()), ["claim-1"])

    def test_contradiction_path_finding(self) -> None:
        paths = self.graph.find_contradiction_paths("claim-1")
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0][0].edge_id, "e-4")
        self.assertEqual(paths[0][0].edge_type, EdgeType.CONTRADICTS)

    def test_json_serialization_roundtrip(self) -> None:
        json_repr = self.graph.to_json()
        reconstructed = EvidenceGraph.from_json(json_repr)

        self.assertEqual(reconstructed.graph_id, self.graph.graph_id)
        self.assertEqual(len(reconstructed.nodes), len(self.graph.nodes))
        self.assertEqual(len(reconstructed.edges), len(self.graph.edges))
        self.assertEqual(
            len(reconstructed.get_inferred_edges()),
            len(self.graph.get_inferred_edges()),
        )

    def test_validate_integrity_pass_and_fail(self) -> None:
        self.graph.validate_integrity()  # Should not raise

        # Manually inject invalid edge endpoint bypassing add_edge check
        corrupt_edge = EvidenceEdge(
            edge_id="e-corrupt", source_id="claim-1", target_id="missing-target",
            edge_type=EdgeType.SUPPORTS, is_inferred=True
        )
        self.graph.edges["e-corrupt"] = corrupt_edge
        with self.assertRaises(GraphIntegrityError):
            self.graph.validate_integrity()


class TestGraphQuerySchemas(unittest.TestCase):
    """Test suite for Boundary F query requests and outputs."""

    def test_graph_query_request_validation(self) -> None:
        req = GraphQueryRequest(
            query_type=GraphQueryType.NEIGHBORHOOD,
            target_entities=["claim-123"],
            max_depth=3,
        )
        self.assertEqual(req.query_type, GraphQueryType.NEIGHBORHOOD)
        self.assertEqual(req.max_depth, 3)

        with self.assertRaises(GraphIntegrityError):
            GraphQueryRequest(query_type=GraphQueryType.NEIGHBORHOOD, target_entities=[])

        with self.assertRaises(GraphIntegrityError):
            GraphQueryRequest(
                query_type=GraphQueryType.NEIGHBORHOOD, target_entities=["c1"], max_depth=0
            )

    def test_graph_query_result(self) -> None:
        node = ClaimNode(claim_id="c-1", canonical_text="text")
        edge = EvidenceEdge(
            edge_id="e-1", source_id="c-1", target_id="c-1",
            edge_type=EdgeType.DERIVED_FROM
        )
        coord = _make_dummy_coordinate()

        res = GraphQueryResult(
            subgraph_nodes=[node],
            typed_edges=[edge],
            provenance_records=[coord],
        )
        self.assertEqual(len(res.subgraph_nodes), 1)
        self.assertEqual(len(res.typed_edges), 1)
        self.assertEqual(len(res.provenance_records), 1)


class TestPersistenceAndMigration(unittest.TestCase):
    """Test suite for abstract persistence adapter and schema migration registry."""

    def setUp(self) -> None:
        self.registry = GraphSchemaMigrationRegistry()
        self.adapter = InMemoryGraphPersistenceAdapter(migration_registry=self.registry)
        self.graph = EvidenceGraph(graph_id="g-persisted", schema_version="1.0.0")
        self.graph.add_node(ClaimNode(claim_id="c-1", canonical_text="Empirical finding."))

    def test_persistence_adapter_lifecycle(self) -> None:
        self.assertFalse(self.adapter.exists("g-persisted"))
        self.adapter.save(self.graph)
        self.assertTrue(self.adapter.exists("g-persisted"))
        self.assertEqual(self.adapter.list_graphs(), ["g-persisted"])
        self.assertEqual(self.adapter.get_schema_version("g-persisted"), "1.0.0")

        loaded = self.adapter.load("g-persisted")
        self.assertEqual(loaded.graph_id, "g-persisted")
        self.assertIn("c-1", loaded.nodes)

        deleted = self.adapter.delete("g-persisted")
        self.assertTrue(deleted)
        self.assertFalse(self.adapter.exists("g-persisted"))
        self.assertFalse(self.adapter.delete("g-persisted"))

        with self.assertRaises(KeyError):
            self.adapter.load("non-existent")

        with self.assertRaises(KeyError):
            self.adapter.get_schema_version("non-existent")

        with self.assertRaises(KeyError):
            self.adapter.migrate("non-existent", "1.1.0")

        with self.assertRaises(GraphIntegrityError):
            self.adapter.save("not-a-graph")  # type: ignore

    def test_schema_migration_registry(self) -> None:
        # Register a migration from 1.0.0 to 1.1.0 that adds an audit field
        def migrate_1_0_to_1_1(data: dict) -> dict:
            data["metadata"]["migrated_audit"] = True
            return data

        self.registry.register_migration("1.0.0", "1.1.0", migrate_1_0_to_1_1)
        self.assertTrue(self.registry.has_migration("1.0.0", "1.1.0"))

        # Same version returns deepcopy without error
        same_ver = self.registry.migrate({"schema_version": "1.0.0"}, "1.0.0")
        self.assertEqual(same_ver["schema_version"], "1.0.0")

        self.adapter.save(self.graph)
        migrated_graph = self.adapter.migrate("g-persisted", "1.1.0")

        self.assertEqual(migrated_graph.schema_version, "1.1.0")
        self.assertEqual(self.adapter.get_schema_version("g-persisted"), "1.1.0")
        self.assertTrue(migrated_graph.metadata["migrated_audit"])

    def test_unregistered_migration_raises_schema_migration_error(self) -> None:
        self.adapter.save(self.graph)
        with self.assertRaises(SchemaMigrationError):
            self.adapter.migrate("g-persisted", "2.0.0")


class TestGraphCornerCases(unittest.TestCase):
    """Test suite covering corner cases and boundary error paths."""

    def test_node_type_coercion_and_errors(self) -> None:
        node = EvidenceNode(node_id="n-1", node_type="CLAIM", label="Text")  # type: ignore
        self.assertEqual(node.node_type, NodeType.CLAIM)

        with self.assertRaises(GraphIntegrityError):
            EvidenceNode(node_id="n-err", node_type="UNKNOWN_TYPE", label="Text")  # type: ignore

    def test_edge_type_coercion_and_errors(self) -> None:
        edge = EvidenceEdge(edge_id="e-coerced", source_id="s", target_id="t", edge_type="SUPPORTS")  # type: ignore
        self.assertEqual(edge.edge_type, EdgeType.SUPPORTS)

        with self.assertRaises(GraphIntegrityError):
            EvidenceEdge(edge_id="e-err", source_id="s", target_id="t", edge_type="NOT_AN_EDGE")  # type: ignore

    def test_graph_container_edge_cases(self) -> None:
        graph = EvidenceGraph(graph_id="g-corner")
        with self.assertRaises(GraphIntegrityError):
            EvidenceGraph(graph_id="")

        with self.assertRaises(GraphIntegrityError):
            graph.add_node("not-a-node")  # type: ignore

        self.assertFalse(graph.remove_node("missing-node"))

        with self.assertRaises(GraphIntegrityError):
            graph.add_edge("not-an-edge")  # type: ignore

        self.assertFalse(graph.remove_edge("missing-edge"))

        # Empty node outgoing / incoming edges
        self.assertEqual(graph.get_outgoing_edges("missing"), [])
        self.assertEqual(graph.get_incoming_edges("missing"), [])
        self.assertEqual(graph.get_neighbors("missing"), [])

        with self.assertRaises(GraphIntegrityError):
            graph.get_neighborhood(["missing"], max_depth=-1)

        self.assertEqual(graph.find_contradiction_paths("missing"), [])

    def test_graph_directions_and_contradiction_paths(self) -> None:
        graph = EvidenceGraph(graph_id="g-traversal")
        c1 = ClaimNode(claim_id="c1", canonical_text="Solar 1")
        c2 = ClaimNode(claim_id="c2", canonical_text="Solar 2")
        c3 = ClaimNode(claim_id="c3", canonical_text="Solar 3")
        graph.add_node(c1)
        graph.add_node(c2)
        graph.add_node(c3)

        e_supp = EvidenceEdge(
            edge_id="e-s", source_id="c1", target_id="c2", edge_type=EdgeType.SUPPORTS
        )
        e_contra = EvidenceEdge(
            edge_id="e-c", source_id="c2", target_id="c3", edge_type=EdgeType.CONTRADICTS
        )
        graph.add_edge(e_supp)
        graph.add_edge(e_contra)


        self.assertEqual(graph.get_neighbors("c1", direction="out"), ["c2"])
        self.assertEqual(graph.get_neighbors("c1", direction="in"), [])
        self.assertEqual(graph.get_neighbors("c2", direction="in"), ["c1"])
        self.assertEqual(graph.get_neighbors("c2", direction="out"), ["c3"])

        # 2-hop contradiction path from c1 -> c2 -> c3
        paths = graph.find_contradiction_paths("c1")
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(paths[0]), 2)
        self.assertEqual(paths[0][0].edge_id, "e-s")
        self.assertEqual(paths[0][1].edge_id, "e-c")

    def test_integrity_check_source_and_conflation(self) -> None:
        graph = EvidenceGraph(graph_id="g-integ")
        c1 = ClaimNode(claim_id="c1", canonical_text="Claim 1")
        graph.add_node(c1)

        # Source missing
        edge_bad_src = EvidenceEdge(
            edge_id="e-bad-src", source_id="missing-src", target_id="c1",
            edge_type=EdgeType.SUPPORTS, is_inferred=True
        )
        graph.edges["e-bad-src"] = edge_bad_src
        with self.assertRaises(GraphIntegrityError):
            graph.validate_integrity()

        graph.edges.pop("e-bad-src")

        # Conflation in validate_integrity (injected post-creation)
        conflated = EvidenceEdge(
            edge_id="e-conf", source_id="c1", target_id="c1",
            edge_type=EdgeType.DERIVED_FROM, is_inferred=False
        )
        conflated.properties["inferred_by"] = "Model"
        graph.edges["e-conf"] = conflated
        with self.assertRaises(InferredEdgeConflationError):
            graph.validate_integrity()


    def test_query_request_type_coercion_and_errors(self) -> None:
        req = GraphQueryRequest(query_type="METHOD_COMPARISON", target_entities=["m1"])  # type: ignore
        self.assertEqual(req.query_type, GraphQueryType.METHOD_COMPARISON)

        with self.assertRaises(GraphIntegrityError):
            GraphQueryRequest(query_type="INVALID_QUERY", target_entities=["m1"])  # type: ignore


class TestCompatibilityAlias(unittest.TestCase):
    """Test suite ensuring layer4_graph re-exports layer5_graph transparently."""

    def test_layer4_graph_imports(self) -> None:
        import laris.layers.layer4_graph as l4
        import laris.layers.layer5_graph as l5

        self.assertIs(l4.EvidenceGraph, l5.EvidenceGraph)
        self.assertIs(l4.NodeType, l5.NodeType)
        self.assertIs(l4.EdgeType, l5.EdgeType)
        self.assertIs(l4.InMemoryGraphPersistenceAdapter, l5.InMemoryGraphPersistenceAdapter)



if __name__ == "__main__":
    unittest.main()
