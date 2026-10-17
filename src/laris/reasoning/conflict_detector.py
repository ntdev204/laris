"""Condition-aware empirical conflict and contradiction detection engine.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, and ADR-004:
- Distinguishes genuine empirical contradictions from incomparable experimental setups
- Analyzes comparative matrix cells and flags scientific discrepancies
- Anchors 100% of conflict records to verified EvidenceCoordinate provenance
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from laris.core.errors import ProvenanceViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.reasoning.schemas import (
    CaveatSeverity,
    ComparativeCell,
    ComparativeMatrix,
    ConflictRecord,
    ConflictType,
    MetricDirection,
    StudyFinding,
)


class ConditionAwareConflictDetector:
    """Detects empirical contradictions while filtering false conflicts from disparate setups."""

    def __init__(
        self,
        discrepancy_threshold: float = 0.05,
    ) -> None:
        self.discrepancy_threshold = discrepancy_threshold

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.strip().lower().replace("_", "").replace("-", "")

    def _collect_coordinates(
        self,
        finding_a: StudyFinding,
        finding_b: StudyFinding,
    ) -> List[EvidenceCoordinate]:
        coords: List[EvidenceCoordinate] = []
        coords.extend(finding_a.evidence_coordinates)
        coords.extend(finding_b.evidence_coordinates)
        if not coords:
            raise ProvenanceViolationError(
                f"Findings '{finding_a.finding_id}' and '{finding_b.finding_id}' lack "
                "verified EvidenceCoordinate provenance."
            )
        return coords

    def evaluate_cell(
        self,
        cell: ComparativeCell,
        finding_a: StudyFinding,
        finding_b: StudyFinding,
        conflict_id: Optional[str] = None,
    ) -> Optional[ConflictRecord]:
        """Analyzes a comparative cell and generates a ConflictRecord if a discrepancy exists."""
        cid = conflict_id or f"conflict-{uuid.uuid4().hex[:8]}"
        coordinates = self._collect_coordinates(finding_a, finding_b)

        # 1. Incomparable setup check
        if not cell.is_comparable or any(
            c.severity == CaveatSeverity.INCOMPARABLE for c in cell.caveats
        ):
            has_divergence = (
                cell.delta is None or abs(cell.delta) >= self.discrepancy_threshold
            )
            if has_divergence:
                delta_str = (
                    f"delta={cell.delta:.4f}"
                    if cell.delta is not None
                    else "non-identical metrics"
                )
                return ConflictRecord(
                    conflict_id=cid,
                    conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
                    finding_a_id=finding_a.finding_id,
                    finding_b_id=finding_b.finding_id,
                    description=(
                        f"Apparent discrepancy ({delta_str}) between "
                        f"'{finding_a.method_name}' and '{finding_b.method_name}' is "
                        "explained by non-identical evaluation conditions or metrics."
                    ),
                    is_genuine_contradiction=False,
                    evidence_coordinates=coordinates,
                    comparability_caveats=cell.caveats,
                )
            return None

        # 2. Comparable setup: Evaluate empirical consistency
        norm_method_a = self._normalize_name(finding_a.method_name)
        norm_method_b = self._normalize_name(finding_b.method_name)

        if cell.delta is not None:
            abs_delta = abs(cell.delta)

            # Case A: Condition boundary discrepancy
            if any(c.caveat_type == "CONDITION_DISPARITY" for c in cell.caveats):
                if abs_delta >= self.discrepancy_threshold:
                    return ConflictRecord(
                        conflict_id=cid,
                        conflict_type=ConflictType.BOUNDARY_CONDITION_DISCREPANCY,
                        finding_a_id=finding_a.finding_id,
                        finding_b_id=finding_b.finding_id,
                        description=(
                            f"Boundary condition sensitivity: {finding_a.metric_name} varies by "
                            f"{abs_delta:.4f} across differing experimental parameter conditions."
                        ),
                        is_genuine_contradiction=True,
                        evidence_coordinates=coordinates,
                        comparability_caveats=cell.caveats,
                    )

            # Case B: Same method evaluated under identical comparable conditions
            if norm_method_a == norm_method_b:
                if abs_delta >= self.discrepancy_threshold:
                    return ConflictRecord(
                        conflict_id=cid,
                        conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
                        finding_a_id=finding_a.finding_id,
                        finding_b_id=finding_b.finding_id,
                        description=(
                            f"Direct empirical contradiction: Method '{finding_a.method_name}' "
                            f"yields conflicting {finding_a.metric_name} scores "
                            f"({finding_a.metric_value} vs {finding_b.metric_value}, "
                            f"delta={cell.delta:.4f}) on {finding_a.dataset_name}."
                        ),
                        is_genuine_contradiction=True,
                        evidence_coordinates=coordinates,
                        comparability_caveats=cell.caveats,
                    )

        return None

    def detect_conflicts(
        self,
        matrix: ComparativeMatrix,
    ) -> List[ConflictRecord]:
        """Scans an entire ComparativeMatrix to extract all conflicts and apparent discrepancies."""
        findings_map: Dict[str, StudyFinding] = {f.finding_id: f for f in matrix.findings}
        conflicts: List[ConflictRecord] = []

        for cell in matrix.cells:
            fa = findings_map.get(cell.finding_a_id)
            fb = findings_map.get(cell.finding_b_id)
            if not fa or not fb:
                continue

            conflict = self.evaluate_cell(cell, fa, fb)
            if conflict is not None:
                conflicts.append(conflict)

        # Cross-method superiority contradiction analysis:
        # Check if study A finds Method X > Method Y, but study B finds Method Y > Method X
        conflicts.extend(self._detect_cross_method_superiority_conflicts(matrix, findings_map))

        return conflicts

    def _detect_cross_method_superiority_conflicts(
        self,
        matrix: ComparativeMatrix,
        findings_map: Dict[str, StudyFinding],
    ) -> List[ConflictRecord]:
        """Detects conflicting claims regarding relative superiority of methods."""
        superiority_conflicts: List[ConflictRecord] = []
        # Group findings by (document_id, normalized_dataset, normalized_metric)
        grouped_by_doc: Dict[str, List[StudyFinding]] = {}
        for f in matrix.findings:
            ds_norm = self._normalize_name(f.dataset_name)
            m_norm = self._normalize_name(f.metric_name)
            key = f"{f.document_id}::{ds_norm}::{m_norm}"
            grouped_by_doc.setdefault(key, []).append(f)

        # Compare relative method comparisons across distinct documents
        doc_keys = list(grouped_by_doc.keys())
        for i in range(len(doc_keys)):
            for j in range(i + 1, len(doc_keys)):
                k1, k2 = doc_keys[i], doc_keys[j]
                # Same dataset and metric across different documents
                _, ds1, m1 = k1.split("::")
                _, ds2, m2 = k2.split("::")
                if ds1 != ds2 or m1 != m2:
                    continue

                list1 = grouped_by_doc[k1]
                list2 = grouped_by_doc[k2]

                for f1_a in list1:
                    for f1_b in list1:
                        if f1_a.finding_id >= f1_b.finding_id:
                            continue
                        m_a = self._normalize_name(f1_a.method_name)
                        m_b = self._normalize_name(f1_b.method_name)
                        if m_a == m_b:
                            continue

                        # Find matching methods in list2
                        f2_a = next(
                            (x for x in list2 if self._normalize_name(x.method_name) == m_a),
                            None,
                        )
                        f2_b = next(
                            (x for x in list2 if self._normalize_name(x.method_name) == m_b),
                            None,
                        )
                        if not f2_a or not f2_b:
                            continue

                        # Check relative direction: does doc 1 claim m_a > m_b
                        # while doc 2 claims m_b > m_a?
                        higher_is_better = (
                            f1_a.metric_direction == MetricDirection.HIGHER_IS_BETTER
                        )
                        doc1_prefers_a = (
                            (f1_a.metric_value > f1_b.metric_value)
                            if higher_is_better
                            else (f1_a.metric_value < f1_b.metric_value)
                        )
                        doc2_prefers_a = (
                            (f2_a.metric_value > f2_b.metric_value)
                            if higher_is_better
                            else (f2_a.metric_value < f2_b.metric_value)
                        )

                        if doc1_prefers_a != doc2_prefers_a:
                            coords = self._collect_coordinates(f1_a, f2_a)
                            superiority_conflicts.append(
                                ConflictRecord(
                                    conflict_id=f"conflict-sup-{uuid.uuid4().hex[:8]}",
                                    conflict_type=ConflictType.CROSS_METHOD_SUPERIORITY_CONTRADICTION,
                                    finding_a_id=f1_a.finding_id,
                                    finding_b_id=f2_a.finding_id,
                                    description=(
                                        f"Cross-method superiority conflict: Document "
                                        f"'{f1_a.document_id}' prefers {f1_a.method_name} over "
                                        f"{f1_b.method_name}, while Document '{f2_a.document_id}' "
                                        f"prefers {f2_b.method_name} under comparable setup."
                                    ),
                                    is_genuine_contradiction=True,
                                    evidence_coordinates=coords,
                                )
                            )

        return superiority_conflicts
