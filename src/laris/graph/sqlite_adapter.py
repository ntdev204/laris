"""Embedded SQLite persistence adapter for EvidenceGraph (MOD-GRAPH-001 / ADR-009)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from laris.core.errors import GraphIntegrityError
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate
from laris.graph.interfaces import (
    BaseGraphPersistenceAdapter,
    GraphSchemaMigrationRegistry,
)
from laris.graph.schemas import (
    EdgeType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)


class SQLiteGraphPersistenceAdapter(BaseGraphPersistenceAdapter):
    """Embedded SQLite storage backend for the heterogeneous Evidence Graph.

    Guarantees local-first execution (ADR-001, ADR-009) with zero external
    service daemons, full ACID transaction semantics, and indexed edge queries.
    """

    def __init__(
        self,
        db_path: Union[str, Path] = ":memory:",
        migration_registry: Optional[GraphSchemaMigrationRegistry] = None,
    ) -> None:
        super().__init__(migration_registry=migration_registry)
        self.db_path = str(db_path)
        self._mem_conn: Optional[sqlite3.Connection] = (
            sqlite3.connect(":memory:") if self.db_path == ":memory:" else None
        )
        if self._mem_conn is not None:
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        self._init_db()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding SQLite connection with foreign keys enabled."""
        if self._mem_conn is not None:
            try:
                yield self._mem_conn
                self._mem_conn.commit()
            except Exception:
                self._mem_conn.rollback()
                raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def close(self) -> None:
        """Closes the underlying in-memory connection if active."""
        if self._mem_conn is not None:
            self._mem_conn.close()
            self._mem_conn = None


    def _init_db(self) -> None:
        """Initializes tables and indices for graph metadata, nodes, and edges."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS laris_graph_meta (
                    graph_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS laris_graph_nodes (
                    graph_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (graph_id, node_id),
                    FOREIGN KEY (graph_id) REFERENCES laris_graph_meta(graph_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS laris_graph_edges (
                    graph_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    is_inferred INTEGER NOT NULL,
                    inference_provenance_json TEXT,
                    confidence_score REAL NOT NULL,
                    epistemic_status TEXT,
                    properties_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (graph_id, edge_id),
                    FOREIGN KEY (graph_id) REFERENCES laris_graph_meta(graph_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_edges_source
                    ON laris_graph_edges (graph_id, source_id);
                CREATE INDEX IF NOT EXISTS idx_edges_target
                    ON laris_graph_edges (graph_id, target_id);
                CREATE INDEX IF NOT EXISTS idx_edges_type
                    ON laris_graph_edges (graph_id, edge_type);
                CREATE INDEX IF NOT EXISTS idx_edges_inferred
                    ON laris_graph_edges (graph_id, is_inferred);
                """
            )

    def save(self, graph: EvidenceGraph) -> None:
        """Persists EvidenceGraph transactionally into SQLite."""
        if not isinstance(graph, EvidenceGraph):
            raise GraphIntegrityError("Expected EvidenceGraph instance.")
        graph.validate_integrity()

        graph_dict = graph.to_dict()
        graph_id = graph.graph_id
        schema_version = graph.schema_version
        metadata_json = json.dumps(graph.metadata, sort_keys=True)
        timestamp = graph_dict.get("created_at") or graph.nodes.get(
            next(iter(graph.nodes), ""), EvidenceNode("dummy", NodeType.DOCUMENT, "")
        ).created_at

        with self._connect() as conn:
            # 1. Upsert graph metadata
            conn.execute(
                """
                INSERT INTO laris_graph_meta (
                    graph_id, schema_version, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(graph_id) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    metadata_json = excluded.metadata_json,
                    updated_at = datetime('now');
                """,
                (graph_id, schema_version, metadata_json, timestamp),
            )

            # 2. Clear existing nodes and edges for atomic replacement
            conn.execute("DELETE FROM laris_graph_nodes WHERE graph_id = ?;", (graph_id,))
            conn.execute("DELETE FROM laris_graph_edges WHERE graph_id = ?;", (graph_id,))

            # 3. Insert nodes
            node_rows = [
                (
                    graph_id,
                    node.node_id,
                    node.node_type.value,
                    node.label,
                    json.dumps(node.properties, sort_keys=True),
                    json.dumps([asdict_coord(p) for p in node.provenance], sort_keys=True),
                    node.created_at,
                )
                for node in graph.nodes.values()
            ]
            if node_rows:
                conn.executemany(
                    """
                    INSERT INTO laris_graph_nodes (
                        graph_id, node_id, node_type, label,
                        properties_json, provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    node_rows,
                )


            # 4. Insert edges
            edge_rows = [
                (
                    graph_id,
                    edge.edge_id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type.value,
                    1 if edge.is_inferred else 0,
                    json.dumps(asdict_coord(edge.inference_provenance))
                    if edge.inference_provenance
                    else None,
                    edge.confidence_score,
                    edge.epistemic_status.value if edge.epistemic_status else None,
                    json.dumps(edge.properties, sort_keys=True),
                    edge.created_at,
                )
                for edge in graph.edges.values()
            ]
            if edge_rows:
                conn.executemany(
                    """
                    INSERT INTO laris_graph_edges (
                        graph_id, edge_id, source_id, target_id, edge_type, is_inferred,
                        inference_provenance_json, confidence_score, epistemic_status,
                        properties_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    edge_rows,
                )

    def load(self, graph_id: str) -> EvidenceGraph:
        """Retrieves and reconstructs an EvidenceGraph from SQLite."""
        with self._connect() as conn:
            meta_row = conn.execute(
                "SELECT schema_version, metadata_json FROM laris_graph_meta WHERE graph_id = ?;",
                (graph_id,),
            ).fetchone()
            if not meta_row:
                raise KeyError(f"Graph '{graph_id}' does not exist in SQLite database.")

            schema_version, metadata_json = meta_row
            metadata = json.loads(metadata_json)

            graph = EvidenceGraph(
                graph_id=graph_id,
                schema_version=schema_version,
                metadata=metadata,
            )

            # Reconstruct nodes
            node_cursor = conn.execute(
                """
                SELECT node_id, node_type, label, properties_json, provenance_json, created_at
                FROM laris_graph_nodes WHERE graph_id = ?;
                """,
                (graph_id,),
            )
            for nid, ntype, label, props_json, prov_json, created_at in node_cursor:
                prov_list = json.loads(prov_json)
                provenance = [parse_coord_dict(p) for p in prov_list]
                node = EvidenceNode(
                    node_id=nid,
                    node_type=NodeType(ntype),
                    label=label,
                    properties=json.loads(props_json),
                    provenance=provenance,
                    created_at=created_at,
                )
                graph.add_node(node)

            # Reconstruct edges
            edge_cursor = conn.execute(
                """
                SELECT edge_id, source_id, target_id, edge_type, is_inferred,
                       inference_provenance_json, confidence_score, epistemic_status,
                       properties_json, created_at
                FROM laris_graph_edges WHERE graph_id = ?;
                """,
                (graph_id,),
            )
            for (
                eid,
                src,
                tgt,
                etype,
                is_inf,
                inf_prov_json,
                conf,
                epistemic,
                props_json,
                created_at,
            ) in edge_cursor:
                inf_coord = (
                    parse_coord_dict(json.loads(inf_prov_json)) if inf_prov_json else None
                )
                edge = EvidenceEdge(
                    edge_id=eid,
                    source_id=src,
                    target_id=tgt,
                    edge_type=EdgeType(etype),
                    is_inferred=bool(is_inf),
                    inference_provenance=inf_coord,
                    confidence_score=float(conf),
                    epistemic_status=EpistemicStatus(epistemic) if epistemic else None,
                    properties=json.loads(props_json),
                    created_at=created_at,
                )
                graph.add_edge(edge, validate_endpoints=False)

        return graph

    def exists(self, graph_id: str) -> bool:
        """Checks if a graph exists in the SQLite storage."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM laris_graph_meta WHERE graph_id = ? LIMIT 1;",
                (graph_id,),
            )
            return cursor.fetchone() is not None

    def delete(self, graph_id: str) -> bool:
        """Deletes a graph and all associated nodes and edges."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM laris_graph_meta WHERE graph_id = ?;",
                (graph_id,),
            )
            # Due to ON DELETE CASCADE, nodes and edges are deleted automatically
            return cursor.rowcount > 0

    def list_graphs(self) -> List[str]:
        """Lists all stored graph IDs in alphabetical order."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT graph_id FROM laris_graph_meta ORDER BY graph_id ASC;")
            return [row[0] for row in cursor.fetchall()]

    def get_schema_version(self, graph_id: str) -> str:
        """Retrieves the schema version recorded for a graph."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT schema_version FROM laris_graph_meta WHERE graph_id = ?;",
                (graph_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"Graph '{graph_id}' does not exist.")
            return str(row[0])

    def migrate(self, graph_id: str, target_version: str) -> EvidenceGraph:
        """Migrates a stored graph to target_version and saves the updated graph."""
        graph = self.load(graph_id)
        current_version = graph.schema_version
        if current_version == target_version:
            return graph

        graph_dict = graph.to_dict()
        migrated_dict = self.migration_registry.migrate(graph_dict, target_version)
        migrated_graph = EvidenceGraph.from_dict(migrated_dict)
        self.save(migrated_graph)
        return migrated_graph

    def count_nodes_and_edges(self, graph_id: str) -> Tuple[int, int]:
        """Returns (node_count, edge_count) for the specified graph."""
        with self._connect() as conn:
            n_count = conn.execute(
                "SELECT COUNT(*) FROM laris_graph_nodes WHERE graph_id = ?;",
                (graph_id,),
            ).fetchone()[0]
            e_count = conn.execute(
                "SELECT COUNT(*) FROM laris_graph_edges WHERE graph_id = ?;",
                (graph_id,),
            ).fetchone()[0]
            return int(n_count), int(e_count)


