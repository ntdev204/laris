"""Unit tests for scientific NLI benchmark, split isolation, and calibration reporting.

Task ID: M3-SEM-003-SUB-02 (Issue #87)
Milestone: M3 (Semantic Relations & NLI)
Boundary C: MOD-SEM-001 (Semantic Intelligence)
"""

import pytest

from laris.core.errors import DataLeakageError, ModuleContractViolationError
from laris.layers.layer2_semantic import (
    BENCHMARK_VERSION,
    EXIT_GATE_MACRO_F1_THRESHOLD,
    SCIENTIFIC_NLI_BENCHMARK_FIXTURES,
    SCIENTIFIC_NLI_TEST_FIXTURES,
    SCIENTIFIC_NLI_TRAIN_FIXTURES,
    SCIENTIFIC_NLI_VAL_FIXTURES,
    BenchmarkNLIPair,
    BenchmarkSplit,
    DeterministicScientificNLIEngine,
    NLICalibrationMetrics,
    NLICalibrationReport,
    NLIFailureDiagnostic,
    NLIFailureType,
    NLILabel,
    NLIOutput,
    SentencePairInput,
    SplitIsolationReport,
    classify_failure_type,
    evaluate_nli_calibration,
    verify_nli_split_isolation,
)
from laris.layers.layer2_semantic.calibration import _compute_ece


