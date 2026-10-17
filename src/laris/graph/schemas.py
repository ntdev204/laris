"""Evidence graph nodes, typed edges, and query schemas for MOD-GRAPH-001 (Layer 5)."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from laris.core.errors import (
    GraphIntegrityError,
    InferredEdgeConflationError,
)
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate


class NodeType(str, Enum):
    """Canonical node categories in the heterogeneous scientific evidence graph."""
    DOCUMENT = "DOCUMENT"
    AUTHOR = "AUTHOR"
    CLAIM = "CLAIM"
    METHOD = "METHOD"
    DATASET = "DATASET"
    METRIC = "METRIC"
    RESULT = "RESULT"
    LIMITATION = "LIMITATION"


class EdgeType(str, Enum):
    """Canonical typed edge relationships in the evidence graph."""
    AUTHORED_BY = "AUTHORED_BY"
    ASSERTS_CLAIM = "ASSERTS_CLAIM"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    EVALUATES_ON = "EVALUATES_ON"
    USES_METHOD = "USES_METHOD"
    MEASURES = "MEASURES"
    HAS_LIMITATION = "HAS_LIMITATION"
    DERIVED_FROM = "DERIVED_FROM"


def _current_timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class EvidenceNode:
    """Canonical base node in the heterogeneous evidence graph."""
    node_id: str
    node_type: NodeType
    label: str
    properties: Dict[str, Any] = field(default_factory=dict)
    provenance: List[EvidenceCoordinate] = field(default_factory=list)
    created_at: str = field(default_factory=_current_timestamp_iso)

    def __post_init__(self) -> None:
        if not self.node_id or not isinstance(self.node_id, str):
            raise GraphIntegrityError("EvidenceNode node_id must be a non-empty string.")
        if not isinstance(self.node_type, NodeType):
            try:
                self.node_type = NodeType(self.node_type)
            except ValueError as exc:
                raise GraphIntegrityError(f"Invalid NodeType: {self.node_type}") from exc
        if not self.created_at:
            self.created_at = _current_timestamp_iso()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes node to dictionary representation."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "label": self.label,
            "properties": dict(self.properties),
            "provenance": [asdict(p) for p in self.provenance],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceNode:
        """Instantiates EvidenceNode from serialized dictionary."""
        provenance = [
            EvidenceCoordinate(
                coordinate_id=coord["coordinate_id"],
                document_id=coord["document_id"],
                document_sha256=coord["document_sha256"],
                page_number=coord["page_number"],
                section_identifier=coord["section_identifier"],
                paragraph_index=coord["paragraph_index"],
                sentence_index=coord["sentence_index"],
                char_start=coord["char_start"],
                char_end=coord["char_end"],
                verbatim_snippet=coord["verbatim_snippet"],
                extraction_confidence=coord.get("extraction_confidence", 1.0),
            )
            for coord in data.get("provenance", [])
        ]
        return cls(
            node_id=data["node_id"],
            node_type=NodeType(data["node_type"]),
            label=data.get("label", data["node_id"]),
            properties=dict(data.get("properties", {})),
            provenance=provenance,
            created_at=data.get("created_at", _current_timestamp_iso()),
        )


@dataclass
class DocumentNode(EvidenceNode):
    """Document entity node representing a published paper or preprint."""
    def __init__(
        self,
        doc_id: str,
        title: str,
        authors: Optional[List[str]] = None,
        doi: str = "",
        publication_year: Optional[int] = None,
        document_sha256: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "title": title,
            "authors": authors or [],
            "doi": doi,
            "publication_year": publication_year,
            "document_sha256": document_sha256,
        })
        super().__init__(
            node_id=doc_id,
            node_type=NodeType.DOCUMENT,
            label=title,
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class AuthorNode(EvidenceNode):
    """Author entity node representing a scientific contributor."""
    def __init__(
        self,
        author_id: str,
        name: str,
        affiliations: Optional[List[str]] = None,
        orcid: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "name": name,
            "affiliations": affiliations or [],
            "orcid": orcid,
        })
        super().__init__(
            node_id=author_id,
            node_type=NodeType.AUTHOR,
            label=name,
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class ClaimNode(EvidenceNode):
    """Claim entity node representing an empirical or theoretical proposition."""
    def __init__(
        self,
        claim_id: str,
        canonical_text: str,
        epistemic_status: EpistemicStatus = EpistemicStatus.DIRECT_AUTHOR_CLAIM,
        confidence_score: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        if not (0.0 <= confidence_score <= 1.0):
            raise GraphIntegrityError("ClaimNode confidence_score must be between 0.0 and 1.0.")
        props = dict(properties or {})
        ep_val = (
            epistemic_status.value
            if isinstance(epistemic_status, EpistemicStatus)
            else epistemic_status
        )
        props.update({
            "canonical_text": canonical_text,
            "epistemic_status": ep_val,
            "confidence_score": confidence_score,
        })

        super().__init__(
            node_id=claim_id,
            node_type=NodeType.CLAIM,
            label=canonical_text[:80],
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class MethodNode(EvidenceNode):
    """Method entity node representing an experimental or computational technique."""
    def __init__(
        self,
        method_id: str,
        name: str,
        category: str = "EXPERIMENTAL",
        description: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "name": name,
            "category": category,
            "description": description,
        })
        super().__init__(
            node_id=method_id,
            node_type=NodeType.METHOD,
            label=name,
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class DatasetNode(EvidenceNode):
    """Dataset entity node representing an experimental corpus or benchmark."""
    def __init__(
        self,
        dataset_id: str,
        name: str,
        domain: str = "",
        license: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "name": name,
            "domain": domain,
            "license": license,
        })
        super().__init__(
            node_id=dataset_id,
            node_type=NodeType.DATASET,
            label=name,
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class MetricNode(EvidenceNode):
    """Metric entity node representing an evaluation dimension or physical quantity."""
    def __init__(
        self,
        metric_id: str,
        name: str,
        unit: str = "",
        dimension: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "name": name,
            "unit": unit,
            "dimension": dimension,
        })
        super().__init__(
            node_id=metric_id,
            node_type=NodeType.METRIC,
            label=name,
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class ResultNode(EvidenceNode):
    """Result entity node representing a measured quantitative experimental output."""
    def __init__(
        self,
        result_id: str,
        metric_name: str,
        value: float,
        uncertainty: Optional[float] = None,
        unit: str = "",
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "metric_name": metric_name,
            "value": value,
            "uncertainty": uncertainty,
            "unit": unit,
        })
        super().__init__(
            node_id=result_id,
            node_type=NodeType.RESULT,
            label=f"{metric_name} = {value} {unit}".strip(),
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class LimitationNode(EvidenceNode):
    """Limitation entity node representing an identified constraint, scope limit, or caveat."""
    def __init__(
        self,
        limitation_id: str,
        description: str,
        category: str = "METHODOLOGICAL",
        is_explicit: bool = True,
        properties: Optional[Dict[str, Any]] = None,
        provenance: Optional[List[EvidenceCoordinate]] = None,
        created_at: str = "",
    ) -> None:
        props = dict(properties or {})
        props.update({
            "description": description,
            "category": category,
            "is_explicit": is_explicit,
        })
        super().__init__(
            node_id=limitation_id,
            node_type=NodeType.LIMITATION,
            label=description[:80],
            properties=props,
            provenance=provenance or [],
            created_at=created_at or _current_timestamp_iso(),
        )


@dataclass
class EvidenceEdge:
    """Canonical typed relationship between two entities in the evidence graph.

    Mandatory Invariant (Boundary F / ADR-009):
    Inferred edges MUST have is_inferred=True and must never masquerade as
    direct author assertions.
    """
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    is_inferred: bool = False
    inference_provenance: Optional[EvidenceCoordinate] = None
    confidence_score: float = 1.0
    epistemic_status: Optional[EpistemicStatus] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_current_timestamp_iso)

    def __post_init__(self) -> None:
        if not self.edge_id or not isinstance(self.edge_id, str):
            raise GraphIntegrityError("EvidenceEdge edge_id must be a non-empty string.")
        if not self.source_id or not isinstance(self.source_id, str):
            raise GraphIntegrityError("EvidenceEdge source_id must be a non-empty string.")
        if not self.target_id or not isinstance(self.target_id, str):
            raise GraphIntegrityError("EvidenceEdge target_id must be a non-empty string.")
        if not isinstance(self.edge_type, EdgeType):
            try:
                self.edge_type = EdgeType(self.edge_type)
            except ValueError as exc:
                raise GraphIntegrityError(f"Invalid EdgeType: {self.edge_type}") from exc
        if not (0.0 <= self.confidence_score <= 1.0):
            raise GraphIntegrityError(
                f"confidence_score must be between 0.0 and 1.0, got {self.confidence_score}"
            )
        # Anti-conflation invariant:
        # If edge properties indicate inferred origins but is_inferred is False, reject.
        if not self.is_inferred:
            if self.properties.get("inferred") is True or "inferred_by" in self.properties:
                raise InferredEdgeConflationError(
                    "Edge has inference properties but is_inferred is set to False."
                )
        if not self.created_at:
            self.created_at = _current_timestamp_iso()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes edge to dictionary representation."""
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "is_inferred": self.is_inferred,
            "inference_provenance": (
                asdict(self.inference_provenance) if self.inference_provenance else None
            ),
            "confidence_score": self.confidence_score,
            "epistemic_status": self.epistemic_status.value if self.epistemic_status else None,
            "properties": dict(self.properties),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceEdge:
        """Instantiates EvidenceEdge from serialized dictionary."""
        coord_dict = data.get("inference_provenance")
        inference_coord = None
        if coord_dict:
            inference_coord = EvidenceCoordinate(
                coordinate_id=coord_dict["coordinate_id"],
                document_id=coord_dict["document_id"],
                document_sha256=coord_dict["document_sha256"],
                page_number=coord_dict["page_number"],
                section_identifier=coord_dict["section_identifier"],
                paragraph_index=coord_dict["paragraph_index"],
                sentence_index=coord_dict["sentence_index"],
                char_start=coord_dict["char_start"],
                char_end=coord_dict["char_end"],
                verbatim_snippet=coord_dict["verbatim_snippet"],
                extraction_confidence=coord_dict.get("extraction_confidence", 1.0),
            )
        epistemic = data.get("epistemic_status")
        return cls(
            edge_id=data["edge_id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            edge_type=EdgeType(data["edge_type"]),
            is_inferred=bool(data.get("is_inferred", False)),
            inference_provenance=inference_coord,
            confidence_score=float(data.get("confidence_score", 1.0)),
            epistemic_status=EpistemicStatus(epistemic) if epistemic else None,
            properties=dict(data.get("properties", {})),
            created_at=data.get("created_at", _current_timestamp_iso()),
        )


@dataclass
class EvidenceGraph:
    """Heterogeneous evidence graph container with adjacency indexing and traversal operations."""
    graph_id: str
    schema_version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)
    nodes: Dict[str, EvidenceNode] = field(default_factory=dict)
    edges: Dict[str, EvidenceEdge] = field(default_factory=dict)

    # In-memory fast adjacency index: node_id -> set of edge_ids
    _outgoing: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _incoming: Dict[str, Set[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.graph_id:
            raise GraphIntegrityError("EvidenceGraph graph_id must be a non-empty string.")
        self._rebuild_adjacency()

    def _rebuild_adjacency(self) -> None:
        self._outgoing = {node_id: set() for node_id in self.nodes}
        self._incoming = {node_id: set() for node_id in self.nodes}
        for edge_id, edge in self.edges.items():
            if edge.source_id in self._outgoing:
                self._outgoing[edge.source_id].add(edge_id)
            if edge.target_id in self._incoming:
                self._incoming[edge.target_id].add(edge_id)

    def add_node(self, node: EvidenceNode) -> None:
        """Adds a node to the graph and initializes adjacency buckets."""
        if not isinstance(node, EvidenceNode):
            raise GraphIntegrityError("Expected EvidenceNode instance.")
        self.nodes[node.node_id] = node
        if node.node_id not in self._outgoing:
            self._outgoing[node.node_id] = set()
        if node.node_id not in self._incoming:
            self._incoming[node.node_id] = set()

    def get_node(self, node_id: str) -> Optional[EvidenceNode]:
        """Retrieves a node by its identifier."""
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """Removes a node and cascades removal of all associated incident edges."""
        if node_id not in self.nodes:
            return False
        # Remove incident edges
        out_e = list(self._outgoing.get(node_id, set()))
        in_e = list(self._incoming.get(node_id, set()))
        for edge_id in out_e + in_e:
            self.remove_edge(edge_id)

        self.nodes.pop(node_id, None)
        self._outgoing.pop(node_id, None)
        self._incoming.pop(node_id, None)
        return True

    def add_edge(self, edge: EvidenceEdge, validate_endpoints: bool = True) -> None:
        """Adds a typed edge to the graph.

        Raises:
            GraphIntegrityError: If validate_endpoints is True and endpoints do not exist.
        """
        if not isinstance(edge, EvidenceEdge):
            raise GraphIntegrityError("Expected EvidenceEdge instance.")
        if validate_endpoints:
            if edge.source_id not in self.nodes:
                raise GraphIntegrityError(
                    f"Edge source_id '{edge.source_id}' does not exist in graph nodes."
                )
            if edge.target_id not in self.nodes:
                raise GraphIntegrityError(
                    f"Edge target_id '{edge.target_id}' does not exist in graph nodes."
                )
        self.edges[edge.edge_id] = edge
        if edge.source_id not in self._outgoing:
            self._outgoing[edge.source_id] = set()
        self._outgoing[edge.source_id].add(edge.edge_id)
        if edge.target_id not in self._incoming:
            self._incoming[edge.target_id] = set()
        self._incoming[edge.target_id].add(edge.edge_id)

    def get_edge(self, edge_id: str) -> Optional[EvidenceEdge]:
        """Retrieves an edge by its identifier."""
        return self.edges.get(edge_id)

    def remove_edge(self, edge_id: str) -> bool:
        """Removes an edge from the graph and updates adjacency indexes."""
        edge = self.edges.pop(edge_id, None)
        if edge is None:
            return False
        if edge.source_id in self._outgoing:
            self._outgoing[edge.source_id].discard(edge_id)
        if edge.target_id in self._incoming:
            self._incoming[edge.target_id].discard(edge_id)
        return True

    def get_outgoing_edges(self, node_id: str) -> List[EvidenceEdge]:
        """Returns all outgoing edges originating from node_id."""
        edge_ids = self._outgoing.get(node_id, set())
        return [self.edges[eid] for eid in edge_ids if eid in self.edges]

    def get_incoming_edges(self, node_id: str) -> List[EvidenceEdge]:
        """Returns all incoming edges terminating at node_id."""
        edge_ids = self._incoming.get(node_id, set())
        return [self.edges[eid] for eid in edge_ids if eid in self.edges]

    def get_neighbors(self, node_id: str, direction: str = "both") -> List[str]:
        """Returns neighbor node IDs according to specified direction ('out', 'in', 'both')."""
        neighbors: Set[str] = set()
        if direction in ("out", "both"):
            for eid in self._outgoing.get(node_id, set()):
                if eid in self.edges:
                    neighbors.add(self.edges[eid].target_id)
        if direction in ("in", "both"):
            for eid in self._incoming.get(node_id, set()):
                if eid in self.edges:
                    neighbors.add(self.edges[eid].source_id)
        return sorted(neighbors)

    def filter_edges(
        self,
        is_inferred: Optional[bool] = None,
        edge_type: Optional[EdgeType] = None,
    ) -> List[EvidenceEdge]:
        """Filters edges by inference flag and/or edge type."""
        results: List[EvidenceEdge] = []
        for edge in self.edges.values():
            if is_inferred is not None and edge.is_inferred != is_inferred:
                continue
            if edge_type is not None and edge.edge_type != edge_type:
                continue
            results.append(edge)
        return results

    def get_author_asserted_edges(self) -> List[EvidenceEdge]:
        """Returns all author-asserted edges (is_inferred=False)."""
        return self.filter_edges(is_inferred=False)

    def get_inferred_edges(self) -> List[EvidenceEdge]:
        """Returns all model-inferred edges (is_inferred=True)."""
        return self.filter_edges(is_inferred=True)

    def get_neighborhood(self, target_entities: List[str], max_depth: int = 1) -> EvidenceGraph:
        """Extracts an induced subgraph containing nodes reachable up to max_depth hops."""
        if max_depth < 0:
            raise GraphIntegrityError("max_depth must be >= 0.")
        visited_nodes: Set[str] = set()
        active_targets = [target for target in target_entities if target in self.nodes]
        queue: deque[tuple[str, int]] = deque((target, 0) for target in active_targets)
        for target in active_targets:
            visited_nodes.add(target)

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            # Explore outgoing and incoming neighbors
            for neighbor in self.get_neighbors(current, direction="both"):
                if neighbor not in visited_nodes and neighbor in self.nodes:
                    visited_nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))

        # Build induced subgraph
        subgraph = EvidenceGraph(
            graph_id=f"{self.graph_id}_subgraph_{max_depth}",
            schema_version=self.schema_version,
            metadata={
                "parent_graph_id": self.graph_id,
                "targets": target_entities,
                "max_depth": max_depth,
            },
        )
        for nid in visited_nodes:
            subgraph.add_node(self.nodes[nid])

        for edge in self.edges.values():
            if edge.source_id in visited_nodes and edge.target_id in visited_nodes:
                subgraph.add_edge(edge, validate_endpoints=False)

        return subgraph

    def find_contradiction_paths(self, claim_id: str) -> List[List[EvidenceEdge]]:
        """Finds direct and indirect contradiction paths connected to claim_id."""
        if claim_id not in self.nodes:
            return []
        paths: List[List[EvidenceEdge]] = []
        # Check incident CONTRADICTS edges
        incident_edges = self.get_outgoing_edges(claim_id) + self.get_incoming_edges(claim_id)
        for edge in incident_edges:
            if edge.edge_type == EdgeType.CONTRADICTS:
                paths.append([edge])

        # 2-hop contradiction: claim -> SUPPORTS/DERIVED_FROM -> other -> CONTRADICTS
        for edge1 in self.get_outgoing_edges(claim_id):
            if edge1.edge_type in (EdgeType.SUPPORTS, EdgeType.DERIVED_FROM):
                for edge2 in self.get_outgoing_edges(edge1.target_id):
                    if edge2.edge_type == EdgeType.CONTRADICTS:
                        paths.append([edge1, edge2])

        return paths

    def validate_integrity(self) -> None:
        """Audits graph referential integrity, endpoint validity, and edge invariants."""
        for edge_id, edge in self.edges.items():
            if edge.source_id not in self.nodes:
                raise GraphIntegrityError(
                    f"Integrity violation: Edge '{edge_id}' source '{edge.source_id}' "
                    "missing from nodes."
                )
            if edge.target_id not in self.nodes:
                raise GraphIntegrityError(
                    f"Integrity violation: Edge '{edge_id}' target '{edge.target_id}' "
                    "missing from nodes."
                )
            has_inferred_props = (
                edge.properties.get("inferred") is True or "inferred_by" in edge.properties
            )
            if not edge.is_inferred and has_inferred_props:
                raise InferredEdgeConflationError(
                    f"Integrity violation: Edge '{edge_id}' conflates inferred reasoning "
                    "with author assertion."
                )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes full graph to dictionary."""
        return {
            "graph_id": self.graph_id,
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceGraph:
        """Deserializes graph from dictionary representation."""
        graph_id = data["graph_id"]
        schema_version = data.get("schema_version", "1.0.0")
        metadata = dict(data.get("metadata", {}))
        graph = cls(graph_id=graph_id, schema_version=schema_version, metadata=metadata)
        for node_dict in data.get("nodes", []):
            graph.add_node(EvidenceNode.from_dict(node_dict))
        for edge_dict in data.get("edges", []):
            graph.add_edge(EvidenceEdge.from_dict(edge_dict), validate_endpoints=False)
        return graph

    def to_json(self, indent: int = 2) -> str:
        """Serializes graph to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> EvidenceGraph:
        """Deserializes graph from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


class GraphQueryType(str, Enum):
    """Supported query types for Boundary F (MOD-GRAPH-001)."""
    NEIGHBORHOOD = "NEIGHBORHOOD"
    CONTRADICTION_PATH = "CONTRADICTION_PATH"
    METHOD_COMPARISON = "METHOD_COMPARISON"


@dataclass
class GraphQueryRequest:
    """Input query specification for Boundary F retrieval interface."""
    query_type: GraphQueryType
    target_entities: List[str]
    max_depth: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.query_type, GraphQueryType):
            try:
                self.query_type = GraphQueryType(self.query_type)
            except ValueError as exc:
                raise GraphIntegrityError(f"Invalid GraphQueryType: {self.query_type}") from exc
        if not self.target_entities:
            raise GraphIntegrityError("target_entities must contain >= 1 entity identifier.")
        if self.max_depth < 1:
            raise GraphIntegrityError("max_depth must be >= 1.")



@dataclass
class GraphQueryResult:
    """Output graph subgraph and verified provenance records for Boundary F."""
    subgraph_nodes: List[EvidenceNode]
    typed_edges: List[EvidenceEdge]
    provenance_records: List[EvidenceCoordinate] = field(default_factory=list)
