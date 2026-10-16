"""Comparative matrix construction and experimental condition alignment.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, and ADR-004:
- Cross-paper experimental condition and metric alignment
- Systematic comparability evaluation and caveat generation
- Prevention of false comparisons across mismatched datasets, splits, or metrics
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.reasoning.schemas import (
    CaveatSeverity,
    ComparabilityCaveat,
    ComparativeCell,
    ComparativeMatrix,
    StudyFinding,
)


class ComparativeMatrixEngine:
    """Engine constructing pairwise comparative matrices across experimental findings."""

    def __init__(
        self,
        strict_split_matching: bool = True,
        strict_condition_matching: bool = False,
    ) -> None:
        self.strict_split_matching = strict_split_matching
        self.strict_condition_matching = strict_condition_matching

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.strip().lower().replace("_", "").replace("-", "")

    def compare_pair(
        self,
        finding_a: StudyFinding,
        finding_b: StudyFinding,
        cell_id: Optional[str] = None,
    ) -> ComparativeCell:
        """Evaluates pairwise comparability between two experimental findings."""
        cid = cell_id or f"cell-{uuid.uuid4().hex[:8]}"
        caveats: List[ComparabilityCaveat] = []

        # 1. Metric alignment
        norm_metric_a = self._normalize_name(finding_a.metric_name)
        norm_metric_b = self._normalize_name(finding_b.metric_name)
        if norm_metric_a != norm_metric_b:
            caveats.append(
                ComparabilityCaveat(
                    caveat_type="METRIC_MISMATCH",
                    description=(
                        f"Metric mismatch: '{finding_a.metric_name}' vs "
                        f"'{finding_b.metric_name}'."
                    ),
                    severity=CaveatSeverity.INCOMPARABLE,
                )
            )

        if finding_a.metric_direction != finding_b.metric_direction:
            caveats.append(
                ComparabilityCaveat(
                    caveat_type="METRIC_DIRECTION_MISMATCH",
                    description=(
                        f"Conflicting metric optimization goals: "
                        f"'{finding_a.metric_direction.value}' vs "
                        f"'{finding_b.metric_direction.value}'."
                    ),
                    severity=CaveatSeverity.INCOMPARABLE,
                )
            )

        # 2. Dataset alignment
        norm_ds_a = self._normalize_name(finding_a.dataset_name)
        norm_ds_b = self._normalize_name(finding_b.dataset_name)
        if norm_ds_a != norm_ds_b:
            caveats.append(
                ComparabilityCaveat(
                    caveat_type="DATASET_MISMATCH",
                    description=(
                        f"Dataset mismatch: '{finding_a.dataset_name}' vs "
                        f"'{finding_b.dataset_name}'."
                    ),
                    severity=CaveatSeverity.INCOMPARABLE,
                )
            )

        # 3. Dataset split alignment
        split_a = finding_a.dataset_split
        split_b = finding_b.dataset_split
        if split_a is not None and split_b is not None:
            if self._normalize_name(split_a) != self._normalize_name(split_b):
                severity = (
                    CaveatSeverity.INCOMPARABLE
                    if self.strict_split_matching
                    else CaveatSeverity.CAUTION
                )
                caveats.append(
                    ComparabilityCaveat(
                        caveat_type="DATASET_SPLIT_MISMATCH",
                        description=f"Evaluation split mismatch: '{split_a}' vs '{split_b}'.",
                        severity=severity,
                    )
                )
        elif (split_a is None) ^ (split_b is None):
            caveats.append(
                ComparabilityCaveat(
                    caveat_type="UNSPECIFIED_SPLIT",
                    description="One study specifies dataset split while the other does not.",
                    severity=CaveatSeverity.CAUTION,
                )
            )

        # 4. Experimental condition parameters alignment
        shared_keys = set(finding_a.condition_parameters.keys()) & set(
            finding_b.condition_parameters.keys()
        )
        for key in sorted(shared_keys):
            val_a = finding_a.condition_parameters[key]
            val_b = finding_b.condition_parameters[key]
            if val_a != val_b:
                severity = (
                    CaveatSeverity.INCOMPARABLE
                    if self.strict_condition_matching
                    else CaveatSeverity.CAUTION
                )
                caveats.append(
                    ComparabilityCaveat(
                        caveat_type="CONDITION_DISPARITY",
                        description=(
                            f"Experimental condition disparity for parameter '{key}': "
                            f"'{val_a}' vs '{val_b}'."
                        ),
                        severity=severity,
                    )
                )

        # Check comparability
        is_comparable = not any(c.severity == CaveatSeverity.INCOMPARABLE for c in caveats)

        # Compute numerical delta and ratio if metrics match
        delta: Optional[float] = None
        ratio: Optional[float] = None
        if norm_metric_a == norm_metric_b:
            delta = finding_a.metric_value - finding_b.metric_value
            if finding_b.metric_value != 0.0:
                ratio = finding_a.metric_value / finding_b.metric_value

        return ComparativeCell(
            cell_id=cid,
            finding_a_id=finding_a.finding_id,
            finding_b_id=finding_b.finding_id,
            is_comparable=is_comparable,
            caveats=caveats,
            delta=delta,
            ratio=ratio,
        )

    def build_matrix(
        self,
        target_task_or_domain: str,
        findings: List[StudyFinding],
        matrix_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ComparativeMatrix:
        """Constructs an all-pairs comparative matrix aligning findings across studies."""
        if not target_task_or_domain or not target_task_or_domain.strip():
            raise ModuleContractViolationError(
                "build_matrix target_task_or_domain must not be empty."
            )

        mid = matrix_id or f"matrix-{uuid.uuid4().hex[:8]}"
        cells: List[ComparativeCell] = []

        # Generate pairwise cells for all distinct pairs (i < j)
        for i in range(len(findings)):
            for j in range(i + 1, len(findings)):
                fa = findings[i]
                fb = findings[j]
                cell = self.compare_pair(fa, fb, cell_id=f"cell-{fa.finding_id}-{fb.finding_id}")
                cells.append(cell)

        return ComparativeMatrix(
            matrix_id=mid,
            target_task_or_domain=target_task_or_domain,
            findings=list(findings),
            cells=cells,
            metadata=dict(metadata or {}),
        )
