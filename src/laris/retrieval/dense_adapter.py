"""Dense semantic vector retrieval adapter for Layer 6 Hybrid Retrieval.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-002, ADR-004, and ADR-010:
- Compact vector similarity search with unit L2 normalized cosine distance
- Optional integration with BaseSentenceEncoder for on-the-fly query encoding
- Strict dimension verification and error semantics (EmbeddingDimensionMismatchError)
- Metadata filtering and first-class provenance coordinate propagation
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.language.encoder import BaseSentenceEncoder
from laris.retrieval.interfaces import BaseRetrievalAdapter
from laris.retrieval.schemas import (
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


@dataclass(frozen=True)
class DenseVectorItem:
    """Passage or document vector representation for dense semantic retrieval."""

    item_id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    coordinates: List[EvidenceCoordinate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.item_id or not self.item_id.strip():
            raise ModuleContractViolationError("DenseVectorItem item_id must not be empty.")
        if not self.text or not self.text.strip():
            raise ModuleContractViolationError("DenseVectorItem text must not be empty.")


class DenseVectorAdapter(BaseRetrievalAdapter):
    """Dense semantic vector retriever implementing BaseRetrievalAdapter."""

    def __init__(
        self,
        encoder: Optional[BaseSentenceEncoder] = None,
        expected_dim: Optional[int] = None,
    ) -> None:
        self.encoder = encoder
        self.expected_dim = expected_dim
        if encoder is not None:
            contract_dim = encoder.get_contract().embedding_dim
            if expected_dim is not None and expected_dim != contract_dim:
                raise EmbeddingDimensionMismatchError(
                    f"Specified expected_dim ({expected_dim}) does not match "
                    f"encoder contract dim ({contract_dim})."
                )
            self.expected_dim = contract_dim

        self._items: Dict[str, DenseVectorItem] = {}
        self._vectors: Dict[str, List[float]] = {}

    @property
    def channel(self) -> RetrievalChannel:
        """Returns DENSE channel identifier."""
        return RetrievalChannel.DENSE

    @property
    def total_items(self) -> int:
        """Returns number of indexed dense items."""
        return len(self._items)

    def has_item(self, item_id: str) -> bool:
        """Checks if an item identifier is present in the index."""
        return item_id in self._items

    @staticmethod
    def _normalize(vec: List[float]) -> List[float]:
        """Normalizes vector to unit L2 norm."""
        norm_sq = sum(x * x for x in vec)
        if norm_sq <= 1e-12:
            return list(vec)
        norm = math.sqrt(norm_sq)
        return [x / norm for x in vec]

    def add_items(self, items: List[DenseVectorItem]) -> None:
        """Indexes dense items and computes/normalizes their embeddings."""
        if not items:
            raise ModuleContractViolationError("items list must not be empty.")

        for item in items:
            if item.item_id in self._items:
                raise ModuleContractViolationError(
                    f"Duplicate item_id '{item.item_id}' in dense index."
                )

            embedding: List[float]
            if item.embedding is not None:
                embedding = item.embedding
            else:
                if self.encoder is None:
                    raise ModuleContractViolationError(
                        f"Item '{item.item_id}' lacks embedding and no "
                        "sentence encoder is configured."
                    )

                encoded = self.encoder.encode_sentence(item.text)
                embedding = encoded.embedding

            if self.expected_dim is None:
                self.expected_dim = len(embedding)
            elif len(embedding) != self.expected_dim:
                raise EmbeddingDimensionMismatchError(
                    f"Item '{item.item_id}' embedding dimension {len(embedding)} "
                    f"does not match expected dimension {self.expected_dim}."
                )

            self._items[item.item_id] = item
            self._vectors[item.item_id] = self._normalize(embedding)

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalCandidate]:
        """Performs cosine similarity search against indexed vector items."""
        if not self._items:
            return []

        query_vec: List[float]
        if query.dense_vector is not None:
            if self.expected_dim is not None and len(query.dense_vector) != self.expected_dim:
                raise EmbeddingDimensionMismatchError(
                    f"Query vector dimension {len(query.dense_vector)} does not match "
                    f"expected index dimension {self.expected_dim}."
                )
            query_vec = self._normalize(query.dense_vector)
        else:
            if self.encoder is None:
                raise ModuleContractViolationError(
                    "Query dense_vector missing and no sentence encoder is configured."
                )
            encoded = self.encoder.encode_sentence(query.text)
            query_vec = self._normalize(encoded.embedding)

        scores: Dict[str, float] = {}
        for item_id, item in self._items.items():
            if query.filter is not None and not query.filter.matches(item.metadata):
                continue
            item_vec = self._vectors[item_id]
            # Dot product of unit vectors equals cosine similarity
            sim = sum(q * v for q, v in zip(query_vec, item_vec))
            scores[item_id] = sim

        # Deterministic sorting: score descending, then item_id ascending
        sorted_items = sorted(
            [(item_id, score) for item_id, score in scores.items()],
            key=lambda x: (-x[1], x[0]),
        )

        candidates: List[RetrievalCandidate] = []
        for rank, (item_id, score) in enumerate(sorted_items[: query.top_k], start=1):
            item = self._items[item_id]
            candidates.append(
                RetrievalCandidate(
                    candidate_id=item_id,
                    content=item.text,
                    score=score,
                    channel=RetrievalChannel.DENSE,
                    rank=rank,
                    metadata=item.metadata,
                    coordinates=list(item.coordinates),
                    source_scores={"dense": score},
                )
            )

        return candidates
