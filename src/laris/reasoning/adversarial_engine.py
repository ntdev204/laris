"""Adversarial counter-evidence retrieval and falsifiable validation plan generator.

Adheres to DOC-SPEC-MOD-001 (Boundary G), DATA_SCHEMAS.md, and ADR-004:
- Synthesizes targeted adversarial queries challenging candidate research gaps
- Evaluates counter-evidence to refute or elevate uncertainty of candidate gaps
- Generates concrete, falsifiable validation protocols adhering to ValidationPlan schema
"""

from __future__ import annotations

import math
from typing import List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.reasoning.schemas import (
    AdversarialRefutationResult,
    CandidateGapStatus,
    CounterEvidenceItem,
    GapClass,
    ResearchGap,
    ValidationPlan,
)


class AdversarialCounterEvidenceEngine:
    """Engine executing adversarial querying and candidate gap refutation analysis."""

    def __init__(
        self,
        refutation_threshold: float = 0.85,
        ambiguity_threshold: float = 0.40,
    ) -> None:
        if math.isnan(refutation_threshold) or not (0.0 <= refutation_threshold <= 1.0):
            raise ModuleContractViolationError(
                "refutation_threshold must be a valid float in [0.0, 1.0]."
            )
        if math.isnan(ambiguity_threshold) or not (0.0 <= ambiguity_threshold <= 1.0):
            raise ModuleContractViolationError(
                "ambiguity_threshold must be a valid float in [0.0, 1.0]."
            )
        if ambiguity_threshold >= refutation_threshold:
            raise ModuleContractViolationError(
                "ambiguity_threshold must be strictly less than refutation_threshold."
            )

        self.refutation_threshold = refutation_threshold
        self.ambiguity_threshold = ambiguity_threshold

    def generate_counter_queries(self, gap: ResearchGap) -> List[str]:
        """Synthesizes targeted adversarial search queries challenging candidate gap novelty."""
        clean_title = gap.title.strip().replace('"', "")
        queries = [
            f'"{clean_title}" solved OR demonstrated OR achieved',
            f"overcoming {gap.gap_class.value} in {clean_title}",
            f"prior work addressing {clean_title}",
            f"empirical counter-evidence to {clean_title}",
        ]
        return queries

    def evaluate_counter_evidence(
        self,
        gap: ResearchGap,
        counter_evidence: List[CounterEvidenceItem],
        generated_queries: Optional[List[str]] = None,
    ) -> AdversarialRefutationResult:
        """Evaluates retrieved counter-evidence and assigns lifecycle verification status."""
        queries = (
            generated_queries
            if generated_queries is not None
            else self.generate_counter_queries(gap)
        )

        if not counter_evidence:
            return AdversarialRefutationResult(
                gap_id=gap.gap_id,
                status=CandidateGapStatus.CONFIRMED_GAP,
                generated_counter_queries=queries,
                counter_evidence=[],
                refutation_rationale=(
                    "No counter-evidence located within defined corpus boundary."
                ),
                updated_uncertainty=gap.calibrated_scores.uncertainty,
                is_refuted=False,
            )

        # Look for decisive refutation
        decisive_item = next(
            (
                item for item in counter_evidence
                if item.refutation_confidence >= self.refutation_threshold
            ),
            None,
        )
        if decisive_item is not None:
            method_desc = (
                f" via '{decisive_item.refuting_method_or_solution}'"
                if decisive_item.refuting_method_or_solution
                else ""
            )
            return AdversarialRefutationResult(
                gap_id=gap.gap_id,
                status=CandidateGapStatus.REFUTED,
                generated_counter_queries=queries,
                counter_evidence=counter_evidence,
                refutation_rationale=(
                    f"Candidate gap is refuted{method_desc} by verified counter-evidence "
                    f"with confidence {decisive_item.refutation_confidence:.2f}."
                ),
                updated_uncertainty=gap.calibrated_scores.uncertainty,
                is_refuted=True,
            )

        # Look for ambiguous counter-evidence
        ambiguous_item = next(
            (
                item for item in counter_evidence
                if item.refutation_confidence >= self.ambiguity_threshold
            ),
            None,
        )
        if ambiguous_item is not None:
            # Elevate epistemic uncertainty due to disputed evidence
            elevated_uncertainty = max(gap.calibrated_scores.uncertainty, 0.50)
            return AdversarialRefutationResult(
                gap_id=gap.gap_id,
                status=CandidateGapStatus.UNRESOLVED_DISPUTE,
                generated_counter_queries=queries,
                counter_evidence=counter_evidence,
                refutation_rationale=(
                    "Ambiguous counter-evidence identified; unresolved empirical dispute exists."
                ),
                updated_uncertainty=elevated_uncertainty,
                is_refuted=False,
            )

        # Weak or irrelevant evidence
        return AdversarialRefutationResult(
            gap_id=gap.gap_id,
            status=CandidateGapStatus.CONFIRMED_GAP,
            generated_counter_queries=queries,
            counter_evidence=counter_evidence,
            refutation_rationale=(
                "All retrieved counter-evidence items fall below ambiguity threshold."
            ),
            updated_uncertainty=gap.calibrated_scores.uncertainty,
            is_refuted=False,
        )


