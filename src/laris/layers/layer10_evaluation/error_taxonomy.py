"""Scientific error taxonomy and categorization engine for Layer 10.

Adheres to DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-004, ADR-008, and Issue #71:
- Fine-grained scientific failure taxonomy distinguishing provenance, epistemic,
  extraction, reasoning, and system faults
- Automated classification mapping from core LARIS exception types to taxons
- Standard remediation suggestions for reproducible pipeline diagnosis
- Thread-safe cataloging and error distribution analytics
"""

from __future__ import annotations

import datetime
import threading
from typing import Any, Dict, List, Optional, Type

from laris.core.errors import (
    CycleDetectedError,
    EpistemicOverreachError,
    ExtractionConfidenceBelowThresholdError,
    GraphIntegrityError,
    HardwareBudgetExceededError,
    InferredEdgeConflationError,
    InvalidNLIInputError,
    MalformedDiscourseSpanError,
    ProbabilityValidationError,
    ProvenanceViolationError,
    TaskRoutingError,
    UncertaintyCeilingExceededError,
    UnitConversionError,
    WeightStagingError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer10_evaluation.schemas import (
    ErrorSeverity,
    ScientificErrorCategory,
    ScientificErrorRecord,
)


class ScientificErrorTaxonomy:
    """Taxonomic classifier and diagnostic manager for scientific research failures."""

    _EXCEPTION_MAPPING: Dict[Type[Exception], ScientificErrorCategory] = {
        ProvenanceViolationError: ScientificErrorCategory.PROVENANCE_FAILURE,
        EpistemicOverreachError: ScientificErrorCategory.EPISTEMIC_FAILURE,
        UncertaintyCeilingExceededError: ScientificErrorCategory.EPISTEMIC_FAILURE,
        ProbabilityValidationError: ScientificErrorCategory.EPISTEMIC_FAILURE,
        MalformedDiscourseSpanError: ScientificErrorCategory.EXTRACTION_FAILURE,
        UnitConversionError: ScientificErrorCategory.EXTRACTION_FAILURE,
        ExtractionConfidenceBelowThresholdError: ScientificErrorCategory.EXTRACTION_FAILURE,
        InvalidNLIInputError: ScientificErrorCategory.REASONING_FAILURE,
        GraphIntegrityError: ScientificErrorCategory.REASONING_FAILURE,
        InferredEdgeConflationError: ScientificErrorCategory.REASONING_FAILURE,
        HardwareBudgetExceededError: ScientificErrorCategory.SYSTEM_FAILURE,
        WeightStagingError: ScientificErrorCategory.SYSTEM_FAILURE,
        TaskRoutingError: ScientificErrorCategory.SYSTEM_FAILURE,
        CycleDetectedError: ScientificErrorCategory.SYSTEM_FAILURE,
    }

    _DEFAULT_REMEDIATIONS: Dict[ScientificErrorCategory, str] = {
        ScientificErrorCategory.PROVENANCE_FAILURE: (
            "Verify character coordinate offsets and sentence boundaries in source document."
        ),
        ScientificErrorCategory.EPISTEMIC_FAILURE: (
            "Recalibrate prediction confidence, dampen causal assertions, or escalate routing."
        ),
        ScientificErrorCategory.EXTRACTION_FAILURE: (
            "Sanitize entity spans, normalize formulas to LaTeX math, or check unit dimensions."
        ),
        ScientificErrorCategory.REASONING_FAILURE: (
            "Verify condition comparability, examine cross-study assumptions, or check NLI inputs."
        ),
        ScientificErrorCategory.SYSTEM_FAILURE: (
            "Offload inactive specialist weights, reduce batch size, or engage fallback tier."
        ),
    }

    def __init__(self) -> None:
        self._catalog: List[ScientificErrorRecord] = []
        self._lock = threading.Lock()

    def classify_exception(self, exc: Exception) -> ScientificErrorCategory:
        """Map a Python exception to its canonical scientific error category."""
        for exc_type, category in self._EXCEPTION_MAPPING.items():
            if isinstance(exc, exc_type):
                return category
        return ScientificErrorCategory.SYSTEM_FAILURE

    def create_record(
        self,
        error_id: str,
        category: ScientificErrorCategory,
        severity: ErrorSeverity,
        source_layer: str,
        description: str,
        provenance_coordinate: Optional[EvidenceCoordinate] = None,
        remediation_suggestion: Optional[str] = None,
        context_metadata: Optional[Dict[str, Any]] = None,
    ) -> ScientificErrorRecord:
        """Construct a validated ScientificErrorRecord with default remediation if omitted."""
        suggestion = remediation_suggestion or self._DEFAULT_REMEDIATIONS.get(category, "")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = ScientificErrorRecord(
            error_id=error_id,
            category=category,
            severity=severity,
            source_layer=source_layer,
            description=description,
            timestamp_iso=now_iso,
            provenance_coordinate=provenance_coordinate,
            remediation_suggestion=suggestion,
            context_metadata=context_metadata or {},
        )
        return record

    def record_error(self, record: ScientificErrorRecord) -> None:
        """Catalog an error record in the audit repository."""
        with self._lock:
            self._catalog.append(record)

    def record_exception(
        self,
        error_id: str,
        exc: Exception,
        source_layer: str,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        provenance_coordinate: Optional[EvidenceCoordinate] = None,
        context_metadata: Optional[Dict[str, Any]] = None,
    ) -> ScientificErrorRecord:
        """Automatically classify an exception and catalog its diagnostic record."""
        category = self.classify_exception(exc)
        record = self.create_record(
            error_id=error_id,
            category=category,
            severity=severity,
            source_layer=source_layer,
            description=str(exc),
            provenance_coordinate=provenance_coordinate,
            context_metadata=context_metadata,
        )
        self.record_error(record)
        return record

    def get_catalog(self) -> List[ScientificErrorRecord]:
        """Return an immutable snapshot of all cataloged scientific error records."""
        with self._lock:
            return list(self._catalog)

    def clear_catalog(self) -> None:
        """Clear error catalog repository."""
        with self._lock:
            self._catalog.clear()

    def get_category_distribution(self) -> Dict[str, int]:
        """Compute frequency distribution of errors across scientific failure categories."""
        with self._lock:
            dist = {c.value: 0 for c in ScientificErrorCategory}
            for rec in self._catalog:
                dist[rec.category.value] += 1
            return dist

    def has_critical_errors(self) -> bool:
        """Whether any cataloged record possesses CRITICAL severity."""
        with self._lock:
            return any(rec.severity == ErrorSeverity.CRITICAL for rec in self._catalog)
