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

    def to_dict(self) -> Dict[str, Any]:
        """Convert error record to a JSON-serializable dictionary."""
        data: Dict[str, Any] = {
            "error_id": self.error_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "source_layer": self.source_layer,
            "description": self.description,
            "timestamp_iso": self.timestamp_iso,
            "remediation_suggestion": self.remediation_suggestion,
            "context_metadata": dict(self.context_metadata),
        }
        if self.provenance_coordinate:
            coord = self.provenance_coordinate
            data["provenance_coordinate"] = {
                "coordinate_id": coord.coordinate_id,
                "document_id": coord.document_id,
                "document_sha256": coord.document_sha256,
                "page_number": coord.page_number,
                "section_identifier": coord.section_identifier,
                "paragraph_index": coord.paragraph_index,
                "sentence_index": coord.sentence_index,
                "char_start": coord.char_start,
                "char_end": coord.char_end,
                "verbatim_snippet": coord.verbatim_snippet,
                "extraction_confidence": coord.extraction_confidence,
            }
        else:
            data["provenance_coordinate"] = None
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScientificErrorRecord:
        """Construct error record from dictionary."""
        coord_data = data.get("provenance_coordinate")
        coord = EvidenceCoordinate(**coord_data) if coord_data else None
        return cls(
            error_id=data["error_id"],
            category=ScientificErrorCategory(data["category"]),
            severity=ErrorSeverity(data["severity"]),
            source_layer=data["source_layer"],
            description=data["description"],
            timestamp_iso=data["timestamp_iso"],
            provenance_coordinate=coord,
            remediation_suggestion=data.get("remediation_suggestion"),
            context_metadata=dict(data.get("context_metadata", {})),
        )



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

    def to_dict(self) -> Dict[str, Any]:
        """Convert benchmark item to a JSON-serializable dictionary."""
        return {
            "item_id": self.item_id,
            "suite_type": self.suite_type.value,
            "input_payload": dict(self.input_payload),
            "expected_output": dict(self.expected_output),
            "evaluation_criteria": dict(self.evaluation_criteria),
            "is_frozen": self.is_frozen,
            "checksum_sha256": self.checksum_sha256,
            "is_training_sample": self.is_training_sample,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BenchmarkItem:
        """Construct benchmark item from dictionary."""
        return cls(
            item_id=data["item_id"],
            suite_type=BenchmarkSuiteType(data["suite_type"]),
            input_payload=dict(data["input_payload"]),
            expected_output=dict(data["expected_output"]),
            evaluation_criteria=dict(data.get("evaluation_criteria", {})),
            is_frozen=data.get("is_frozen", True),
            checksum_sha256=data.get("checksum_sha256", ""),
            is_training_sample=data.get("is_training_sample", False),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert manifest to a JSON-serializable dictionary."""
        return {
            "manifest_id": self.manifest_id,
            "suite_type": self.suite_type.value,
            "version": self.version,
            "created_at_iso": self.created_at_iso,
            "items": [item.to_dict() for item in self.items],
            "manifest_checksum_sha256": self.manifest_checksum_sha256,
            "is_immutable": self.is_immutable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FrozenBenchmarkManifest:
        """Construct manifest from dictionary."""
        items = [BenchmarkItem.from_dict(it) for it in data["items"]]
        return cls(
            manifest_id=data["manifest_id"],
            suite_type=BenchmarkSuiteType(data["suite_type"]),
            version=data["version"],
            created_at_iso=data["created_at_iso"],
            items=items,
            manifest_checksum_sha256=data.get("manifest_checksum_sha256", ""),
            is_immutable=data.get("is_immutable", True),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert regression threshold to a dictionary."""
        return {
            "metric_name": self.metric_name,
            "minimum_acceptable_value": self.minimum_acceptable_value,
            "maximum_allowable_drop": self.maximum_allowable_drop,
            "is_hard_gate": self.is_hard_gate,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RegressionThreshold:
        """Construct regression threshold from dictionary."""
        return cls(
            metric_name=data["metric_name"],
            minimum_acceptable_value=float(data["minimum_acceptable_value"]),
            maximum_allowable_drop=float(data.get("maximum_allowable_drop", 0.02)),
            is_hard_gate=bool(data.get("is_hard_gate", True)),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert benchmark baseline to a dictionary."""
        return {
            "baseline_id": self.baseline_id,
            "checkpoint_id": self.checkpoint_id,
            "metrics": dict(self.metrics),
            "timestamp_iso": self.timestamp_iso,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BenchmarkBaseline:
        """Construct benchmark baseline from dictionary."""
        return cls(
            baseline_id=data["baseline_id"],
            checkpoint_id=data["checkpoint_id"],
            metrics=dict(data["metrics"]),
            timestamp_iso=data["timestamp_iso"],
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation run request to a dictionary."""
        return {
            "run_id": self.run_id,
            "benchmark_suite_id": self.benchmark_suite_id,
            "target_checkpoint_id": self.target_checkpoint_id,
            "baseline_checkpoint_id": self.baseline_checkpoint_id,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvaluationRunRequest:
        """Construct evaluation run request from dictionary."""
        return cls(
            run_id=data["run_id"],
            benchmark_suite_id=data["benchmark_suite_id"],
            target_checkpoint_id=data["target_checkpoint_id"],
            baseline_checkpoint_id=data.get("baseline_checkpoint_id"),
            dry_run=data.get("dry_run", False),
        )


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert benchmark run report to a JSON-serializable dictionary."""
        return {
            "run_id": self.run_id,
            "benchmark_suite_id": self.benchmark_suite_id,
            "target_checkpoint_id": self.target_checkpoint_id,
            "timestamp_iso": self.timestamp_iso,
            "metrics_table": dict(self.metrics_table),
            "regressions_detected": list(self.regressions_detected),
            "errors_cataloged": [err.to_dict() for err in self.errors_cataloged],
            "pass_fail_status": self.pass_fail_status,
            "baseline_checkpoint_id": self.baseline_checkpoint_id,
            "is_verified_offline": self.is_verified_offline,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BenchmarkRunReport:
        """Construct benchmark run report from dictionary."""
        errors = [
            ScientificErrorRecord.from_dict(err)
            for err in data.get("errors_cataloged", [])
        ]
        return cls(
            run_id=data["run_id"],
            benchmark_suite_id=data["benchmark_suite_id"],
            target_checkpoint_id=data["target_checkpoint_id"],
            timestamp_iso=data["timestamp_iso"],
            metrics_table=dict(data.get("metrics_table", {})),
            regressions_detected=list(data.get("regressions_detected", [])),
            errors_cataloged=errors,
            pass_fail_status=data["pass_fail_status"],
            baseline_checkpoint_id=data.get("baseline_checkpoint_id"),
            is_verified_offline=data.get("is_verified_offline", True),
        )

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Serialize benchmark report to deterministic JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> BenchmarkRunReport:
        """Deserialize benchmark report from JSON string."""
        return cls.from_dict(json.loads(json_str))

