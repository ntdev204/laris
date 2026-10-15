"""Scientific NLI benchmark fixtures, evaluation, and calibration reporting.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008, and Milestone M3 Exit Gate.
Evaluates Macro-F1 >= 0.82 gate, Expected Calibration Error (ECE), and false entailment rates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer2_semantic.engine import DeterministicScientificNLIEngine
from laris.layers.layer2_semantic.schemas import (
    NLIEngineContract,
    NLILabel,
    SentencePairInput,
)

BENCHMARK_VERSION: str = "v1.0.0"
EXIT_GATE_MACRO_F1_THRESHOLD: float = 0.82


@dataclass(frozen=True)
class BenchmarkNLIPair:
    """A standardized scientific NLI benchmark test item."""

    pair_id: str
    premise: str
    hypothesis: str
    gold_label: NLILabel
    domain: str
    topical_overlap: str = "MODERATE"
    is_hard_negative: bool = False

    def to_input(self) -> SentencePairInput:
        return SentencePairInput(
            premise=self.premise,
            hypothesis=self.hypothesis,
            pair_id=self.pair_id,
            metadata={
                "domain": self.domain,
                "gold_label": self.gold_label.value,
                "is_hard_negative": self.is_hard_negative,
            },
        )


# Comprehensive balanced scientific evaluation set covering physics, biology, chemistry, materials
SCIENTIFIC_NLI_BENCHMARK_FIXTURES: list[BenchmarkNLIPair] = [
    # --- CONTRADICTION: Hard Negatives (High topical overlap, opposite meaning) ---
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-001",
        premise="The alloy exhibited high tensile strength under extreme temperature.",
        hypothesis="The alloy suffered brittle fracture and failed under extreme temperature.",
        gold_label=NLILabel.CONTRADICTION,
        domain="materials_science",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-002",
        premise="Target kinase phosphorylation was enhanced after molecule administration.",
        hypothesis="Target kinase phosphorylation was inhibited after molecule administration.",
        gold_label=NLILabel.CONTRADICTION,
        domain="molecular_biology",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-003",
        premise="Gene expression of the oncogene was upregulated four-fold.",
        hypothesis="Gene expression of the oncogene was downregulated four-fold.",
        gold_label=NLILabel.CONTRADICTION,
        domain="genomics",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-004",
        premise="The compound behaves as an electrical conductor at ambient pressure.",
        hypothesis="The compound behaves as an electrical insulator at ambient pressure.",
        gold_label=NLILabel.CONTRADICTION,
        domain="condensed_matter",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-005",
        premise="The nanoparticles were completely soluble in aqueous phosphate buffers.",
        hypothesis="The nanoparticles were completely insoluble in aqueous phosphate buffers.",
        gold_label=NLILabel.CONTRADICTION,
        domain="chemistry",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-006",
        premise="Catalytic turnover frequency increased with reactant concentration.",
        hypothesis="Catalytic turnover frequency decreased with reactant concentration.",
        gold_label=NLILabel.CONTRADICTION,
        domain="catalysis",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-007",
        premise="The synthesized polymer adopts a crystalline morphology.",
        hypothesis="The synthesized polymer adopts an amorphous morphology.",
        gold_label=NLILabel.CONTRADICTION,
        domain="polymer_science",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-008",
        premise="The therapeutic agent was non-toxic across all mammalian cell cultures.",
        hypothesis="The therapeutic agent was toxic across all mammalian cell cultures.",
        gold_label=NLILabel.CONTRADICTION,
        domain="toxicology",
        topical_overlap="HIGH",
        is_hard_negative=True,
    ),
    # --- ENTAILMENT: Paraphrases, directional agreement, and semantic implications ---
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-009",
        premise="Superconductivity was verified in cuprates below critical temp 93 Kelvin.",
        hypothesis="Cuprate ceramics exhibit superconductivity below critical temp 93 Kelvin.",
        gold_label=NLILabel.ENTAILMENT,
        domain="superconductivity",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-010",
        premise="Cryo-EM microscopy resolved the ribosome structure at 2.1 Angstrom resolution.",
        hypothesis="The ribosome structure was resolved at 2.1 Angstrom resolution via cryo-EM.",
        gold_label=NLILabel.ENTAILMENT,
        domain="structural_biology",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-011",
        premise="The thermal conductivity of diamond exceeds that of copper at room temperature.",
        hypothesis="Diamond exhibits higher thermal conductivity than copper at room temperature.",
        gold_label=NLILabel.ENTAILMENT,
        domain="solid_state_physics",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-012",
        premise="Cellular ATP levels were elevated substantially after metabolic activation.",
        hypothesis="Metabolic activation yielded elevated cellular ATP levels.",
        gold_label=NLILabel.ENTAILMENT,
        domain="biochemistry",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-013",
        premise="Electrochemical impedance spectra confirmed low charge transfer resistance.",
        hypothesis="Low charge transfer resistance was confirmed by impedance spectra.",
        gold_label=NLILabel.ENTAILMENT,
        domain="electrochemistry",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-014",
        premise="The optical band gap widened upon quantum confinement.",
        hypothesis="Quantum confinement produced widened optical band gaps.",
        gold_label=NLILabel.ENTAILMENT,
        domain="nanotechnology",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-015",
        premise="The catalyst promotes the oxygen reduction reaction at alkaline pH.",
        hypothesis="In alkaline media, the oxygen reduction reaction is enhanced by the catalyst.",
        gold_label=NLILabel.ENTAILMENT,
        domain="catalysis",
        topical_overlap="HIGH",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-016",
        premise="X-ray diffraction confirmed a face-centered cubic lattice geometry.",
        hypothesis="The lattice geometry is face-centered cubic according to diffraction data.",
        gold_label=NLILabel.ENTAILMENT,
        domain="crystallography",
        topical_overlap="HIGH",
    ),
    # --- NEUTRAL: Domain-adjacent or independent scientific assertions ---
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-017",
        premise="Superconductivity was verified in cuprates below critical temp 93 Kelvin.",
        hypothesis="Silicon wafer fabrication requires cleanroom facilities with laminar air flow.",
        gold_label=NLILabel.NEUTRAL,
        domain="materials_science",
        topical_overlap="LOW",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-018",
        premise="CRISPR endonuclease Cas9 cleaves double-stranded DNA at target sites.",
        hypothesis="Chromatographic purification of proteins requires affinity columns.",
        gold_label=NLILabel.NEUTRAL,
        domain="molecular_biology",
        topical_overlap="LOW",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-019",
        premise="The black hole event horizon emits Hawking radiation under semiclassical gravity.",
        hypothesis="Lithium-ion batteries suffer cathode degradation during fast cycling regimes.",
        gold_label=NLILabel.NEUTRAL,
        domain="astrophysics",
        topical_overlap="LOW",
    ),

    BenchmarkNLIPair(
        pair_id="NLI-BENCH-020",
        premise="The organic synthesis was performed in anhydrous dichloromethane solvent.",
        hypothesis="Spectrophotometric absorption was measured between 400 nm and 700 nm.",
        gold_label=NLILabel.NEUTRAL,
        domain="organic_chemistry",
        topical_overlap="LOW",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-021",
        premise="The superconductor exhibits Meissner effect expulsion of external magnetic flux.",
        hypothesis="Superconducting cables are manufactured using copper stabilization cladding.",
        gold_label=NLILabel.NEUTRAL,
        domain="superconductivity",
        topical_overlap="MODERATE",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-022",
        premise="Cellular apoptosis was measured by flow cytometry with Annexin V staining.",
        hypothesis="Western blotting was conducted using chemiluminescent substrate detection.",
        gold_label=NLILabel.NEUTRAL,
        domain="cellular_biology",
        topical_overlap="MODERATE",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-023",
        premise="The magnetic transition occurs at a Curie temperature of 770 Celsius.",
        hypothesis="Thermogravimetric analysis was conducted up to 1000 Celsius under nitrogen.",
        gold_label=NLILabel.NEUTRAL,
        domain="magnetism",
        topical_overlap="MODERATE",
    ),
    BenchmarkNLIPair(
        pair_id="NLI-BENCH-024",
        premise="The neural network achieved 92 percent precision on the pathology dataset.",
        hypothesis="Data preprocessing applied random horizontal flips for visual augmentation.",
        gold_label=NLILabel.NEUTRAL,
        domain="machine_learning",
        topical_overlap="MODERATE",
    ),
]


@dataclass(frozen=True)
class NLICalibrationMetrics:
    """Comprehensive performance and calibration metrics for 3-way NLI."""

    total_samples: int
    accuracy: float
    per_class_precision: dict[str, float]
    per_class_recall: dict[str, float]
    per_class_f1: dict[str, float]
    macro_f1: float
    expected_calibration_error: float
    false_entailment_count: int
    false_entailment_rate: float
    hard_negative_accuracy: float
    gate_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NLICalibrationMetrics:
        return cls(
            total_samples=int(data["total_samples"]),
            accuracy=float(data["accuracy"]),
            per_class_precision=data["per_class_precision"],
            per_class_recall=data["per_class_recall"],
            per_class_f1=data["per_class_f1"],
            macro_f1=float(data["macro_f1"]),
            expected_calibration_error=float(data["expected_calibration_error"]),
            false_entailment_count=int(data["false_entailment_count"]),
            false_entailment_rate=float(data["false_entailment_rate"]),
            hard_negative_accuracy=float(data["hard_negative_accuracy"]),
            gate_passed=bool(data["gate_passed"]),
        )


@dataclass(frozen=True)
class NLICalibrationReport:
    """Cryptographically verifiable scientific NLI calibration report."""

    report_id: str
    benchmark_version: str
    timestamp_iso: str
    metrics: NLICalibrationMetrics
    report_sha256: str
    failure_cases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "benchmark_version": self.benchmark_version,
            "timestamp_iso": self.timestamp_iso,
            "metrics": self.metrics.to_dict(),
            "report_sha256": self.report_sha256,
            "failure_cases": self.failure_cases,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NLICalibrationReport:
        return cls(
            report_id=data["report_id"],
            benchmark_version=data["benchmark_version"],
            timestamp_iso=data["timestamp_iso"],
            metrics=NLICalibrationMetrics.from_dict(data["metrics"]),
            report_sha256=data["report_sha256"],
            failure_cases=data.get("failure_cases", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> NLICalibrationReport:
        return cls.from_dict(json.loads(json_str))

    def render_summary_text(self) -> str:
        """Render markdown summary of evaluation and exit gate results."""
        m = self.metrics
        status = "PASSED (Macro-F1 >= 0.82)" if m.gate_passed else "FAILED (Macro-F1 < 0.82)"
        lines = [
            f"# Scientific NLI Calibration Report [{self.benchmark_version}]",
            f"**Status:** {status}",
            f"**Timestamp:** {self.timestamp_iso}",
            f"**Report SHA-256:** `{self.report_sha256}`",
            "",
            "## Summary Metrics",
            f"- **Total Samples:** {m.total_samples}",
            f"- **Overall Accuracy:** {m.accuracy * 100:.2f}%",
            (
                f"- **Macro-Averaged F1:** {m.macro_f1:.4f} "
                f"(Exit Gate: >= {EXIT_GATE_MACRO_F1_THRESHOLD})"
            ),
            f"- **Expected Calibration Error (ECE):** {m.expected_calibration_error:.4f}",
            f"- **Hard Negative Contradiction Accuracy:** {m.hard_negative_accuracy * 100:.2f}%",
            (
                f"- **False Entailment Rate:** {m.false_entailment_rate * 100:.2f}% "
                f"({m.false_entailment_count} cases)"
            ),
            "",
            "## Per-Class Performance",
            "| Class | Precision | Recall | F1 Score |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for label in [NLILabel.ENTAILMENT, NLILabel.CONTRADICTION, NLILabel.NEUTRAL]:
            p = m.per_class_precision.get(label.value, 0.0)
            r = m.per_class_recall.get(label.value, 0.0)
            f1 = m.per_class_f1.get(label.value, 0.0)
            lines.append(f"| `{label.value}` | {p:.4f} | {r:.4f} | {f1:.4f} |")

        if self.failure_cases:
            lines.extend(["", "## Failure Analysis (Discrepancies)"])
            for case in self.failure_cases:
                lines.append(
                    f"- **[{case['pair_id']}]** Expected `{case['gold_label']}`, "
                    f"Got `{case['predicted_label']}` (confidence={case['confidence']:.3f})"
                )

        return "\n".join(lines)


def evaluate_nli_calibration(
    engine: NLIEngineContract | None = None,
    benchmark_pairs: list[BenchmarkNLIPair] | None = None,
    num_bins: int = 10,
) -> NLICalibrationReport:
    """Evaluate an NLI engine against the scientific benchmark suite."""
    if engine is None:
        engine = DeterministicScientificNLIEngine()
    if benchmark_pairs is None:
        benchmark_pairs = SCIENTIFIC_NLI_BENCHMARK_FIXTURES

    if not benchmark_pairs:
        raise ModuleContractViolationError("benchmark_pairs cannot be empty.")

    labels = [NLILabel.ENTAILMENT, NLILabel.CONTRADICTION, NLILabel.NEUTRAL]
    label_vals = [e.value for e in labels]

    tp: dict[str, int] = {v: 0 for v in label_vals}
    fp: dict[str, int] = {v: 0 for v in label_vals}
    fn: dict[str, int] = {v: 0 for v in label_vals}

    total_correct = 0
    false_entailment_count = 0
    hard_neg_total = 0
    hard_neg_correct = 0

    predictions: list[tuple[float, bool]] = []
    failure_cases: list[dict[str, Any]] = []

    for item in benchmark_pairs:
        out = engine.infer(item.to_input())
        pred_label = out.prediction.value
        gold_label = item.gold_label.value

        conf = max(out.probabilities.values()) if out.probabilities else 1.0
        is_correct = pred_label == gold_label

        predictions.append((float(conf), is_correct))

        if is_correct:
            total_correct += 1
            tp[pred_label] += 1
        else:
            fp[pred_label] += 1
            fn[gold_label] += 1
            failure_cases.append(
                {
                    "pair_id": item.pair_id,
                    "premise": item.premise,
                    "hypothesis": item.hypothesis,
                    "gold_label": gold_label,
                    "predicted_label": pred_label,
                    "confidence": round(float(conf), 4),
                    "probabilities": out.probabilities,
                }
            )

        # Track false entailment (gold is contradiction, predicted is entailment)
        if item.gold_label == NLILabel.CONTRADICTION and out.prediction == NLILabel.ENTAILMENT:
            false_entailment_count += 1

        # Track hard negatives
        if item.is_hard_negative:
            hard_neg_total += 1
            if is_correct:
                hard_neg_correct += 1

    total_n = len(benchmark_pairs)
    accuracy = total_correct / total_n

    precisions: dict[str, float] = {}
    recalls: dict[str, float] = {}
    f1s: dict[str, float] = {}

    for val in label_vals:
        p = tp[val] / (tp[val] + fp[val]) if (tp[val] + fp[val]) > 0 else 0.0
        r = tp[val] / (tp[val] + fn[val]) if (tp[val] + fn[val]) > 0 else 0.0
        f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
        precisions[val] = round(p, 4)
        recalls[val] = round(r, 4)
        f1s[val] = round(f1, 4)

    active_labels = [v for v in label_vals if (tp[v] + fn[v] > 0) or (tp[v] + fp[v] > 0)]
    if not active_labels:
        active_labels = label_vals

    macro_f1 = round(sum(f1s[v] for v in active_labels) / len(active_labels), 4)

    # Compute Expected Calibration Error (ECE)
    ece = _compute_ece(predictions, num_bins=num_bins)

    contradiction_total = sum(1 for p in benchmark_pairs if p.gold_label == NLILabel.CONTRADICTION)
    false_entailment_rate = (
        round(false_entailment_count / contradiction_total, 4) if contradiction_total > 0 else 0.0
    )
    hard_neg_accuracy = round(hard_neg_correct / hard_neg_total, 4) if hard_neg_total > 0 else 1.0

    gate_passed = macro_f1 >= EXIT_GATE_MACRO_F1_THRESHOLD

    metrics = NLICalibrationMetrics(
        total_samples=total_n,
        accuracy=round(accuracy, 4),
        per_class_precision=precisions,
        per_class_recall=recalls,
        per_class_f1=f1s,
        macro_f1=macro_f1,
        expected_calibration_error=round(ece, 4),
        false_entailment_count=false_entailment_count,
        false_entailment_rate=false_entailment_rate,
        hard_negative_accuracy=hard_neg_accuracy,
        gate_passed=gate_passed,
    )

    # Deterministic SHA-256 digest of metrics
    digest_input = json.dumps(metrics.to_dict(), sort_keys=True).encode("utf-8")
    report_sha256 = hashlib.sha256(digest_input).hexdigest()

    report = NLICalibrationReport(
        report_id=f"NLI-CALIB-{report_sha256[:12]}",
        benchmark_version=BENCHMARK_VERSION,
        timestamp_iso=datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        report_sha256=report_sha256,
        failure_cases=failure_cases,
    )

    return report


def _compute_ece(predictions: list[tuple[float, bool]], num_bins: int = 10) -> float:
    """Calculate Expected Calibration Error (ECE) across confidence bins."""
    if not predictions:
        return 0.0

    bins: list[list[tuple[float, bool]]] = [[] for _ in range(num_bins)]
    bin_width = 1.0 / num_bins

    for conf, is_correct in predictions:
        bin_idx = min(num_bins - 1, int(conf / bin_width))
        bins[bin_idx].append((conf, is_correct))

    ece = 0.0
    n = len(predictions)

    for b in bins:
        if not b:
            continue
        bin_size = len(b)
        avg_conf = sum(c for c, _ in b) / bin_size
        acc = sum(1 for _, correct in b if correct) / bin_size
        ece += (bin_size / n) * abs(acc - avg_conf)

    return float(ece)
