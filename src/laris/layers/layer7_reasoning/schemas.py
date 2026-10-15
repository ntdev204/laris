"""Schemas for Layer 7 Research Reasoning Engine adhering to Boundary G (MOD-REASON-001).

Adheres to DOC-SPEC-MOD-001, ADR-001, and ADR-004:
- Comparable experimental matrix records with condition alignment
- Structured conflict records distinguishing genuine contradictions from incomparable setups
- Epistemic evidence coordinate anchoring for 100% of reasoning outputs
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    EpistemicOverreachError,
    ModuleContractViolationError,
    ProvenanceViolationError,
)
from laris.core.schemas import EvidenceCoordinate


class MetricDirection(str, Enum):
    """Directionality optimization goal for experimental metrics."""

    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class CaveatSeverity(str, Enum):
    """Severity classification for experimental comparability caveats."""

    INFORMATIONAL = "INFORMATIONAL"
    CAUTION = "CAUTION"
    INCOMPARABLE = "INCOMPARABLE"


class ConflictType(str, Enum):
    """Taxonomy of scientific contradictions and discrepancies across literature."""

    DIRECT_EMPIRICAL_CONTRADICTION = "DIRECT_EMPIRICAL_CONTRADICTION"
    CROSS_METHOD_SUPERIORITY_CONTRADICTION = "CROSS_METHOD_SUPERIORITY_CONTRADICTION"
    BOUNDARY_CONDITION_DISCREPANCY = "BOUNDARY_CONDITION_DISCREPANCY"
    APPARENT_CONFLICT_INCOMPARABLE = "APPARENT_CONFLICT_INCOMPARABLE"


@dataclass(frozen=True)
class StudyFinding:
    """Discrete experimental finding from a scientific study anchored to evidence."""

    finding_id: str
    document_id: str
    method_name: str
    dataset_name: str
    metric_name: str
    metric_value: float
    claim_id: Optional[str] = None
    dataset_split: Optional[str] = None
    metric_direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    condition_parameters: Dict[str, Any] = field(default_factory=dict)
    evidence_coordinates: List[EvidenceCoordinate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.finding_id or not self.finding_id.strip():
            raise ModuleContractViolationError("StudyFinding finding_id must not be empty.")
        if not self.document_id or not self.document_id.strip():
            raise ModuleContractViolationError("StudyFinding document_id must not be empty.")
        if not self.method_name or not self.method_name.strip():
            raise ModuleContractViolationError("StudyFinding method_name must not be empty.")
        if not self.dataset_name or not self.dataset_name.strip():
            raise ModuleContractViolationError("StudyFinding dataset_name must not be empty.")
        if not self.metric_name or not self.metric_name.strip():
            raise ModuleContractViolationError("StudyFinding metric_name must not be empty.")
        if math.isnan(self.metric_value) or math.isinf(self.metric_value):
            raise ModuleContractViolationError("StudyFinding metric_value must be a finite float.")
        if not self.evidence_coordinates:
            raise ProvenanceViolationError(
                f"StudyFinding '{self.finding_id}' lacks verified EvidenceCoordinate records."
            )


@dataclass(frozen=True)
class ComparabilityCaveat:
    """Caveat explaining differences or limitations in experimental comparability."""

    caveat_type: str
    description: str
    severity: CaveatSeverity = CaveatSeverity.INFORMATIONAL

    def __post_init__(self) -> None:
        if not self.caveat_type or not self.caveat_type.strip():
            raise ModuleContractViolationError("ComparabilityCaveat caveat_type must not be empty.")
        if not self.description or not self.description.strip():
            raise ModuleContractViolationError("ComparabilityCaveat description must not be empty.")


@dataclass(frozen=True)
class ComparativeCell:
    """Pairwise comparison between two experimental study findings."""

    cell_id: str
    finding_a_id: str
    finding_b_id: str
    is_comparable: bool
    caveats: List[ComparabilityCaveat] = field(default_factory=list)
    delta: Optional[float] = None
    ratio: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.cell_id or not self.cell_id.strip():
            raise ModuleContractViolationError("ComparativeCell cell_id must not be empty.")
        if not self.finding_a_id or not self.finding_a_id.strip():
            raise ModuleContractViolationError("ComparativeCell finding_a_id must not be empty.")
        if not self.finding_b_id or not self.finding_b_id.strip():
            raise ModuleContractViolationError("ComparativeCell finding_b_id must not be empty.")


@dataclass(frozen=True)
class ComparativeMatrix:
    """Multi-study comparative matrix aligning experimental findings and conditions."""

    matrix_id: str
    target_task_or_domain: str
    findings: List[StudyFinding]
    cells: List[ComparativeCell]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.matrix_id or not self.matrix_id.strip():
            raise ModuleContractViolationError("ComparativeMatrix matrix_id must not be empty.")
        if not self.target_task_or_domain or not self.target_task_or_domain.strip():
            raise ModuleContractViolationError(
                "ComparativeMatrix target_task_or_domain must not be empty."
            )


@dataclass(frozen=True)
class ConflictRecord:
    """Structured record of a cross-paper empirical conflict or apparent discrepancy."""

    conflict_id: str
    conflict_type: ConflictType
    finding_a_id: str
    finding_b_id: str
    description: str
    is_genuine_contradiction: bool
    evidence_coordinates: List[EvidenceCoordinate]
    comparability_caveats: List[ComparabilityCaveat] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.conflict_id or not self.conflict_id.strip():
            raise ModuleContractViolationError("ConflictRecord conflict_id must not be empty.")
        if not self.finding_a_id or not self.finding_a_id.strip():
            raise ModuleContractViolationError("ConflictRecord finding_a_id must not be empty.")
        if not self.finding_b_id or not self.finding_b_id.strip():
            raise ModuleContractViolationError("ConflictRecord finding_b_id must not be empty.")
        if not self.description or not self.description.strip():
            raise ModuleContractViolationError("ConflictRecord description must not be empty.")
        if not self.evidence_coordinates:
            raise ProvenanceViolationError(
                f"ConflictRecord '{self.conflict_id}' lacks verified EvidenceCoordinate records."
            )


class GapClass(str, Enum):
    """Canonical 12-class research gap typology per DATA_SCHEMAS.md and MOD-REASON-001."""

    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    METHODOLOGICAL_GAP = "METHODOLOGICAL_GAP"
    MEASUREMENT_EVALUATION_GAP = "MEASUREMENT_EVALUATION_GAP"
    DATASET_DOMAIN_GAP = "DATASET_DOMAIN_GAP"
    GENERALIZATION_GAP = "GENERALIZATION_GAP"
    REPRODUCIBILITY_GAP = "REPRODUCIBILITY_GAP"
    CONFLICTING_EVIDENCE_GAP = "CONFLICTING_EVIDENCE_GAP"
    ASSUMPTION_BOUNDARY_GAP = "ASSUMPTION_BOUNDARY_GAP"
    INTEGRATION_INTERDISCIPLINARY_GAP = "INTEGRATION_INTERDISCIPLINARY_GAP"
    DEPLOYMENT_RESOURCE_GAP = "DEPLOYMENT_RESOURCE_GAP"
    TEMPORAL_GAP = "TEMPORAL_GAP"
    UNDEREXPLORED_RESEARCH_QUESTION = "UNDEREXPLORED_RESEARCH_QUESTION"


@dataclass(frozen=True)
class CalibratedGapScores:
    """Calibrated multi-dimensional scoring model for candidate research gaps.

    In accordance with ADR-001 and Epistemic Principles:
    - All dimensions are normalized to the closed interval [0.0, 1.0].
    - Global novelty claims are strictly prohibited when corpus coverage is bounded.
    """

    novelty: float
    grounding: float
    feasibility: float
    significance: float
    uncertainty: float
    composite_score: float
    corpus_bounded: bool = True
    is_global_claim: bool = False

    def __post_init__(self) -> None:
        scores = {
            "novelty": self.novelty,
            "grounding": self.grounding,
            "feasibility": self.feasibility,
            "significance": self.significance,
            "uncertainty": self.uncertainty,
            "composite_score": self.composite_score,
        }
        for name, val in scores.items():
            if math.isnan(val) or math.isinf(val):
                raise ModuleContractViolationError(
                    f"CalibratedGapScores {name} must be a finite float."
                )
            if not (0.0 <= val <= 1.0):
                raise ModuleContractViolationError(
                    f"CalibratedGapScores {name} ({val}) must be within [0.0, 1.0]."
                )

        if self.corpus_bounded and self.is_global_claim:
            raise EpistemicOverreachError(
                "Global novelty claims are strictly prohibited when corpus coverage is bounded. "
                "Claims must be qualified as corpus-bounded gaps."
            )


@dataclass(frozen=True)
class ValidationPlan:
    """Actionable validation protocol design formulated for an identified research gap."""

    proposed_methodology: str
    required_datasets: List[str]
    expected_baselines: List[str]
    evaluation_metrics: List[str]

    def __post_init__(self) -> None:
        if not self.proposed_methodology or not self.proposed_methodology.strip():
            raise ModuleContractViolationError(
                "ValidationPlan proposed_methodology must not be empty."
            )
        if not self.required_datasets:
            raise ModuleContractViolationError(
                "ValidationPlan required_datasets must contain at least one dataset."
            )
        if not self.expected_baselines:
            raise ModuleContractViolationError(
                "ValidationPlan expected_baselines must contain at least one baseline."
            )
        if not self.evaluation_metrics:
            raise ModuleContractViolationError(
                "ValidationPlan evaluation_metrics must contain at least one metric."
            )


@dataclass(frozen=True)
class CorpusScope:
    """Corpus boundary definition preventing epistemic overreach in novelty claims."""

    scope_id: str
    document_count: int
    is_bounded: bool = True
    inclusion_criteria: List[str] = field(default_factory=list)
    exclusion_criteria: List[str] = field(default_factory=list)
    coverage_notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.scope_id or not self.scope_id.strip():
            raise ModuleContractViolationError("CorpusScope scope_id must not be empty.")
        if self.document_count < 0:
            raise ModuleContractViolationError(
                "CorpusScope document_count must be a non-negative integer."
            )


@dataclass(frozen=True)
class ResearchGap:
    """Complete research gap entity with 12-class taxonomy, provenance, and scoring."""

    gap_id: str
    gap_class: GapClass
    title: str
    description: str
    epistemic_rationale: str
    supporting_evidence: List[EvidenceCoordinate]
    calibrated_scores: CalibratedGapScores
    validation_plan: ValidationPlan
    counter_evidence_searched: bool = False
    corpus_scope: Optional[CorpusScope] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.gap_id or not self.gap_id.strip():
            raise ModuleContractViolationError("ResearchGap gap_id must not be empty.")
        if not self.title or not self.title.strip():
            raise ModuleContractViolationError("ResearchGap title must not be empty.")
        if not self.description or not self.description.strip():
            raise ModuleContractViolationError("ResearchGap description must not be empty.")
        if not self.epistemic_rationale or not self.epistemic_rationale.strip():
            raise ModuleContractViolationError(
                "ResearchGap epistemic_rationale must not be empty."
            )
        if not self.supporting_evidence:
            raise ProvenanceViolationError(
                f"ResearchGap '{self.gap_id}' lacks verified EvidenceCoordinate records."
            )
        if self.corpus_scope and self.corpus_scope.is_bounded:
            if self.calibrated_scores.is_global_claim:
                raise EpistemicOverreachError(
                    f"ResearchGap '{self.gap_id}' asserts global novelty but corpus scope "
                    f"'{self.corpus_scope.scope_id}' is bounded."
                )

