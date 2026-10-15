"""Unit and contract tests for SQLiteGraphPersistenceAdapter and GraphProvenanceBenchmark."""

import tempfile
import unittest
from pathlib import Path

from laris.core.errors import GraphIntegrityError
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.layers.layer5_graph import (
    AuthorNode,
    ClaimNode,
    DatasetNode,
    DocumentNode,
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    GraphProvenanceBenchmark,
    GraphSchemaMigrationRegistry,
    LimitationNode,
    MethodNode,
    MetricNode,
    ResultNode,
    SQLiteGraphPersistenceAdapter,
)


def _make_sample_coord(coord_id: str) -> EvidenceCoordinate:
    return EvidenceCoordinate(
        coordinate_id=coord_id,
        document_id="doc-xyz",
        document_sha256="c" * 64,
        page_number=4,
        section_identifier="sec-discussion",
        paragraph_index=1,
        sentence_index=2,
        char_start=200,
        char_end=310,
        verbatim_snippet="Perovskite efficiency degrades under moisture exposure.",
        extraction_confidence=0.97,
    )


class TestSQLiteGraphPersistenceAdapter(unittest.TestCase):
    """Test suite verifying SQLite persistence, transactions, and cascade deletions."""

    def setUp(self) -> None:
        self.registry = GraphSchemaMigrationRegistry()
        self.adapter = SQLiteGraphPersistenceAdapter(
            db_path=":memory:",
            migration_registry=self.registry,
        )
        self.graph = EvidenceGraph(
            graph_id="g-sqlite-01",
            schema_version="1.0.0",
            metadata={"domain": "Materials Science", "corpus_id": "stem-2024"},
        )
        self.coord = _make_sample_coord("coord-01")

        # Create nodes of various types
        self.doc = DocumentNode(doc_id="doc-01", title="Halide Perovskites")
        self.author = AuthorNode(author_id="auth-01", name="Dr. Scientist")
        self.claim1 = ClaimNode(
            claim_id="claim-01",
            canonical_text="Perovskite shows 25.2% PCE.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
            provenance=[self.coord],
        )
        self.claim2 = ClaimNode(
            claim_id="claim-02",
            canonical_text="Stability degraded at 85% RH.",
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING,
        )
        self.method = MethodNode(method_id="meth-01", name="Spin Coating")
        self.dataset = DatasetNode(dataset_id="data-01", name="Degradation-Benchmark")
        self.metric = MetricNode(metric_id="met-01", name="PCE", unit="%")
        self.result = ResultNode(result_id="res-01", metric_name="PCE", value=25.2, unit="%")
        self.lim = LimitationNode(
            limitation_id="lim-01", description="Limited to nitrogen glovebox"
        )


        for node in [
            self.doc, self.author, self.claim1, self.claim2, self.method,
            self.dataset, self.metric, self.result, self.lim
        ]:
            self.graph.add_node(node)

        # Create edges
        self.e1 = EvidenceEdge(
            edge_id="e1", source_id="doc-01", target_id="auth-01",
            edge_type=EdgeType.AUTHORED_BY, is_inferred=False
        )
        self.e2 = EvidenceEdge(
            edge_id="e2", source_id="doc-01", target_id="claim-01",
            edge_type=EdgeType.ASSERTS_CLAIM, is_inferred=False
        )
        self.e3 = EvidenceEdge(
            edge_id="e3", source_id="claim-01", target_id="claim-02",
            edge_type=EdgeType.SUPPORTS, is_inferred=True,
            inference_provenance=self.coord, confidence_score=0.93,
            epistemic_status=EpistemicStatus.EMPIRICALLY_SUPPORTED_FINDING
        )
        self.e4 = EvidenceEdge(
            edge_id="e4", source_id="claim-01", target_id="lim-01",
            edge_type=EdgeType.HAS_LIMITATION, is_inferred=False
        )

        for edge in [self.e1, self.e2, self.e3, self.e4]:
            self.graph.add_edge(edge)

    def test_save_and_load_roundtrip_integrity(self) -> None:
        self.adapter.save(self.graph)
        self.assertTrue(self.adapter.exists("g-sqlite-01"))
        self.assertEqual(self.adapter.list_graphs(), ["g-sqlite-01"])
        self.assertEqual(self.adapter.get_schema_version("g-sqlite-01"), "1.0.0")

        loaded = self.adapter.load("g-sqlite-01")
        self.assertEqual(loaded.graph_id, self.graph.graph_id)
        self.assertEqual(len(loaded.nodes), len(self.graph.nodes))
        self.assertEqual(len(loaded.edges), len(self.graph.edges))
        self.assertEqual(loaded.metadata["domain"], "Materials Science")

        # Verify claim provenance
        loaded_c1 = loaded.get_node("claim-01")
        self.assertIsNotNone(loaded_c1)
        self.assertEqual(len(loaded_c1.provenance), 1)
        self.assertEqual(loaded_c1.provenance[0].coordinate_id, "coord-01")
        self.assertEqual(loaded_c1.provenance[0].char_start, 200)

        # Verify inferred edge
        loaded_e3 = loaded.get_edge("e3")
        self.assertIsNotNone(loaded_e3)
        self.assertTrue(loaded_e3.is_inferred)
        self.assertEqual(loaded_e3.confidence_score, 0.93)
        self.assertIsNotNone(loaded_e3.inference_provenance)
        self.assertEqual(loaded_e3.inference_provenance.page_number, 4)

    def test_counts_and_deletion(self) -> None:
        self.adapter.save(self.graph)
        n_count, e_count = self.adapter.count_nodes_and_edges("g-sqlite-01")
        self.assertEqual(n_count, len(self.graph.nodes))
        self.assertEqual(e_count, len(self.graph.edges))

        deleted = self.adapter.delete("g-sqlite-01")
        self.assertTrue(deleted)
        self.assertFalse(self.adapter.exists("g-sqlite-01"))
        self.assertFalse(self.adapter.delete("g-sqlite-01"))
        self.assertEqual(self.adapter.list_graphs(), [])

    def test_error_paths_for_non_existent_graph(self) -> None:
        with self.assertRaises(KeyError):
            self.adapter.load("unknown-graph")

        with self.assertRaises(KeyError):
            self.adapter.get_schema_version("unknown-graph")

        with self.assertRaises(GraphIntegrityError):
            self.adapter.save("not-an-evidence-graph")  # type: ignore

    def test_schema_migration_in_sqlite(self) -> None:
        def migrate_v1_to_v2(data: dict) -> dict:
            data["metadata"]["upgraded"] = True
            return data

        self.registry.register_migration("1.0.0", "2.0.0", migrate_v1_to_v2)
        self.adapter.save(self.graph)

        # Same version returns graph without modification
        same = self.adapter.migrate("g-sqlite-01", "1.0.0")
        self.assertEqual(same.schema_version, "1.0.0")

        # Migrate to v2.0.0
        migrated = self.adapter.migrate("g-sqlite-01", "2.0.0")
        self.assertEqual(migrated.schema_version, "2.0.0")
        self.assertEqual(self.adapter.get_schema_version("g-sqlite-01"), "2.0.0")

        # Reload from scratch
        fresh_loaded = self.adapter.load("g-sqlite-01")
        self.assertEqual(fresh_loaded.schema_version, "2.0.0")
        self.assertTrue(fresh_loaded.metadata.get("upgraded"))

    def test_persistent_file_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "evidence_store.db"
            adapter_1 = SQLiteGraphPersistenceAdapter(db_path=db_file)
            adapter_1.save(self.graph)

            self.assertTrue(db_file.exists())
            self.assertGreater(db_file.stat().st_size, 0)

            # Re-open with new adapter instance from disk
            adapter_2 = SQLiteGraphPersistenceAdapter(db_path=db_file)
            self.assertTrue(adapter_2.exists("g-sqlite-01"))
            loaded = adapter_2.load("g-sqlite-01")
            self.assertEqual(len(loaded.nodes), len(self.graph.nodes))
            self.assertEqual(len(loaded.edges), len(self.graph.edges))

    def test_connection_rollback_and_helpers(self) -> None:
        from laris.layers.layer5_graph.sqlite_adapter import asdict_coord

        self.assertIsNone(asdict_coord(None))

        # Test rollback on memory connection
        with self.assertRaises(RuntimeError):
            with self.adapter._connect() as conn:
                conn.execute("CREATE TABLE test_rollback (id INT);")
                raise RuntimeError("Trigger rollback")

        # Test rollback on file connection
        with tempfile.TemporaryDirectory() as tmpdir:
            file_adapter = SQLiteGraphPersistenceAdapter(db_path=Path(tmpdir) / "test.db")
            with self.assertRaises(RuntimeError):
                with file_adapter._connect() as conn:
                    conn.execute("CREATE TABLE test_file_rb (id INT);")
                    raise RuntimeError("Trigger file rollback")

        # Test close
        self.adapter.close()
        self.assertIsNone(self.adapter._mem_conn)



