"""Calibrated multi-dimensional scoring engine for scientific research gaps.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, ADR-004, and Epistemic Principles:
- Calibrated composite scoring: f(Novelty, Grounding, Feasibility, Significance, 1 - Uncertainty)
- Strict prohibition of global novelty claims when literature corpus coverage is bounded
- Automated epistemic uncertainty adjustments for sparse corpus sampling
"""

from __future__ import annotations

import math
from typing import Optional

from laris.core.errors import EpistemicOverreachError, ModuleContractViolationError
from laris.layers.layer7_reasoning.schemas import CalibratedGapScores, CorpusScope


class CalibratedGapScoringEngine:
    """Computes calibrated multi-dimensional gap scores and enforces corpus boundedness."""

    def __init__(
        self,
        weight_novelty: float = 0.25,
        weight_grounding: float = 0.25,
        weight_feasibility: float = 0.20,
        weight_significance: float = 0.20,
        weight_certainty: float = 0.10,
    ) -> None:
        total = (
            weight_novelty
            + weight_grounding
            + weight_feasibility
            + weight_significance
            + weight_certainty
        )
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ModuleContractViolationError(
                f"Dimension weights must sum to 1.0 (got {total:.4f})."
            )
        weights = [
            weight_novelty,
            weight_grounding,
            weight_feasibility,
            weight_significance,
            weight_certainty,
        ]
        if any(w < 0.0 for w in weights):
            raise ModuleContractViolationError("Dimension weights must be non-negative.")

        self.w_novelty = weight_novelty
        self.w_grounding = weight_grounding
        self.w_feasibility = weight_feasibility
        self.w_significance = weight_significance
        self.w_certainty = weight_certainty

    def score_gap(
        self,
        novelty: float,
        grounding: float,
        feasibility: float,
        significance: float,
        uncertainty: float,
        corpus_scope: Optional[CorpusScope] = None,
        assert_global_novelty: bool = False,
    ) -> CalibratedGapScores:
        """Computes calibrated multi-dimensional score model for a research gap.

        Parameters
        ----------
        novelty : float
            Corpus-relative novelty score in [0.0, 1.0].
        grounding : float
            Empirical evidence grounding score in [0.0, 1.0].
        feasibility : float
            Technical feasibility of validation in [0.0, 1.0].
        significance : float
            Scientific significance / impact score in [0.0, 1.0].
        uncertainty : float
            Epistemic uncertainty estimate in [0.0, 1.0].
        corpus_scope : Optional[CorpusScope]
            Corpus boundary specification. Defaults to bounded if omitted.
        assert_global_novelty : bool
            Whether caller attempts to claim global novelty. Strictly forbidden
            when corpus coverage is bounded.

        Returns
        -------
        CalibratedGapScores
            Fully validated and calibrated gap scores.
        """
        # Validate input domain
        metrics = {
            "novelty": novelty,
            "grounding": grounding,
            "feasibility": feasibility,
            "significance": significance,
            "uncertainty": uncertainty,
        }
        for name, val in metrics.items():
            if math.isnan(val) or math.isinf(val):
                raise ModuleContractViolationError(
                    f"Gap score input '{name}' must be a finite float."
                )
            if not (0.0 <= val <= 1.0):
                raise ModuleContractViolationError(
                    f"Gap score input '{name}' ({val}) must be within [0.0, 1.0]."
                )

        # Corpus boundedness rule
        is_bounded = corpus_scope.is_bounded if corpus_scope is not None else True
        if is_bounded and assert_global_novelty:
            raise EpistemicOverreachError(
                "Global novelty claims are strictly prohibited when literature corpus coverage "
                "is bounded. Gaps must be qualified as corpus-bounded."
            )

        # Sparse corpus coverage adjustment:
        # If corpus has very few documents (< 5), minimum epistemic uncertainty is elevated
        effective_uncertainty = uncertainty
        if corpus_scope is not None and corpus_scope.document_count < 5:
            effective_uncertainty = max(effective_uncertainty, 0.20)

        # Composite score calculation
        certainty = 1.0 - effective_uncertainty
        composite = (
            self.w_novelty * novelty
            + self.w_grounding * grounding
            + self.w_feasibility * feasibility
            + self.w_significance * significance
            + self.w_certainty * certainty
        )
        composite = max(0.0, min(1.0, composite))

        return CalibratedGapScores(
            novelty=novelty,
            grounding=grounding,
            feasibility=feasibility,
            significance=significance,
            uncertainty=effective_uncertainty,
            composite_score=round(composite, 4),
            corpus_bounded=is_bounded,
            is_global_claim=assert_global_novelty,
        )
