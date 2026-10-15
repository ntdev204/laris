"""Canonical data schemas, filters, and query contracts for Layer 6 Hybrid Retrieval.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-004, ADR-005, and ADR-010:
- Explicit multi-channel taxonomy: LEXICAL, DENSE, GRAPH, HYBRID
- Bounded query parameters with depth ceilings and top-k limits
- First-class evidence coordinate provenance retention on all candidates
- Metadata filtering over documents, years, entity types, and inference flags
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError, RetrievalDepthExceededError
from laris.core.schemas import EvidenceCoordinate

MAX_RETRIEVAL_DEPTH: int = 5
DEFAULT_RRF_K: float = 60.0


class RetrievalChannel(str, Enum):
    """Supported retrieval modalities in Layer 6."""

    LEXICAL = "lexical"
    DENSE = "dense"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class MetadataFilter:
    """Predicate filter applied to indexed documents, passages, or graph nodes."""

    document_ids: Optional[List[str]] = None
    node_types: Optional[List[str]] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    custom_attributes: Dict[str, Any] = field(default_factory=dict)
    exclude_inferred: bool = False

    def __post_init__(self) -> None:
        if (
            self.min_year is not None
            and self.max_year is not None
            and self.min_year > self.max_year
        ):
            raise ModuleContractViolationError(
                f"min_year ({self.min_year}) cannot be greater than max_year ({self.max_year})."
            )

    def matches(self, metadata: Dict[str, Any]) -> bool:
        """Evaluates whether the given candidate metadata satisfies all filter conditions."""
        if not metadata and (
            self.document_ids
            or self.node_types
            or self.min_year is not None
            or self.max_year is not None
            or self.custom_attributes
            or self.exclude_inferred
        ):
            # If metadata is empty and any filter is active
            if self.document_ids or self.node_types or self.custom_attributes:
                return False
            if self.min_year is not None or self.max_year is not None:
                return False

        if self.document_ids is not None:
            doc_id = metadata.get("document_id") or metadata.get("doc_id")
            if doc_id not in self.document_ids:
                return False

        if self.node_types is not None:
            node_type = metadata.get("node_type")
            if node_type is None:
                return False
            allowed_types = {nt.lower() for nt in self.node_types}
            if str(node_type).lower() not in allowed_types:
                return False


        year = metadata.get("year") or metadata.get("publication_year")
        if self.min_year is not None:
            if year is None or year < self.min_year:
                return False
        if self.max_year is not None:
            if year is None or year > self.max_year:
                return False

        if self.exclude_inferred:
            if metadata.get("is_inferred") is True:
                return False

        for k, v in self.custom_attributes.items():
            if metadata.get(k) != v:
                return False

        return True


@dataclass(frozen=True)
class RetrievalCandidate:
    """Discrete evidence candidate retrieved from a single or fused retrieval channel."""

    candidate_id: str
    content: str
    score: float
    channel: RetrievalChannel
    rank: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    coordinates: List[EvidenceCoordinate] = field(default_factory=list)
    source_scores: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.candidate_id.strip():
            raise ModuleContractViolationError("RetrievalCandidate candidate_id must not be empty.")
        if self.rank < 1:
            raise ModuleContractViolationError(
                f"RetrievalCandidate rank must be >= 1, got {self.rank}."
            )


@dataclass
class RetrievalQuery:
    """Input query specification for multi-channel retrieval."""

    text: str
    top_k: int = 10
    filter: Optional[MetadataFilter] = None
    dense_vector: Optional[List[float]] = None
    target_entities: Optional[List[str]] = None
    max_depth: int = 2

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ModuleContractViolationError(
                "RetrievalQuery text must not be empty or whitespace."
            )

        if self.top_k <= 0:
            raise ModuleContractViolationError(f"top_k must be > 0, got {self.top_k}.")
        if self.max_depth < 1:
            raise ModuleContractViolationError(f"max_depth must be >= 1, got {self.max_depth}.")
        if self.max_depth > MAX_RETRIEVAL_DEPTH:
            raise RetrievalDepthExceededError(
                f"max_depth ({self.max_depth}) exceeds ceiling ({MAX_RETRIEVAL_DEPTH})."
            )
