"""Abstract interfaces and contracts for Layer 6 retrieval adapters and rank combiners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from laris.layers.layer6_retrieval.schemas import (
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


class BaseRetrievalAdapter(ABC):
    """Abstract contract for single-modality retrieval adapters."""

    @property
    @abstractmethod
    def channel(self) -> RetrievalChannel:  # pragma: no cover
        """Returns the specific retrieval channel implemented by this adapter."""
        pass

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> List[RetrievalCandidate]:  # pragma: no cover
        """Executes retrieval for the given query and returns ranked candidates."""
        pass

    @abstractmethod
    def has_item(self, item_id: str) -> bool:  # pragma: no cover
        """Checks if a document, passage, or node exists in the adapter index."""
        pass

    @property
    @abstractmethod
    def total_items(self) -> int:  # pragma: no cover
        """Returns the total number of indexed items."""
        pass


class BaseFusionCombiner(ABC):
    """Abstract contract for multi-channel rank fusion algorithms."""

    @abstractmethod
    def combine(
        self,
        channel_results: Dict[RetrievalChannel, List[RetrievalCandidate]],
        top_k: int,
    ) -> List[RetrievalCandidate]:  # pragma: no cover
        """Fuses ranked candidate lists from multiple channels into a unified ranking."""
        pass
