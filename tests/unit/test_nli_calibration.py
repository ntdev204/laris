"""Unit tests for scientific NLI benchmark and calibration reporting.

Task ID: M3-SEM-003-SUB-01 (Issue #55)
Milestone: M3 (Semantic Relations & NLI)
Boundary C: MOD-SEM-001 (Semantic Intelligence)
"""

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer2_semantic import (
    BENCHMARK_VERSION,
    EXIT_GATE_MACRO_F1_THRESHOLD,
    SCIENTIFIC_NLI_BENCHMARK_FIXTURES,
    BenchmarkNLIPair,
    DeterministicScientificNLIEngine,
    NLICalibrationMetrics,
    NLICalibrationReport,
    NLILabel,
    evaluate_nli_calibration,
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
        from laris.layers.layer2_semantic import NLIOutput, SentencePairInput

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

        # Markdown includes failure case section
        md = report.render_summary_text()
        assert "## Failure Analysis (Discrepancies)" in md
        assert "**Status:** FAILED" in md
