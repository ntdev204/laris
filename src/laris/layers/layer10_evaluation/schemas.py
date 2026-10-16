"""Data contracts and schemas for Layer 10 Evaluation, Feedback & Learning.

Adheres to DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #71:
- Scientific error taxonomy (provenance, epistemic, extraction, reasoning, system)
- Immutable frozen benchmark manifests with cryptographic SHA-256 integrity
- Regression gate thresholds and baseline comparison schemas
- Evaluation run requests and comprehensive structured benchmark reports
- Zero training set contamination invariants protecting evaluation splits
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from laris.core.errors import (
    BenchmarkContaminationError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate


class ScientificErrorCategory(str, Enum):
    """Categorical classification of failures across scientific reasoning pipelines."""

    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    EPISTEMIC_FAILURE = "EPISTEMIC_FAILURE"
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"
    REASONING_FAILURE = "REASONING_FAILURE"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


class ErrorSeverity(str, Enum):
    """Severity level of an identified scientific failure or anomaly."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BenchmarkSuiteType(str, Enum):
    """Standardized benchmark suite domains adhering to ADR-008."""

    SEMANTIC_EQUIVALENCE = "SEMANTIC_EQUIVALENCE"
    NLI_CONTRADICTION = "NLI_CONTRADICTION"
    SCIENTIFIC_EXTRACTION = "SCIENTIFIC_EXTRACTION"
    CROSS_PAPER_SYNTHESIS = "CROSS_PAPER_SYNTHESIS"
    RESEARCH_GAP_VALIDATION = "RESEARCH_GAP_VALIDATION"
    RESOURCE_EFFICIENCY = "RESOURCE_EFFICIENCY"


