"""Discourse graph parser and provenance verification engine.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-004, and ADR-008.
Provides multi-sentence discourse graph construction and strict causal vs
correlational verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from laris.core.schemas import EvidenceCoordinate
from laris.reasoning.relations import (
    CORRELATIONAL_CUES,
    DiscourseRelationOutput,
    DiscourseRelationType,
)

CAUSAL_CUES: list[str] = [
    "led to",
    "caused",
    "resulted in",
    "induced",
    "triggered",
    "yielded",
    "produced",
]

CONTRAST_CUES: list[str] = [
    "in contrast",
    "however",
    "conversely",
    "whereas",
    "on the other hand",
    "while",
]

CONCESSIVE_CUES: list[str] = [
    "although",
    "despite",
    "even though",
    "nonetheless",
    "nevertheless",
]

TEMPORAL_CUES: list[str] = [
    "subsequently",
    "prior to",
    "following",
    "thereafter",
    "before",
    "after",
]

ELABORATION_CUES: list[str] = [
    "specifically",
    "in particular",
    "namely",
    "for instance",
    "for example",
]


@dataclass(frozen=True)
class DiscourseGraphEdge:
    """Directed edge representing a typed discourse relation between two sentences."""

    edge_id: str
    source_sentence_id: str
    target_sentence_id: str
    relation: DiscourseRelationOutput

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_sentence_id": self.source_sentence_id,
            "target_sentence_id": self.target_sentence_id,
            "relation": self.relation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscourseGraphEdge:
        return cls(
            edge_id=data["edge_id"],
            source_sentence_id=data["source_sentence_id"],
            target_sentence_id=data["target_sentence_id"],
            relation=DiscourseRelationOutput.from_dict(data["relation"]),
        )


@dataclass
class DiscourseGraph:
    """Multi-sentence scientific discourse graph with provenance tracing."""

    document_id: str
    edges: list[DiscourseGraphEdge] = field(default_factory=list)

    def add_edge(self, edge: DiscourseGraphEdge) -> None:
        self.edges.append(edge)

    def get_causal_chains(self) -> list[list[str]]:
        """Extract multi-sentence causal paths where every transition is verified CAUSAL."""
        adj: dict[str, list[str]] = {}
        for edge in self.edges:
            if (
                edge.relation.relation_type == DiscourseRelationType.CAUSAL
                and edge.relation.causal_verified
            ):
                adj.setdefault(edge.source_sentence_id, []).append(edge.target_sentence_id)

        chains: list[list[str]] = []

        def dfs(current: str, path: list[str]) -> None:
            neighbors = adj.get(current, [])
            if not neighbors:
                if len(path) > 1:
                    chains.append(list(path))
                return
            for nxt in neighbors:
                if nxt not in path:
                    dfs(nxt, path + [nxt])

        targets = {target for tgts in adj.values() for target in tgts}
        start_nodes = [node for node in adj if node not in targets]
        if not start_nodes and adj:
            start_nodes = list(adj.keys())

        for start_node in start_nodes:
            dfs(start_node, [start_node])

        return chains

    def get_edges_by_type(
        self, relation_type: DiscourseRelationType
    ) -> list[DiscourseGraphEdge]:
        """Filter graph edges by specific discourse relation type."""
        return [e for e in self.edges if e.relation.relation_type == relation_type]

    def trace_provenance(self) -> list[EvidenceCoordinate]:
        """Collect all verified EvidenceCoordinate objects linked across graph edges."""
        coords: list[EvidenceCoordinate] = []
        for edge in self.edges:
            if edge.relation.evidence_coordinate is not None:
                coords.append(edge.relation.evidence_coordinate)
        return coords


class ScientificDiscourseParser:
    """Rule-based scientific discourse parser classifying inter-sentential transitions."""

    def parse_pair(
        self,
        arg1: str,
        arg2: str,
        relation_id: str,
        causal_verified: bool = False,
        evidence_coordinate: EvidenceCoordinate | None = None,
    ) -> DiscourseRelationOutput:
        """Parse the discourse relation between two consecutive scientific sentences."""
        arg1_lower = arg1.lower()
        arg2_lower = arg2.lower()
        combined = f"{arg1_lower} {arg2_lower}"

        # 1. Check for Correlational cues first (ADR-008 priority)
        matched_corr = next((c for c in CORRELATIONAL_CUES if c in combined), None)
        if matched_corr:
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.CORRELATIONAL,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_corr,
                confidence=0.92,
                uncertainty_score=0.10,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        # 2. Check for Contrast cues
        matched_contrast = next((c for c in CONTRAST_CUES if c in combined), None)
        # 3. Check for Concessive cues
        matched_concessive = next((c for c in CONCESSIVE_CUES if c in combined), None)

        if matched_contrast and matched_concessive:
            # Ambiguous conflict between contrast and concessive
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.AMBIGUOUS,
                arg1=arg1,
                arg2=arg2,
                connective_cue=f"{matched_contrast}+{matched_concessive}",
                confidence=0.50,
                uncertainty_score=0.85,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        if matched_contrast:
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.CONTRAST,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_contrast,
                confidence=0.90,
                uncertainty_score=0.15,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        if matched_concessive:
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.CONCESSIVE,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_concessive,
                confidence=0.88,
                uncertainty_score=0.18,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        # 4. Check for Causal cues
        matched_causal = next((c for c in CAUSAL_CUES if c in combined), None)
        if matched_causal:
            if not causal_verified:
                # If causal cues exist without explicit causal verification,
                # assign high uncertainty or require verification
                pass
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.CAUSAL,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_causal,
                confidence=0.95 if causal_verified else 0.70,
                uncertainty_score=0.05 if causal_verified else 0.40,
                causal_verified=causal_verified,
                evidence_coordinate=evidence_coordinate,
            )

        # 5. Check for Temporal cues
        matched_temp = next((c for c in TEMPORAL_CUES if c in combined), None)
        if matched_temp:
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.TEMPORAL,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_temp,
                confidence=0.85,
                uncertainty_score=0.20,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        # 6. Check for Elaboration cues
        matched_elab = next((c for c in ELABORATION_CUES if c in combined), None)
        if matched_elab:
            return DiscourseRelationOutput(
                relation_id=relation_id,
                relation_type=DiscourseRelationType.ELABORATION,
                arg1=arg1,
                arg2=arg2,
                connective_cue=matched_elab,
                confidence=0.85,
                uncertainty_score=0.20,
                causal_verified=False,
                evidence_coordinate=evidence_coordinate,
            )

        # 7. No recognized discourse cue -> UNKNOWN_RELATION with high epistemic uncertainty
        return DiscourseRelationOutput(
            relation_id=relation_id,
            relation_type=DiscourseRelationType.UNKNOWN_RELATION,
            arg1=arg1,
            arg2=arg2,
            connective_cue=None,
            confidence=0.30,
            uncertainty_score=0.95,
            causal_verified=False,
            evidence_coordinate=evidence_coordinate,
        )
