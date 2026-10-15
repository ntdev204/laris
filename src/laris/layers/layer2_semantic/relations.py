"""Semantic equivalence, scientific coreference, and discourse relation contracts.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-004, and ADR-008.
Enforces epistemic guardrails preventing unsupported causal claims from observational data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from laris.core.errors import (
    EpistemicOverreachError,
    InvalidNLIInputError,
    ModuleContractViolationError,
    UncertaintyCeilingExceededError,
)
from laris.core.schemas import EvidenceCoordinate

SCHEMA_VERSION: str = "0.1.0"

# Markers indicating strictly correlational assertions without established causation
CORRELATIONAL_CUES: list[str] = [
    "correlated with",
    "correlated to",
    "correlation between",
    "associated with",
    "association between",
    "co-occurred with",
    "co-occurs with",
    "linked to",
    "accompanied by",
]


class EquivalenceStatus(str, Enum):
    """Categorical classification of semantic equivalence between statements."""

    EQUIVALENT = "EQUIVALENT"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"
    PARTIALLY_EQUIVALENT = "PARTIALLY_EQUIVALENT"
    AMBIGUOUS = "AMBIGUOUS"

    @classmethod
    def from_str(cls, val: str) -> EquivalenceStatus:
        norm = val.strip().upper()
        try:
            return cls(norm)
        except ValueError:
            raise ModuleContractViolationError(
                f"Unknown EquivalenceStatus '{val}'. Allowed: {[e.value for e in cls]}"
            )


@dataclass(frozen=True)
class SemanticEquivalenceOutput:
    """Output contract for semantic equivalence evaluation."""

    text_a: str
    text_b: str
    status: EquivalenceStatus
    confidence: float
    topical_similarity: float
    evidence_notes: str | None = None
    schema_version: str = SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text_a, str) or not self.text_a.strip():
            raise InvalidNLIInputError("text_a must be a non-empty string.")
        if not isinstance(self.text_b, str) or not self.text_b.strip():
            raise InvalidNLIInputError("text_b must be a non-empty string.")
        if not isinstance(self.status, EquivalenceStatus):
            if isinstance(self.status, str):
                object.__setattr__(self, "status", EquivalenceStatus.from_str(self.status))
            else:
                raise ModuleContractViolationError("status must be an EquivalenceStatus.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ModuleContractViolationError(
                f"confidence must be in [0.0, 1.0]. Got: {self.confidence}"
            )
        if not (0.0 <= self.topical_similarity <= 1.0):
            raise ModuleContractViolationError(
                f"topical_similarity must be in [0.0, 1.0]. Got: {self.topical_similarity}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_a": self.text_a,
            "text_b": self.text_b,
            "status": self.status.value,
            "confidence": self.confidence,
            "topical_similarity": self.topical_similarity,
            "evidence_notes": self.evidence_notes,
            "schema_version": self.schema_version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticEquivalenceOutput:
        return cls(
            text_a=data["text_a"],
            text_b=data["text_b"],
            status=EquivalenceStatus.from_str(data["status"]),
            confidence=float(data["confidence"]),
            topical_similarity=float(data["topical_similarity"]),
            evidence_notes=data.get("evidence_notes"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> SemanticEquivalenceOutput:
        return cls.from_dict(json.loads(json_str))


class CoreferenceResolutionStatus(str, Enum):
    """Status of coreference mention resolution."""

    RESOLVED = "RESOLVED"
    AMBIGUOUS_ANTECEDENT = "AMBIGUOUS_ANTECEDENT"
    UNRESOLVED_SINGLETON = "UNRESOLVED_SINGLETON"


@dataclass(frozen=True)
class MentionSpan:
    """Exact text span for an entity or nominal mention."""

    mention_id: str
    text: str
    start_char: int
    end_char: int
    sentence_index: int | None = None
    evidence_coordinate: EvidenceCoordinate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mention_id, str) or not self.mention_id.strip():
            raise ModuleContractViolationError("mention_id must be a non-empty string.")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ModuleContractViolationError("text must be a non-empty string.")
        if self.start_char < 0:
            raise ModuleContractViolationError("start_char must be non-negative.")
        if self.end_char <= self.start_char:
            raise ModuleContractViolationError("end_char must be strictly greater than start_char.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_id": self.mention_id,
            "text": self.text,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "sentence_index": self.sentence_index,
            "evidence_coordinate": asdict(self.evidence_coordinate)
            if self.evidence_coordinate
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MentionSpan:
        coord = None
        if data.get("evidence_coordinate") is not None:
            coord = EvidenceCoordinate(**data["evidence_coordinate"])
        return cls(
            mention_id=data["mention_id"],
            text=data["text"],
            start_char=int(data["start_char"]),
            end_char=int(data["end_char"]),
            sentence_index=data.get("sentence_index"),
            evidence_coordinate=coord,
        )


@dataclass(frozen=True)
class CoreferenceCluster:
    """Equivalence cluster of coreferent scientific mentions."""

    cluster_id: str
    canonical_mention: str
    mentions: list[MentionSpan]
    confidence: float
    status: CoreferenceResolutionStatus = CoreferenceResolutionStatus.RESOLVED

    def __post_init__(self) -> None:
        if not isinstance(self.cluster_id, str) or not self.cluster_id.strip():
            raise ModuleContractViolationError("cluster_id must be a non-empty string.")
        if not isinstance(self.canonical_mention, str) or not self.canonical_mention.strip():
            raise ModuleContractViolationError("canonical_mention must be a non-empty string.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ModuleContractViolationError(
                f"confidence must be in [0.0, 1.0]. Got: {self.confidence}"
            )
        if not isinstance(self.status, CoreferenceResolutionStatus):
            if isinstance(self.status, str):
                norm = self.status.strip().upper()
                object.__setattr__(self, "status", CoreferenceResolutionStatus(norm))
            else:
                raise ModuleContractViolationError("Invalid CoreferenceResolutionStatus.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "canonical_mention": self.canonical_mention,
            "mentions": [m.to_dict() for m in self.mentions],
            "confidence": self.confidence,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreferenceCluster:
        return cls(
            cluster_id=data["cluster_id"],
            canonical_mention=data["canonical_mention"],
            mentions=[MentionSpan.from_dict(m) for m in data.get("mentions", [])],
            confidence=float(data["confidence"]),
            status=CoreferenceResolutionStatus(data.get("status", "RESOLVED")),
        )


@dataclass(frozen=True)
class CoreferenceOutput:
    """Output contract for coreference resolution."""

    clusters: list[CoreferenceCluster]
    unresolved_mentions: list[MentionSpan] = field(default_factory=list)
    document_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "clusters": [c.to_dict() for c in self.clusters],
            "unresolved_mentions": [m.to_dict() for m in self.unresolved_mentions],
            "document_id": self.document_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreferenceOutput:
        return cls(
            clusters=[CoreferenceCluster.from_dict(c) for c in data.get("clusters", [])],
            unresolved_mentions=[
                MentionSpan.from_dict(m) for m in data.get("unresolved_mentions", [])
            ],
            document_id=data.get("document_id"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> CoreferenceOutput:
        return cls.from_dict(json.loads(json_str))


class DiscourseRelationType(str, Enum):
    """Penn Discourse Treebank (PDTB) aligned typed discourse relations."""

    CAUSAL = "CAUSAL"
    CORRELATIONAL = "CORRELATIONAL"
    CONTRAST = "CONTRAST"
    CONCESSIVE = "CONCESSIVE"
    TEMPORAL = "TEMPORAL"
    ELABORATION = "ELABORATION"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN_RELATION = "UNKNOWN_RELATION"

    @classmethod
    def from_str(cls, val: str) -> DiscourseRelationType:
        norm = val.strip().upper()
        try:
            return cls(norm)
        except ValueError:
            raise ModuleContractViolationError(
                f"Unknown DiscourseRelationType '{val}'. Allowed: {[e.value for e in cls]}"
            )


@dataclass(frozen=True)
class DiscourseRelationOutput:
    """Output contract for typed inter-sentential discourse relations.

    Enforces epistemic guardrails preventing unsupported causal claims.
    """

    relation_id: str
    relation_type: DiscourseRelationType
    arg1: str
    arg2: str
    connective_cue: str | None = None
    confidence: float = 1.0
    uncertainty_score: float = 0.0
    causal_verified: bool = False
    evidence_coordinate: EvidenceCoordinate | None = None
    schema_version: str = SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.relation_id, str) or not self.relation_id.strip():
            raise ModuleContractViolationError("relation_id must be a non-empty string.")
        if not isinstance(self.arg1, str) or not self.arg1.strip():
            raise InvalidNLIInputError("arg1 must be a non-empty string.")
        if not isinstance(self.arg2, str) or not self.arg2.strip():
            raise InvalidNLIInputError("arg2 must be a non-empty string.")
        if not isinstance(self.relation_type, DiscourseRelationType):
            if isinstance(self.relation_type, str):
                norm_rel = DiscourseRelationType.from_str(self.relation_type)
                object.__setattr__(self, "relation_type", norm_rel)
            else:
                raise ModuleContractViolationError("Invalid DiscourseRelationType.")

        if not (0.0 <= self.confidence <= 1.0):
            raise ModuleContractViolationError(
                f"confidence must be in [0.0, 1.0]. Got: {self.confidence}"
            )
        if not (0.0 <= self.uncertainty_score <= 1.0):
            raise UncertaintyCeilingExceededError(
                f"uncertainty_score must be in [0.0, 1.0]. Got: {self.uncertainty_score}"
            )

        # Epistemic guardrail check
        self._validate_epistemic_causal_integrity()

    def _validate_epistemic_causal_integrity(self) -> None:
        """Enforce ADR-008: Observation of correlation cannot be asserted as causation

        without verified empirical causal proof.
        """
        if self.relation_type == DiscourseRelationType.CAUSAL and not self.causal_verified:
            combined_text = f"{self.arg1} {self.arg2}".lower()
            cue_text = (self.connective_cue or "").lower()
            for cue in CORRELATIONAL_CUES:
                if cue in cue_text or cue in combined_text:
                    raise EpistemicOverreachError(
                        f"Epistemic Overreach: Statement asserts correlational cue '{cue}' "
                        f"but relation is classified as CAUSAL without causal verification."
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "relation_type": self.relation_type.value,
            "arg1": self.arg1,
            "arg2": self.arg2,
            "connective_cue": self.connective_cue,
            "confidence": self.confidence,
            "uncertainty_score": self.uncertainty_score,
            "causal_verified": self.causal_verified,
            "evidence_coordinate": asdict(self.evidence_coordinate)
            if self.evidence_coordinate
            else None,
            "schema_version": self.schema_version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiscourseRelationOutput:
        coord = None
        if data.get("evidence_coordinate") is not None:
            coord = EvidenceCoordinate(**data["evidence_coordinate"])
        return cls(
            relation_id=data["relation_id"],
            relation_type=DiscourseRelationType.from_str(data["relation_type"]),
            arg1=data["arg1"],
            arg2=data["arg2"],
            connective_cue=data.get("connective_cue"),
            confidence=float(data.get("confidence", 1.0)),
            uncertainty_score=float(data.get("uncertainty_score", 0.0)),
            causal_verified=bool(data.get("causal_verified", False)),
            evidence_coordinate=coord,
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> DiscourseRelationOutput:
        return cls.from_dict(json.loads(json_str))
