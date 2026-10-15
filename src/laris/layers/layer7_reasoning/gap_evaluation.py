"""Synthetic gold standard dataset and evaluation harness for research gap typology.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, and Issue #95:
- Curated gold standard covering all 12 GapClass categories with synthetic STEM scenarios
- Verification of bounded-corpus guard enforcing refusal of global novelty claims
- Uncertainty propagation verification for sparse versus comprehensive literature sampling
- Automated evaluation metrics reporting classification accuracy and guard adherence
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from laris.core.errors import EpistemicOverreachError
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer7_reasoning.gap_classifier import RuleBasedGapClassifier
from laris.layers.layer7_reasoning.gap_scorer import CalibratedGapScoringEngine
from laris.layers.layer7_reasoning.schemas import (
    CaveatSeverity,
    ComparabilityCaveat,
    ConflictRecord,
    ConflictType,
    CorpusScope,
    GapClass,
)


@dataclass(frozen=True)
class GapTypologyGoldCase:
    """Individual synthetic benchmark case for gap typology and scoring calibration."""

    case_id: str
    expected_class: GapClass
    title: str
    description: str
    scenario_domain: str
    conflict_record: Optional[ConflictRecord] = None
    corpus_scope: Optional[CorpusScope] = None
    input_novelty: float = 0.8
    input_grounding: float = 0.8
    input_feasibility: float = 0.7
    input_significance: float = 0.8
    input_uncertainty: float = 0.1
    expected_uncertainty_floor: Optional[float] = None
    assert_global_claim: bool = False
    should_refuse_global: bool = False


@dataclass(frozen=True)
class GapEvaluationReport:
    """Summary report detailing gap classification accuracy and guard adherence."""

    total_cases: int
    correct_classifications: int
    accuracy: float
    bounded_guard_tests: int
    bounded_guard_adherence: float
    uncertainty_calibration_tests: int
    uncertainty_calibration_adherence: float
    passed: bool
    confusion_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)


class GapTypologyEvaluationSuite:
    """Harness evaluating the 12-class gap typology and scoring calibration."""

    def __init__(
        self,
        classifier: Optional[RuleBasedGapClassifier] = None,
        scoring_engine: Optional[CalibratedGapScoringEngine] = None,
    ) -> None:
        self.classifier = classifier or RuleBasedGapClassifier()
        self.scoring_engine = scoring_engine or CalibratedGapScoringEngine()

    @staticmethod
    def _create_synthetic_coordinate(doc_id: str, snippet: str) -> EvidenceCoordinate:
        doc_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
        return EvidenceCoordinate(
            coordinate_id=f"coord-{hashlib.sha256(doc_id.encode()).hexdigest()[:8]}",
            document_id=doc_id,
            document_sha256=doc_hash,
            page_number=2,
            section_identifier="sec-eval",
            paragraph_index=1,
            sentence_index=3,
            char_start=0,
            char_end=len(snippet),
            verbatim_snippet=snippet,
            extraction_confidence=0.99,
        )

    def generate_gold_set(self) -> List[GapTypologyGoldCase]:
        """Constructs a comprehensive synthetic gold set across all 12 gap categories."""
        cases: List[GapTypologyGoldCase] = []

        # 1. DEPLOYMENT_RESOURCE_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-01-deployment-resource",
                expected_class=GapClass.DEPLOYMENT_RESOURCE_GAP,
                title="Excessive VRAM Footprint in 3D Point Cloud Processing",
                description=(
                    "State-of-the-art lidar segmentation requires 28 GB VRAM, preventing "
                    "real-time embedded deployment on autonomous vehicle edge hardware."
                ),
                scenario_domain="Autonomous Vehicles / Embedded Systems",
                input_novelty=0.75,
                input_grounding=0.90,
                input_feasibility=0.85,
                input_significance=0.80,
                input_uncertainty=0.10,
            )
        )

        # 2. REPRODUCIBILITY_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-02-reproducibility",
                expected_class=GapClass.REPRODUCIBILITY_GAP,
                title="Missing Artifacts and Non-Reproducible Quantum Teleportation Claims",
                description=(
                    "Attempts to replicate experimental quantum teleportation fidelities "
                    "failed due to missing calibration artifacts and unreproducible code."
                ),
                scenario_domain="Quantum Information",
                input_novelty=0.70,
                input_grounding=0.85,
                input_feasibility=0.60,
                input_significance=0.75,
                input_uncertainty=0.15,
            )
        )

        # 3. MEASUREMENT_EVALUATION_GAP
        coord_eval = self._create_synthetic_coordinate("paper-eval-01", "Metric disparity")
        caveat_eval = ComparabilityCaveat(
            caveat_type="METRIC_DISPARITY",
            description="Comparison between Word Error Rate and Sentence Accuracy.",
            severity=CaveatSeverity.INCOMPARABLE,
        )
        conf_eval = ConflictRecord(
            conflict_id="conf-eval-01",
            conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
            finding_a_id="f-eval-1",
            finding_b_id="f-eval-2",
            description="Apparent discrepancy explained by incompatible metric definitions.",
            is_genuine_contradiction=False,
            evidence_coordinates=[coord_eval],
            comparability_caveats=[caveat_eval],
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-03-measurement-evaluation",
                expected_class=GapClass.MEASUREMENT_EVALUATION_GAP,
                title="Inadequate Evaluation Protocol in Speech Recognition",
                description="Evaluation metric suffers from benchmark leakage and scoring flaws.",
                scenario_domain="Speech Processing",
                conflict_record=conf_eval,
            )
        )

        # 4. DATASET_DOMAIN_GAP
        coord_dom = self._create_synthetic_coordinate("paper-dom-01", "Domain disparity")
        caveat_dom = ComparabilityCaveat(
            caveat_type="SPLIT_DISPARITY",
            description="In-domain studio audio vs noisy real-world field recordings.",
            severity=CaveatSeverity.INCOMPARABLE,
        )
        conf_dom = ConflictRecord(
            conflict_id="conf-dom-01",
            conflict_type=ConflictType.APPARENT_CONFLICT_INCOMPARABLE,
            finding_a_id="f-dom-1",
            finding_b_id="f-dom-2",
            description="Performance difference attributable to domain shift.",
            is_genuine_contradiction=False,
            evidence_coordinates=[coord_dom],
            comparability_caveats=[caveat_dom],
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-04-dataset-domain",
                expected_class=GapClass.DATASET_DOMAIN_GAP,
                title="Dataset Scarcity in Low-Resource Acoustic Environments",
                description="Dataset scarcity and unannotated domain shift impede generalization.",
                scenario_domain="Acoustic Signal Processing",
                conflict_record=conf_dom,
            )
        )

        # 5. GENERALIZATION_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-05-generalization",
                expected_class=GapClass.GENERALIZATION_GAP,
                title="Catastrophic Degradation Under Out-of-Distribution Weather Shift",
                description=(
                    "Vision models degrade sharply under covariate distribution shift and "
                    "out-of-distribution OOD adversarial weather conditions."
                ),
                scenario_domain="Computer Vision",
                input_novelty=0.80,
                input_grounding=0.85,
                input_feasibility=0.75,
                input_significance=0.85,
                input_uncertainty=0.10,
            )
        )

        # 6. ASSUMPTION_BOUNDARY_GAP
        coord_bound = self._create_synthetic_coordinate("paper-cryo-01", "Thermal limit")
        caveat_bound = ComparabilityCaveat(
            caveat_type="CONDITION_DISPARITY",
            description="Operating temperature exceeds superconductivity threshold.",
            severity=CaveatSeverity.CAUTION,
        )
        conf_bound = ConflictRecord(
            conflict_id="conf-bound-01",
            conflict_type=ConflictType.BOUNDARY_CONDITION_DISCREPANCY,
            finding_a_id="f-bound-1",
            finding_b_id="f-bound-2",
            description="Gate fidelity drops sharply above 100 mK operating limit.",
            is_genuine_contradiction=True,
            evidence_coordinates=[coord_bound],
            comparability_caveats=[caveat_bound],
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-06-assumption-boundary",
                expected_class=GapClass.ASSUMPTION_BOUNDARY_GAP,
                title="Superconducting Qubit Coherence Breakdown at Thermal Boundary",
                description="Breakdown observed when stage temperature exceeds operating boundary.",
                scenario_domain="Superconducting Hardware",
                conflict_record=conf_bound,
            )
        )

        # 7. INTEGRATION_INTERDISCIPLINARY_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-07-integration-interdisciplinary",
                expected_class=GapClass.INTEGRATION_INTERDISCIPLINARY_GAP,
                title="Unbridged Theoretical Divide Between Crystallography and Deep Learning",
                description=(
                    "Siloed disciplines lack an interdisciplinary cross-discipline framework "
                    "bridging molecular dynamics with transformer representations."
                ),
                scenario_domain="Structural Bioinformatics",
                input_novelty=0.90,
                input_grounding=0.80,
                input_feasibility=0.70,
                input_significance=0.90,
                input_uncertainty=0.15,
            )
        )

        # 8. TEMPORAL_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-08-temporal",
                expected_class=GapClass.TEMPORAL_GAP,
                title="Temporal Concept Drift in Longitudinal Epidemiological Surveillance",
                description=(
                    "Temporal concept drift renders historical outdated baselines obsolete "
                    "as viral transmission dynamics evolve over time."
                ),
                scenario_domain="Epidemiology",
                input_novelty=0.75,
                input_grounding=0.85,
                input_feasibility=0.80,
                input_significance=0.85,
                input_uncertainty=0.10,
            )
        )

        # 9. CONFLICTING_EVIDENCE_GAP
        coord_conf = self._create_synthetic_coordinate("paper-conflict-01", "Contradiction")
        conf_emp = ConflictRecord(
            conflict_id="conf-emp-01",
            conflict_type=ConflictType.DIRECT_EMPIRICAL_CONTRADICTION,
            finding_a_id="f-emp-1",
            finding_b_id="f-emp-2",
            description=(
                "Direct empirical contradiction between two independent replication studies."
            ),
            is_genuine_contradiction=True,
            evidence_coordinates=[coord_conf],
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-09-conflicting-evidence",
                expected_class=GapClass.CONFLICTING_EVIDENCE_GAP,
                title="Direct Empirical Contradiction on Perovskite Bandgap Stability",
                description=(
                    "Opposing empirical findings show severe contradiction between studies."
                ),
                scenario_domain="Materials Chemistry",
                conflict_record=conf_emp,
            )
        )

        # 10. METHODOLOGICAL_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-10-methodological",
                expected_class=GapClass.METHODOLOGICAL_GAP,
                title="Algorithmic Limitation in Non-Equilibrium Thermodynamic Simulation",
                description=(
                    "Current algorithmic limitation in modeling methodology prevents accurate "
                    "computation of entropy generation in chaotic fluids."
                ),
                scenario_domain="Computational Physics",
                input_novelty=0.85,
                input_grounding=0.80,
                input_feasibility=0.75,
                input_significance=0.85,
                input_uncertainty=0.10,
            )
        )

        # 11. KNOWLEDGE_GAP
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-11-knowledge",
                expected_class=GapClass.KNOWLEDGE_GAP,
                title="Unknown Quantum Entanglement Mechanism in Warm Biological Molecules",
                description=(
                    "The underlying theoretical mechanism and fundamental scientific principle "
                    "governing coherence in avian magnetoreception remain unknown."
                ),
                scenario_domain="Quantum Biology",
                input_novelty=0.95,
                input_grounding=0.75,
                input_feasibility=0.65,
                input_significance=0.95,
                input_uncertainty=0.20,
            )
        )

        # 12. UNDEREXPLORED_RESEARCH_QUESTION
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-12-underexplored",
                expected_class=GapClass.UNDEREXPLORED_RESEARCH_QUESTION,
                title="Phytoplankton Radiative Forcing Under Arctic Sea Ice Retreat",
                description=(
                    "An underexplored open question with scarce literature and uncharted scope "
                    "regarding biological albedo shifts in seasonal polar melts."
                ),
                scenario_domain="Polar Climatology",
                input_novelty=0.90,
                input_grounding=0.70,
                input_feasibility=0.75,
                input_significance=0.85,
                input_uncertainty=0.20,
            )
        )

        # 13. Bounded-Corpus Guard Refusal Case
        scope_bounded = CorpusScope(
            scope_id="scope-quantum-bounded",
            document_count=50,
            is_bounded=True,
            coverage_notes="Restricted to cryo-qubits.",
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-13-bounded-guard-refusal",
                expected_class=GapClass.METHODOLOGICAL_GAP,
                title="Algorithmic Methodology Limitation and Global Claim Refusal",
                description=(
                    "Algorithmic modeling methodology limitation with invalid global novelty claim."
                ),
                scenario_domain="Epistemic Verification",
                corpus_scope=scope_bounded,
                assert_global_claim=True,
                should_refuse_global=True,
            )
        )

        # 14. Sparse Corpus Uncertainty Floor Calibration Case
        scope_sparse = CorpusScope(
            scope_id="scope-nascent-sparse",
            document_count=3,
            is_bounded=True,
            coverage_notes="Sparse sample of only 3 papers.",
        )
        cases.append(
            GapTypologyGoldCase(
                case_id="gold-14-sparse-uncertainty-floor",
                expected_class=GapClass.UNDEREXPLORED_RESEARCH_QUESTION,
                title="Sparse Corpus Epistemic Uncertainty Elevation",
                description=(
                    "Sparse corpus coverage must elevate minimum uncertainty floor to 0.20."
                ),
                scenario_domain="Epistemic Verification",
                corpus_scope=scope_sparse,
                input_uncertainty=0.04,
                expected_uncertainty_floor=0.20,
            )
        )

        return cases

    def run_evaluation(
        self,
        cases: Optional[List[GapTypologyGoldCase]] = None,
    ) -> GapEvaluationReport:
        """Executes full evaluation suite against gold set cases and returns structured report."""
        eval_cases = cases if cases is not None else self.generate_gold_set()

        total = len(eval_cases)
        correct_classifications = 0
        bounded_guard_tests = 0
        bounded_guard_passed = 0
        uncertainty_tests = 0
        uncertainty_passed = 0
        failures: List[str] = []
        confusion: Dict[str, Dict[str, int]] = {}

        for case in eval_cases:
            # 1. Classification check
            pred_class = self.classifier.classify_candidate(
                title=case.title,
                description=case.description,
                conflict=case.conflict_record,
            )
            exp_str = case.expected_class.value
            pred_str = pred_class.value
            confusion.setdefault(exp_str, {}).setdefault(pred_str, 0)
            confusion[exp_str][pred_str] += 1

            if pred_class == case.expected_class:
                correct_classifications += 1
            else:
                failures.append(
                    f"[{case.case_id}] Expected {case.expected_class.value}, "
                    f"got {pred_class.value}."
                )

            # 2. Bounded Guard Check
            if case.should_refuse_global:
                bounded_guard_tests += 1
                try:
                    self.scoring_engine.score_gap(
                        novelty=case.input_novelty,
                        grounding=case.input_grounding,
                        feasibility=case.input_feasibility,
                        significance=case.input_significance,
                        uncertainty=case.input_uncertainty,
                        corpus_scope=case.corpus_scope,
                        assert_global_novelty=True,
                    )
                    failures.append(
                        f"[{case.case_id}] Failed to refuse global novelty claim on bounded corpus."
                    )
                except EpistemicOverreachError:
                    bounded_guard_passed += 1

            # 3. Uncertainty Calibration Check
            if case.expected_uncertainty_floor is not None:
                uncertainty_tests += 1
                scores = self.scoring_engine.score_gap(
                    novelty=case.input_novelty,
                    grounding=case.input_grounding,
                    feasibility=case.input_feasibility,
                    significance=case.input_significance,
                    uncertainty=case.input_uncertainty,
                    corpus_scope=case.corpus_scope,
                    assert_global_novelty=False,
                )
                if scores.uncertainty >= case.expected_uncertainty_floor:
                    uncertainty_passed += 1
                else:
                    failures.append(
                        f"[{case.case_id}] Uncertainty {scores.uncertainty} below expected "
                        f"floor {case.expected_uncertainty_floor}."
                    )

        acc = correct_classifications / total if total > 0 else 0.0
        guard_rate = (
            bounded_guard_passed / bounded_guard_tests if bounded_guard_tests > 0 else 1.0
        )
        unc_rate = uncertainty_passed / uncertainty_tests if uncertainty_tests > 0 else 1.0

        passed = (acc == 1.0) and (guard_rate == 1.0) and (unc_rate == 1.0)

        return GapEvaluationReport(
            total_cases=total,
            correct_classifications=correct_classifications,
            accuracy=round(acc, 4),
            bounded_guard_tests=bounded_guard_tests,
            bounded_guard_adherence=round(guard_rate, 4),
            uncertainty_calibration_tests=uncertainty_tests,
            uncertainty_calibration_adherence=round(unc_rate, 4),
            passed=passed,
            confusion_breakdown=confusion,
            failures=failures,
        )
