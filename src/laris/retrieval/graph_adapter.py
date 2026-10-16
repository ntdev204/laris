"""Graph retrieval adapter for Layer 6 Hybrid Retrieval over EvidenceGraph.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, ADR-009, and ADR-010:
- Deterministic bounded BFS traversal over heterogeneous nodes and typed edges
- Depth ceiling enforcement preventing context window explosion
- Direct propagation of verified EvidenceCoordinate provenance
- Epistemic filtering over inferred vs author-asserted subgraphs
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from laris.core.errors import ModuleContractViolationError, RetrievalDepthExceededError
from laris.core.schemas import EvidenceCoordinate
from laris.graph.interfaces import BaseGraphPersistenceAdapter
from laris.graph.schemas import EvidenceGraph
from laris.retrieval.interfaces import BaseRetrievalAdapter
from laris.retrieval.schemas import (
    MAX_RETRIEVAL_DEPTH,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


class GraphRetrievalAdapter(BaseRetrievalAdapter):
    """Evidence graph retrieval adapter implementing BaseRetrievalAdapter."""

    def __init__(
        self,
        graph: Optional[EvidenceGraph] = None,
        persistence_adapter: Optional[BaseGraphPersistenceAdapter] = None,
        graph_id: Optional[str] = None,
        max_allowed_depth: int = MAX_RETRIEVAL_DEPTH,
    ) -> None:
        if max_allowed_depth < 1:
            raise ModuleContractViolationError(
                f"max_allowed_depth must be >= 1, got {max_allowed_depth}."
            )
        self.max_allowed_depth = max_allowed_depth
        self.persistence_adapter = persistence_adapter
        self.graph_id = graph_id

        if graph is not None:
            self.graph = graph
        elif persistence_adapter is not None and graph_id is not None:
            self.graph = persistence_adapter.load(graph_id)
        else:
            self.graph = EvidenceGraph(graph_id="ephemeral_retrieval_graph")

    @property
    def channel(self) -> RetrievalChannel:
        """Returns GRAPH channel identifier."""
        return RetrievalChannel.GRAPH

    @property
    def total_items(self) -> int:
        """Returns total number of nodes in graph."""
        return len(self.graph.nodes)

    def has_item(self, item_id: str) -> bool:
        """Checks if a node identifier exists in graph."""
        return item_id in self.graph.nodes

    def set_graph(self, graph: EvidenceGraph) -> None:
        """Replaces active evidence graph with new instance."""
        self.graph = graph

    def _find_seed_entities(self, query: RetrievalQuery) -> List[str]:
        """Resolves seed entities from query target_entities or text search over graph nodes."""
        if query.target_entities:
            return [e for e in query.target_entities if e in self.graph.nodes]

        tokens = [t.lower() for t in re.findall(r"\w+", query.text) if len(t) >= 2]
        if not tokens:
            return []

        matched_seeds: List[str] = []
        for node_id, node in self.graph.nodes.items():
            label_lower = node.label.lower()
            id_lower = node.node_id.lower()
            text_prop = str(node.properties.get("canonical_text", "")).lower()
            title_prop = str(node.properties.get("title", "")).lower()

            if any(
                t in label_lower or t in id_lower or t in text_prop or t in title_prop
                for t in tokens
            ):
                matched_seeds.append(node_id)

        return matched_seeds

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalCandidate]:
        """Executes depth-bounded graph neighborhood retrieval with provenance tracking."""
        if not self.graph.nodes:
            return []

        if query.max_depth > self.max_allowed_depth:
            raise RetrievalDepthExceededError(
                f"Query max_depth {query.max_depth} exceeds adapter limit "
                f"{self.max_allowed_depth}."
            )

        seed_nodes = self._find_seed_entities(query)
        if not seed_nodes:
            return []

        visited: Dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque()
        for seed in seed_nodes:
            visited[seed] = 0
            queue.append((seed, 0))

        while queue:
            current, depth = queue.popleft()
            if depth >= query.max_depth:
                continue

            for neighbor in self.graph.get_neighbors(current, direction="both"):
                if neighbor in self.graph.nodes:
                    if neighbor not in visited or visited[neighbor] > depth + 1:
                        visited[neighbor] = depth + 1
                        queue.append((neighbor, depth + 1))

        scored_candidates: List[
            Tuple[str, str, float, Dict[str, Any], List[EvidenceCoordinate]]
        ] = []

        for node_id, depth in visited.items():
            node = self.graph.nodes[node_id]
            deg = len(self.graph.get_incoming_edges(node_id)) + len(
                self.graph.get_outgoing_edges(node_id)
            )

            metadata: Dict[str, Any] = {
                "node_id": node.node_id,
                "node_type": node.node_type.value,
                "is_inferred": bool(node.properties.get("is_inferred", False)),
                "degree": deg,
                "depth": depth,
            }
            metadata.update(node.properties)

            if query.filter is not None and not query.filter.matches(metadata):
                continue

            depth_score = 1.0 / (1.0 + float(depth))
            deg_boost = 0.1 * min(deg, 10) / 10.0
            score = depth_score + deg_boost

            content = (
                str(node.properties.get("canonical_text", ""))
                or str(node.properties.get("title", ""))
                or node.label
                or node.node_id
            )
            coordinates = list(node.provenance)
            scored_candidates.append((node_id, content, score, metadata, coordinates))

        # Deterministic sorting: score descending, then node_id ascending
        sorted_candidates = sorted(scored_candidates, key=lambda x: (-x[2], x[0]))

        results: List[RetrievalCandidate] = []
        for rank, (node_id, content, score, metadata, coords) in enumerate(
            sorted_candidates[: query.top_k], start=1
        ):
            results.append(
                RetrievalCandidate(
                    candidate_id=node_id,
                    content=content,
                    score=score,
                    channel=RetrievalChannel.GRAPH,
                    rank=rank,
                    metadata=metadata,
                    coordinates=coords,
                    source_scores={"graph": score},
                )
            )

        return results
