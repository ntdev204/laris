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

from laris.core.errors import ModuleContractViolationError, ProvenanceViolationError
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
