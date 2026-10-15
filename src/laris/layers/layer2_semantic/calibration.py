"""Scientific NLI benchmark fixtures, evaluation, split isolation, and calibration reporting.

Module ID: MOD-SEM-001 (Boundary C)
Governed by: docs/specifications/MODULE_CONTRACTS.md, ADR-002, ADR-008, and Milestone M3 Exit Gate.
Evaluates Macro-F1 >= 0.82 gate, Expected Calibration Error (ECE), and false entailment rates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.layers.layer2_semantic.engine import DeterministicScientificNLIEngine
from laris.layers.layer2_semantic.schemas import (
    NLIEngineContract,
    NLILabel,
    SentencePairInput,
)

BENCHMARK_VERSION: str = "v1.0.0"
EXIT_GATE_MACRO_F1_THRESHOLD: float = 0.82


class BenchmarkSplit(str, Enum):
    """Dataset partition split identifier."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class NLIFailureType(str, Enum):
    """Categorization of NLI inference failure modes."""

    POLARITY_INVERSION = "POLARITY_INVERSION"
    FALSE_ENTAILMENT = "FALSE_ENTAILMENT"
    FALSE_CONTRADICTION = "FALSE_CONTRADICTION"
    UNWARRANTED_NEUTRAL = "UNWARRANTED_NEUTRAL"
    MISCLASSIFIED_NEUTRAL = "MISCLASSIFIED_NEUTRAL"


@dataclass(frozen=True)
class NLIFailureDiagnostic:
    """Structured diagnostic representation of an NLI inference failure case."""

    pair_id: str
    premise: str
    hypothesis: str
    gold_label: NLILabel
    predicted_label: NLILabel
    failure_type: NLIFailureType
    confidence: float
    domain: str
    topical_overlap: str
    diagnostic_message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "premise": self.premise,
            "hypothesis": self.hypothesis,
            "gold_label": self.gold_label.value,
            "predicted_label": self.predicted_label.value,
            "failure_type": self.failure_type.value,
            "confidence": round(self.confidence, 4),
            "domain": self.domain,
            "topical_overlap": self.topical_overlap,
            "diagnostic_message": self.diagnostic_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NLIFailureDiagnostic:
        return cls(
            pair_id=str(data["pair_id"]),
            premise=str(data["premise"]),
            hypothesis=str(data["hypothesis"]),
            gold_label=NLILabel(data["gold_label"]),
            predicted_label=NLILabel(data["predicted_label"]),
            failure_type=NLIFailureType(data["failure_type"]),
            confidence=float(data["confidence"]),
            domain=str(data["domain"]),
            topical_overlap=str(data["topical_overlap"]),
            diagnostic_message=str(data["diagnostic_message"]),
        )


def classify_failure_type(gold: NLILabel, pred: NLILabel) -> NLIFailureType:
    """Categorize the exact semantic failure mode between gold and predicted labels."""
    if (gold == NLILabel.CONTRADICTION and pred == NLILabel.ENTAILMENT) or (
        gold == NLILabel.ENTAILMENT and pred == NLILabel.CONTRADICTION
    ):
        return NLIFailureType.POLARITY_INVERSION
    if pred == NLILabel.ENTAILMENT:
        return NLIFailureType.FALSE_ENTAILMENT
    if pred == NLILabel.CONTRADICTION:
        return NLIFailureType.FALSE_CONTRADICTION
    if pred == NLILabel.NEUTRAL:
        return NLIFailureType.UNWARRANTED_NEUTRAL
    return NLIFailureType.MISCLASSIFIED_NEUTRAL


