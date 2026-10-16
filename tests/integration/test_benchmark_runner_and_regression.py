"""Integration tests for Layer 10 benchmark runner, regression gates, and report serialization.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #103:
- Cryptographic stability and checksum integrity of frozen benchmark manifests across 6 domains
- Multi-checkpoint baseline regression comparisons with floor and ceiling gate enforcement
- Deterministic JSON serialization, disk round-trip persistence, and schema reconstitution
- Scientific error taxonomy cataloging, diagnostic breakdown, and thread-safe evaluation history
- Zero training data contamination isolation adhering to strict Boundary J guarantees
"""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Dict

import pytest

from laris.core.errors import (
    EpistemicOverreachError,
    InvalidNLIInputError,
    ModuleContractViolationError,
    ProvenanceViolationError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.layers.layer10_evaluation.benchmark_runner import BenchmarkRunner
from laris.layers.layer10_evaluation.error_taxonomy import ScientificErrorTaxonomy
from laris.layers.layer10_evaluation.schemas import (
    BenchmarkBaseline,
    BenchmarkItem,
    BenchmarkRunReport,
    BenchmarkSuiteType,
    ErrorSeverity,
    EvaluationRunRequest,
    FrozenBenchmarkManifest,
    RegressionThreshold,
    ScientificErrorCategory,
)


class TestStableBenchmarkManifestIntegrity:
    """Integration tests for benchmark manifests across all 6 standardized evaluation suites."""

    @pytest.mark.parametrize(
        "suite_type",
        [
            BenchmarkSuiteType.SEMANTIC_EQUIVALENCE,
            BenchmarkSuiteType.NLI_CONTRADICTION,
            BenchmarkSuiteType.SCIENTIFIC_EXTRACTION,
            BenchmarkSuiteType.CROSS_PAPER_SYNTHESIS,
            BenchmarkSuiteType.RESEARCH_GAP_VALIDATION,
            BenchmarkSuiteType.RESOURCE_EFFICIENCY,
        ],
    )
    def test_all_suite_manifest_construction_and_checksum_determinism(
        self, suite_type: BenchmarkSuiteType
    ) -> None:
        """Verify deterministic checksum calculation and registration for all suite domains."""
        runner = BenchmarkRunner()
        manifest_id = f"SUITE-{suite_type.value}"

        manifest = runner.create_synthetic_manifest(
            manifest_id=manifest_id,
            suite_type=suite_type,
            version="1.0.0",
            num_items=5,
        )

        assert manifest.manifest_id == manifest_id
        assert manifest.suite_type == suite_type
        assert len(manifest.items) == 5
        assert len(manifest.manifest_checksum_sha256) == 64
        assert manifest.is_immutable is True

        # Manifest serialization round-trip
        manifest_dict = manifest.to_dict()
        reconstituted = FrozenBenchmarkManifest.from_dict(manifest_dict)
        assert reconstituted.manifest_id == manifest.manifest_id
        assert reconstituted.manifest_checksum_sha256 == manifest.manifest_checksum_sha256
        assert len(reconstituted.items) == len(manifest.items)
        assert reconstituted.items[0].checksum_sha256 == manifest.items[0].checksum_sha256

        # Register in runner
        runner.register_manifest(manifest)
        fetched = runner.get_manifest(manifest_id)
        assert fetched.manifest_checksum_sha256 == manifest.manifest_checksum_sha256

    def test_tamper_detection_in_manifest_items(self) -> None:
        """Verify that altering item contents invalidates manifest cryptographic checksum."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-TAMPER",
            BenchmarkSuiteType.NLI_CONTRADICTION,
            num_items=3,
        )

        # Alter an item input payload without updating checksum
        with pytest.raises(ModuleContractViolationError, match="Checksum mismatch"):
            BenchmarkItem(
                item_id=manifest.items[0].item_id,
                suite_type=manifest.items[0].suite_type,
                input_payload={"premise": "TAMPERED PREMISE", "hypothesis": "TAMPERED HYP"},
                expected_output=manifest.items[0].expected_output,
                checksum_sha256=manifest.items[0].checksum_sha256,  # Old checksum!
            )

        # Item instantiation with mismatched checksum must raise contract violation
        with pytest.raises(ModuleContractViolationError, match="Checksum mismatch"):
            _ = BenchmarkItem(
                item_id="BAD-CHECKSUM",
                suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                input_payload={"a": 1},
                expected_output={"b": 2},
                checksum_sha256="0000000000000000000000000000000000000000000000000000000000000000",
            )

        # Recomputed valid item checksum with altered content
        valid_recomputed_item = BenchmarkItem(
            item_id=manifest.items[0].item_id,
            suite_type=manifest.items[0].suite_type,
            input_payload={"premise": "TAMPERED PREMISE", "hypothesis": "TAMPERED HYP"},
            expected_output=manifest.items[0].expected_output,
        )

        # Substituting into manifest must trigger manifest checksum mismatch
        new_items = [valid_recomputed_item, manifest.items[1], manifest.items[2]]
        with pytest.raises(ModuleContractViolationError, match="Manifest checksum mismatch"):
            FrozenBenchmarkManifest(
                manifest_id="SUITE-TAMPER",
                suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                version="1.0.0",
                created_at_iso=manifest.created_at_iso,
                items=new_items,
                manifest_checksum_sha256=manifest.manifest_checksum_sha256,  # Old manifest digest
            )


class TestBaselineComparisonAndRegressionGates:
    """Integration tests for multi-checkpoint comparisons, floor gates, and ceiling gates."""

    @pytest.fixture
    def configured_runner(self) -> BenchmarkRunner:
        """Provide a benchmark runner with registered baseline and synthetic manifest."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-M9-REGRESSION",
            BenchmarkSuiteType.NLI_CONTRADICTION,
            num_items=10,
        )
        runner.register_manifest(manifest)

        baseline = BenchmarkBaseline(
            baseline_id="BASE-M8-RELEASE",
            checkpoint_id="CHK-RELEASE-v0.8.0",
            metrics={
                "nli_accuracy": 0.940,
                "contradiction_recall": 0.920,
                "citation_precision": 0.990,
                "gap_novelty_f1": 0.880,
                "peak_vram_gb": 13.50,
            },
            timestamp_iso="2026-10-15T12:00:00Z",
        )
        runner.register_baseline(baseline)
        return runner

    def test_checkpoint_comparison_improved_candidate_passes(
        self, configured_runner: BenchmarkRunner
    ) -> None:
        """Verify candidate exceeding baseline metrics passes all regression gates."""
        req = EvaluationRunRequest(
            run_id="RUN-CANDIDATE-IMPROVED",
            benchmark_suite_id="SUITE-M9-REGRESSION",
            target_checkpoint_id="CHK-CANDIDATE-v0.9.0-ALPHA",
            baseline_checkpoint_id="CHK-RELEASE-v0.8.0",
        )
        candidate_metrics = {
            "nli_accuracy": 0.955,  # Improved (+0.015)
            "contradiction_recall": 0.935,  # Improved (+0.015)
            "citation_precision": 0.995,  # Improved (+0.005)
            "gap_novelty_f1": 0.890,  # Improved (+0.010)
            "peak_vram_gb": 13.20,  # Improved (-0.3 GB, well below 15.0 GB ceiling)
        }
        report = configured_runner.run_evaluation(req, custom_metrics=candidate_metrics)
        assert report.pass_fail_status is True
        assert len(report.regressions_detected) == 0
        assert report.baseline_checkpoint_id == "CHK-RELEASE-v0.8.0"

    def test_checkpoint_comparison_allowable_drop_within_budget(
        self, configured_runner: BenchmarkRunner
    ) -> None:
        """Verify metric drop within allowable threshold (<= 0.03) passes regression gate."""
        req = EvaluationRunRequest(
            run_id="RUN-CANDIDATE-TOLERABLE-DROP",
            benchmark_suite_id="SUITE-M9-REGRESSION",
            target_checkpoint_id="CHK-CANDIDATE-v0.9.0-BETA1",
            baseline_checkpoint_id="CHK-RELEASE-v0.8.0",
        )
        # Drop nli_accuracy by 0.02 (0.940 -> 0.920), within allowable drop 0.03
        candidate_metrics = {
            "nli_accuracy": 0.920,
            "contradiction_recall": 0.920,
            "citation_precision": 0.990,
            "gap_novelty_f1": 0.880,
            "peak_vram_gb": 13.50,
        }
        report = configured_runner.run_evaluation(req, custom_metrics=candidate_metrics)
        assert report.pass_fail_status is True
        assert len(report.regressions_detected) == 0

    def test_checkpoint_comparison_excessive_drop_fails(
        self, configured_runner: BenchmarkRunner
    ) -> None:
        """Verify metric drop beyond allowable threshold (> 0.03) triggers regression gate."""
        req = EvaluationRunRequest(
            run_id="RUN-CANDIDATE-EXCESSIVE-DROP",
            benchmark_suite_id="SUITE-M9-REGRESSION",
            target_checkpoint_id="CHK-CANDIDATE-v0.9.0-BETA2",
            baseline_checkpoint_id="CHK-RELEASE-v0.8.0",
        )
        # Drop nli_accuracy by 0.05 (0.940 -> 0.890), exceeding allowable drop 0.03
        candidate_metrics = {
            "nli_accuracy": 0.890,
            "contradiction_recall": 0.920,
            "citation_precision": 0.990,
            "gap_novelty_f1": 0.880,
            "peak_vram_gb": 13.50,
        }
        report = configured_runner.run_evaluation(req, custom_metrics=candidate_metrics)
        assert report.pass_fail_status is False
        assert len(report.regressions_detected) == 1
        assert "Regression on 'nli_accuracy'" in report.regressions_detected[0]

    def test_checkpoint_comparison_ceiling_breach_fails(
        self, configured_runner: BenchmarkRunner
    ) -> None:
        """Verify exceeding hardware ceiling (peak VRAM > 15.0 GB) triggers gate failure."""
        req = EvaluationRunRequest(
            run_id="RUN-CANDIDATE-CEILING-BREACH",
            benchmark_suite_id="SUITE-M9-REGRESSION",
            target_checkpoint_id="CHK-CANDIDATE-v0.9.0-OOM-RISK",
            baseline_checkpoint_id="CHK-RELEASE-v0.8.0",
        )
        candidate_metrics = {
            "nli_accuracy": 0.960,
            "contradiction_recall": 0.940,
            "citation_precision": 0.990,
            "gap_novelty_f1": 0.900,
            "peak_vram_gb": 15.40,  # Exceeds 15.0 GB maximum allowable ceiling
        }
        report = configured_runner.run_evaluation(req, custom_metrics=candidate_metrics)
        assert report.pass_fail_status is False
        assert any("Ceiling breach on 'peak_vram_gb'" in r for r in report.regressions_detected)

    def test_checkpoint_comparison_floor_breach_fails(
        self, configured_runner: BenchmarkRunner
    ) -> None:
        """Verify metric falling below absolute floor fails even without baseline comparison."""
        req = EvaluationRunRequest(
            run_id="RUN-CANDIDATE-FLOOR-BREACH",
            benchmark_suite_id="SUITE-M9-REGRESSION",
            target_checkpoint_id="CHK-CANDIDATE-v0.9.0-LOW-ACC",
        )
        # NLI accuracy floor is 0.88; candidate has 0.84
        candidate_metrics = {
            "nli_accuracy": 0.840,
            "contradiction_recall": 0.910,
            "citation_precision": 0.990,
            "peak_vram_gb": 13.0,
        }
        report = configured_runner.run_evaluation(req, custom_metrics=candidate_metrics)
        assert report.pass_fail_status is False
        assert any("failed minimum threshold" in r for r in report.regressions_detected)