class TestNLICalibrationSuite:
    """Verifies scientific NLI benchmark evaluation, calibration metrics, and report generation."""

    def test_benchmark_fixtures_composition(self) -> None:
        """Verify the canonical benchmark contains balanced classes and domains."""
        fixtures = SCIENTIFIC_NLI_BENCHMARK_FIXTURES
        assert len(fixtures) == 24

        counts: dict[NLILabel, int] = {}
        for item in fixtures:
            counts[item.gold_label] = counts.get(item.gold_label, 0) + 1
            assert len(item.premise) > 10
            assert len(item.hypothesis) > 10
            assert item.domain

        # 8 per class (balanced 3-way split)
        assert counts[NLILabel.CONTRADICTION] == 8
        assert counts[NLILabel.ENTAILMENT] == 8
        assert counts[NLILabel.NEUTRAL] == 8

        # Hard negatives exist for contradiction
        hard_negs = [item for item in fixtures if item.is_hard_negative]
        assert len(hard_negs) == 8

    def test_benchmark_pair_to_input(self) -> None:
        """Verify conversion from BenchmarkNLIPair to SentencePairInput."""
        item = SCIENTIFIC_NLI_BENCHMARK_FIXTURES[0]
        sp_input = item.to_input()
        assert sp_input.pair_id == item.pair_id
        assert sp_input.premise == item.premise
        assert sp_input.hypothesis == item.hypothesis
        assert sp_input.metadata["domain"] == item.domain
        assert sp_input.metadata["gold_label"] == item.gold_label.value
        assert sp_input.metadata["is_hard_negative"] is True
        assert sp_input.metadata["split"] == "test"

    def test_evaluate_calibration_passes_gate(self) -> None:
        """Verify that default deterministic NLI engine meets or exceeds Macro-F1 >= 0.82."""
        engine = DeterministicScientificNLIEngine()
        report = evaluate_nli_calibration(engine=engine)

        assert report.benchmark_version == BENCHMARK_VERSION
        assert report.report_id.startswith("NLI-CALIB-")
        assert len(report.report_sha256) == 64

        m = report.metrics
        assert m.total_samples == len(SCIENTIFIC_NLI_BENCHMARK_FIXTURES)
        assert m.macro_f1 >= EXIT_GATE_MACRO_F1_THRESHOLD
        assert m.gate_passed is True

        # False entailment rate on contradictions must be zero
        assert m.false_entailment_count == 0
        assert m.false_entailment_rate == 0.0

        # Hard negative accuracy must be 1.0 (contradiction invariant preserved)
        assert m.hard_negative_accuracy == 1.0

        # Calibration error (ECE) should be bounded in [0.0, 1.0]
        assert 0.0 <= m.expected_calibration_error <= 1.0

        # Confusion matrix has entries for all 3 classes
        assert len(m.confusion_matrix) == 3
        for k in ["ENTAILMENT", "CONTRADICTION", "NEUTRAL"]:
            assert m.confusion_matrix[k][k] == 8

    def test_evaluate_calibration_empty_benchmark_error(self) -> None:
        """Verify error when benchmark is empty."""
        with pytest.raises(ModuleContractViolationError, match="cannot be empty"):
            evaluate_nli_calibration(benchmark_pairs=[])

    def test_evaluate_calibration_custom_subset(self) -> None:
        """Verify evaluation on a custom subset of benchmark items."""
        subset = [
            BenchmarkNLIPair(
                pair_id="CUSTOM-001",
                premise="Substance A is an electrical conductor.",
                hypothesis="Substance A is an electrical insulator.",
                gold_label=NLILabel.CONTRADICTION,
                domain="materials",
                is_hard_negative=True,
            ),
            BenchmarkNLIPair(
                pair_id="CUSTOM-002",
                premise="Cuprate ceramics exhibit superconductivity below 93 Kelvin.",
                hypothesis="Below 93 Kelvin, cuprate ceramics exhibit superconductivity.",
                gold_label=NLILabel.ENTAILMENT,
                domain="superconductivity",
            ),
        ]
        report = evaluate_nli_calibration(benchmark_pairs=subset)
        assert report.metrics.total_samples == 2
        assert report.metrics.accuracy == 1.0
        assert report.metrics.macro_f1 == 1.0
        assert report.metrics.gate_passed is True

    def test_report_serialization_round_trip(self) -> None:
        """Verify to_dict/from_dict and to_json/from_json serialization integrity."""
        report = evaluate_nli_calibration()
        as_dict = report.to_dict()
        reconstructed = NLICalibrationReport.from_dict(as_dict)

        assert reconstructed.report_id == report.report_id
        assert reconstructed.benchmark_version == report.benchmark_version
        assert reconstructed.report_sha256 == report.report_sha256
        assert reconstructed.metrics.macro_f1 == report.metrics.macro_f1
        assert reconstructed.metrics.accuracy == report.metrics.accuracy
        assert reconstructed.metrics.gate_passed == report.metrics.gate_passed

        as_json = report.to_json()
        from_json_report = NLICalibrationReport.from_json(as_json)
        assert from_json_report.report_sha256 == report.report_sha256
        assert (
            from_json_report.metrics.expected_calibration_error
            == report.metrics.expected_calibration_error
        )

    def test_report_render_summary_text(self) -> None:
        """Verify markdown rendering of report summary."""
        report = evaluate_nli_calibration()
        md = report.render_summary_text()

        assert "# Scientific NLI Calibration Report" in md
        assert "**Status:** PASSED" in md
        assert "Report SHA-256:" in md
        assert "Overall Accuracy:" in md
        assert "Macro-Averaged F1:" in md
        assert "Expected Calibration Error (ECE):" in md
        assert "Hard Negative Contradiction Accuracy:" in md
        assert "Per-Class Performance" in md
        assert "| `CONTRADICTION` |" in md
        assert "| `ENTAILMENT` |" in md
        assert "| `NEUTRAL` |" in md
        assert "## Confusion Matrix" in md

    def test_ece_computation_edge_cases(self) -> None:
        """Verify Expected Calibration Error calculation on edge cases."""
        # Empty predictions
        assert _compute_ece([]) == 0.0

        # Perfect predictions: confidence 1.0, all correct
        perfect_preds = [(1.0, True) for _ in range(10)]
        assert _compute_ece(perfect_preds) == 0.0

        # Completely uncalibrated: confidence 1.0, all incorrect
        uncalibrated = [(1.0, False) for _ in range(10)]
        assert _compute_ece(uncalibrated) == pytest.approx(1.0, abs=1e-5)

    def test_metrics_serialization(self) -> None:
        """Verify NLICalibrationMetrics dictionary serialization."""
        report = evaluate_nli_calibration()
        m = report.metrics
        d = m.to_dict()
        m2 = NLICalibrationMetrics.from_dict(d)
        assert m == m2

    def test_false_entailment_and_failure_analysis(self) -> None:
        """Verify tracking of false entailment rate and failure case rendering."""

        class MockBrokenNLIEngine:
            def infer(self, pair: SentencePairInput) -> NLIOutput:
                # Always predict ENTAILMENT with high confidence
                return NLIOutput(
                    pair_id=pair.pair_id,
                    prediction=NLILabel.ENTAILMENT,
                    probabilities={
                        NLILabel.ENTAILMENT.value: 0.90,
                        NLILabel.CONTRADICTION.value: 0.05,
                        NLILabel.NEUTRAL.value: 0.05,
                    },
                    uncertainty_score=0.1,
                    topical_similarity=0.9,
                )

        report = evaluate_nli_calibration(engine=MockBrokenNLIEngine())
        assert report.metrics.gate_passed is False
        assert report.metrics.false_entailment_count > 0
        assert report.metrics.false_entailment_rate > 0.0
        assert report.metrics.hard_negative_accuracy == 0.0
        assert len(report.failure_cases) > 0
        assert len(report.failure_diagnostics) > 0

        # Markdown includes failure case section
        md = report.render_summary_text()
        assert "## Failure Diagnostics (Failure Analysis)" in md
        assert "**Status:** FAILED" in md


