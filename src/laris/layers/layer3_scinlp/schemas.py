"""Discourse entity schemas and extraction boundary contracts.

Module ID: MOD-SCINLP-001 (Boundary D: Scientific Language Intelligence)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008.
Provides typed records for claims, methods, datasets, metrics, results, limitations,
assumptions, and mathematical formulas with rigorous physical coordinate anchoring.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from laris.core.errors import (
    ExtractionConfidenceBelowThresholdError,
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EpistemicStatus, EvidenceCoordinate

MIN_EXTRACTION_CONFIDENCE: float = 0.0
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.50


class DiscourseEntityType(str, Enum):
    """Enumeration of scientific discourse unit categories conforming to Boundary D."""

    CLAIM = "CLAIM"
    METHOD = "METHOD"
    DATASET = "DATASET"
    METRIC = "METRIC"
    RESULT = "RESULT"
    LIMITATION = "LIMITATION"
    ASSUMPTION = "ASSUMPTION"
    FORMULA = "FORMULA"


def _validate_coordinate_span(
    coord: EvidenceCoordinate,
    text: str,
    confidence: float,
    min_confidence: float = MIN_EXTRACTION_CONFIDENCE,
) -> None:
    """Validate physical coordinate offsets, span bounds, and confidence values."""
    if not isinstance(coord, EvidenceCoordinate):
        raise ModuleContractViolationError(
            f"Expected EvidenceCoordinate, got {type(coord).__name__}"
        )

    if coord.char_start < 0 or coord.char_end < coord.char_start:
        raise MalformedDiscourseSpanError(
            f"Invalid character offset bounds: [{coord.char_start}, {coord.char_end}]"
        )

    if not (0.0 <= confidence <= 1.0):
        raise ModuleContractViolationError(
            f"Confidence score {confidence} must be in range [0.0, 1.0]"
        )

    if confidence < min_confidence:
        raise ExtractionConfidenceBelowThresholdError(
            f"Extraction confidence {confidence} is below minimum threshold {min_confidence}"
        )

    if not text or not text.strip():
        raise MalformedDiscourseSpanError("Entity text content cannot be empty or whitespace only")


@dataclass(frozen=True)
class ClaimRecord:
    """Typed representation of an extracted scientific claim."""

    claim_id: str
    text: str
    epistemic_status: EpistemicStatus
    confidence: float
    coordinate: EvidenceCoordinate
    related_methods: tuple[str, ...] = ()
    measured_metrics: tuple[str, ...] = ()
    is_hedged: bool = False

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.text, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "epistemic_status": self.epistemic_status.value,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "related_methods": list(self.related_methods),
            "measured_metrics": list(self.measured_metrics),
            "is_hedged": self.is_hedged,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimRecord:
        return cls(
            claim_id=str(data["claim_id"]),
            text=str(data["text"]),
            epistemic_status=EpistemicStatus(data["epistemic_status"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            related_methods=tuple(data.get("related_methods", ())),
            measured_metrics=tuple(data.get("measured_metrics", ())),
            is_hedged=bool(data.get("is_hedged", False)),
        )


@dataclass(frozen=True)
class MethodRecord:
    """Typed representation of an experimental or computational method."""

    method_id: str
    name: str
    category: str
    confidence: float
    coordinate: EvidenceCoordinate
    parameters: dict[str, str] = field(default_factory=dict)
    tools_software: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.name, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "name": self.name,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "parameters": self.parameters,
            "tools_software": list(self.tools_software),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MethodRecord:
        return cls(
            method_id=str(data["method_id"]),
            name=str(data["name"]),
            category=str(data.get("category", "general")),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            parameters=dict(data.get("parameters", {})),
            tools_software=tuple(data.get("tools_software", ())),
        )


@dataclass(frozen=True)
class DatasetRecord:
    """Typed representation of a scientific corpus or experimental dataset reference."""

    dataset_id: str
    name: str
    confidence: float
    coordinate: EvidenceCoordinate
    sample_size: int | None = None
    organism_or_domain: str = "general"
    accession_id: str | None = None

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.name, self.confidence)
        if self.sample_size is not None and self.sample_size < 0:
            raise ModuleContractViolationError("sample_size must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "sample_size": self.sample_size,
            "organism_or_domain": self.organism_or_domain,
            "accession_id": self.accession_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetRecord:
        return cls(
            dataset_id=str(data["dataset_id"]),
            name=str(data["name"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            sample_size=int(data["sample_size"]) if data.get("sample_size") is not None else None,
            organism_or_domain=str(data.get("organism_or_domain", "general")),
            accession_id=data.get("accession_id"),
        )


@dataclass(frozen=True)
class MetricRecord:
    """Typed representation of an evaluation metric or experimental quantity."""

    metric_id: str
    name: str
    confidence: float
    coordinate: EvidenceCoordinate
    value: float | str | None = None
    unit: str | None = None
    comparison_operator: str | None = None

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.name, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "value": self.value,
            "unit": self.unit,
            "comparison_operator": self.comparison_operator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricRecord:
        return cls(
            metric_id=str(data["metric_id"]),
            name=str(data["name"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            value=data.get("value"),
            unit=data.get("unit"),
            comparison_operator=data.get("comparison_operator"),
        )


@dataclass(frozen=True)
class ResultRecord:
    """Typed representation of an empirical outcome or experimental result."""

    result_id: str
    description: str
    confidence: float
    coordinate: EvidenceCoordinate
    statistically_significant: bool | None = None
    p_value: float | None = None
    effect_size: float | None = None
    supporting_metric_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.description, self.confidence)
        if self.p_value is not None and not (0.0 <= self.p_value <= 1.0):
            raise ModuleContractViolationError("p_value must be in range [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "description": self.description,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "statistically_significant": self.statistically_significant,
            "p_value": self.p_value,
            "effect_size": self.effect_size,
            "supporting_metric_ids": list(self.supporting_metric_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResultRecord:
        return cls(
            result_id=str(data["result_id"]),
            description=str(data["description"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            statistically_significant=data.get("statistically_significant"),
            p_value=float(data["p_value"]) if data.get("p_value") is not None else None,
            effect_size=(
                float(data["effect_size"]) if data.get("effect_size") is not None else None
            ),
            supporting_metric_ids=tuple(data.get("supporting_metric_ids", ())),
        )


@dataclass(frozen=True)
class LimitationRecord:
    """Typed representation of an author-disclosed or extracted limitation."""

    limitation_id: str
    description: str
    confidence: float
    coordinate: EvidenceCoordinate
    scope: str = "general"
    is_author_disclosed: bool = True

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.description, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "limitation_id": self.limitation_id,
            "description": self.description,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "scope": self.scope,
            "is_author_disclosed": self.is_author_disclosed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LimitationRecord:
        return cls(
            limitation_id=str(data["limitation_id"]),
            description=str(data["description"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            scope=str(data.get("scope", "general")),
            is_author_disclosed=bool(data.get("is_author_disclosed", True)),
        )


@dataclass(frozen=True)
class AssumptionRecord:
    """Typed representation of a scientific premise or model assumption."""

    assumption_id: str
    statement: str
    confidence: float
    coordinate: EvidenceCoordinate
    is_explicit: bool = True

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.statement, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "statement": self.statement,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "is_explicit": self.is_explicit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssumptionRecord:
        return cls(
            assumption_id=str(data["assumption_id"]),
            statement=str(data["statement"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            is_explicit=bool(data.get("is_explicit", True)),
        )


@dataclass(frozen=True)
class FormulaRecord:
    """Typed representation of an extracted LaTeX mathematical expression."""

    formula_id: str
    latex_source: str
    confidence: float
    coordinate: EvidenceCoordinate
    variables: tuple[str, ...] = ()
    is_inline: bool = True

    def __post_init__(self) -> None:
        _validate_coordinate_span(self.coordinate, self.latex_source, self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "latex_source": self.latex_source,
            "confidence": round(self.confidence, 4),
            "coordinate": asdict(self.coordinate),
            "variables": list(self.variables),
            "is_inline": self.is_inline,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FormulaRecord:
        return cls(
            formula_id=str(data["formula_id"]),
            latex_source=str(data["latex_source"]),
            confidence=float(data["confidence"]),
            coordinate=EvidenceCoordinate(**data["coordinate"]),
            variables=tuple(data.get("variables", ())),
            is_inline=bool(data.get("is_inline", True)),
        )


@dataclass(frozen=True)
class DiscourseExtractionSet:
    """Standardized multi-entity extraction bundle conforming to Boundary D."""

    document_id: str
    extraction_id: str
    timestamp_iso: str
    claims: list[ClaimRecord] = field(default_factory=list)
    methods: list[MethodRecord] = field(default_factory=list)
    datasets: list[DatasetRecord] = field(default_factory=list)
    metrics: list[MetricRecord] = field(default_factory=list)
    results: list[ResultRecord] = field(default_factory=list)
    limitations: list[LimitationRecord] = field(default_factory=list)
    assumptions: list[AssumptionRecord] = field(default_factory=list)
    formulas: list[FormulaRecord] = field(default_factory=list)
    provenance_manifest_sha256: str = ""

    def total_entities_count(self) -> int:
        """Return the sum of all extracted discourse entities."""
        return (
            len(self.claims)
            + len(self.methods)
            + len(self.datasets)
            + len(self.metrics)
            + len(self.results)
            + len(self.limitations)
            + len(self.assumptions)
            + len(self.formulas)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "extraction_id": self.extraction_id,
            "timestamp_iso": self.timestamp_iso,
            "claims": [c.to_dict() for c in self.claims],
            "methods": [m.to_dict() for m in self.methods],
            "datasets": [d.to_dict() for d in self.datasets],
            "metrics": [m.to_dict() for m in self.metrics],
            "results": [r.to_dict() for r in self.results],
            "limitations": [lim.to_dict() for lim in self.limitations],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "formulas": [f.to_dict() for f in self.formulas],
            "provenance_manifest_sha256": self.provenance_manifest_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscourseExtractionSet:
        return cls(
            document_id=str(data["document_id"]),
            extraction_id=str(data["extraction_id"]),
            timestamp_iso=str(data["timestamp_iso"]),
            claims=[ClaimRecord.from_dict(c) for c in data.get("claims", [])],
            methods=[MethodRecord.from_dict(m) for m in data.get("methods", [])],
            datasets=[DatasetRecord.from_dict(d) for d in data.get("datasets", [])],
            metrics=[MetricRecord.from_dict(m) for m in data.get("metrics", [])],
            results=[ResultRecord.from_dict(r) for r in data.get("results", [])],
            limitations=[LimitationRecord.from_dict(lim) for lim in data.get("limitations", [])],
            assumptions=[AssumptionRecord.from_dict(a) for a in data.get("assumptions", [])],
            formulas=[FormulaRecord.from_dict(f) for f in data.get("formulas", [])],
            provenance_manifest_sha256=str(data.get("provenance_manifest_sha256", "")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> DiscourseExtractionSet:
        return cls.from_dict(json.loads(json_str))

    def compute_manifest_hash(self) -> str:
        """Compute deterministic SHA-256 digest of all entity coordinate IDs."""
        coord_ids: list[str] = []
        for c in self.claims:
            coord_ids.append(c.coordinate.coordinate_id)
        for m in self.methods:
            coord_ids.append(m.coordinate.coordinate_id)
        for d in self.datasets:
            coord_ids.append(d.coordinate.coordinate_id)
        for mtr in self.metrics:
            coord_ids.append(mtr.coordinate.coordinate_id)
        for r in self.results:
            coord_ids.append(r.coordinate.coordinate_id)
        for lim in self.limitations:
            coord_ids.append(lim.coordinate.coordinate_id)
        for a in self.assumptions:
            coord_ids.append(a.coordinate.coordinate_id)
        for f in self.formulas:
            coord_ids.append(f.coordinate.coordinate_id)

        payload = {
            "document_id": self.document_id,
            "extraction_id": self.extraction_id,
            "coordinate_ids": sorted(coord_ids),
            "total_entities": self.total_entities_count(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


@runtime_checkable
class DiscourseExtractorContract(Protocol):
    """Runtime contract for Scientific Language Intelligence extractor conforming to Boundary D."""

    def extract(
        self,
        document_id: str,
        text: str,
        coordinates: list[EvidenceCoordinate] | None = None,
    ) -> DiscourseExtractionSet:
        """Extract typed discourse entities from input text or physical coordinates."""
        ...
