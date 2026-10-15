"""Reciprocal Rank Fusion (RRF) implementation for multi-channel ranking integration.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-004, and ADR-010:
- Deterministic score fusion: RRF(d) = sum(w_c / (k + r_c(d)))
- Scale-invariant combination of unbounded lexical BM25 and normalized cosine similarities
- Preservation and deduplication of EvidenceCoordinate provenance records
- Deterministic tie-breaking on candidate identifier strings
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer6_retrieval.interfaces import BaseFusionCombiner
from laris.layers.layer6_retrieval.schemas import (
    DEFAULT_RRF_K,
    RetrievalCandidate,
    RetrievalChannel,
)


class ReciprocalRankFusion(BaseFusionCombiner):
    """Rank fusion algorithm combining rankings across lexical, dense, and graph channels."""

    def __init__(
        self,
        k: float = DEFAULT_RRF_K,
        weights: Optional[Dict[RetrievalChannel, float]] = None,
    ) -> None:
        if k <= 0.0:
            raise ModuleContractViolationError(f"RRF smoothing parameter k must be > 0.0, got {k}.")
        self.k = k
        self.weights = dict(weights or {})
        for ch, w in self.weights.items():
            if w < 0.0:
                raise ModuleContractViolationError(
                    f"RRF weight for channel '{ch}' must be >= 0.0, got {w}."
                )

    def combine(
        self,
        channel_results: Dict[RetrievalChannel, List[RetrievalCandidate]],
        top_k: int,
    ) -> List[RetrievalCandidate]:
        """Combines ranked candidate lists into a unified deterministic ranking."""
        if top_k <= 0:
            raise ModuleContractViolationError(f"top_k must be > 0, got {top_k}.")

        # candidate_id -> aggregated data
        accumulated_scores: Dict[str, float] = {}
        candidate_contents: Dict[str, str] = {}
        candidate_metadata: Dict[str, Dict[str, Any]] = {}
        candidate_coords: Dict[str, Dict[str, EvidenceCoordinate]] = {}
        source_scores_map: Dict[str, Dict[str, float]] = {}

        for channel, candidates in channel_results.items():
            weight = self.weights.get(channel, 1.0)
            if weight <= 0.0:
                continue

            for cand in candidates:
                cid = cand.candidate_id
                rrf_contrib = weight / (self.k + float(cand.rank))
                accumulated_scores[cid] = accumulated_scores.get(cid, 0.0) + rrf_contrib

                if (
                    cid not in candidate_contents
                    or len(cand.content) > len(candidate_contents[cid])
                ):
                    candidate_contents[cid] = cand.content


                if cid not in candidate_metadata:
                    candidate_metadata[cid] = {}
                candidate_metadata[cid].update(cand.metadata)

                if cid not in candidate_coords:
                    candidate_coords[cid] = {}
                for coord in cand.coordinates:
                    candidate_coords[cid][coord.coordinate_id] = coord

                if cid not in source_scores_map:
                    source_scores_map[cid] = {}
                source_scores_map[cid][channel.value] = cand.score

        # Deterministic sorting: RRF score descending, then candidate_id ascending
        sorted_cids = sorted(
            accumulated_scores.keys(),
            key=lambda cid: (-accumulated_scores[cid], cid),
        )

        fused_candidates: List[RetrievalCandidate] = []
        for rank, cid in enumerate(sorted_cids[:top_k], start=1):
            fused_candidates.append(
                RetrievalCandidate(
                    candidate_id=cid,
                    content=candidate_contents.get(cid, ""),
                    score=accumulated_scores[cid],
                    channel=RetrievalChannel.HYBRID,
                    rank=rank,
                    metadata=candidate_metadata.get(cid, {}),
                    coordinates=list(candidate_coords.get(cid, {}).values()),
                    source_scores=source_scores_map.get(cid, {}),
                )
            )

        return fused_candidates
