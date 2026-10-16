"""Stripped-Heading Evaluation Benchmark and False-Positive Suite.

Module ID: MOD-SCINLP-002 (Boundary D: Scientific Language Intelligence)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008.
Provides multi-domain evaluation of limitation, assumption, and negative finding
recall with section headings removed, alongside rigorous false-positive distractor tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer3_scinlp.limitations import (
    HeadingIndependentLimitationDetector,
    LimitationDetectionResult,
    strip_headings,
)


@dataclass(frozen=True)
class StrippedHeadingBenchmarkSample:
    """A synthetic scientific sample for stripped-heading benchmark evaluation."""

    sample_id: str
    domain: str
    text_with_headings: str
    ground_truth_limitations: list[str] = field(default_factory=list)
    ground_truth_assumptions: list[str] = field(default_factory=list)
    ground_truth_negative_findings: list[str] = field(default_factory=list)
    is_negative_control: bool = False

    def all_ground_truth(self) -> list[str]:
        return [
            *self.ground_truth_limitations,
            *self.ground_truth_assumptions,
            *self.ground_truth_negative_findings,
        ]


@dataclass(frozen=True)
class StrippedHeadingBenchmarkMetrics:
    """Evaluation metrics for a specific domain or consolidated benchmark run."""

    domain: str
    sample_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float
    uncertainty_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "sample_count": self.sample_count,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "false_positive_rate": self.false_positive_rate,
            "uncertainty_distribution": self.uncertainty_distribution,
        }


@dataclass(frozen=True)
class StrippedHeadingBenchmarkReport:
    """Consolidated report for stripped-heading evaluation and false-positive verification."""

    benchmark_timestamp: str
    overall_metrics: StrippedHeadingBenchmarkMetrics
    domain_metrics: dict[str, StrippedHeadingBenchmarkMetrics]
    total_samples: int
    gate_passed: bool
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_timestamp": self.benchmark_timestamp,
            "overall_metrics": self.overall_metrics.to_dict(),
            "domain_metrics": {k: v.to_dict() for k, v in self.domain_metrics.items()},
            "total_samples": self.total_samples,
            "gate_passed": self.gate_passed,
            "summary": self.summary,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def format_markdown_report(self) -> str:
        """Format benchmark findings as a human-readable markdown report."""
        status_text = "PASSED" if self.gate_passed else "FAILED"
        lines = [
            "# Stripped-Heading Limitation & Assumption Evaluation Report",
            f"**Timestamp:** {self.benchmark_timestamp}",
            f"**Gate Status:** {status_text} (Target: Recall >= 80%, Distractor FP == 0)",
            "",
            "## Overall Benchmark Metrics",
            f"- **Recall:** {self.overall_metrics.recall:.2%}",
            f"- **Precision:** {self.overall_metrics.precision:.2%}",
            f"- **F1 Score:** {self.overall_metrics.f1_score:.4f}",
            f"- **False Positive Rate:** {self.overall_metrics.false_positive_rate:.2%}",
            f"- **Total Samples Evaluated:** {self.total_samples}",
            "",
            "## Epistemic Uncertainty Distribution",
            f"- Low Uncertainty (<0.30): "
            f"{self.overall_metrics.uncertainty_distribution.get('low', 0)}",
            f"- Medium Uncertainty (0.30-0.60): "
            f"{self.overall_metrics.uncertainty_distribution.get('medium', 0)}",
            f"- High Uncertainty (>=0.60): "
            f"{self.overall_metrics.uncertainty_distribution.get('high', 0)}",
            "",
            "## Domain Breakdown",
            "| Domain | Samples | Recall | Precision | F1 | False Positives |",
            "|---|---|---|---|---|---|",
        ]
        for dom, m in self.domain_metrics.items():
            lines.append(
                f"| {dom} | {m.sample_count} | {m.recall:.2%} | {m.precision:.2%} | "
                f"{m.f1_score:.4f} | {m.false_positives} |"
            )
        lines.append("")
        lines.append(f"**Summary:** {self.summary}")
        return "\n".join(lines)


def get_default_synthetic_benchmark_corpus() -> list[StrippedHeadingBenchmarkSample]:
    """Provide a diverse multi-domain synthetic corpus with stripped-heading test cases."""
    return [
        # Domain 1: Computer Science & Machine Learning
        StrippedHeadingBenchmarkSample(
            sample_id="cs-ml-001",
            domain="computer_science",
            text_with_headings=(
                "# 1. Architecture\n"
                "We propose an autoregressive graph transformer for molecular discovery.\n\n"
                "## 2. Theoretical Assumptions\n"
                "We assume that the underlying physical system satisfies energy conservation. "
                "Under the assumption of independent and identically distributed token sequences, "
                "convergence holds.\n\n"
                "## 3. Results and Limitations\n"
                "Our model achieves strong accuracy on small molecules. "
                "However, computational cost is prohibitive due to quadratic complexity in "
                "sequence length. "
                "Furthermore, our model might plausibly fail to generalize to unseen protein "
                "targets under distribution shift. "
                "A notable limitation is that our empirical evaluation is restricted to English "
                "molecular captions. "
                "In our experiments, no statistically significant improvement was observed on "
                "dense crystal lattices."
            ),
            ground_truth_limitations=[
                "computational cost is prohibitive",
                "might plausibly fail to generalize",
                "restricted to English molecular captions",
            ],
            ground_truth_assumptions=[
                "underlying physical system satisfies energy conservation",
                "independent and identically distributed token sequences",
            ],
            ground_truth_negative_findings=[
                "no statistically significant improvement was observed on dense crystal lattices",
            ],
            is_negative_control=False,
        ),
        # Domain 2: Biomedicine & Clinical Pharmacology
        StrippedHeadingBenchmarkSample(
            sample_id="bio-med-002",
            domain="biomedicine",
            text_with_headings=(
                "# 1. Clinical Study Design\n"
                "We investigated the antihypertensive efficacy of compound X-24 in a cohort.\n\n"
                "## 2. Pharmacological Assumptions\n"
                "Under the assumption that patient cohorts maintain normotensive baselines "
                "prior to administration, we estimate systemic vascular resistance.\n\n"
                "## 3. Observational Limitations and Null Results\n"
                "Our empirical study suffers from data scarcity and small cohort size in rare "
                "subgroups. "
                "The clinical scope is restricted to adult demographics, and we leave pediatric "
                "trials for future work. "
                "Moreover, the treatment yielded comparable or inferior results compared to "
                "standard-of-care ACE inhibitors. "
                "A simplified model and imperfect proxy was used to estimate endothelial "
                "compliance."
            ),
            ground_truth_limitations=[
                "data scarcity and small cohort size",
                "restricted to adult demographics",
                "simplified model and imperfect proxy",
            ],
            ground_truth_assumptions=[
                "patient cohorts maintain normotensive baselines",
            ],
            ground_truth_negative_findings=[
                "yielded comparable or inferior results compared to standard-of-care",
            ],
            is_negative_control=False,
        ),
        # Domain 3: Physics & Materials Science
        StrippedHeadingBenchmarkSample(
            sample_id="phys-mat-003",
            domain="physics",
            text_with_headings=(
                "# 1. First-Principles Methodology\n"
                "We simulate thermal conductivity in perovskite superlattices.\n\n"
                "## 2. Thermodynamic Premises\n"
                "We assume that the crystalline lattice remains isothermal during rapid laser "
                "excitation.\n\n"
                "## 3. Computational Boundary Conditions\n"
                "The first-order approximation error could potentially introduce bias in "
                "molecular force calculations. "
                "A key limitation is that scalability is limited and does not scale to "
                "macromolecular systems. "
                "Finally, the null hypothesis could not be rejected for high-temperature "
                "superconductivity transition."
            ),
            ground_truth_limitations=[
                "first-order approximation error could potentially introduce bias",
                "scalability is limited and does not scale to macromolecular systems",
            ],
            ground_truth_assumptions=[
                "crystalline lattice remains isothermal",
            ],
            ground_truth_negative_findings=[
                "null hypothesis could not be rejected for high-temperature "
                "superconductivity transition",
            ],
            is_negative_control=False,
        ),
        # Domain 4: Negative Control / Distractor Suite - Corporate & Legal Disclaimers
        StrippedHeadingBenchmarkSample(
            sample_id="distractor-legal-004",
            domain="distractor_control",
            text_with_headings=(
                "# 1. Corporate Notice\n"
                "DeepMind Technologies Ltd. and Anthropic PBC are registered corporate entities. "
                "Acme Solutions Limited liability company provides infrastructure services.\n\n"
                "## 2. Terms of Service\n"
                "The authors assume no responsibility or liability for damages arising from "
                "third-party usage. "
                "The contributors disclaim all warranties regarding fitness for a particular "
                "purpose. "
                "Our automated deployment operates without limitation across all cloud "
                "environments. "
                "The cryptographic verification pipeline never fails."
            ),
            ground_truth_limitations=[],
            ground_truth_assumptions=[],
            ground_truth_negative_findings=[],
            is_negative_control=True,
        ),
        # Domain 5: Negative Control / Distractor Suite - Prior Work Critiques
        StrippedHeadingBenchmarkSample(
            sample_id="distractor-prior-work-005",
            domain="distractor_control",
            text_with_headings=(
                "# 1. Related Work\n"
                "Prior works suffered from severe computational overhead and memory bottlenecks. "
                "Existing methods exhibit poor generalization when exposed to distribution shift. "
                "Earlier studies were restricted to English monolingual text corpora. "
                "Previous approaches failed to outperform simple heuristic baselines. "
                "Traditional frameworks assumed that variables were strictly linear.\n\n"
                "## 2. Our Advancement\n"
                "Unlike prior works that were limited to planar graphs, our framework handles "
                "complex 3D meshes seamlessly."
            ),
            ground_truth_limitations=[],
            ground_truth_assumptions=[],
            ground_truth_negative_findings=[],
            is_negative_control=True,
        ),
        # Domain 6: Negative Control / Distractor Suite - Conversational & Didactic Text
        StrippedHeadingBenchmarkSample(
            sample_id="distractor-conversational-006",
            domain="distractor_control",
            text_with_headings=(
                "# 1. Background Primer\n"
                "We assume the reader is familiar with differential geometry and group theory. "
                "We do not assume that variables are independent across observation windows. "
                "There is no reason to assume that gradient descent diverges under mild "
                "smoothness.\n\n"
                "We did not observe any degradation in validation loss during training."
            ),
            ground_truth_limitations=[],
            ground_truth_assumptions=[],
            ground_truth_negative_findings=[],
            is_negative_control=True,
        ),
    ]


class StrippedHeadingBenchmark:
    """Benchmark runner for heading-independent limitation, assumption, and negative finding.

    Evaluates extraction recall with all section headers stripped, verifies zero false-positive
    leakage on distractor texts, and tracks epistemic uncertainty calibration.
    """

    def __init__(
        self,
        detector: HeadingIndependentLimitationDetector | None = None,
    ) -> None:
        self.detector = detector or HeadingIndependentLimitationDetector(confidence_threshold=0.50)

    def evaluate_sample(
        self, sample: StrippedHeadingBenchmarkSample
    ) -> tuple[LimitationDetectionResult, StrippedHeadingBenchmarkMetrics]:
        """Evaluate a single sample with headings stripped."""
        stripped_text = strip_headings(sample.text_with_headings)
        detection_result = self.detector.detect(stripped_text, document_id=sample.sample_id)

        all_detected_texts = [
            *[lim.description for lim in detection_result.limitations],
            *[a.statement for a in detection_result.assumptions],
            *[nf.description for nf in detection_result.negative_findings],
        ]

        # Uncertainty distribution
        unc_dist = detection_result.uncertainty_distribution

        if sample.is_negative_control:
            # For negative controls, any detection is a false positive
            fp = len(all_detected_texts)
            tn = 1 if fp == 0 else 0
            tp = 0
            fn = 0
            precision = 1.0 if fp == 0 else 0.0
            recall = 1.0
            f1 = 1.0 if fp == 0 else 0.0
            fpr = 0.0 if fp == 0 else 1.0
        else:
            ground_truth = sample.all_ground_truth()
            tp = 0
            matched_detected_indices: set[int] = set()

            for gt in ground_truth:
                gt_lower = gt.lower()
                for idx, det in enumerate(all_detected_texts):
                    det_lower = det.lower()
                    if gt_lower in det_lower or det_lower in gt_lower:
                        tp += 1
                        matched_detected_indices.add(idx)
                        break

            fn = len(ground_truth) - tp
            fp = len(all_detected_texts) - len(matched_detected_indices)
            tn = 0

            precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
            f1 = (
                (2 * precision * recall) / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )
            fpr = 0.0

        metrics = StrippedHeadingBenchmarkMetrics(
            domain=sample.domain,
            sample_count=1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            true_negatives=tn,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1_score=round(f1, 4),
            false_positive_rate=round(fpr, 4),
            uncertainty_distribution=unc_dist,
        )
        return detection_result, metrics

    def run_benchmark(
        self,
        samples: list[StrippedHeadingBenchmarkSample] | None = None,
    ) -> StrippedHeadingBenchmarkReport:
        """Run complete stripped-heading evaluation across all samples and synthesize metrics."""
        corpus = samples if samples is not None else get_default_synthetic_benchmark_corpus()
        if not corpus:
            raise ModuleContractViolationError("Benchmark corpus cannot be empty.")

        domain_aggregates: dict[str, dict[str, Any]] = {}
        total_tp = 0
        total_fp = 0
        total_fn = 0
        total_tn = 0
        total_unc_dist: dict[str, int] = {"low": 0, "medium": 0, "high": 0}

        for sample in corpus:
            _, metrics = self.evaluate_sample(sample)
            dom = sample.domain
            if dom not in domain_aggregates:
                domain_aggregates[dom] = {
                    "sample_count": 0,
                    "tp": 0,
                    "fp": 0,
                    "fn": 0,
                    "tn": 0,
                    "unc": {"low": 0, "medium": 0, "high": 0},
                }

            domain_aggregates[dom]["sample_count"] += 1
            domain_aggregates[dom]["tp"] += metrics.true_positives
            domain_aggregates[dom]["fp"] += metrics.false_positives
            domain_aggregates[dom]["fn"] += metrics.false_negatives
            domain_aggregates[dom]["tn"] += metrics.true_negatives
            for k, count in metrics.uncertainty_distribution.items():
                domain_aggregates[dom]["unc"][k] = domain_aggregates[dom]["unc"].get(k, 0) + count
                total_unc_dist[k] = total_unc_dist.get(k, 0) + count

            total_tp += metrics.true_positives
            total_fp += metrics.false_positives
            total_fn += metrics.false_negatives
            total_tn += metrics.true_negatives

        domain_metrics: dict[str, StrippedHeadingBenchmarkMetrics] = {}
        for dom, agg in domain_aggregates.items():
            tp = agg["tp"]
            fp = agg["fp"]
            fn = agg["fn"]
            tn = agg["tn"]
            prec = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fp == 0 else 0.0)
            rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

            domain_metrics[dom] = StrippedHeadingBenchmarkMetrics(
                domain=dom,
                sample_count=agg["sample_count"],
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                true_negatives=tn,
                precision=round(prec, 4),
                recall=round(rec, 4),
                f1_score=round(f1, 4),
                false_positive_rate=round(fpr, 4),
                uncertainty_distribution=agg["unc"],
            )

        overall_prec = (
            total_tp / (total_tp + total_fp)
            if (total_tp + total_fp) > 0
            else (1.0 if total_fp == 0 else 0.0)
        )
        overall_rec = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
        overall_f1 = (
            (2 * overall_prec * overall_rec) / (overall_prec + overall_rec)
            if (overall_prec + overall_rec) > 0
            else 0.0
        )
        overall_fpr = total_fp / (total_fp + total_tn) if (total_fp + total_tn) > 0 else 0.0

        overall_metrics = StrippedHeadingBenchmarkMetrics(
            domain="overall",
            sample_count=len(corpus),
            true_positives=total_tp,
            false_positives=total_fp,
            false_negatives=total_fn,
            true_negatives=total_tn,
            precision=round(overall_prec, 4),
            recall=round(overall_rec, 4),
            f1_score=round(overall_f1, 4),
            false_positive_rate=round(overall_fpr, 4),
            uncertainty_distribution=total_unc_dist,
        )

        # Gate verification: Recall >= 0.80 and distractor false positives == 0
        distractor_entry = domain_metrics.get("distractor_control")
        distractor_fp = distractor_entry.false_positives if distractor_entry is not None else 0
        gate_passed = (overall_rec >= 0.80) and (distractor_fp == 0)

        timestamp = datetime.now(timezone.utc).isoformat()
        status_str = "PASSED" if gate_passed else "FAILED"
        summary = (
            f"Benchmark completed on {len(corpus)} samples across {len(domain_metrics)} domains. "
            f"Overall Recall: {overall_rec:.2%}, Precision: {overall_prec:.2%}, "
            f"F1: {overall_f1:.4f}. Distractor False Positives: {distractor_fp}. "
            f"Gate status: {status_str}."
        )

        return StrippedHeadingBenchmarkReport(
            benchmark_timestamp=timestamp,
            overall_metrics=overall_metrics,
            domain_metrics=domain_metrics,
            total_samples=len(corpus),
            gate_passed=gate_passed,
            summary=summary,
        )
