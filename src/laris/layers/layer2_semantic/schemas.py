"""Schemas and contracts for Layer 2 Semantic Intelligence and NLI.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md and ADR-002
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from laris.core.errors import (
    InvalidNLIInputError,
    ProbabilityValidationError,
    UncertaintyCeilingExceededError,
)

# Standard tolerance for probability sums
PROBABILITY_SUM_TOLERANCE: float = 1e-5
LN_3: float = math.log(3.0)


class NLILabel(str, Enum):
    """Canonical three-way Natural Language Inference classification labels."""

    ENTAILMENT = "ENTAILMENT"
    CONTRADICTION = "CONTRADICTION"
    NEUTRAL = "NEUTRAL"

    @classmethod
    def from_str(cls, value: str) -> NLILabel:
        """Parse string to NLILabel case-insensitively."""
        normalized = value.strip().upper()
        try:
            return cls(normalized)
        except ValueError:
            raise InvalidNLIInputError(
                f"Unknown NLI label '{value}'. Allowed labels: {[e.value for e in cls]}"
            )


@dataclass(frozen=True)
class SentencePairInput:
    """Input contract for sentence-pair semantic inference (MOD-SEM-001).

    Attributes:
        premise: Grounding or reference scientific sentence (non-empty).
        hypothesis: Proposed or candidate scientific sentence (non-empty).
        context_span: Optional surrounding paragraph or discourse context.
        pair_id: Optional unique identifier for tracking and lineage.
        metadata: Optional auxiliary key-value metadata.
    """

    premise: str
    hypothesis: str
    context_span: str | None = None
    pair_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.premise, str) or not self.premise.strip():
            msg = f"Premise must be non-empty string. Got: {type(self.premise).__name__}"
            raise InvalidNLIInputError(msg)
        if not isinstance(self.hypothesis, str) or not self.hypothesis.strip():
            msg = f"Hypothesis must be non-empty string. Got: {type(self.hypothesis).__name__}"
            raise InvalidNLIInputError(msg)
        if self.context_span is not None and not isinstance(self.context_span, str):
            msg = f"context_span must be string or None. Got: {type(self.context_span).__name__}"
            raise InvalidNLIInputError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to standard JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SentencePairInput:
        """Construct instance from dictionary."""
        return cls(
            premise=data["premise"],
            hypothesis=data["hypothesis"],
            context_span=data.get("context_span"),
            pair_id=data.get("pair_id"),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> SentencePairInput:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class NLIProbabilities:
    """Validated 3-way NLI probability distribution.

    Enforces that individual probabilities lie in [0.0, 1.0] and sum to 1.0 within tolerance.
    """

    entailment: float
    contradiction: float
    neutral: float
    tolerance: float = PROBABILITY_SUM_TOLERANCE

    def __post_init__(self) -> None:
        # Check type and valid individual bounds
        probs = {
            NLILabel.ENTAILMENT: self.entailment,
            NLILabel.CONTRADICTION: self.contradiction,
            NLILabel.NEUTRAL: self.neutral,
        }

        for label, p in probs.items():
            if not isinstance(p, (int, float)) or math.isnan(p) or math.isinf(p):
                raise ProbabilityValidationError(
                    f"Probability for {label.value} must be a valid real number. Received: {p!r}"
                )
            if p < -self.tolerance or p > 1.0 + self.tolerance:
                raise ProbabilityValidationError(
                    f"Probability for {label.value} out of bounds: {p:.6f} not in [0.0, 1.0]"
                )

        prob_sum = self.entailment + self.contradiction + self.neutral
        if abs(prob_sum - 1.0) > self.tolerance:
            raise ProbabilityValidationError(
                f"NLI probabilities must sum to 1.0 within tolerance {self.tolerance}. "
                f"Sum={prob_sum:.6f} (entailment={self.entailment:.6f}, "
                f"contradiction={self.contradiction:.6f}, neutral={self.neutral:.6f})"
            )

    def to_dict(self) -> dict[str, float]:
        """Convert to canonical dictionary mapping label name to probability."""
        return {
            NLILabel.ENTAILMENT.value: float(self.entailment),
            NLILabel.CONTRADICTION.value: float(self.contradiction),
            NLILabel.NEUTRAL.value: float(self.neutral),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, float],
        tolerance: float = PROBABILITY_SUM_TOLERANCE,
    ) -> NLIProbabilities:
        """Construct NLIProbabilities from dictionary supporting flexible casing."""
        norm_data = {k.strip().upper(): v for k, v in data.items()}
        try:
            return cls(
                entailment=float(norm_data[NLILabel.ENTAILMENT.value]),
                contradiction=float(norm_data[NLILabel.CONTRADICTION.value]),
                neutral=float(norm_data[NLILabel.NEUTRAL.value]),
                tolerance=tolerance,
            )
        except KeyError as err:
            raise ProbabilityValidationError(
                f"Missing required NLI probability key in dictionary: {err}"
            ) from err

    def predicted_label(self) -> NLILabel:
        """Derive predicted label via argmax with deterministic tie-breaking.

        Priority on exact tie: CONTRADICTION > ENTAILMENT > NEUTRAL
        (safety-first for contradiction).
        """
        max_p = max(self.entailment, self.contradiction, self.neutral)
        if math.isclose(self.contradiction, max_p, abs_tol=1e-9):
            return NLILabel.CONTRADICTION
        if math.isclose(self.entailment, max_p, abs_tol=1e-9):
            return NLILabel.ENTAILMENT
        return NLILabel.NEUTRAL

    def margin(self) -> float:
        """Calculate margin between highest and second highest probability."""
        sorted_probs = sorted(
            [self.entailment, self.contradiction, self.neutral], reverse=True
        )
        return float(sorted_probs[0] - sorted_probs[1])

    def normalized_entropy(self) -> float:
        """Calculate Shannon entropy normalized by ln(3) into [0.0, 1.0].

        H(P) = -sum(p_i * ln(p_i)) / ln(3).
        H = 0.0 for deterministic prediction, H = 1.0 for uniform distribution (1/3, 1/3, 1/3).
        """
        h = 0.0
        for p in (self.entailment, self.contradiction, self.neutral):
            clamped_p = max(0.0, min(1.0, p))
            if clamped_p > 0.0:
                h -= clamped_p * math.log(clamped_p)
        normalized = h / LN_3
        return float(max(0.0, min(1.0, normalized)))


@dataclass(frozen=True)
class NLIOutput:
    """Output contract for Natural Language Inference (Boundary C: MOD-SEM-001).

    Attributes:
        prediction: Predicted 3-way label (ENTAILMENT, CONTRADICTION, NEUTRAL).
        probabilities: Calibrated class probabilities dictionary or object.
        uncertainty_score: Calibrated epistemic uncertainty in [0.0, 1.0].
        pair_id: Optional tracking identifier.
        topical_similarity: Optional lexical/semantic vector similarity in [0.0, 1.0].
        context_span: Optional preserved context span.
        metadata: Optional inference execution metadata.
    """

    prediction: NLILabel
    probabilities: dict[str, float]
    uncertainty_score: float
    pair_id: str | None = None
    topical_similarity: float | None = None
    context_span: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate prediction
        if not isinstance(self.prediction, NLILabel):
            if isinstance(self.prediction, str):
                object.__setattr__(self, "prediction", NLILabel.from_str(self.prediction))
            else:
                raise InvalidNLIInputError(
                    f"prediction must be an instance of NLILabel or valid label string. "
                    f"Received: {type(self.prediction).__name__}"
                )

        # Validate probabilities
        if not isinstance(self.probabilities, dict):
            raise ProbabilityValidationError(
                f"probabilities must be a dict. Received: {type(self.probabilities).__name__}"
            )
        # Validate that probabilities conform to NLIProbabilities constraints
        nli_probs = NLIProbabilities.from_dict(self.probabilities)
        object.__setattr__(self, "probabilities", nli_probs.to_dict())

        # Validate uncertainty_score
        if not isinstance(self.uncertainty_score, (int, float)) or math.isnan(
            self.uncertainty_score
        ):
            raise UncertaintyCeilingExceededError(
                f"uncertainty_score must be a float. Received: {self.uncertainty_score!r}"
            )
        if self.uncertainty_score < 0.0 or self.uncertainty_score > 1.0:
            msg = f"uncertainty_score out of range [0.0, 1.0]: {self.uncertainty_score}"
            raise UncertaintyCeilingExceededError(msg)

        # Validate topical_similarity if present
        if self.topical_similarity is not None:
            if not isinstance(self.topical_similarity, (int, float)) or math.isnan(
                self.topical_similarity
            ):
                raise InvalidNLIInputError(
                    f"topical_similarity must be a float. Received: {self.topical_similarity!r}"
                )
            if self.topical_similarity < 0.0 or self.topical_similarity > 1.0:
                msg = f"topical_similarity out of range [0.0, 1.0]: {self.topical_similarity}"
                raise InvalidNLIInputError(msg)

    def verify_contradiction_invariant(self) -> bool:
        """Verify the foundational MOD-SEM-001 architectural invariant:

        'High semantic/topical similarity score must NEVER override NLI contradiction prediction.'
        Returns True if invariant holds.
        """
        if self.topical_similarity is not None and self.topical_similarity >= 0.8:
            # When topical similarity is high, if probabilities establish contradiction,
            # prediction MUST be CONTRADICTION and cannot be overridden to ENTAILMENT.
            probs = NLIProbabilities.from_dict(self.probabilities)
            if probs.contradiction > probs.entailment and self.prediction != NLILabel.CONTRADICTION:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize output to dictionary."""
        return {
            "prediction": self.prediction.value,
            "probabilities": self.probabilities,
            "uncertainty_score": self.uncertainty_score,
            "pair_id": self.pair_id,
            "topical_similarity": self.topical_similarity,
            "context_span": self.context_span,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NLIOutput:
        """Deserialize from dictionary."""
        return cls(
            prediction=NLILabel.from_str(data["prediction"]),
            probabilities=data["probabilities"],
            uncertainty_score=float(data["uncertainty_score"]),
            pair_id=data.get("pair_id"),
            topical_similarity=data.get("topical_similarity"),
            context_span=data.get("context_span"),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> NLIOutput:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class NLIPairBatch:
    """Batch container for sentence pair inputs."""

    items: list[SentencePairInput] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    def to_list(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.items]

    @classmethod
    def from_list(cls, items: list[dict[str, Any]]) -> NLIPairBatch:
        return cls(items=[SentencePairInput.from_dict(i) for i in items])


@dataclass(frozen=True)
class NLIOutputBatch:
    """Batch container for NLI inference outputs."""

    outputs: list[NLIOutput] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.outputs)

    def to_list(self) -> list[dict[str, Any]]:
        return [out.to_dict() for out in self.outputs]

    @classmethod
    def from_list(cls, items: list[dict[str, Any]]) -> NLIOutputBatch:
        return cls(outputs=[NLIOutput.from_dict(i) for i in items])


@runtime_checkable
class NLIEngineContract(Protocol):
    """Protocol interface defining required operations of an NLI Engine (Boundary C)."""

    def infer(self, pair: SentencePairInput) -> NLIOutput:
        """Execute 3-way NLI inference on a single premise-hypothesis pair."""
        ...

    def infer_batch(self, pairs: list[SentencePairInput]) -> list[NLIOutput]:
        """Execute 3-way NLI inference over a batch of premise-hypothesis pairs."""
        ...
