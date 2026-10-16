"""Synthetic benchmark dataset and evaluation harness for adversarial counter-evidence.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, ADR-001, ADR-004, and Issue #96:
- Synthetic benchmark cases challenging candidate research gaps with counter-evidence
- Verification of decisive refutation and rejection of invalidated candidate gaps
- Verification of epistemic uncertainty elevation under empirical disputes
- Verification of concrete, falsifiable, and measurable validation protocols
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.schemas import EvidenceCoordinate
from laris.reasoning.adversarial_engine import (
    AdversarialCounterEvidenceEngine,
    ValidationPlanGenerator,
)
from laris.reasoning.schemas import (
    CalibratedGapScores,
    CandidateGapStatus,
    CounterEvidenceItem,
    GapClass,
    ResearchGap,
    ValidationPlan,
)


@dataclass(frozen=True)
class AdversarialBenchmarkCase:
    """Individual synthetic benchmark case for counter-evidence refutation and validation."""

    case_id: str
    candidate_gap: ResearchGap
    counter_evidence: List[CounterEvidenceItem]
    expected_status: CandidateGapStatus
    expected_is_refuted: bool
    scenario_domain: str
    description: str = ""
    expected_min_uncertainty: Optional[float] = None
    expected_max_uncertainty: Optional[float] = None
    expected_metrics: List[str] = field(default_factory=list)
    expected_baselines: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AdversarialEvaluationReport:
    """Summary report detailing adversarial refutation accuracy and plan measurability."""

    total_cases: int
    status_matches: int
    status_accuracy: float
    plan_measurability_tests: int
    plan_measurability_adherence: float
    uncertainty_calibration_tests: int
    uncertainty_calibration_adherence: float
    refuted_count: int
    disputed_count: int
    confirmed_count: int
    passed: bool
    failures: List[str] = field(default_factory=list)
    case_results: List[Dict[str, Any]] = field(default_factory=list)


class AdversarialBenchmarkSuite:
    """Harness evaluating adversarial counter-evidence analysis and validation protocols."""

    def __init__(
        self,
        engine: Optional[AdversarialCounterEvidenceEngine] = None,
        plan_generator: Optional[ValidationPlanGenerator] = None,
    ) -> None:
        self.engine = engine or AdversarialCounterEvidenceEngine()
        self.plan_generator = plan_generator or ValidationPlanGenerator()

    @staticmethod
    def _create_synthetic_coordinate(
        doc_id: str,
        snippet: str,
        page_num: int = 1,
    ) -> EvidenceCoordinate:
        doc_hash = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
        coord_id = f"coord-adv-{hashlib.sha256(doc_id.encode()).hexdigest()[:8]}"
        return EvidenceCoordinate(
            coordinate_id=coord_id,
            document_id=doc_id,
            document_sha256=doc_hash,
            page_number=page_num,
            section_identifier="sec-experiments",
            paragraph_index=1,
            sentence_index=2,
            char_start=0,
            char_end=len(snippet),
            verbatim_snippet=snippet,
            extraction_confidence=0.98,
        )

    def _create_synthetic_gap(
        self,
        gap_id: str,
        gap_class: GapClass,
        title: str,
        description: str,
        uncertainty: float = 0.12,
        composite_score: float = 0.85,
    ) -> ResearchGap:
        coord = self._create_synthetic_coordinate(
            f"doc-{gap_id}",
            f"Observed gap: {description}",
        )
        scores = CalibratedGapScores(
            novelty=0.88,
            grounding=0.90,
            feasibility=0.80,
            significance=0.85,
            uncertainty=uncertainty,
            composite_score=composite_score,
            corpus_bounded=True,
            is_global_claim=False,
        )
        plan = ValidationPlan(
            proposed_methodology=f"Initial investigation for {title}",
            required_datasets=["InitialBenchmark"],
            expected_baselines=["InitialBaseline"],
            evaluation_metrics=["InitialMetric"],
        )
        return ResearchGap(
            gap_id=gap_id,
            gap_class=gap_class,
            title=title,
            description=description,
            epistemic_rationale="Synthetic gap formulation for adversarial validation.",
            supporting_evidence=[coord],
            calibrated_scores=scores,
            validation_plan=plan,
        )

    def generate_benchmark_cases(self) -> List[AdversarialBenchmarkCase]:
        """Constructs diverse synthetic benchmark cases across STEM domains."""
        cases: List[AdversarialBenchmarkCase] = []

        # 1. Decisive Refutation: Edge Robotics Latency
        gap1 = self._create_synthetic_gap(
            "gap-bench-01-latency",
            GapClass.DEPLOYMENT_RESOURCE_GAP,
            "Excessive Latency in 3D Point Cloud Segmentation",
            "No existing segmentation model executes under 50 ms on edge hardware.",
            uncertainty=0.10,
        )
        coord1 = self._create_synthetic_coordinate(
            "paper-fastpoint-2024",
            "FastPointNet achieves 32 ms real-time inference on Nvidia Jetson Orin.",
            page_num=5,
        )
        item1 = CounterEvidenceItem(
            coordinate=coord1,
            refutation_snippet=coord1.verbatim_snippet,
            refutation_confidence=0.95,
            refuting_method_or_solution="FastPointNet",
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-01-decisive-refutation-latency",
                candidate_gap=gap1,
                counter_evidence=[item1],
                expected_status=CandidateGapStatus.REFUTED,
                expected_is_refuted=True,
                scenario_domain="Autonomous Robotics",
                description="High-confidence counter-evidence provides existing solution < 50 ms.",
                expected_metrics=["PeakVRAM_GB", "Latency_ms", "Throughput_fps"],
                expected_baselines=["UncompressedFP32Baseline", "8BitQuantizedBaseline"],
            )
        )

        # 2. Decisive Refutation: Solid-State Electrolyte Conductivity
        gap2 = self._create_synthetic_gap(
            "gap-bench-02-battery",
            GapClass.KNOWLEDGE_GAP,
            "Absence of Room-Temperature Superionic Lithium Conductors",
            "No solid electrolyte demonstrates ionic conductivity exceeding 10 mS/cm at 298 K.",
            uncertainty=0.15,
        )
        coord2 = self._create_synthetic_coordinate(
            "paper-superionic-2024",
            "Halide electrolyte Li3YCl6 reaches 14.2 mS/cm ionic conductivity at 298 K.",
            page_num=3,
        )
        item2 = CounterEvidenceItem(
            coordinate=coord2,
            refutation_snippet=coord2.verbatim_snippet,
            refutation_confidence=0.92,
            refuting_method_or_solution="Li3YCl6 Halide Conductor",
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-02-decisive-refutation-solid-state",
                candidate_gap=gap2,
                counter_evidence=[item2],
                expected_status=CandidateGapStatus.REFUTED,
                expected_is_refuted=True,
                scenario_domain="Battery Chemistry",
                description="Verified crystal structure refutes claimed absence of material.",
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        # 3. Unresolved Empirical Dispute: Cryogenic Qubit Coherence
        gap3 = self._create_synthetic_gap(
            "gap-bench-03-qubit",
            GapClass.ASSUMPTION_BOUNDARY_GAP,
            "Fluxonium Coherence Breakdown Above 50 mK",
            "Fluxonium qubits exhibit unavoidable dephasing collapse above 50 mK base stage.",
            uncertainty=0.12,
        )
        coord3 = self._create_synthetic_coordinate(
            "paper-qubit-dispute-2024",
            "Preliminary measurements show 120 us T2 at 65 mK using high-attenuation shielding.",
            page_num=4,
        )
        item3 = CounterEvidenceItem(
            coordinate=coord3,
            refutation_snippet=coord3.verbatim_snippet,
            refutation_confidence=0.62,
            refuting_method_or_solution="High-attenuation cryogenic filter",
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-03-unresolved-dispute-qubit",
                candidate_gap=gap3,
                counter_evidence=[item3],
                expected_status=CandidateGapStatus.UNRESOLVED_DISPUTE,
                expected_is_refuted=False,
                scenario_domain="Quantum Information",
                description="Ambiguous finding disputes thermal limit; uncertainty elevated.",
                expected_min_uncertainty=0.50,
                expected_metrics=["CriticalThresholdBreakdown", "FidelityRetentionRate"],
                expected_baselines=["NominalOperatingBaseline", "UnconstrainedModel"],
            )
        )

        # 4. Unresolved Empirical Dispute: Biomarker Sensitivity in Oncology
        gap4 = self._create_synthetic_gap(
            "gap-bench-04-biomarker",
            GapClass.CONFLICTING_EVIDENCE_GAP,
            "Contradictory ctDNA Sensitivity in Early Stage Pancreatic Cancer",
            "Reported ctDNA detection sensitivity varies from 20% to 78% in Stage I PDAC.",
            uncertainty=0.20,
        )
        coord4 = self._create_synthetic_coordinate(
            "paper-biomarker-2023",
            "Hybrid targeted panel yields 52% sensitivity in small validation cohort (N=30).",
            page_num=2,
        )
        item4 = CounterEvidenceItem(
            coordinate=coord4,
            refutation_snippet=coord4.verbatim_snippet,
            refutation_confidence=0.58,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-04-unresolved-dispute-biomarker",
                candidate_gap=gap4,
                counter_evidence=[item4],
                expected_status=CandidateGapStatus.UNRESOLVED_DISPUTE,
                expected_is_refuted=False,
                scenario_domain="Oncology",
                description="Intermediate-confidence cohort study leaves clinical dispute open.",
                expected_min_uncertainty=0.50,
                expected_metrics=["RelativeSuperiorityDelta", "PValueSignificance"],
                expected_baselines=["ConflictingMethodA", "ConflictingMethodB"],
            )
        )

        # 5. Confirmed Gap: Dark Matter Halo Velocity Anomaly (Empty Counter-Evidence)
        gap5 = self._create_synthetic_gap(
            "gap-bench-05-astrophysics",
            GapClass.UNDEREXPLORED_RESEARCH_QUESTION,
            "Dwarf Spheroidal Velocity Dispersion Inconsistency in Outer Halos",
            "Kinematic dispersion in ultra-faint dwarf outer fringes lacks theoretical model.",
            uncertainty=0.18,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-05-confirmed-empty-counter-evidence",
                candidate_gap=gap5,
                counter_evidence=[],
                expected_status=CandidateGapStatus.CONFIRMED_GAP,
                expected_is_refuted=False,
                scenario_domain="Astrophysics",
                description="Zero counter-evidence discovered; candidate gap confirmed.",
                expected_min_uncertainty=0.18,
                expected_max_uncertainty=0.18,
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        # 6. Confirmed Gap: Weak Irrelevant Counter-Evidence Below Ambiguity Threshold
        gap6 = self._create_synthetic_gap(
            "gap-bench-06-nlp-domain",
            GapClass.GENERALIZATION_GAP,
            "Low-Resource Dialect Translation Degradation Under Phonetic Shift",
            "Seq2seq models fail catastrophic generalization on acoustic dialectal shifts.",
            uncertainty=0.14,
        )
        coord6 = self._create_synthetic_coordinate(
            "paper-general-nlp",
            "General review of translation techniques across major European languages.",
            page_num=1,
        )
        item6 = CounterEvidenceItem(
            coordinate=coord6,
            refutation_snippet=coord6.verbatim_snippet,
            refutation_confidence=0.20,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-06-confirmed-weak-counter-evidence",
                candidate_gap=gap6,
                counter_evidence=[item6],
                expected_status=CandidateGapStatus.CONFIRMED_GAP,
                expected_is_refuted=False,
                scenario_domain="Natural Language Processing",
                description="Weak background citation (< 0.40) does not refute candidate gap.",
                expected_min_uncertainty=0.14,
                expected_max_uncertainty=0.14,
                expected_metrics=["OODAccuracyDrop", "CovariateRobustnessScore"],
                expected_baselines=[
                    "InDomainSupervisedBaseline",
                    "RobustDomainAdaptedBaseline",
                ],
            )
        )

        # 7. Reproducibility Gap Validation Protocol Verification
        gap7 = self._create_synthetic_gap(
            "gap-bench-07-reproducibility",
            GapClass.REPRODUCIBILITY_GAP,
            "Irreproducible Claim of Room-Temperature Ambient Hydride Superconductivity",
            "Independent laboratories fail to reproduce resistance drop in N-doped lutetium.",
            uncertainty=0.16,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-07-reproducibility-validation-protocol",
                candidate_gap=gap7,
                counter_evidence=[],
                expected_status=CandidateGapStatus.CONFIRMED_GAP,
                expected_is_refuted=False,
                scenario_domain="Condensed Matter Physics",
                description="Validation plan must specify replication fidelity and variance.",
                expected_metrics=["ReplicationFidelity", "MetricVariance"],
                expected_baselines=["AuthorPublishedWeights", "IndependentScratchBaseline"],
            )
        )

        # 8. Multi-Item Hierarchy: Decisive Evidence Precedence
        gap8 = self._create_synthetic_gap(
            "gap-bench-08-multi-item",
            GapClass.DEPLOYMENT_RESOURCE_GAP,
            "High VRAM Overhead in Real-Time SLAM",
            "Dense visual SLAM requires 16 GB VRAM, precluding drone integration.",
            uncertainty=0.11,
        )
        coord8a = self._create_synthetic_coordinate("doc-slam-weak", "General survey.")
        coord8b = self._create_synthetic_coordinate("doc-slam-ambig", "Partial quantization.")
        coord8c = self._create_synthetic_coordinate("doc-slam-strong", "MicroSLAM fits in 2 GB.")
        items8 = [
            CounterEvidenceItem(
                coordinate=coord8a,
                refutation_snippet=coord8a.verbatim_snippet,
                refutation_confidence=0.25,
            ),
            CounterEvidenceItem(
                coordinate=coord8b,
                refutation_snippet=coord8b.verbatim_snippet,
                refutation_confidence=0.65,
                refuting_method_or_solution="QuantSLAM",
            ),
            CounterEvidenceItem(
                coordinate=coord8c,
                refutation_snippet=coord8c.verbatim_snippet,
                refutation_confidence=0.93,
                refuting_method_or_solution="MicroSLAM",
            ),
        ]
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-08-multi-item-precedence",
                candidate_gap=gap8,
                counter_evidence=items8,
                expected_status=CandidateGapStatus.REFUTED,
                expected_is_refuted=True,
                scenario_domain="Autonomous Drones",
                description="Decisive counter-evidence takes precedence over ambiguous/weak items.",
                expected_metrics=["PeakVRAM_GB", "Latency_ms", "Throughput_fps"],
            )
        )

        # 9. Exact Boundary Threshold: At Refutation Threshold (0.85)
        gap9 = self._create_synthetic_gap(
            "gap-bench-09-exact-refutation-bound",
            GapClass.METHODOLOGICAL_GAP,
            "Non-Convergent Gradient Estimation in Diffusion Geometry",
            "Stochastic gradient estimates fail to converge on curved manifolds.",
            uncertainty=0.13,
        )
        coord9 = self._create_synthetic_coordinate(
            "doc-exact-bound",
            "ManifoldDiff delivers provably convergent gradient estimator on Riemannian manifolds.",
        )
        item9 = CounterEvidenceItem(
            coordinate=coord9,
            refutation_snippet=coord9.verbatim_snippet,
            refutation_confidence=0.85,  # Exactly equal to default refutation threshold
            refuting_method_or_solution="ManifoldDiff",
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-09-boundary-refutation-threshold",
                candidate_gap=gap9,
                counter_evidence=[item9],
                expected_status=CandidateGapStatus.REFUTED,
                expected_is_refuted=True,
                scenario_domain="Differential Geometry / ML",
                description="Refutation confidence at exactly 0.85 threshold must trigger REFUTED.",
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        # 10. Exact Boundary Threshold: At Ambiguity Threshold (0.40)
        gap10 = self._create_synthetic_gap(
            "gap-bench-10-exact-ambiguity-bound",
            GapClass.INTEGRATION_INTERDISCIPLINARY_GAP,
            "Lack of Unified Ontological Mapping Between Cryo-EM and AlphaFold",
            "Discrepant nomenclature prevents automated integration of protein models.",
            uncertainty=0.15,
        )
        coord10 = self._create_synthetic_coordinate(
            "doc-ont-ambig",
            "Early draft ontology covers 40% of standard secondary structure cross-references.",
        )
        item10 = CounterEvidenceItem(
            coordinate=coord10,
            refutation_snippet=coord10.verbatim_snippet,
            refutation_confidence=0.40,  # Exactly equal to default ambiguity threshold
            refuting_method_or_solution="DraftCrossOntology",
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-10-boundary-ambiguity-threshold",
                candidate_gap=gap10,
                counter_evidence=[item10],
                expected_status=CandidateGapStatus.UNRESOLVED_DISPUTE,
                expected_is_refuted=False,
                scenario_domain="Structural Bioinformatics",
                description="Confidence at exactly 0.40 threshold must trigger UNRESOLVED_DISPUTE.",
                expected_min_uncertainty=0.50,
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        # 11. Just Below Ambiguity Threshold (0.39)
        gap11 = self._create_synthetic_gap(
            "gap-bench-11-sub-ambiguity",
            GapClass.TEMPORAL_GAP,
            "Longitudinal Concept Drift in Pharmacovigilance Signals",
            "Signal extraction algorithms do not account for adverse event reporting decay.",
            uncertainty=0.10,
        )
        coord11 = self._create_synthetic_coordinate(
            "doc-temp-sub",
            "Informal commentary on periodic updating of drug safety databases.",
        )
        item11 = CounterEvidenceItem(
            coordinate=coord11,
            refutation_snippet=coord11.verbatim_snippet,
            refutation_confidence=0.39,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-11-sub-ambiguity-threshold",
                candidate_gap=gap11,
                counter_evidence=[item11],
                expected_status=CandidateGapStatus.CONFIRMED_GAP,
                expected_is_refuted=False,
                scenario_domain="Pharmacology",
                description="Confidence at 0.39 (< 0.40) must confirm gap without elevating unc.",
                expected_min_uncertainty=0.10,
                expected_max_uncertainty=0.10,
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        # 12. Dataset Domain Gap with Tailored Validation Plan
        gap12 = self._create_synthetic_gap(
            "gap-bench-12-dataset-domain",
            GapClass.DATASET_DOMAIN_GAP,
            "Severe Acoustic Scarcity in Oceanic Autonomous Gliders",
            "Deep sea acoustic recording datasets lack annotations for benthic fauna vocalization.",
            uncertainty=0.17,
        )
        cases.append(
            AdversarialBenchmarkCase(
                case_id="adv-12-dataset-domain-plan",
                candidate_gap=gap12,
                counter_evidence=[],
                expected_status=CandidateGapStatus.CONFIRMED_GAP,
                expected_is_refuted=False,
                scenario_domain="Marine Bioacoustics",
                description="Validation plan measurability verification for dataset domain gap.",
                expected_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
            )
        )

        return cases

    def verify_plan_measurability(
        self,
        plan: ValidationPlan,
        case: AdversarialBenchmarkCase,
    ) -> bool:
        """Verifies that validation plan is actionable, falsifiable, and measurable."""
        if len(plan.proposed_methodology.strip()) < 20:
            return False
        if not plan.required_datasets or not plan.expected_baselines or not plan.evaluation_metrics:
            return False

        # Verify expected metrics if specified
        for expected_metric in case.expected_metrics:
            if expected_metric not in plan.evaluation_metrics:
                return False

        # Verify expected baselines if specified
        for expected_baseline in case.expected_baselines:
            if expected_baseline not in plan.expected_baselines:
                return False

        return True

    def run_evaluation(
        self,
        cases: Optional[List[AdversarialBenchmarkCase]] = None,
    ) -> AdversarialEvaluationReport:
        """Executes full evaluation against benchmark cases and produces structured report."""
        eval_cases = cases if cases is not None else self.generate_benchmark_cases()

        total = len(eval_cases)
        status_matches = 0
        plan_tests = 0
        plan_passed = 0
        unc_tests = 0
        unc_passed = 0
        refuted_count = 0
        disputed_count = 0
        confirmed_count = 0
        failures: List[str] = []
        case_results: List[Dict[str, Any]] = []

        for case in eval_cases:
            # 1. Run adversarial engine evaluation
            result = self.engine.evaluate_counter_evidence(
                gap=case.candidate_gap,
                counter_evidence=case.counter_evidence,
            )

            # Record status distribution
            if result.status == CandidateGapStatus.REFUTED:
                refuted_count += 1
            elif result.status == CandidateGapStatus.UNRESOLVED_DISPUTE:
                disputed_count += 1
            elif result.status == CandidateGapStatus.CONFIRMED_GAP:
                confirmed_count += 1

            # Check status and is_refuted
            status_ok = (result.status == case.expected_status) and (
                result.is_refuted == case.expected_is_refuted
            )
            if status_ok:
                status_matches += 1
            else:
                failures.append(
                    f"[{case.case_id}] Status mismatch: expected {case.expected_status.value} "
                    f"(refuted={case.expected_is_refuted}), got {result.status.value} "
                    f"(refuted={result.is_refuted})."
                )

            # 2. Check uncertainty calibration
            if (
                case.expected_min_uncertainty is not None
                or case.expected_max_uncertainty is not None
            ):
                unc_tests += 1
                unc_ok = True
                if (
                    case.expected_min_uncertainty is not None
                    and result.updated_uncertainty < case.expected_min_uncertainty
                ):
                    unc_ok = False
                    failures.append(
                        f"[{case.case_id}] Uncertainty {result.updated_uncertainty:.2f} "
                        f"below expected minimum {case.expected_min_uncertainty:.2f}."
                    )
                if (
                    case.expected_max_uncertainty is not None
                    and result.updated_uncertainty > case.expected_max_uncertainty
                ):
                    unc_ok = False
                    failures.append(
                        f"[{case.case_id}] Uncertainty {result.updated_uncertainty:.2f} "
                        f"exceeds expected maximum {case.expected_max_uncertainty:.2f}."
                    )
                if unc_ok:
                    unc_passed += 1

            # 3. Generate validation plan and verify measurability
            plan = self.plan_generator.generate_plan(case.candidate_gap)
            plan_tests += 1
            plan_ok = self.verify_plan_measurability(plan, case)
            if plan_ok:
                plan_passed += 1
            else:
                failures.append(
                    f"[{case.case_id}] Validation plan failed measurability check: {plan}."
                )

            case_results.append(
                {
                    "case_id": case.case_id,
                    "domain": case.scenario_domain,
                    "status": result.status.value,
                    "is_refuted": result.is_refuted,
                    "updated_uncertainty": result.updated_uncertainty,
                    "plan_metrics": plan.evaluation_metrics,
                    "status_passed": status_ok,
                    "plan_passed": plan_ok,
                }
            )

        status_acc = status_matches / total if total > 0 else 0.0
        plan_rate = plan_passed / plan_tests if plan_tests > 0 else 1.0
        unc_rate = unc_passed / unc_tests if unc_tests > 0 else 1.0

        all_passed = (
            (status_acc == 1.0)
            and (plan_rate == 1.0)
            and (unc_rate == 1.0)
            and (len(failures) == 0)
        )

        return AdversarialEvaluationReport(
            total_cases=total,
            status_matches=status_matches,
            status_accuracy=round(status_acc, 4),
            plan_measurability_tests=plan_tests,
            plan_measurability_adherence=round(plan_rate, 4),
            uncertainty_calibration_tests=unc_tests,
            uncertainty_calibration_adherence=round(unc_rate, 4),
            refuted_count=refuted_count,
            disputed_count=disputed_count,
            confirmed_count=confirmed_count,
            passed=all_passed,
            failures=failures,
            case_results=case_results,
        )