class TestBenchmarkReportSerializationAndPersistence:
    """Integration tests for report JSON serialization, disk round-trip, and schema fidelity."""

    def test_report_json_roundtrip_with_taxonomy_errors(self, tmp_path: Path) -> None:
        """Verify lossless JSON persistence and deserialization of evaluation reports."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-SERIALIZE",
            BenchmarkSuiteType.SCIENTIFIC_EXTRACTION,
            num_items=3,
        )
        runner.register_manifest(manifest)

        # Coordinate anchoring for provenance error test
        coord = EvidenceCoordinate(
            coordinate_id="COORD-PAPER-01#p3s2",
            document_id="DOC-ARXIV-2401.0001",
            document_sha256="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            page_number=3,
            section_identifier="Section 4.1",
            paragraph_index=2,
            sentence_index=1,
            char_start=120,
            char_end=240,
            verbatim_snippet="Results indicate 95% efficacy under condition X.",
            extraction_confidence=0.98,
        )

        tax = runner.get_taxonomy()
        tax.record_exception(
            error_id="ERR-PROV-001",
            exc=ProvenanceViolationError("Missing anchor coordinate in cited finding"),
            source_layer="Layer 5 Provenance",
            severity=ErrorSeverity.HIGH,
            provenance_coordinate=coord,
            remediation_suggestion=(
                "Re-index document coordinates before citation graph generation."
            ),
        )
        tax.record_exception(
            error_id="ERR-EPIST-002",
            exc=EpistemicOverreachError("Causal claim inferred from correlational observation"),
            source_layer="Layer 7 Reasoning",
            severity=ErrorSeverity.CRITICAL,
            remediation_suggestion="Downgrade epistemic status to HYPOTHESIS.",
        )

        def mock_evaluator(item: BenchmarkItem) -> Dict[str, float]:
            if "item_001" in item.item_id:
                raise InvalidNLIInputError(f"Contradiction check failed on {item.item_id}")
            return {"citation_precision": 0.99, "nli_accuracy": 0.93}

        req = EvaluationRunRequest(
            run_id="RUN-SERIALIZE-TEST",
            benchmark_suite_id="SUITE-SERIALIZE",
            target_checkpoint_id="CHK-RELEASE-v0.9.0",
        )
        report = runner.run_evaluation(req, evaluator_fn=mock_evaluator)

        # In-memory JSON serialization round-trip
        json_str = report.to_json(indent=2)
        assert isinstance(json_str, str)
        reconstituted = BenchmarkRunReport.from_json(json_str)

        assert reconstituted.run_id == report.run_id
        assert reconstituted.benchmark_suite_id == report.benchmark_suite_id
        assert reconstituted.target_checkpoint_id == report.target_checkpoint_id
        assert reconstituted.timestamp_iso == report.timestamp_iso
        assert reconstituted.pass_fail_status == report.pass_fail_status
        assert reconstituted.metrics_table == report.metrics_table
        assert reconstituted.regressions_detected == report.regressions_detected
        assert len(reconstituted.errors_cataloged) == len(report.errors_cataloged)

        # File-based disk persistence round-trip
        report_file = str(tmp_path / "benchmark_report.json")
        runner.save_report_json(report, report_file)
        loaded_report = runner.load_report_json(report_file)

        assert loaded_report.run_id == report.run_id
        assert loaded_report.pass_fail_status == report.pass_fail_status
        assert loaded_report.metrics_table["nli_accuracy"] == report.metrics_table["nli_accuracy"]

        # Verify taxonomy errors and nested provenance coordinate reconstitution
        tax_errors = tax.get_catalog()
        prov_err = next(e for e in tax_errors if e.error_id == "ERR-PROV-001")
        assert prov_err.category == ScientificErrorCategory.PROVENANCE_FAILURE
        assert prov_err.provenance_coordinate is not None
        assert prov_err.provenance_coordinate.coordinate_id == "COORD-PAPER-01#p3s2"
        assert prov_err.provenance_coordinate.page_number == 3

        # Test dictionary serialization of tax errors
        err_dict = prov_err.to_dict()
        err_reconstituted = prov_err.from_dict(err_dict)
        assert err_reconstituted.error_id == prov_err.error_id
        assert err_reconstituted.provenance_coordinate is not None
        assert (
            err_reconstituted.provenance_coordinate.coordinate_id
            == prov_err.provenance_coordinate.coordinate_id
        )

    def test_schema_serialization_roundtrip_all_components(self) -> None:
        """Verify dictionary serialization round-trip for thresholds, baselines, and requests."""
        # RegressionThreshold
        threshold = RegressionThreshold(
            metric_name="gap_novelty_f1",
            minimum_acceptable_value=0.85,
            maximum_allowable_drop=0.025,
            is_hard_gate=True,
        )
        t_dict = threshold.to_dict()
        t_recon = RegressionThreshold.from_dict(t_dict)
        assert t_recon.metric_name == threshold.metric_name
        assert t_recon.minimum_acceptable_value == threshold.minimum_acceptable_value
        assert t_recon.maximum_allowable_drop == threshold.maximum_allowable_drop

        # BenchmarkBaseline
        baseline = BenchmarkBaseline(
            baseline_id="BASE-TEST",
            checkpoint_id="CHK-TEST-001",
            metrics={"m1": 0.95, "m2": 0.88},
            timestamp_iso="2026-10-15T12:00:00Z",
        )
        b_dict = baseline.to_dict()
        b_recon = BenchmarkBaseline.from_dict(b_dict)
        assert b_recon.baseline_id == baseline.baseline_id
        assert b_recon.metrics == baseline.metrics

        # EvaluationRunRequest
        req = EvaluationRunRequest(
            run_id="REQ-TEST",
            benchmark_suite_id="SUITE-TEST",
            target_checkpoint_id="CHK-TARGET",
            baseline_checkpoint_id="CHK-BASE",
            dry_run=True,
        )
        r_dict = req.to_dict()
        r_recon = EvaluationRunRequest.from_dict(r_dict)
        assert r_recon.run_id == req.run_id
        assert r_recon.dry_run is True


class TestConcurrentBenchmarkRunsAndDiagnostics:
    """Integration tests for concurrent execution safety and diagnostic error taxons."""

    def test_concurrent_evaluation_runs_thread_safety(self) -> None:
        """Verify thread-safe execution across concurrent evaluation requests."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-CONCURRENT",
            BenchmarkSuiteType.NLI_CONTRADICTION,
            num_items=5,
        )
        runner.register_manifest(manifest)

        def run_single_eval(worker_id: int) -> BenchmarkRunReport:
            req = EvaluationRunRequest(
                run_id=f"RUN-CONCURRENT-{worker_id:03d}",
                benchmark_suite_id="SUITE-CONCURRENT",
                target_checkpoint_id=f"CHK-WORKER-{worker_id:03d}",
            )
            metrics = {
                "nli_accuracy": 0.90 + (worker_id * 0.005),
                "contradiction_recall": 0.91,
                "citation_precision": 0.99,
                "peak_vram_gb": 13.0 + (worker_id * 0.1),
            }
            return runner.run_evaluation(req, custom_metrics=metrics)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(run_single_eval, i) for i in range(10)]
            reports = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(reports) == 10
        assert len(runner.get_run_history()) == 10
        assert all(r.pass_fail_status is True for r in reports)

    def test_error_taxonomy_diagnostic_summary_and_critical_detection(self) -> None:
        """Verify diagnostic cataloging, breakdown by layer, and critical error detection."""
        tax = ScientificErrorTaxonomy()

        # Catalog errors across multiple layers
        tax.record_exception(
            error_id="ERR-1",
            exc=ProvenanceViolationError("Unanchored claim"),
            source_layer="Layer 5 Graph",
            severity=ErrorSeverity.HIGH,
        )
        tax.record_exception(
            error_id="ERR-2",
            exc=EpistemicOverreachError("Unwarranted deduction"),
            source_layer="Layer 7 Reasoning",
            severity=ErrorSeverity.MEDIUM,
        )
        tax.record_exception(
            error_id="ERR-3",
            exc=InvalidNLIInputError("Malformed syntax"),
            source_layer="Layer 7 Reasoning",
            severity=ErrorSeverity.CRITICAL,
        )

        assert tax.has_critical_errors() is True
        catalog = tax.get_catalog()
        assert len(catalog) == 3

        dist = tax.get_category_distribution()
        assert dist[ScientificErrorCategory.PROVENANCE_FAILURE.value] == 1
        assert dist[ScientificErrorCategory.EPISTEMIC_FAILURE.value] == 1
        assert dist[ScientificErrorCategory.REASONING_FAILURE.value] == 1
        assert dist[ScientificErrorCategory.SYSTEM_FAILURE.value] == 0
