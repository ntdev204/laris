"""Synthetic scientific contradiction benchmarks and comparability evaluation suite.

Adheres to DOC-SPEC-MOD-001 (Boundary G), ADR-001, and ADR-004:
- Comprehensive synthetic benchmark cases testing true conflicts vs incomparable setups
- Zero data download; self-contained synthetic fixtures with verifiable coordinates
- Automated evaluation of conflict precision, recall, and evidence citation integrity
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Optional

from laris.core.schemas import EvidenceCoordinate
from laris.reasoning.conflict_detector import ConditionAwareConflictDetector
from laris.reasoning.matrix_engine import ComparativeMatrixEngine
from laris.reasoning.schemas import (
    ConflictType,
    MetricDirection,
    StudyFinding,
)


@dataclass(frozen=True)
class ContradictionBenchmarkCase:
    """Individual synthetic benchmark test case pairing two findings with expected outcome."""

    case_id: str
    scenario_description: str
    finding_a: StudyFinding
    finding_b: StudyFinding
    expected_conflict_type: Optional[ConflictType]
    expected_is_genuine: bool


@dataclass(frozen=True)
class ConflictBenchmarkReport:
    """Quantitative performance and evidence citation report for conflict detection."""

    total_cases: int
    matched_cases: int
    unmatched_cases: int
    false_positives: int
    evidence_citation_rate: float
    accuracy: float
    passed: bool
    details: List[str] = field(default_factory=list)


class ConflictEvaluationBenchmark:
    """Evaluation harness running synthetic contradiction and comparability benchmarks."""

    def __init__(
        self,
        matrix_engine: Optional[ComparativeMatrixEngine] = None,
        conflict_detector: Optional[ConditionAwareConflictDetector] = None,
    ) -> None:
        self.matrix_engine = matrix_engine or ComparativeMatrixEngine()
        self.conflict_detector = conflict_detector or ConditionAwareConflictDetector()

    @staticmethod
    def _create_synthetic_coordinate(
        doc_id: str,
        snippet: str,
        page: int = 1,
    ) -> EvidenceCoordinate:
        """Helper generating a valid EvidenceCoordinate with canonical SHA-256."""
        doc_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
        return EvidenceCoordinate(
            coordinate_id=f"coord-{hashlib.sha256(doc_id.encode()).hexdigest()[:8]}",
            document_id=doc_id,
            document_sha256=doc_hash,
            page_number=page,
            section_identifier="sec-results",
            paragraph_index=1,
            sentence_index=2,
            char_start=0,
            char_end=len(snippet),
            verbatim_snippet=snippet,
            extraction_confidence=0.99,
        )

    def generate_benchmark_suite(self) -> List[ContradictionBenchmarkCase]:
        """Builds a curated suite of scientific benchmark cases across six modalities."""
        cases: List[ContradictionBenchmarkCase] = []

        # 1. True Direct Empirical Contradiction (Identical conditions, disparate results)
        snippet_1a = "Transmon Qubit-1 yields T1 relaxation time of 125.4 microseconds."
        snippet_1b = (
            "Under identical dilution refrigerator conditions, Qubit-1 yields T1 of 32.1 us."
        )
        f_1a = StudyFinding(
            finding_id="t1-alpha",
            document_id="paper-qubit-2023",
            method_name="TransmonQubit",
            dataset_name="CryoBenchmark",
            dataset_split="test",
            metric_name="T1_relaxation_us",
            metric_value=125.4,
            metric_direction=MetricDirection.HIGHER_IS_BETTER,
            condition_parameters={"temperature_mk": 15, "frequency_ghz": 5.2},
            evidence_coordinates=[
                self._create_synthetic_coordinate("paper-qubit-2023", snippet_1a)
            ],
        )
        f_1b = StudyFinding(
            finding_id="t1-beta",
            document_id="paper-qubit-2024",
            method_name="TransmonQubit",
            dataset_name="CryoBenchmark",
            dataset_split="test",
            metric_name="T1_relaxation_us",
            metric_value=32.1,
            metric_direction=MetricDirection.HIGHER_IS_BETTER,
            condition_parameters={"temperature_mk": 15, "frequency_ghz": 5.2},
            evidence_coordinates=[
                self._create_synthetic_coordinate("paper-qubit-2024", snippet_1b)
            ],
        )
        cases.append(
            ContradictionBenchmarkCase(
                case_id="case-01-direct-empirical-contradiction",
                scenario_description=(
                    "Identical hardware and temperature, contradictory T1 coherence"
                ),
                finding_a=f_1a,
                finding_b=f_1b,
                expected_conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
                expected_is_genuine=True,
            )
        )

        # 2. Apparent Conflict: Disparate Dataset Splits (In-domain vs OOD)
        snippet_2a = "Model achieves 91.2% accuracy on in-domain test set."
        snippet_2b = "Under cross-domain distribution shift, accuracy degrades to 58.4%."
        f_2a = StudyFinding(
            finding_id="ood-indomain",
            document_id="paper-cv-2023",
            method_name="ResNet50Robust",
            dataset_name="ImageNetRobust",
            dataset_split="in_domain_test",
            metric_name="top1_acc",
            metric_value=0.912,
            metric_direction=MetricDirection.HIGHER_IS_BETTER,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-cv-2023", snippet_2a)],
        )
        f_2b = StudyFinding(
            finding_id="ood-shifted",
            document_id="paper-cv-2024",
            method_name="ResNet50Robust",
            dataset_name="ImageNetRobust",
            dataset_split="ood_adversarial_split",
            metric_name="top1_acc",
            metric_value=0.584,
            metric_direction=MetricDirection.HIGHER_IS_BETTER,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-cv-2024", snippet_2b)],
        )
        cases.append(
            ContradictionBenchmarkCase(
                case_id="case-02-apparent-conflict-split-mismatch",
                scenario_description="Apparent score drop explained by in-domain vs OOD split",
                finding_a=f_2a,
                finding_b=f_2b,
                expected_conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
                expected_is_genuine=False,
            )
        )

        # 3. Apparent Conflict: Incompatible Metrics (Error rate vs Accuracy)
        snippet_3a = "Word error rate is 8.5% on LibriSpeech."
        snippet_3b = "Accuracy is 91.5% on LibriSpeech test clean."
        f_3a = StudyFinding(
            finding_id="asr-wer",
            document_id="paper-asr-2023",
            method_name="ConformerASR",
            dataset_name="LibriSpeech",
            dataset_split="test",
            metric_name="WER",
            metric_value=0.085,
            metric_direction=MetricDirection.LOWER_IS_BETTER,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-asr-2023", snippet_3a)],
        )
        f_3b = StudyFinding(
            finding_id="asr-acc",
            document_id="paper-asr-2024",
            method_name="ConformerASR",
            dataset_name="LibriSpeech",
            dataset_split="test",
            metric_name="Accuracy",
            metric_value=0.915,
            metric_direction=MetricDirection.HIGHER_IS_BETTER,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-asr-2024", snippet_3b)],
        )
        cases.append(
            ContradictionBenchmarkCase(
                case_id="case-03-apparent-conflict-metric-mismatch",
                scenario_description=(
                    "Differing metric definitions (WER vs Accuracy) are incomparable"
                ),
                finding_a=f_3a,
                finding_b=f_3b,
                expected_conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
                expected_is_genuine=False,
            )
        )

        # 4. Boundary Condition Discrepancy (Parameter sensitivity)
        snippet_4a = "At low temperature 10 mK, gate fidelity is 99.8%."
        snippet_4b = "Elevating stage temperature to 100 mK drops fidelity to 88.2%."
        f_4a = StudyFinding(
            finding_id="gate-10mk",
            document_id="paper-gates-2023",
            method_name="TwoQubitCZGate",
            dataset_name="QuantumFidelity",
            dataset_split="test",
            metric_name="Fidelity",
            metric_value=0.998,
            condition_parameters={"temperature_mk": 10},
            evidence_coordinates=[
                self._create_synthetic_coordinate("paper-gates-2023", snippet_4a)
            ],
        )
        f_4b = StudyFinding(
            finding_id="gate-100mk",
            document_id="paper-gates-2024",
            method_name="TwoQubitCZGate",
            dataset_name="QuantumFidelity",
            dataset_split="test",
            metric_name="Fidelity",
            metric_value=0.882,
            condition_parameters={"temperature_mk": 100},
            evidence_coordinates=[
                self._create_synthetic_coordinate("paper-gates-2024", snippet_4b)
            ],
        )
        cases.append(
            ContradictionBenchmarkCase(
                case_id="case-04-boundary-condition-discrepancy",
                scenario_description=(
                    "Fidelity variation attributable to thermal operating boundary"
                ),
                finding_a=f_4a,
                finding_b=f_4b,
                expected_conflict_type=ConflictType.BOUNDARY_CONDITION_DISCREPANCY,
                expected_is_genuine=True,
            )
        )

        # 5. Non-conflicting Consistent Replications
        snippet_5a = "Replication study A measures bandgap of 1.42 eV."
        snippet_5b = "Replication study B measures bandgap of 1.43 eV."
        f_5a = StudyFinding(
            finding_id="gaas-a",
            document_id="paper-semi-2022",
            method_name="Photoluminescence",
            dataset_name="GaAsCrystals",
            dataset_split="test",
            metric_name="Bandgap_eV",
            metric_value=1.42,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-semi-2022", snippet_5a)],
        )
        f_5b = StudyFinding(
            finding_id="gaas-b",
            document_id="paper-semi-2023",
            method_name="Photoluminescence",
            dataset_name="GaAsCrystals",
            dataset_split="test",
            metric_name="Bandgap_eV",
            metric_value=1.43,
            evidence_coordinates=[self._create_synthetic_coordinate("paper-semi-2023", snippet_5b)],
        )
        cases.append(
            ContradictionBenchmarkCase(
                case_id="case-05-consistent-replication-no-conflict",
                scenario_description="Consistent experimental measurements within margin of error",
                finding_a=f_5a,
                finding_b=f_5b,
                expected_conflict_type=None,
                expected_is_genuine=False,
            )
        )

        return cases

    def run_benchmark(
        self,
        cases: Optional[List[ContradictionBenchmarkCase]] = None,
    ) -> ConflictBenchmarkReport:
        """Executes the benchmark evaluation and returns a typed validation report."""
        suite = cases or self.generate_benchmark_suite()
        matched = 0
        unmatched = 0
        false_positives = 0
        evidence_cited_count = 0
        total_conflicts_evaluated = 0
        details: List[str] = []

        for case in suite:
            cell = self.matrix_engine.compare_pair(case.finding_a, case.finding_b)
            conflict = self.conflict_detector.evaluate_cell(cell, case.finding_a, case.finding_b)

            if conflict is not None:
                total_conflicts_evaluated += 1
                if conflict.evidence_coordinates:
                    evidence_cited_count += 1

            if case.expected_conflict_type is None:
                # Expected no conflict
                if conflict is None:
                    matched += 1
                    details.append(f"PASS: {case.case_id} correctly yielded no conflict.")
                else:
                    unmatched += 1
                    false_positives += 1
                    details.append(
                        f"FAIL: {case.case_id} expected no conflict, got {conflict.conflict_type}."
                    )
            else:
                # Expected conflict
                if conflict is None:
                    unmatched += 1
                    details.append(
                        f"FAIL: {case.case_id} expected {case.expected_conflict_type}, got None."
                    )
                elif conflict.conflict_type == case.expected_conflict_type:
                    matched += 1
                    details.append(
                        f"PASS: {case.case_id} correctly identified {conflict.conflict_type}."
                    )
                else:
                    unmatched += 1
                    details.append(
                        f"FAIL: {case.case_id} expected {case.expected_conflict_type}, "
                        f"got {conflict.conflict_type}."
                    )

        total_cases = len(suite)
        accuracy = matched / total_cases if total_cases > 0 else 0.0
        citation_rate = (
            evidence_cited_count / total_conflicts_evaluated
            if total_conflicts_evaluated > 0
            else 1.0
        )
        passed = (unmatched == 0) and (citation_rate == 1.0) and (false_positives == 0)

        return ConflictBenchmarkReport(
            total_cases=total_cases,
            matched_cases=matched,
            unmatched_cases=unmatched,
            false_positives=false_positives,
            evidence_citation_rate=citation_rate,
            accuracy=accuracy,
            passed=passed,
            details=details,
        )