class TestGraphProvenanceBenchmark(unittest.TestCase):
    """Test suite executing the provenance, conflation, and latency benchmark suite."""

    def setUp(self) -> None:
        self.benchmark = GraphProvenanceBenchmark()

    def test_provenance_preservation_benchmark(self) -> None:
        result = self.benchmark.run_provenance_preservation(num_nodes=40)
        self.assertTrue(result.passed)
        self.assertEqual(result.preservation_rate, 1.0)
        self.assertEqual(result.max_coord_discrepancy, 0.0)
        self.assertEqual(result.perfect_matches, result.total_coordinates)

    def test_anti_conflation_audit(self) -> None:
        result = self.benchmark.run_anti_conflation_audit(num_asserted=25, num_inferred=25)
        self.assertTrue(result.passed)
        self.assertEqual(result.conflated_count, 0)
        self.assertEqual(result.conflation_rate, 0.0)
        self.assertEqual(result.total_asserted_edges, 25)
        self.assertEqual(result.total_inferred_edges, 25)

    def test_persistence_latency_benchmark(self) -> None:
        result = self.benchmark.run_persistence_latency_benchmark(num_nodes=50, num_edges=60)
        self.assertTrue(result.passed)
        self.assertGreater(result.node_count, 0)
        self.assertGreater(result.edge_count, 0)
        self.assertLess(result.save_duration_ms, 500.0)
        self.assertLess(result.load_duration_ms, 200.0)

    def test_full_benchmark_suite_execution(self) -> None:
        report = self.benchmark.run_full_benchmark_suite()
        self.assertTrue(report.overall_status)
        self.assertTrue(report.provenance_result.passed)
        self.assertTrue(report.conflation_result.passed)
        self.assertTrue(report.latency_result.passed)
        self.assertEqual(report.metadata["adapter"], "SQLiteGraphPersistenceAdapter")


if __name__ == "__main__":
    unittest.main()