@dataclass(frozen=True)
class SplitIsolationReport:
    """Cryptographically verifiable report of dataset split isolation."""

    is_isolated: bool
    train_size: int
    val_size: int
    test_size: int
    leakage_violations: list[str]
    split_manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitIsolationReport:
        return cls(
            is_isolated=bool(data["is_isolated"]),
            train_size=int(data["train_size"]),
            val_size=int(data["val_size"]),
            test_size=int(data["test_size"]),
            leakage_violations=list(data.get("leakage_violations", [])),
            split_manifest_sha256=str(data["split_manifest_sha256"]),
        )


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
    split: BenchmarkSplit = BenchmarkSplit.TEST
    author_ids: tuple[str, ...] = ("AUTH-SYNTH-TST-1",)
    document_ids: tuple[str, ...] = ("DOC-SYNTH-TST-1",)

    def to_input(self) -> SentencePairInput:
        return SentencePairInput(
            premise=self.premise,
            hypothesis=self.hypothesis,
            pair_id=self.pair_id,
            metadata={
                "domain": self.domain,
                "gold_label": self.gold_label.value,
                "is_hard_negative": self.is_hard_negative,
                "split": self.split.value,
                "author_ids": list(self.author_ids),
                "document_ids": list(self.document_ids),
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

# Explicit alias for testing split
SCIENTIFIC_NLI_TEST_FIXTURES: list[BenchmarkNLIPair] = SCIENTIFIC_NLI_BENCHMARK_FIXTURES

# Synthetic training split (isolated author IDs, document IDs, and non-overlapping content)
SCIENTIFIC_NLI_TRAIN_FIXTURES: list[BenchmarkNLIPair] = [
    BenchmarkNLIPair(
        pair_id="NLI-TRN-001",
        premise="Graphene exhibits ballistic electron transport at room temperature.",
        hypothesis="Graphene exhibits high scattering and low mobility at room temperature.",
        gold_label=NLILabel.CONTRADICTION,
        domain="condensed_matter",
        topical_overlap="HIGH",
        is_hard_negative=True,
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-1",),
        document_ids=("DOC-SYNTH-TRN-1",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-TRN-002",
        premise="Enzyme velocity increased linearly with substrate concentration.",
        hypothesis="Enzyme velocity decreased linearly with substrate concentration.",
        gold_label=NLILabel.CONTRADICTION,
        domain="enzymology",
        topical_overlap="HIGH",
        is_hard_negative=True,
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-1",),
        document_ids=("DOC-SYNTH-TRN-1",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-TRN-003",
        premise="The crystal belongs to the monoclinic space group P21/c.",
        hypothesis="Single-crystal analysis confirmed monoclinic P21/c symmetry.",
        gold_label=NLILabel.ENTAILMENT,
        domain="crystallography",
        topical_overlap="HIGH",
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-2",),
        document_ids=("DOC-SYNTH-TRN-2",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-TRN-004",
        premise="Photoluminescence quantum yield reached 85 percent in perovskite films.",
        hypothesis="Perovskite thin films demonstrated an 85 percent photoluminescence yield.",
        gold_label=NLILabel.ENTAILMENT,
        domain="optics",
        topical_overlap="HIGH",
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-2",),
        document_ids=("DOC-SYNTH-TRN-2",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-TRN-005",
        premise="The superconductor exhibits Meissner effect flux expulsion.",
        hypothesis="Centrifugation was carried out at 14000 rpm for 20 minutes.",
        gold_label=NLILabel.NEUTRAL,
        domain="superconductivity",
        topical_overlap="LOW",
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-3",),
        document_ids=("DOC-SYNTH-TRN-3",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-TRN-006",
        premise="Polymer chain entanglement governs melt shear viscosity.",
        hypothesis="Mass spectrometry identified peptides in the digest sample.",
        gold_label=NLILabel.NEUTRAL,
        domain="polymer_physics",
        topical_overlap="LOW",
        split=BenchmarkSplit.TRAIN,
        author_ids=("AUTH-SYNTH-TRN-3",),
        document_ids=("DOC-SYNTH-TRN-3",),
    ),
]

# Synthetic validation split (isolated author IDs, document IDs, and non-overlapping content)
SCIENTIFIC_NLI_VAL_FIXTURES: list[BenchmarkNLIPair] = [
    BenchmarkNLIPair(
        pair_id="NLI-VAL-001",
        premise="Membrane permeability was enhanced by detergent treatment.",
        hypothesis="Membrane permeability was inhibited by detergent treatment.",
        gold_label=NLILabel.CONTRADICTION,
        domain="cellular_biology",
        topical_overlap="HIGH",
        is_hard_negative=True,
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-1",),
        document_ids=("DOC-SYNTH-VAL-1",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-VAL-002",
        premise="The magnetic susceptibility diverges at the critical temperature.",
        hypothesis="The magnetic susceptibility drops to zero at the critical temperature.",
        gold_label=NLILabel.CONTRADICTION,
        domain="magnetism",
        topical_overlap="HIGH",
        is_hard_negative=True,
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-1",),
        document_ids=("DOC-SYNTH-VAL-1",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-VAL-003",
        premise="Thermal annealing increased grain size from 20 nm to 80 nm.",
        hypothesis="Grain size enlarged from 20 nm to 80 nm following thermal annealing.",
        gold_label=NLILabel.ENTAILMENT,
        domain="metallurgy",
        topical_overlap="HIGH",
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-2",),
        document_ids=("DOC-SYNTH-VAL-2",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-VAL-004",
        premise="Target protein expression was upregulated five-fold after induction.",
        hypothesis="Induction resulted in a five-fold upregulation of target protein expression.",
        gold_label=NLILabel.ENTAILMENT,
        domain="biochemistry",
        topical_overlap="HIGH",
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-2",),
        document_ids=("DOC-SYNTH-VAL-2",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-VAL-005",
        premise="Topological insulators possess gapless metallic surface states.",
        hypothesis="Electrophoresis was performed on a 12 percent SDS-PAGE gel.",
        gold_label=NLILabel.NEUTRAL,
        domain="quantum_materials",
        topical_overlap="LOW",
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-3",),
        document_ids=("DOC-SYNTH-VAL-3",),
    ),
    BenchmarkNLIPair(
        pair_id="NLI-VAL-006",
        premise="The exothermic reaction releases 240 kJ per mole of reactant.",
        hypothesis="Microscopy images were processed using edge-detection filters.",
        gold_label=NLILabel.NEUTRAL,
        domain="thermodynamics",
        topical_overlap="LOW",
        split=BenchmarkSplit.VALIDATION,
        author_ids=("AUTH-SYNTH-VAL-3",),
        document_ids=("DOC-SYNTH-VAL-3",),
    ),
]


def verify_nli_split_isolation(
    splits: dict[BenchmarkSplit | str, list[BenchmarkNLIPair]],
    raise_on_leakage: bool = True,
) -> SplitIsolationReport:
    """Verify strict partition isolation between training/tuning and evaluation splits.

    Ensures zero premise/hypothesis text overlap, zero author leakage, and zero document leakage.
    Raises DataLeakageError if leakage is found and raise_on_leakage is True.
    """
    train_pairs: list[BenchmarkNLIPair] = []
    val_pairs: list[BenchmarkNLIPair] = []
    test_pairs: list[BenchmarkNLIPair] = []

    for k, v in splits.items():
        key_str = k.value if isinstance(k, BenchmarkSplit) else str(k).lower()
        if key_str == BenchmarkSplit.TRAIN.value:
            train_pairs.extend(v)
        elif key_str in (BenchmarkSplit.VALIDATION.value, "val"):
            val_pairs.extend(v)
        elif key_str == BenchmarkSplit.TEST.value:
            test_pairs.extend(v)

    def _normalize(t: str) -> str:
        return " ".join(t.lower().strip().split())

    violations: list[str] = []

    # 1. Check text overlap between test and train/val
    eval_texts = {_normalize(p.premise): p.pair_id for p in test_pairs}
    eval_texts.update({_normalize(p.hypothesis): p.pair_id for p in test_pairs})

    for p in train_pairs:
        norm_p = _normalize(p.premise)
        norm_h = _normalize(p.hypothesis)
        if norm_p in eval_texts:
            violations.append(
                f"Text leakage: premise in train ({p.pair_id}) matches test ({eval_texts[norm_p]})"
            )
        if norm_h in eval_texts:
            violations.append(
                f"Text leakage: hypothesis in train ({p.pair_id}) "
                f"matches test ({eval_texts[norm_h]})"
            )

    for p in val_pairs:
        norm_p = _normalize(p.premise)
        norm_h = _normalize(p.hypothesis)
        if norm_p in eval_texts:
            violations.append(
                f"Text leakage: premise in val ({p.pair_id}) matches test ({eval_texts[norm_p]})"
            )
        if norm_h in eval_texts:
            violations.append(
                f"Text leakage: hypothesis in val ({p.pair_id}) "
                f"matches test ({eval_texts[norm_h]})"
            )

    # 2. Check author and document ID leakage
    test_authors = {a for p in test_pairs for a in p.author_ids if a}
    test_docs = {d for p in test_pairs for d in p.document_ids if d}

    train_authors = {a for p in train_pairs for a in p.author_ids if a}
    train_docs = {d for p in train_pairs for d in p.document_ids if d}

    val_authors = {a for p in val_pairs for a in p.author_ids if a}
    val_docs = {d for p in val_pairs for d in p.document_ids if d}

    author_leakage = test_authors.intersection(train_authors.union(val_authors))
    if author_leakage:
        violations.append(f"Author leakage across splits: {sorted(author_leakage)}")

    doc_leakage = test_docs.intersection(train_docs.union(val_docs))
    if doc_leakage:
        violations.append(f"Document leakage across splits: {sorted(doc_leakage)}")

    # 3. Check duplicate pair_ids across splits
    seen_ids: dict[str, str] = {}
    for split_name, pair_list in [
        ("train", train_pairs),
        ("val", val_pairs),
        ("test", test_pairs),
    ]:
        for p in pair_list:
            if p.pair_id in seen_ids:
                violations.append(
                    f"Duplicate pair_id '{p.pair_id}' in split '{split_name}' "
                    f"(already in '{seen_ids[p.pair_id]}')"
                )
            else:
                seen_ids[p.pair_id] = split_name

    is_isolated = len(violations) == 0

    if raise_on_leakage and not is_isolated:
        raise DataLeakageError("; ".join(violations))

    manifest_payload = {
        "train_size": len(train_pairs),
        "val_size": len(val_pairs),
        "test_size": len(test_pairs),
        "train_ids": sorted(p.pair_id for p in train_pairs),
        "val_ids": sorted(p.pair_id for p in val_pairs),
        "test_ids": sorted(p.pair_id for p in test_pairs),
        "is_isolated": is_isolated,
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return SplitIsolationReport(
        is_isolated=is_isolated,
        train_size=len(train_pairs),
        val_size=len(val_pairs),
        test_size=len(test_pairs),
        leakage_violations=violations,
        split_manifest_sha256=manifest_sha256,
    )


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
    confusion_matrix: dict[str, dict[str, int]] = field(default_factory=dict)

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
            confusion_matrix=data.get("confusion_matrix", {}),
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
    failure_diagnostics: list[NLIFailureDiagnostic] = field(default_factory=list)
    split_isolation: SplitIsolationReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "benchmark_version": self.benchmark_version,
            "timestamp_iso": self.timestamp_iso,
            "metrics": self.metrics.to_dict(),
            "report_sha256": self.report_sha256,
            "failure_cases": self.failure_cases,
            "failure_diagnostics": [d.to_dict() for d in self.failure_diagnostics],
            "split_isolation": (
                self.split_isolation.to_dict() if self.split_isolation is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NLICalibrationReport:
        diag_list = [
            NLIFailureDiagnostic.from_dict(d)
            for d in data.get("failure_diagnostics", [])
        ]
        iso = (
            SplitIsolationReport.from_dict(data["split_isolation"])
            if data.get("split_isolation")
            else None
        )
        return cls(
            report_id=data["report_id"],
            benchmark_version=data["benchmark_version"],
            timestamp_iso=data["timestamp_iso"],
            metrics=NLICalibrationMetrics.from_dict(data["metrics"]),
            report_sha256=data["report_sha256"],
            failure_cases=data.get("failure_cases", []),
            failure_diagnostics=diag_list,
            split_isolation=iso,
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

        if m.confusion_matrix:
            cm = m.confusion_matrix
            lines.extend(
                [
                    "",
                    "## Confusion Matrix",
                    "| Gold \\ Pred | ENTAILMENT | CONTRADICTION | NEUTRAL |",
                    "| :--- | :--- | :--- | :--- |",
                    (
                        f"| **`ENTAILMENT`** | {cm.get('ENTAILMENT', {}).get('ENTAILMENT', 0)} | "
                        f"{cm.get('ENTAILMENT', {}).get('CONTRADICTION', 0)} | "
                        f"{cm.get('ENTAILMENT', {}).get('NEUTRAL', 0)} |"
                    ),
                    (
                        f"| **`CONTRADICTION`** | "
                        f"{cm.get('CONTRADICTION', {}).get('ENTAILMENT', 0)} | "
                        f"{cm.get('CONTRADICTION', {}).get('CONTRADICTION', 0)} | "
                        f"{cm.get('CONTRADICTION', {}).get('NEUTRAL', 0)} |"
                    ),
                    (
                        f"| **`NEUTRAL`** | {cm.get('NEUTRAL', {}).get('ENTAILMENT', 0)} | "
                        f"{cm.get('NEUTRAL', {}).get('CONTRADICTION', 0)} | "
                        f"{cm.get('NEUTRAL', {}).get('NEUTRAL', 0)} |"
                    ),
                ]
            )

        if self.split_isolation is not None:
            iso = self.split_isolation
            iso_status = "PASSED (Zero leakage)" if iso.is_isolated else "FAILED (Data leakage)"
            lines.extend(
                [
                    "",
                    "## Split Isolation Status",
                    f"- **Isolation Status:** {iso_status}",
                    f"- **Train Partition Size:** {iso.train_size}",
                    f"- **Validation Partition Size:** {iso.val_size}",
                    f"- **Test Partition Size:** {iso.test_size}",
                    f"- **Split Manifest Digest:** `{iso.split_manifest_sha256}`",
                ]
            )
            if iso.leakage_violations:
                lines.append(f"- **Leakage Violations:** {len(iso.leakage_violations)}")
                for v in iso.leakage_violations:
                    lines.append(f"  - `{v}`")

        if self.failure_diagnostics:
            lines.extend(
                [
                    "",
                    "## Failure Diagnostics (Failure Analysis)",
                    "| Pair ID | Failure Mode | Gold | Pred | Conf | Domain |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- |",
                ]
            )
            for fd in self.failure_diagnostics:
                lines.append(
                    f"| `{fd.pair_id}` | `{fd.failure_type.value}` | `{fd.gold_label.value}` | "
                    f"`{fd.predicted_label.value}` | {fd.confidence:.3f} | {fd.domain} |"
                )
        elif self.failure_cases:
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
    split_isolation: SplitIsolationReport | None = None,
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

    confusion_matrix: dict[str, dict[str, int]] = {
        g: {p: 0 for p in label_vals} for g in label_vals
    }

    total_correct = 0
    false_entailment_count = 0
    hard_neg_total = 0
    hard_neg_correct = 0

    predictions: list[tuple[float, bool]] = []
    failure_cases: list[dict[str, Any]] = []
    failure_diagnostics: list[NLIFailureDiagnostic] = []

    for item in benchmark_pairs:
        out = engine.infer(item.to_input())
        pred_label = out.prediction.value
        gold_label = item.gold_label.value

        conf = max(out.probabilities.values()) if out.probabilities else 1.0
        is_correct = pred_label == gold_label

        confusion_matrix[gold_label][pred_label] += 1
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
            f_type = classify_failure_type(item.gold_label, out.prediction)
            diag = NLIFailureDiagnostic(
                pair_id=item.pair_id,
                premise=item.premise,
                hypothesis=item.hypothesis,
                gold_label=item.gold_label,
                predicted_label=out.prediction,
                failure_type=f_type,
                confidence=float(conf),
                domain=item.domain,
                topical_overlap=item.topical_overlap,
                diagnostic_message=(
                    f"Model predicted {out.prediction.value} instead of gold {gold_label} "
                    f"with confidence {conf:.3f} (failure mode: {f_type.value})"
                ),
            )
            failure_diagnostics.append(diag)

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
        confusion_matrix=confusion_matrix,
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
        failure_diagnostics=failure_diagnostics,
        split_isolation=split_isolation,
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
