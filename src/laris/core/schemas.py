"""Canonical data schemas for LARIS adhering to DOC-SPEC-SCHEMA-001."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict


class EpistemicStatus(str, Enum):
    """Seven-class epistemic taxonomy for scientific assertions."""
    DIRECT_AUTHOR_CLAIM = "DIRECT_AUTHOR_CLAIM"
    EMPIRICALLY_SUPPORTED_FINDING = "EMPIRICALLY_SUPPORTED_FINDING"
    MULTI_SOURCE_SYNTHESIS = "MULTI_SOURCE_SYNTHESIS"
    HYPOTHESIS = "HYPOTHESIS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNVERIFIABLE_ASSERTION = "UNVERIFIABLE_ASSERTION"


@dataclass(frozen=True)
class EvidenceCoordinate:
    """Immutable coordinate anchoring a discrete evidence snippet to its physical source."""
    coordinate_id: str
    document_id: str
    document_sha256: str
    page_number: int
    section_identifier: str
    paragraph_index: int
    sentence_index: int
    char_start: int
    char_end: int
    verbatim_snippet: str
    extraction_confidence: float = 1.0

    def __post_init__(self):
        if self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ValueError("Invalid character offset range")
        if not (0.0 <= self.extraction_confidence <= 1.0):
            raise ValueError("extraction_confidence must be between 0.0 and 1.0")


@dataclass
class ScientificClaim:
    """Extracted scientific proposition bound to verified evidence coordinates."""
    claim_id: str
    canonical_text: str
    epistemic_status: EpistemicStatus
    evidence_coordinates: List[str]
    related_methods: List[str] = field(default_factory=list)
    measured_metrics: List[str] = field(default_factory=list)
    confidence_score: float = 1.0

    def __post_init__(self):
        if not self.evidence_coordinates:
            raise ValueError("ScientificClaim MUST reference at least one evidence_coordinate")
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("confidence_score must be between 0.0 and 1.0")


class ResearchGapClass(str, Enum):
    """Twelve-class canonical research gap taxonomy."""
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
class CalibratedScores:
    """Multi-dimensional calibrated evaluation scores for a candidate gap."""
    novelty: float
    grounding: float
    feasibility: float
    significance: float
    uncertainty: float

    @property
    def composite_score(self) -> float:
        """Computes calibrated composite gap score."""
        return (
            0.25 * self.novelty +
            0.25 * self.grounding +
            0.20 * self.feasibility +
            0.20 * self.significance +
            0.10 * (1.0 - self.uncertainty)
        )


@dataclass
class ValidationPlan:
    """Concrete empirical validation protocol for an identified research gap."""
    proposed_methodology: str
    required_datasets: List[str]
    expected_baselines: List[str]
    evaluation_metrics: List[str]


@dataclass
class ResearchGap:
    """Formal research gap entity with evidence rationale and validation plan."""
    gap_id: str
    gap_class: ResearchGapClass
    title: str
    description: str
    epistemic_rationale: str
    supporting_evidence: List[str]
    calibrated_scores: CalibratedScores
    validation_plan: ValidationPlan
    counter_evidence_searched: bool = True


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Real-time physical hardware telemetry snapshot."""
    timestamp_iso: str
    vram_allocated_bytes: int
    vram_reserved_bytes: int
    host_ram_used_bytes: int
    active_specialist_id: str
    active_param_count: int
    weight_transfer_ms: float = 0.0
    inference_latency_ms: float = 0.0

    @property
    def vram_allocated_gb(self) -> float:
        return self.vram_allocated_bytes / (1024 ** 3)