class ValidationPlanGenerator:
    """Generates concrete, falsifiable validation protocols tailored to gap classes."""

    def generate_plan(self, gap: ResearchGap) -> ValidationPlan:
        """Constructs an actionable, falsifiable ValidationPlan for the target research gap."""
        gc = gap.gap_class

        if gc == GapClass.DEPLOYMENT_RESOURCE_GAP:
            return ValidationPlan(
                proposed_methodology=(
                    f"Profile real-time memory footprint and execution latency of '{gap.title}' "
                    "across varying batch sizes on edge GPU architectures."
                ),
                required_datasets=["EdgeDeviceProfilingBenchmark", "StandardInferenceSuite"],
                expected_baselines=["UncompressedFP32Baseline", "8BitQuantizedBaseline"],
                evaluation_metrics=["PeakVRAM_GB", "Latency_ms", "Throughput_fps"],
            )

        if gc == GapClass.REPRODUCIBILITY_GAP:
            return ValidationPlan(
                proposed_methodology=(
                    f"Conduct multi-seed independent reproduction study of '{gap.title}' "
                    "across isolated computing environments."
                ),
                required_datasets=["OriginalEvaluationDataset", "ReplicationTestSplit"],
                expected_baselines=["AuthorPublishedWeights", "IndependentScratchBaseline"],
                evaluation_metrics=["ReplicationFidelity", "MetricVariance"],
            )

        if gc == GapClass.CONFLICTING_EVIDENCE_GAP:
            return ValidationPlan(
                proposed_methodology=(
                    f"Execute head-to-head empirical arbitration protocol evaluating '{gap.title}' "
                    "under identical laboratory hardware and temperature parameters."
                ),
                required_datasets=["StandardizedArbitrationDataset", "ControlledSplitV1"],
                expected_baselines=["ConflictingMethodA", "ConflictingMethodB"],
                evaluation_metrics=["RelativeSuperiorityDelta", "PValueSignificance"],
            )

        if gc == GapClass.GENERALIZATION_GAP:
            return ValidationPlan(
                proposed_methodology=(
                    f"Evaluate out-of-distribution transfer degradation of '{gap.title}' "
                    "under progressive covariate distribution shifts."
                ),
                required_datasets=["InDomainValidationSet", "AdversarialOODShiftSet"],
                expected_baselines=["InDomainSupervisedBaseline", "RobustDomainAdaptedBaseline"],
                evaluation_metrics=["OODAccuracyDrop", "CovariateRobustnessScore"],
            )

        if gc == GapClass.ASSUMPTION_BOUNDARY_GAP:
            return ValidationPlan(
                proposed_methodology=(
                    f"Perform parameter sweep across critical operating bounds for '{gap.title}' "
                    "to characterize performance degradation thresholds."
                ),
                required_datasets=["ParameterSweepDataset", "BoundaryConditionStressSuite"],
                expected_baselines=["NominalOperatingBaseline", "UnconstrainedModel"],
                evaluation_metrics=["CriticalThresholdBreakdown", "FidelityRetentionRate"],
            )

        # Default fallback protocol for knowledge, methodological, or open gaps
        return ValidationPlan(
            proposed_methodology=(
                f"Formulate controlled hypothesis validation experiment targeting '{gap.title}' "
                "with standardized empirical controls."
            ),
            required_datasets=["DomainBenchmarkV1", "HeldOutEvaluationSplit"],
            expected_baselines=["StateOfTheArtBaseline", "AblatedModelVariant"],
            evaluation_metrics=["PrimaryTaskMetric", "EpistemicConfidenceScore"],
        )
