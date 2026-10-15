"""Heading-Independent Limitation and Assumption Detection.

Module ID: MOD-SCINLP-002 (Boundary D: Scientific Language Intelligence)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008.
Extracts author-disclosed limitations, boundary conditions, negative/null findings,
and model assumptions from scientific texts without relying on section headers,
with explicit representation of epistemic uncertainty and categorization.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from laris.core.errors import (
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer3_scinlp.schemas import (
    AssumptionRecord,
    LimitationCategory,
    LimitationRecord,
    NegativeFindingRecord,
)

# --- Lexical & Syntactic Patterns ---

HEDGE_TERMS = {
    "might",
    "may",
    "could",
    "potentially",
    "likely",
    "suggests",
    "seems",
    "appears",
    "tentative",
    "plausibly",
    "uncertain",
    "preliminary",
    "possible",
    "partially",
}

# Categorized limitation regexes
COMPUTATIONAL_PATTERNS = re.compile(
    r"\b(computational cost|computational overhead|memory bottleneck|gpu memory|"
    r"scalability is limited|does not scale to|prohibitive (?:training|inference|latency)|"
    r"high time complexity|expensive to train|memory footprint|resource constraints)\b",
    re.IGNORECASE,
)

DATA_SPARSITY_PATTERNS = re.compile(
    r"\b(small dataset|data scarcity|limited training data|scarcity of annotations|"
    r"imbalanced (?:sample|classes|dataset)|restricted to english|few-shot limitations|"
    r"lack of labeled data|unannotated corpora|sample size is small)\b",
    re.IGNORECASE,
)

GENERALIZATION_PATTERNS = re.compile(
    r"\b(fails to generalize|out-of-domain failure|distribution shift|"
    r"sensitivity to hyperparameters|susceptible to overfitting|brittle on noisy|"
    r"poor generalization|domain adaptation gap|degrades on unseen)\b",
    re.IGNORECASE,
)

SCOPE_RESTRICTION_PATTERNS = re.compile(
    r"\b(outside the scope|we leave for future work|is restricted to|"
    r"does not consider|we limit our evaluation to|beyond the scope of|"
    r"we focus solely on|restricted to 2d|we do not investigate)\b",
    re.IGNORECASE,
)

METHODOLOGICAL_PATTERNS = re.compile(
    r"\b(approximation error|heuristic nature|lack of theoretical guarantee|"
    r"simplified model|first-order approximation|strong simplification|"
    r"assumes linearity|unverified heuristic|imperfect proxy)\b",
    re.IGNORECASE,
)

GENERAL_LIMITATION_MARKERS = re.compile(
    r"\b(a limitation of|our approach is limited|one drawback is|"
    r"main disadvantage|key limitation|fails when|weakness of our|"
    r"cannot handle|restricted applicability|caveat of our)\b",
    re.IGNORECASE,
)

NEGATIVE_FINDING_PATTERNS = re.compile(
    r"\b(no statistically significant improvement|fails to outperform|"
    r"did not observe any gain|no observable benefit|null hypothesis could not be rejected|"
    r"yielded comparable or inferior results|performance degraded|"
    r"did not lead to improvements|failed to reproduce|no advantage over)\b",
    re.IGNORECASE,
)

ASSUMPTION_PATTERNS = re.compile(
    r"\b(we assume that|under the assumption that|under the assumption of|"
    r"assuming that|is assumed to be|we make the assumption that|"
    r"supposing that|held constant|under the premise that|"
    r"assumes independent and identically distributed|assuming i\.?i\.?d\.?)\b",
    re.IGNORECASE,
)

# Strip standard headings pattern
HEADING_STRIP_REGEX = re.compile(
    r"^(?:#{1,6}\s+.*|[0-9]+(?:\.[0-9]+)*\.?\s+[A-Z].*)$", re.MULTILINE
)


def strip_headings(text: str) -> str:
    """Remove explicit Markdown and numbered section headings to evaluate parsing."""
    return HEADING_STRIP_REGEX.sub("", text)


def _split_into_sentences(text: str) -> list[tuple[int, int, str]]:
    """Split text into sentences with character offset ranges, respecting decimals and math."""
    spans: list[tuple[int, int, str]] = []
    if not text.strip():
        return spans

    split_pattern = re.compile(r"(?<=[.!?])(?<!\d\.)\s+(?=[A-Z\$\\])|\n\s*\n")
    start = 0
    for match in split_pattern.finditer(text):
        m_start = match.start()
        raw_part = text[start:m_start]
        stripped = raw_part.strip()
        if stripped:
            real_start = start + raw_part.find(stripped)
            real_end = real_start + len(stripped)
            spans.append((real_start, real_end, stripped))
        start = match.end()

    trailing = text[start:]
    stripped_trailing = trailing.strip()
    if stripped_trailing:
        real_start = start + trailing.find(stripped_trailing)
        real_end = real_start + len(stripped_trailing)
        spans.append((real_start, real_end, stripped_trailing))

    return spans


def compute_uncertainty_score(sentence: str) -> float:
    """Compute epistemic uncertainty score [0.0, 1.0] based on linguistic hedges."""
    tokens = re.findall(r"\b[a-zA-Z]+\b", sentence.lower())
    if not tokens:
        return 0.10

    hedge_count = sum(1 for t in tokens if t in HEDGE_TERMS)
    if hedge_count == 0:
        return 0.10
    elif hedge_count == 1:
        return 0.40
    elif hedge_count == 2:
        return 0.65
    else:
        return min(0.95, 0.65 + (hedge_count - 2) * 0.10)


@dataclass(frozen=True)
class LimitationDetectionResult:
    """Consolidated detection bundle for heading-independent discourse units."""

    document_id: str
    limitations: list[LimitationRecord] = field(default_factory=list)
    assumptions: list[AssumptionRecord] = field(default_factory=list)
    negative_findings: list[NegativeFindingRecord] = field(default_factory=list)
    uncertainty_distribution: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)

    def total_count(self) -> int:
        return len(self.limitations) + len(self.assumptions) + len(self.negative_findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "limitations": [lim.to_dict() for lim in self.limitations],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "negative_findings": [nf.to_dict() for nf in self.negative_findings],
            "uncertainty_distribution": self.uncertainty_distribution,
            "category_counts": self.category_counts,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LimitationDetectionResult:
        return cls(
            document_id=str(data["document_id"]),
            limitations=[LimitationRecord.from_dict(d) for d in data.get("limitations", [])],
            assumptions=[AssumptionRecord.from_dict(d) for d in data.get("assumptions", [])],
            negative_findings=[
                NegativeFindingRecord.from_dict(d) for d in data.get("negative_findings", [])
            ],
            uncertainty_distribution=dict(data.get("uncertainty_distribution", {})),
            category_counts=dict(data.get("category_counts", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> LimitationDetectionResult:
        return cls.from_dict(json.loads(json_str))


class HeadingIndependentLimitationDetector:
    """Infers limitations, boundary conditions, negative findings, and assumptions without headers.

    Conforms to MOD-SCINLP-002 (Boundary D: Scientific Language Intelligence).
    Maintains exact evidence coordinates, explicit uncertainty scores, and categorizations.
    """

    def __init__(self, confidence_threshold: float = 0.50) -> None:
        if not (0.0 <= confidence_threshold <= 1.0):
            raise ModuleContractViolationError(
                f"confidence_threshold must be in range [0.0, 1.0], got {confidence_threshold}"
            )
        self.confidence_threshold = confidence_threshold

    def _create_coordinate(
        self,
        document_id: str,
        document_sha256: str,
        char_start: int,
        char_end: int,
        snippet: str,
        confidence: float,
        provided_coords: list[EvidenceCoordinate] | None = None,
    ) -> EvidenceCoordinate:
        """Create or match coordinate anchored to physical offsets."""
        if provided_coords:
            for coord in provided_coords:
                if coord.char_start <= char_start and coord.char_end >= char_end:
                    return coord

        coord_id = f"{document_id}:p1:{char_start}-{char_end}"
        return EvidenceCoordinate(
            coordinate_id=coord_id,
            document_id=document_id,
            document_sha256=document_sha256,
            page_number=1,
            section_identifier="body",
            paragraph_index=0,
            sentence_index=0,
            char_start=char_start,
            char_end=char_end,
            verbatim_snippet=snippet,
            extraction_confidence=confidence,
        )

    def detect(
        self,
        text: str,
        document_id: str,
        coordinates: list[EvidenceCoordinate] | None = None,
        strip_headers: bool = False,
    ) -> LimitationDetectionResult:
        """Extract limitations, assumptions, and negative results independent of headings."""
        if not isinstance(document_id, str) or not document_id.strip():
            raise ModuleContractViolationError("document_id must be a non-empty string.")
        if not isinstance(text, str):
            raise ModuleContractViolationError("text must be a string.")

        if coordinates is not None:
            for coord in coordinates:
                if not isinstance(coord, EvidenceCoordinate):
                    raise ModuleContractViolationError(
                        f"Expected EvidenceCoordinate, got {type(coord).__name__}"
                    )
                if (
                    coord.char_start < 0
                    or coord.char_end < coord.char_start
                    or coord.char_end > len(text)
                ):
                    raise MalformedDiscourseSpanError(
                        f"Invalid coordinate offsets: [{coord.char_start}, {coord.char_end}] "
                        f"for text length {len(text)}"
                    )

        target_text = strip_headings(text) if strip_headers else text
        doc_sha256 = hashlib.sha256(target_text.encode("utf-8")).hexdigest()

        limitations: list[LimitationRecord] = []
        assumptions: list[AssumptionRecord] = []
        negative_findings: list[NegativeFindingRecord] = []

        sentences = _split_into_sentences(target_text)

        for start, end, sent in sentences:
            uncertainty = compute_uncertainty_score(sent)

            # 1. Negative / Null Findings
            if NEGATIVE_FINDING_PATTERNS.search(sent):
                confidence = 0.88
                if confidence >= self.confidence_threshold:
                    coord = self._create_coordinate(
                        document_id, doc_sha256, start, end, sent, confidence, coordinates
                    )
                    negative_findings.append(
                        NegativeFindingRecord(
                            finding_id=f"neg-{start}-{end}",
                            description=sent,
                            confidence=confidence,
                            coordinate=coord,
                            is_null_result=True,
                            uncertainty_score=uncertainty,
                        )
                    )

            # 2. Limitations & Boundary Conditions
            lim_category = self._classify_limitation(sent)
            if lim_category is not None:
                confidence = 0.85
                if confidence >= self.confidence_threshold:
                    coord = self._create_coordinate(
                        document_id, doc_sha256, start, end, sent, confidence, coordinates
                    )
                    limitations.append(
                        LimitationRecord(
                            limitation_id=f"lim-{start}-{end}",
                            description=sent,
                            confidence=confidence,
                            coordinate=coord,
                            scope="general",
                            is_author_disclosed=True,
                            category=lim_category.value,
                            uncertainty_score=uncertainty,
                        )
                    )

            # 3. Model Assumptions
            if ASSUMPTION_PATTERNS.search(sent):
                confidence = 0.86
                if confidence >= self.confidence_threshold:
                    coord = self._create_coordinate(
                        document_id, doc_sha256, start, end, sent, confidence, coordinates
                    )
                    assumptions.append(
                        AssumptionRecord(
                            assumption_id=f"asm-{start}-{end}",
                            statement=sent,
                            confidence=confidence,
                            coordinate=coord,
                            is_explicit=True,
                            domain="general",
                            uncertainty_score=uncertainty,
                        )
                    )

        # Compute summary metrics
        uncertainty_scores: list[float] = [
            *(lim.uncertainty_score for lim in limitations),
            *(a.uncertainty_score for a in assumptions),
            *(nf.uncertainty_score for nf in negative_findings),
        ]
        uncertainty_dist = {"low": 0, "medium": 0, "high": 0}
        for score in uncertainty_scores:
            if score < 0.30:
                uncertainty_dist["low"] += 1
            elif score < 0.60:
                uncertainty_dist["medium"] += 1
            else:
                uncertainty_dist["high"] += 1

        cat_counts: dict[str, int] = {}
        for lim in limitations:
            cat_counts[lim.category] = cat_counts.get(lim.category, 0) + 1

        return LimitationDetectionResult(
            document_id=document_id,
            limitations=limitations,
            assumptions=assumptions,
            negative_findings=negative_findings,
            uncertainty_distribution=uncertainty_dist,
            category_counts=cat_counts,
        )

    def _classify_limitation(self, sentence: str) -> LimitationCategory | None:
        """Classify limitation category or return None if sentence is not a limitation."""
        if COMPUTATIONAL_PATTERNS.search(sentence):
            return LimitationCategory.COMPUTATIONAL_RESOURCE
        if DATA_SPARSITY_PATTERNS.search(sentence):
            return LimitationCategory.DATA_SPARSITY
        if GENERALIZATION_PATTERNS.search(sentence):
            return LimitationCategory.GENERALIZATION_BOUND
        if SCOPE_RESTRICTION_PATTERNS.search(sentence):
            return LimitationCategory.SCOPE_RESTRICTION
        if METHODOLOGICAL_PATTERNS.search(sentence):
            return LimitationCategory.METHODOLOGICAL
        if GENERAL_LIMITATION_MARKERS.search(sentence):
            return LimitationCategory.GENERAL
        return None

    def evaluate_stripped_heading_recall(
        self,
        ground_truth_statements: list[str],
        text: str,
        document_id: str = "eval-doc",
    ) -> dict[str, float]:
        """Benchmark limitation detection recall when headings are completely stripped."""
        stripped_text = strip_headings(text)
        result = self.detect(stripped_text, document_id=document_id)

        all_detected = [lim.description.lower() for lim in result.limitations]
        all_detected.extend([neg.description.lower() for neg in result.negative_findings])

        if not ground_truth_statements:
            return {"recall": 1.0, "detected_count": len(all_detected), "ground_truth_count": 0}

        matches = 0
        for gt in ground_truth_statements:
            gt_lower = gt.lower()
            if any(gt_lower in det or det in gt_lower for det in all_detected):
                matches += 1

        recall = matches / len(ground_truth_statements)
        return {
            "recall": round(recall, 4),
            "detected_count": len(all_detected),
            "ground_truth_count": len(ground_truth_statements),
        }