class TestBenchmarkSplitIsolation:
    """Verifies train/validation/test split isolation, leakage detection, and reporting."""

    def test_canonical_splits_isolation(self) -> None:
        """Canonical synthetic splits must exhibit zero leakage across text, author, and doc."""
        splits = {
            BenchmarkSplit.TRAIN: SCIENTIFIC_NLI_TRAIN_FIXTURES,
            BenchmarkSplit.VALIDATION: SCIENTIFIC_NLI_VAL_FIXTURES,
            BenchmarkSplit.TEST: SCIENTIFIC_NLI_TEST_FIXTURES,
        }
        report = verify_nli_split_isolation(splits)
        assert report.is_isolated is True
        assert len(report.leakage_violations) == 0
        assert report.train_size == 6
        assert report.val_size == 6
        assert report.test_size == 24
        assert len(report.split_manifest_sha256) == 64

    def test_split_text_leakage_detection(self) -> None:
        """Test premise/hypothesis text overlap is detected and flagged."""
        leaked_train_pair = BenchmarkNLIPair(
            pair_id="LEAK-TRN-001",
            premise=SCIENTIFIC_NLI_TEST_FIXTURES[0].premise,
            hypothesis="Distinct hypothesis sentence.",
            gold_label=NLILabel.ENTAILMENT,
            domain="materials_science",
            split=BenchmarkSplit.TRAIN,
            author_ids=("AUTH-LEAK-1",),
            document_ids=("DOC-LEAK-1",),
        )
        splits = {
            BenchmarkSplit.TRAIN: [leaked_train_pair],
            BenchmarkSplit.TEST: SCIENTIFIC_NLI_TEST_FIXTURES,
        }
        with pytest.raises(DataLeakageError, match="Text leakage"):
            verify_nli_split_isolation(splits, raise_on_leakage=True)

        report = verify_nli_split_isolation(splits, raise_on_leakage=False)
        assert report.is_isolated is False
        assert any("Text leakage" in v for v in report.leakage_violations)

    def test_split_author_leakage_detection(self) -> None:
        """Test author ID overlap between train and test splits is caught."""
        shared_author_train = BenchmarkNLIPair(
            pair_id="LEAK-AUTH-001",
            premise="Completely distinct premise text for testing.",
            hypothesis="Completely distinct hypothesis text for testing.",
            gold_label=NLILabel.NEUTRAL,
            domain="biology",
            split=BenchmarkSplit.TRAIN,
            author_ids=("AUTH-SYNTH-TST-1",),  # Same author as test set!
            document_ids=("DOC-DISJOINT-1",),
        )
        splits = {
            BenchmarkSplit.TRAIN: [shared_author_train],
            BenchmarkSplit.TEST: SCIENTIFIC_NLI_TEST_FIXTURES,
        }
        with pytest.raises(DataLeakageError, match="Author leakage across splits"):
            verify_nli_split_isolation(splits, raise_on_leakage=True)

    def test_split_document_leakage_detection(self) -> None:
        """Test document ID overlap between train and test splits is caught."""
        shared_doc_train = BenchmarkNLIPair(
            pair_id="LEAK-DOC-001",
            premise="Completely distinct premise text for doc test.",
            hypothesis="Completely distinct hypothesis text for doc test.",
            gold_label=NLILabel.NEUTRAL,
            domain="chemistry",
            split=BenchmarkSplit.TRAIN,
            author_ids=("AUTH-DISJOINT-1",),
            document_ids=("DOC-SYNTH-TST-1",),  # Same document ID as test set!
        )
        splits = {
            BenchmarkSplit.TRAIN: [shared_doc_train],
            BenchmarkSplit.TEST: SCIENTIFIC_NLI_TEST_FIXTURES,
        }
        with pytest.raises(DataLeakageError, match="Document leakage across splits"):
            verify_nli_split_isolation(splits, raise_on_leakage=True)

    def test_split_duplicate_pair_id_detection(self) -> None:
        """Test duplicate pair ID across different splits is caught."""
        dup_train = BenchmarkNLIPair(
            pair_id="NLI-BENCH-001",  # Same ID as fixture in test!
            premise="Unique premise text.",
            hypothesis="Unique hypothesis text.",
            gold_label=NLILabel.NEUTRAL,
            domain="physics",
            split=BenchmarkSplit.TRAIN,
            author_ids=("AUTH-DISJOINT-1",),
            document_ids=("DOC-DISJOINT-1",),
        )
        splits = {
            BenchmarkSplit.TRAIN: [dup_train],
            BenchmarkSplit.TEST: SCIENTIFIC_NLI_TEST_FIXTURES,
        }
        with pytest.raises(DataLeakageError, match="Duplicate pair_id"):
            verify_nli_split_isolation(splits, raise_on_leakage=True)

    def test_failure_classification_modes(self) -> None:
        """Verify accurate classification of semantic failure types."""
        assert (
            classify_failure_type(NLILabel.CONTRADICTION, NLILabel.ENTAILMENT)
            == NLIFailureType.POLARITY_INVERSION
        )
        assert (
            classify_failure_type(NLILabel.ENTAILMENT, NLILabel.CONTRADICTION)
            == NLIFailureType.POLARITY_INVERSION
        )
        assert (
            classify_failure_type(NLILabel.NEUTRAL, NLILabel.ENTAILMENT)
            == NLIFailureType.FALSE_ENTAILMENT
        )
        assert (
            classify_failure_type(NLILabel.NEUTRAL, NLILabel.CONTRADICTION)
            == NLIFailureType.FALSE_CONTRADICTION
        )
        assert (
            classify_failure_type(NLILabel.ENTAILMENT, NLILabel.NEUTRAL)
            == NLIFailureType.UNWARRANTED_NEUTRAL
        )
        assert (
            classify_failure_type(NLILabel.CONTRADICTION, NLILabel.NEUTRAL)
            == NLIFailureType.UNWARRANTED_NEUTRAL
        )

    def test_failure_diagnostic_serialization(self) -> None:
        """Verify NLIFailureDiagnostic round-trip serialization."""
        diag = NLIFailureDiagnostic(
            pair_id="TEST-001",
            premise="Premise text.",
            hypothesis="Hypothesis text.",
            gold_label=NLILabel.CONTRADICTION,
            predicted_label=NLILabel.ENTAILMENT,
            failure_type=NLIFailureType.POLARITY_INVERSION,
            confidence=0.88,
            domain="materials",
            topical_overlap="HIGH",
            diagnostic_message="Critical inversion",
        )
        d = diag.to_dict()
        reconstructed = NLIFailureDiagnostic.from_dict(d)
        assert reconstructed == diag

    def test_split_isolation_report_serialization(self) -> None:
        """Verify SplitIsolationReport round-trip serialization."""
        iso = SplitIsolationReport(
            is_isolated=True,
            train_size=10,
            val_size=5,
            test_size=20,
            leakage_violations=[],
            split_manifest_sha256="abc1234567890",
        )
        d = iso.to_dict()
        reconstructed = SplitIsolationReport.from_dict(d)
        assert reconstructed == iso

    def test_report_with_split_isolation_rendering(self) -> None:
        """Verify NLICalibrationReport renders split isolation section when present."""
        iso = SplitIsolationReport(
            is_isolated=True,
            train_size=6,
            val_size=6,
            test_size=24,
            leakage_violations=[],
            split_manifest_sha256="deadbeef12345678",
        )
        report = evaluate_nli_calibration(split_isolation=iso)
        assert report.split_isolation is not None
        md = report.render_summary_text()
        assert "## Split Isolation Status" in md
        assert "Isolation Status:** PASSED (Zero leakage)" in md
        assert "Train Partition Size:** 6" in md
        assert "Test Partition Size:** 24" in md
        assert "deadbeef12345678" in md

        # Test serialization round-trip preserving split_isolation
        as_json = report.to_json()
        rec = NLICalibrationReport.from_json(as_json)
        assert rec.split_isolation is not None
        assert rec.split_isolation.split_manifest_sha256 == "deadbeef12345678"