@dataclass(frozen=True)
class ScientificErrorRecord:
    """Structured record of a pipeline error categorized under the scientific taxonomy."""

    error_id: str
    category: ScientificErrorCategory
    severity: ErrorSeverity
    source_layer: str
    description: str
    timestamp_iso: str
    provenance_coordinate: Optional[EvidenceCoordinate] = None
    remediation_suggestion: Optional[str] = None
    context_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate error record contracts."""
        if not self.error_id or not self.error_id.strip():
            raise ModuleContractViolationError("ScientificErrorRecord error_id cannot be empty.")
        if not self.source_layer or not self.source_layer.strip():
            raise ModuleContractViolationError("source_layer cannot be empty.")
        if not self.description or not self.description.strip():
            raise ModuleContractViolationError("description cannot be empty.")
        if not self.timestamp_iso or not self.timestamp_iso.strip():
            raise ModuleContractViolationError("timestamp_iso cannot be empty.")


@dataclass(frozen=True)
class BenchmarkItem:
    """Individual test sample within a frozen benchmark evaluation suite."""

    item_id: str
    suite_type: BenchmarkSuiteType
    input_payload: Dict[str, Any]
    expected_output: Dict[str, Any]
    evaluation_criteria: Dict[str, float] = field(default_factory=dict)
    is_frozen: bool = True
    checksum_sha256: str = ""
    is_training_sample: bool = False

    def __post_init__(self) -> None:
        """Validate benchmark item attributes and calculate SHA-256 identity."""
        if not self.item_id or not self.item_id.strip():
            raise ModuleContractViolationError("BenchmarkItem item_id cannot be empty.")
        if self.is_training_sample:
            raise BenchmarkContaminationError(
                f"BenchmarkItem '{self.item_id}' is marked as a training sample; "
                "evaluation sets must remain strictly isolated."
            )
        computed_checksum = self._compute_checksum()
        if self.checksum_sha256 and self.checksum_sha256 != computed_checksum:
            raise ModuleContractViolationError(
                f"Checksum mismatch for item '{self.item_id}': expected "
                f"'{self.checksum_sha256}', calculated '{computed_checksum}'."
            )
        if not self.checksum_sha256:
            object.__setattr__(self, "checksum_sha256", computed_checksum)

    def _compute_checksum(self) -> str:
        """Compute canonical SHA-256 hash across item inputs and expected outputs."""
        serialized = json.dumps(
            {
                "item_id": self.item_id,
                "suite_type": self.suite_type.value,
                "input_payload": self.input_payload,
                "expected_output": self.expected_output,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FrozenBenchmarkManifest:
    """Immutable manifest containing a frozen evaluation set and cryptographic checksum."""

    manifest_id: str
    suite_type: BenchmarkSuiteType
    version: str
    created_at_iso: str
    items: List[BenchmarkItem]
    is_immutable: bool = True
    manifest_checksum_sha256: str = ""

    def __post_init__(self) -> None:
        """Validate manifest invariants and compute manifest-level cryptographic hash."""
        if not self.manifest_id or not self.manifest_id.strip():
            raise ModuleContractViolationError("manifest_id cannot be empty.")
        if not self.version or not self.version.strip():
            raise ModuleContractViolationError("version cannot be empty.")
        if not self.created_at_iso or not self.created_at_iso.strip():
            raise ModuleContractViolationError("created_at_iso cannot be empty.")
        if not self.items:
            raise ModuleContractViolationError("FrozenBenchmarkManifest must contain items.")

        # Check for training contamination across all contained items
        for item in self.items:
            if item.is_training_sample:
                raise BenchmarkContaminationError(
                    f"Contamination detected: item '{item.item_id}' is marked as training data."
                )

        computed_checksum = self._compute_manifest_checksum()
        if self.manifest_checksum_sha256 and self.manifest_checksum_sha256 != computed_checksum:
            raise ModuleContractViolationError(
                f"Manifest checksum mismatch for '{self.manifest_id}': expected "
                f"'{self.manifest_checksum_sha256}', calculated '{computed_checksum}'."
            )
        if not self.manifest_checksum_sha256:
            object.__setattr__(self, "manifest_checksum_sha256", computed_checksum)

    def _compute_manifest_checksum(self) -> str:
        """Calculate combined SHA-256 digest of all constituent item hashes."""
        hasher = hashlib.sha256()
        for item in sorted(self.items, key=lambda i: i.item_id):
            hasher.update(item.checksum_sha256.encode("utf-8"))
        return hasher.hexdigest()


@dataclass(frozen=True)
class RegressionThreshold:
    """Target performance threshold and allowable drop margin against release baseline."""

    metric_name: str
    minimum_acceptable_value: float
    maximum_allowable_drop: float = 0.02
    is_hard_gate: bool = True

    def __post_init__(self) -> None:
        """Validate regression threshold parameters."""
        if not self.metric_name or not self.metric_name.strip():
            raise ModuleContractViolationError("metric_name cannot be empty.")
        if self.maximum_allowable_drop < 0.0:
            raise ModuleContractViolationError("maximum_allowable_drop cannot be negative.")


@dataclass(frozen=True)
class BenchmarkBaseline:
    """Historical release benchmark metrics used for regression comparison."""

    baseline_id: str
    checkpoint_id: str
    metrics: Dict[str, float]
    timestamp_iso: str

    def __post_init__(self) -> None:
        """Validate baseline attributes."""
        if not self.baseline_id or not self.baseline_id.strip():
            raise ModuleContractViolationError("baseline_id cannot be empty.")
        if not self.checkpoint_id or not self.checkpoint_id.strip():
            raise ModuleContractViolationError("checkpoint_id cannot be empty.")
        if not self.timestamp_iso or not self.timestamp_iso.strip():
            raise ModuleContractViolationError("timestamp_iso cannot be empty.")


@dataclass(frozen=True)
class EvaluationRunRequest:
    """Input dispatch schema for benchmark evaluation runs adhering to Boundary J."""

    run_id: str
    benchmark_suite_id: str
    target_checkpoint_id: str
    baseline_checkpoint_id: Optional[str] = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Validate evaluation run request fields."""
        if not self.run_id or not self.run_id.strip():
            raise ModuleContractViolationError("run_id cannot be empty.")
        if not self.benchmark_suite_id or not self.benchmark_suite_id.strip():
            raise ModuleContractViolationError("benchmark_suite_id cannot be empty.")
        if not self.target_checkpoint_id or not self.target_checkpoint_id.strip():
            raise ModuleContractViolationError("target_checkpoint_id cannot be empty.")


@dataclass(frozen=True)
class BenchmarkRunReport:
    """Standardized output schema for benchmark capability and regression reports."""

    run_id: str
    benchmark_suite_id: str
    target_checkpoint_id: str
    timestamp_iso: str
    metrics_table: Dict[str, float]
    regressions_detected: List[str]
    errors_cataloged: List[ScientificErrorRecord]
    pass_fail_status: bool
    baseline_checkpoint_id: Optional[str] = None
    is_verified_offline: bool = True

    def __post_init__(self) -> None:
        """Validate benchmark run report invariants."""
        if not self.run_id or not self.run_id.strip():
            raise ModuleContractViolationError("run_id cannot be empty.")
        if not self.benchmark_suite_id or not self.benchmark_suite_id.strip():
            raise ModuleContractViolationError("benchmark_suite_id cannot be empty.")
        if not self.target_checkpoint_id or not self.target_checkpoint_id.strip():
            raise ModuleContractViolationError("target_checkpoint_id cannot be empty.")
        if not self.timestamp_iso or not self.timestamp_iso.strip():
            raise ModuleContractViolationError("timestamp_iso cannot be empty.")
