"""Hybrid multi-channel retrieval engine for Layer 6.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010:
- Coordinates Lexical, Dense, and Graph retrieval adapters behind modular interfaces
- Unified Reciprocal Rank Fusion across diverse scoring modalities
- Epistemic provenance preservation anchored to EvidenceCoordinate records
- Depth ceiling enforcement and deterministic candidate ordering
"""

from __future__ import annotations

from typing import Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer6_retrieval.fusion import ReciprocalRankFusion
from laris.layers.layer6_retrieval.interfaces import (
    BaseFusionCombiner,
    BaseRetrievalAdapter,
)
from laris.layers.layer6_retrieval.schemas import (
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


class HybridRetrievalEngine:
    """Multi-channel hybrid retrieval orchestrator for scientific literature."""

    def __init__(
        self,
        adapters: Optional[Dict[RetrievalChannel, BaseRetrievalAdapter]] = None,
        fusion_combiner: Optional[BaseFusionCombiner] = None,
    ) -> None:
        self._adapters: Dict[RetrievalChannel, BaseRetrievalAdapter] = {}
        if adapters:
            for ch, adapter in adapters.items():
                self.register_adapter(adapter)
        self.fusion_combiner: BaseFusionCombiner = fusion_combiner or ReciprocalRankFusion()

    @property
    def registered_channels(self) -> List[RetrievalChannel]:
        """Returns list of currently registered retrieval channels."""
        return sorted(self._adapters.keys(), key=lambda c: c.value)

    def has_adapter(self, channel: RetrievalChannel) -> bool:
        """Checks if an adapter is registered for the specified channel."""
        return channel in self._adapters

    def get_adapter(self, channel: RetrievalChannel) -> Optional[BaseRetrievalAdapter]:
        """Returns the adapter instance for the specified channel, or None."""
        return self._adapters.get(channel)

    def register_adapter(self, adapter: BaseRetrievalAdapter) -> None:
        """Registers a retrieval adapter for its declared channel."""
        if not isinstance(adapter, BaseRetrievalAdapter):
            raise ModuleContractViolationError(
                "Adapter must be an instance of BaseRetrievalAdapter."
            )
        self._adapters[adapter.channel] = adapter

    def unregister_adapter(self, channel: RetrievalChannel) -> bool:
        """Removes the adapter for the specified channel. Returns True if removed."""
        if channel in self._adapters:
            del self._adapters[channel]
            return True
        return False

    def retrieve_channel(
        self,
        channel: RetrievalChannel,
        query: RetrievalQuery,
    ) -> List[RetrievalCandidate]:
        """Executes retrieval strictly on a single specified channel."""
        if channel not in self._adapters:
            raise ModuleContractViolationError(
                f"No adapter registered for channel '{channel.value}'."
            )
        return self._adapters[channel].retrieve(query)

    def retrieve(
        self,
        query: RetrievalQuery,
        channels: Optional[List[RetrievalChannel]] = None,
        fallback_on_channel_failure: bool = False,
    ) -> List[RetrievalCandidate]:
        """Executes multi-channel retrieval and combines results via rank fusion.

        If fallback_on_channel_failure is True, errors from individual channels
        (such as a missing dense encoder) are gracefully bypassed in favor of
        surviving channels.
        """
        active_channels = channels or list(self._adapters.keys())
        if not active_channels:
            return []

        channel_results: Dict[RetrievalChannel, List[RetrievalCandidate]] = {}
        for ch in active_channels:
            if ch in self._adapters:
                try:
                    channel_results[ch] = self._adapters[ch].retrieve(query)
                except Exception:
                    if not fallback_on_channel_failure:
                        raise

        if not channel_results:
            return []

        return self.fusion_combiner.combine(channel_results, top_k=query.top_k)

