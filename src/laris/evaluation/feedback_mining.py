"""Expert feedback capture, hard-negative mining, and contamination isolation.

Adheres to DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #72:
- Human-in-the-loop expert review feedback capture with complete lineage provenance
- Hard-negative perturbation and contrastive mining across scientific error taxons
- Strict zero-contamination isolation ensuring training samples never infect frozen evaluation sets
- Partition metadata governance guaranteeing distinct split allocations
"""

from __future__ import annotations

import datetime
import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    BenchmarkContaminationError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.evaluation.schemas import (
    FrozenBenchmarkManifest,
    ScientificErrorCategory,
)


class ReviewerDecision(str, Enum):
    """Categorical assessment decision issued during qualitative expert review."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVISE = "REVISE"
    FLAG_CONTRADICTION = "FLAG_CONTRADICTION"
    FLAG_OVERREACH = "FLAG_OVERREACH"
    FLAG_PROVENANCE_GAP = "FLAG_PROVENANCE_GAP"


class FeedbackSource(str, Enum):
    """Origin of qualitative feedback annotations."""

    HUMAN_EXPERT = "HUMAN_EXPERT"
    AUTOMATED_AUDITOR = "AUTOMATED_AUDITOR"
    SYNTHETIC_CHALLENGE = "SYNTHETIC_CHALLENGE"


class HardNegativeStrategy(str, Enum):
    """Scientific perturbation strategy used to mine hard-negative examples."""

    CONDITION_INVERSION = "CONDITION_INVERSION"
    ENTITY_SUBSTITUTION = "ENTITY_SUBSTITUTION"
    NUMERICAL_PERTURBATION = "NUMERICAL_PERTURBATION"
    CAUSAL_DIRECTION_REVERSAL = "CAUSAL_DIRECTION_REVERSAL"
    PROVENANCE_CORRUPTION = "PROVENANCE_CORRUPTION"


@dataclass(frozen=True)
class ExpertFeedbackRecord:
    """Immutable audit record of qualitative expert review feedback with provenance lineage."""

    feedback_id: str
    target_item_id: str
    reviewer_id: str
    decision: ReviewerDecision
    rationale: str
    source: FeedbackSource = FeedbackSource.HUMAN_EXPERT
    corrected_output: Optional[Dict[str, Any]] = None
    provenance_coordinate: Optional[EvidenceCoordinate] = None
    timestamp_iso: str = ""
    lineage_parent_ids: List[str] = field(default_factory=list)
    context_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate feedback record contracts and populate default timestamp."""
        if not self.feedback_id or not self.feedback_id.strip():
            raise ModuleContractViolationError("feedback_id cannot be empty.")
        if not self.target_item_id or not self.target_item_id.strip():
            raise ModuleContractViolationError("target_item_id cannot be empty.")
        if not self.reviewer_id or not self.reviewer_id.strip():
            raise ModuleContractViolationError("reviewer_id cannot be empty.")
        if not self.rationale or not self.rationale.strip():
            raise ModuleContractViolationError("rationale cannot be empty.")

        if not self.timestamp_iso:
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            object.__setattr__(self, "timestamp_iso", now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Convert feedback record to a JSON-serializable dictionary."""
        coord_dict = None
        if self.provenance_coordinate:
            c = self.provenance_coordinate
            coord_dict = {
                "coordinate_id": c.coordinate_id,
                "document_id": c.document_id,
                "document_sha256": c.document_sha256,
                "page_number": c.page_number,
                "section_identifier": c.section_identifier,
                "paragraph_index": c.paragraph_index,
                "sentence_index": c.sentence_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "verbatim_snippet": c.verbatim_snippet,
                "extraction_confidence": c.extraction_confidence,
            }

        return {
            "feedback_id": self.feedback_id,
            "target_item_id": self.target_item_id,
            "reviewer_id": self.reviewer_id,
            "decision": self.decision.value,
            "rationale": self.rationale,
            "source": self.source.value,
            "corrected_output": dict(self.corrected_output) if self.corrected_output else None,
            "provenance_coordinate": coord_dict,
            "timestamp_iso": self.timestamp_iso,
            "lineage_parent_ids": list(self.lineage_parent_ids),
            "context_metadata": dict(self.context_metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExpertFeedbackRecord:
        """Construct feedback record from dictionary."""
        coord_data = data.get("provenance_coordinate")
        coord = EvidenceCoordinate(**coord_data) if coord_data else None
        return cls(
            feedback_id=data["feedback_id"],
            target_item_id=data["target_item_id"],
            reviewer_id=data["reviewer_id"],
            decision=ReviewerDecision(data["decision"]),
            rationale=data["rationale"],
            source=FeedbackSource(data.get("source", FeedbackSource.HUMAN_EXPERT.value)),
            corrected_output=data.get("corrected_output"),
            provenance_coordinate=coord,
            timestamp_iso=data.get("timestamp_iso", ""),
            lineage_parent_ids=list(data.get("lineage_parent_ids", [])),
            context_metadata=dict(data.get("context_metadata", {})),
        )


@dataclass(frozen=True)
class HardNegativeSample:
    """Adversarially perturbed or mined hard negative example anchored to review lineage."""

    sample_id: str
    source_feedback_id: str
    hard_negative_category: ScientificErrorCategory
    strategy: HardNegativeStrategy
    premise: str
    hypothesis: str
    perturbed_condition: str
    expected_label: str = "CONTRADICTION"
    difficulty_score: float = 0.85
    is_training_eligible: bool = True
    split_assignment: str = "train"
    checksum_sha256: str = ""
    provenance_coordinate: Optional[EvidenceCoordinate] = None

    def __post_init__(self) -> None:
        """Validate sample contracts, enforce training split isolation, and compute hash."""
        if not self.sample_id or not self.sample_id.strip():
            raise ModuleContractViolationError("sample_id cannot be empty.")
        if not self.source_feedback_id or not self.source_feedback_id.strip():
            raise ModuleContractViolationError("source_feedback_id cannot be empty.")
        if not self.premise or not self.premise.strip():
            raise ModuleContractViolationError("premise cannot be empty.")
        if not self.hypothesis or not self.hypothesis.strip():
            raise ModuleContractViolationError("hypothesis cannot be empty.")
        if not self.perturbed_condition or not self.perturbed_condition.strip():
            raise ModuleContractViolationError("perturbed_condition cannot be empty.")

        if not (0.0 <= self.difficulty_score <= 1.0):
            raise ModuleContractViolationError(
                f"difficulty_score {self.difficulty_score} must be between 0.0 and 1.0."
            )

        # Invariant: Training-eligible hard negatives must NEVER be routed to test or val splits
        if self.is_training_eligible and self.split_assignment in ("val", "test", "evaluation"):
            raise BenchmarkContaminationError(
                f"HardNegativeSample '{self.sample_id}' is marked training-eligible but assigned "
                f"to evaluation split '{self.split_assignment}'. Cross-split leakage prohibited."
            )

        computed = self._compute_checksum()
        if self.checksum_sha256 and self.checksum_sha256 != computed:
            raise ModuleContractViolationError(
                f"HardNegativeSample checksum mismatch: expected '{self.checksum_sha256}', "
                f"calculated '{computed}'."
            )
        if not self.checksum_sha256:
            object.__setattr__(self, "checksum_sha256", computed)

    def _compute_checksum(self) -> str:
        """Calculate canonical SHA-256 digest across sample inputs and perturbation."""
        content = json.dumps(
            {
                "sample_id": self.sample_id,
                "source_feedback_id": self.source_feedback_id,
                "hard_negative_category": self.hard_negative_category.value,
                "strategy": self.strategy.value,
                "premise": self.premise,
                "hypothesis": self.hypothesis,
                "perturbed_condition": self.perturbed_condition,
                "expected_label": self.expected_label,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert sample to a JSON-serializable dictionary."""
        coord_dict = None
        if self.provenance_coordinate:
            c = self.provenance_coordinate
            coord_dict = {
                "coordinate_id": c.coordinate_id,
                "document_id": c.document_id,
                "document_sha256": c.document_sha256,
                "page_number": c.page_number,
                "section_identifier": c.section_identifier,
                "paragraph_index": c.paragraph_index,
                "sentence_index": c.sentence_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "verbatim_snippet": c.verbatim_snippet,
                "extraction_confidence": c.extraction_confidence,
            }

        return {
            "sample_id": self.sample_id,
            "source_feedback_id": self.source_feedback_id,
            "hard_negative_category": self.hard_negative_category.value,
            "strategy": self.strategy.value,
            "premise": self.premise,
            "hypothesis": self.hypothesis,
            "perturbed_condition": self.perturbed_condition,
            "expected_label": self.expected_label,
            "difficulty_score": self.difficulty_score,
            "is_training_eligible": self.is_training_eligible,
            "split_assignment": self.split_assignment,
            "checksum_sha256": self.checksum_sha256,
            "provenance_coordinate": coord_dict,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> HardNegativeSample:
        """Construct hard negative sample from dictionary."""
        coord_data = data.get("provenance_coordinate")
        coord = EvidenceCoordinate(**coord_data) if coord_data else None
        return cls(
            sample_id=data["sample_id"],
            source_feedback_id=data["source_feedback_id"],
            hard_negative_category=ScientificErrorCategory(data["hard_negative_category"]),
            strategy=HardNegativeStrategy(data["strategy"]),
            premise=data["premise"],
            hypothesis=data["hypothesis"],
            perturbed_condition=data["perturbed_condition"],
            expected_label=data.get("expected_label", "CONTRADICTION"),
            difficulty_score=float(data.get("difficulty_score", 0.85)),
            is_training_eligible=bool(data.get("is_training_eligible", True)),
            split_assignment=data.get("split_assignment", "train"),
            checksum_sha256=data.get("checksum_sha256", ""),
            provenance_coordinate=coord,
        )


class FeedbackMiningRepository:
    """Thread-safe repository for expert review lineage, negative mining, and leakage isolation."""

    def __init__(self) -> None:
        self._feedback_records: Dict[str, ExpertFeedbackRecord] = {}
        self._hard_negatives: Dict[str, HardNegativeSample] = {}
        self._lock = threading.Lock()

    def record_feedback(self, feedback: ExpertFeedbackRecord) -> None:
        """Record an expert review feedback entry into the audit trail."""
        with self._lock:
            self._feedback_records[feedback.feedback_id] = feedback

    def get_feedback(self, feedback_id: str) -> ExpertFeedbackRecord:
        """Retrieve feedback entry by unique identifier."""
        with self._lock:
            if feedback_id not in self._feedback_records:
                raise ModuleContractViolationError(
                    f"Feedback record '{feedback_id}' not found."
                )
            return self._feedback_records[feedback_id]

    def list_feedback(self) -> List[ExpertFeedbackRecord]:
        """Return list of all registered expert feedback entries."""
        with self._lock:
            return list(self._feedback_records.values())

    def mine_hard_negative(
        self,
        feedback: ExpertFeedbackRecord,
        strategy: HardNegativeStrategy,
        premise: str,
        hypothesis: str,
        perturbed_condition: str,
        expected_label: str = "CONTRADICTION",
        difficulty_score: float = 0.85,
        category: Optional[ScientificErrorCategory] = None,
        sample_id: Optional[str] = None,
    ) -> HardNegativeSample:
        """Mine and register an adversarial hard negative sample derived from review feedback."""
        # Derive error category from reviewer decision if not explicitly provided
        cat = category
        if cat is None:
            if feedback.decision == ReviewerDecision.FLAG_CONTRADICTION:
                cat = ScientificErrorCategory.REASONING_FAILURE
            elif feedback.decision == ReviewerDecision.FLAG_OVERREACH:
                cat = ScientificErrorCategory.EPISTEMIC_FAILURE
            elif feedback.decision == ReviewerDecision.FLAG_PROVENANCE_GAP:
                cat = ScientificErrorCategory.PROVENANCE_FAILURE
            else:
                cat = ScientificErrorCategory.EXTRACTION_FAILURE

        with self._lock:
            if sample_id:
                final_id = sample_id
            else:
                base_id = f"HN-{feedback.feedback_id}-{strategy.value.lower()}"
                if base_id not in self._hard_negatives:
                    final_id = base_id
                else:
                    counter = 1
                    while f"{base_id}-{counter:03d}" in self._hard_negatives:
                        counter += 1
                    final_id = f"{base_id}-{counter:03d}"

            sample = HardNegativeSample(
                sample_id=final_id,
                source_feedback_id=feedback.feedback_id,
                hard_negative_category=cat,
                strategy=strategy,
                premise=premise,
                hypothesis=hypothesis,
                perturbed_condition=perturbed_condition,
                expected_label=expected_label,
                difficulty_score=difficulty_score,
                is_training_eligible=True,
                split_assignment="train",
                provenance_coordinate=feedback.provenance_coordinate,
            )

            self._hard_negatives[sample.sample_id] = sample
            # Ensure feedback is also stored if not already registered
            if feedback.feedback_id not in self._feedback_records:
                self._feedback_records[feedback.feedback_id] = feedback

        return sample

    def record_hard_negative(self, sample: HardNegativeSample) -> None:
        """Register a pre-constructed hard negative sample."""
        with self._lock:
            self._hard_negatives[sample.sample_id] = sample

    def get_hard_negative(self, sample_id: str) -> HardNegativeSample:
        """Retrieve mined hard negative sample by ID."""
        with self._lock:
            if sample_id not in self._hard_negatives:
                raise ModuleContractViolationError(
                    f"Hard negative sample '{sample_id}' not found."
                )
            return self._hard_negatives[sample_id]

    def list_hard_negatives(self) -> List[HardNegativeSample]:
        """Return list of all registered hard negative samples."""
        with self._lock:
            return list(self._hard_negatives.values())

    def assert_zero_contamination(
        self,
        samples: List[HardNegativeSample],
        frozen_manifests: List[FrozenBenchmarkManifest],
    ) -> None:
        """Verify zero contamination between candidate training samples and frozen evaluation sets.

        Raises:
            BenchmarkContaminationError: If any sample shares identity, payload, or hash with
                                         any item in the frozen benchmark manifests.
        """
        # Build index of frozen test item signatures
        frozen_checksums: Dict[str, str] = {}
        frozen_item_ids: Dict[str, str] = {}

        for manifest in frozen_manifests:
            for item in manifest.items:
                frozen_checksums[item.checksum_sha256] = manifest.manifest_id
                frozen_item_ids[item.item_id] = manifest.manifest_id

        for sample in samples:
            # Check ID overlap
            if sample.sample_id in frozen_item_ids:
                manifest_id = frozen_item_ids[sample.sample_id]
                raise BenchmarkContaminationError(
                    f"Contamination detected: sample ID '{sample.sample_id}' matches an item "
                    f"in frozen evaluation suite '{manifest_id}'."
                )

            # Check exact hash overlap
            if sample.checksum_sha256 in frozen_checksums:
                manifest_id = frozen_checksums[sample.checksum_sha256]
                raise BenchmarkContaminationError(
                    f"Contamination detected: sample '{sample.sample_id}' checksum matches an "
                    f"item in frozen evaluation suite '{manifest_id}'."
                )

            # Check split assignment
            if sample.split_assignment in ("val", "test", "evaluation"):
                raise BenchmarkContaminationError(
                    f"Contamination detected: sample '{sample.sample_id}' is assigned to "
                    f"evaluation split '{sample.split_assignment}'."
                )

    def export_training_split(
        self,
        samples: Optional[List[HardNegativeSample]] = None,
        frozen_manifests: Optional[List[FrozenBenchmarkManifest]] = None,
    ) -> List[Dict[str, Any]]:
        """Export training-ready hard negative samples with strict contamination validation."""
        target_samples = samples if samples is not None else self.list_hard_negatives()
        if frozen_manifests:
            self.assert_zero_contamination(target_samples, frozen_manifests)

        export_list: List[Dict[str, Any]] = []
        for s in target_samples:
            if not s.is_training_eligible:
                continue
            item_dict = s.to_dict()
            item_dict["partition"] = "train"
            export_list.append(item_dict)

        return export_list