def asdict_coord(coord: Optional[EvidenceCoordinate]) -> Optional[Dict[str, Any]]:
    """Helper converting EvidenceCoordinate to dict."""
    if coord is None:
        return None
    return {
        "coordinate_id": coord.coordinate_id,
        "document_id": coord.document_id,
        "document_sha256": coord.document_sha256,
        "page_number": coord.page_number,
        "section_identifier": coord.section_identifier,
        "paragraph_index": coord.paragraph_index,
        "sentence_index": coord.sentence_index,
        "char_start": coord.char_start,
        "char_end": coord.char_end,
        "verbatim_snippet": coord.verbatim_snippet,
        "extraction_confidence": coord.extraction_confidence,
    }


def parse_coord_dict(d: Dict[str, Any]) -> EvidenceCoordinate:
    """Helper converting dict to EvidenceCoordinate."""
    return EvidenceCoordinate(
        coordinate_id=d["coordinate_id"],
        document_id=d["document_id"],
        document_sha256=d["document_sha256"],
        page_number=int(d["page_number"]),
        section_identifier=str(d["section_identifier"]),
        paragraph_index=int(d["paragraph_index"]),
        sentence_index=int(d["sentence_index"]),
        char_start=int(d["char_start"]),
        char_end=int(d["char_end"]),
        verbatim_snippet=str(d["verbatim_snippet"]),
        extraction_confidence=float(d.get("extraction_confidence", 1.0)),
    )
