"""Unit tests for Layer 10 benchmark runner, regression gates, and error taxonomy.

Tests compliance with DOC-SPEC-MOD-001 (Boundary J), ADR-001, ADR-007, ADR-008, and Issue #71:
- Data contract validation for benchmark items, manifests, thresholds, baselines, and reports
- Cryptographic SHA-256 manifest and item integrity verification
- Strict evaluation isolation rejecting training data contamination
- Automated scientific error taxonomy mapping across core failure categories
- Regression gate enforcement against floor thresholds, ceiling constraints, and baselines
- Custom evaluator callback execution and exception diagnostic cataloging
"""

from __future__ import annotations

import pytest

from laris.core.errors import (
    BenchmarkContaminationError,
    CycleDetectedError,
    EpistemicOverreachError,
    ExtractionConfidenceBelowThresholdError,
    GraphIntegrityError,
    HardwareBudgetExceededError,
    InferredEdgeConflationError,
    InvalidNLIInputError,
    MalformedDiscourseSpanError,
    ModuleContractViolationError,
    ProvenanceViolationError,
    TaskRoutingError,
    UncertaintyCeilingExceededError,
    WeightStagingError,
)
from laris.core.schemas import EvidenceCoordinate
from laris.evaluation.benchmark_runner import (
    BenchmarkRunner,
)
from laris.evaluation.error_taxonomy import (
    ScientificErrorTaxonomy,
)
from laris.evaluation.schemas import (
    BenchmarkBaseline,
    BenchmarkItem,
    BenchmarkRunReport,
    BenchmarkSuiteType,
    ErrorSeverity,
    EvaluationRunRequest,
    FrozenBenchmarkManifest,
    RegressionThreshold,
    ScientificErrorCategory,
    ScientificErrorRecord,
)


class TestBenchmarkSchemasAndContracts:
    """Tests schema contracts, invariants, and cryptographic hashing."""

    def test_valid_scientific_error_record(self) -> None:
        """Test valid ScientificErrorRecord instantiation."""
        coord = EvidenceCoordinate(
            coordinate_id="COORD-001",
            document_id="DOC-001",
            document_sha256="abc123sha256",
            page_number=2,
            section_identifier="sec_methods",
            paragraph_index=1,
            sentence_index=3,
            char_start=10,
            char_end=50,
            verbatim_snippet="sample snippet",
        )
        rec = ScientificErrorRecord(
            error_id="ERR-001",
            category=ScientificErrorCategory.PROVENANCE_FAILURE,
            severity=ErrorSeverity.HIGH,
            source_layer="Layer 6 Retrieval",
            description="Missing coordinate offset.",
            timestamp_iso="2026-10-16T00:00:00Z",
            provenance_coordinate=coord,
            remediation_suggestion="Verify sentence boundaries.",
        )
        assert rec.error_id == "ERR-001"
        assert rec.category == ScientificErrorCategory.PROVENANCE_FAILURE
        assert rec.severity == ErrorSeverity.HIGH

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "error_id": "",
                    "category": ScientificErrorCategory.PROVENANCE_FAILURE,
                    "severity": ErrorSeverity.HIGH,
                    "source_layer": "Layer 6",
                    "description": "desc",
                    "timestamp_iso": "2026-10-16T00:00:00Z",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "error_id": "E1",
                    "category": ScientificErrorCategory.PROVENANCE_FAILURE,
                    "severity": ErrorSeverity.HIGH,
                    "source_layer": "   ",
                    "description": "desc",
                    "timestamp_iso": "2026-10-16T00:00:00Z",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "error_id": "E1",
                    "category": ScientificErrorCategory.PROVENANCE_FAILURE,
                    "severity": ErrorSeverity.HIGH,
                    "source_layer": "Layer 6",
                    "description": "",
                    "timestamp_iso": "2026-10-16T00:00:00Z",
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "error_id": "E1",
                    "category": ScientificErrorCategory.PROVENANCE_FAILURE,
                    "severity": ErrorSeverity.HIGH,
                    "source_layer": "Layer 6",
                    "description": "desc",
                    "timestamp_iso": "",
                },
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_scientific_error_record(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of malformed ScientificErrorRecord fields."""
        with pytest.raises(expected_err):
            ScientificErrorRecord(**kwargs)

    def test_valid_benchmark_item(self) -> None:
        """Test valid BenchmarkItem and auto-computed SHA-256 hash."""
        item = BenchmarkItem(
            item_id="item_001",
            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
            input_payload={"premise": "A", "hypothesis": "B"},
            expected_output={"label": "CONTRADICTION"},
        )
        assert item.item_id == "item_001"
        assert len(item.checksum_sha256) == 64
        assert item.is_frozen is True

    def test_benchmark_item_training_contamination_rejected(self) -> None:
        """Verify BenchmarkItem raises BenchmarkContaminationError if marked as training sample."""
        with pytest.raises(BenchmarkContaminationError, match="training sample"):
            BenchmarkItem(
                item_id="item_contaminated",
                suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                input_payload={"premise": "A", "hypothesis": "B"},
                expected_output={"label": "CONTRADICTION"},
                is_training_sample=True,
            )

    def test_benchmark_item_checksum_mismatch_rejected(self) -> None:
        """Verify BenchmarkItem rejects tampered or mismatched checksum."""
        with pytest.raises(ModuleContractViolationError, match="Checksum mismatch"):
            BenchmarkItem(
                item_id="item_tampered",
                suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                input_payload={"premise": "A", "hypothesis": "B"},
                expected_output={"label": "CONTRADICTION"},
                checksum_sha256="bad_checksum_12345",
            )

    def test_valid_frozen_benchmark_manifest(self) -> None:
        """Test valid FrozenBenchmarkManifest and auto-computed manifest checksum."""
        item1 = BenchmarkItem(
            item_id="i1",
            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
            input_payload={"p": 1},
            expected_output={"o": 1},
        )
        item2 = BenchmarkItem(
            item_id="i2",
            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
            input_payload={"p": 2},
            expected_output={"o": 2},
        )
        manifest = FrozenBenchmarkManifest(
            manifest_id="MAN-001",
            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
            version="1.0.0",
            created_at_iso="2026-10-16T00:00:00Z",
            items=[item1, item2],
        )
        assert manifest.manifest_id == "MAN-001"
        assert len(manifest.manifest_checksum_sha256) == 64

    @pytest.mark.parametrize(
        ("kwargs", "expected_err"),
        [
            (
                {
                    "manifest_id": "",
                    "suite_type": BenchmarkSuiteType.NLI_CONTRADICTION,
                    "version": "1.0.0",
                    "created_at_iso": "2026-10-16",
                    "items": [
                        BenchmarkItem(
                            item_id="i",
                            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                            input_payload={},
                            expected_output={},
                        )
                    ],
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "manifest_id": "M1",
                    "suite_type": BenchmarkSuiteType.NLI_CONTRADICTION,
                    "version": "",
                    "created_at_iso": "2026-10-16",
                    "items": [
                        BenchmarkItem(
                            item_id="i",
                            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                            input_payload={},
                            expected_output={},
                        )
                    ],
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "manifest_id": "M1",
                    "suite_type": BenchmarkSuiteType.NLI_CONTRADICTION,
                    "version": "1.0.0",
                    "created_at_iso": "",
                    "items": [
                        BenchmarkItem(
                            item_id="i",
                            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                            input_payload={},
                            expected_output={},
                        )
                    ],
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "manifest_id": "M1",
                    "suite_type": BenchmarkSuiteType.NLI_CONTRADICTION,
                    "version": "1.0.0",
                    "created_at_iso": "2026-10-16",
                    "items": [],
                },
                ModuleContractViolationError,
            ),
            (
                {
                    "manifest_id": "M1",
                    "suite_type": BenchmarkSuiteType.NLI_CONTRADICTION,
                    "version": "1.0.0",
                    "created_at_iso": "2026-10-16",
                    "items": [
                        BenchmarkItem(
                            item_id="i",
                            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
                            input_payload={},
                            expected_output={},
                        )
                    ],
                    "manifest_checksum_sha256": "bad_manifest_hash",
                },
                ModuleContractViolationError,
            ),
        ],
    )
    def test_invalid_frozen_benchmark_manifest(self, kwargs: dict, expected_err: type) -> None:
        """Test rejection of malformed FrozenBenchmarkManifest fields."""
        with pytest.raises(expected_err):
            FrozenBenchmarkManifest(**kwargs)

    def test_regression_threshold_contract(self) -> None:
        """Test RegressionThreshold invariants."""
        thresh = RegressionThreshold(
            metric_name="nli_accuracy",
            minimum_acceptable_value=0.90,
            maximum_allowable_drop=0.02,
        )
        assert thresh.metric_name == "nli_accuracy"
        assert thresh.minimum_acceptable_value == 0.90

        with pytest.raises(ModuleContractViolationError):
            RegressionThreshold(metric_name="", minimum_acceptable_value=0.5)

        with pytest.raises(ModuleContractViolationError):
            RegressionThreshold(
                metric_name="acc", minimum_acceptable_value=0.5, maximum_allowable_drop=-0.1
            )

    def test_benchmark_baseline_contract(self) -> None:
        """Test BenchmarkBaseline parameter validation."""
        base = BenchmarkBaseline(
            baseline_id="BASE-001",
            checkpoint_id="CHK-M8",
            metrics={"acc": 0.95},
            timestamp_iso="2026-10-16T00:00:00Z",
        )
        assert base.baseline_id == "BASE-001"

        with pytest.raises(ModuleContractViolationError):
            BenchmarkBaseline(
                baseline_id="",
                checkpoint_id="CHK",
                metrics={},
                timestamp_iso="2026-10-16",
            )
        with pytest.raises(ModuleContractViolationError):
            BenchmarkBaseline(
                baseline_id="B1",
                checkpoint_id="",
                metrics={},
                timestamp_iso="2026-10-16",
            )
        with pytest.raises(ModuleContractViolationError):
            BenchmarkBaseline(
                baseline_id="B1",
                checkpoint_id="CHK",
                metrics={},
                timestamp_iso="",
            )

    def test_evaluation_run_request_and_report_contracts(self) -> None:
        """Test EvaluationRunRequest and BenchmarkRunReport validation."""
        req = EvaluationRunRequest(
            run_id="RUN-01",
            benchmark_suite_id="SUITE-NLI",
            target_checkpoint_id="CHK-TARGET",
        )
        assert req.run_id == "RUN-01"

        with pytest.raises(ModuleContractViolationError):
            EvaluationRunRequest(run_id="", benchmark_suite_id="S", target_checkpoint_id="C")
        with pytest.raises(ModuleContractViolationError):
            EvaluationRunRequest(run_id="R", benchmark_suite_id="", target_checkpoint_id="C")
        with pytest.raises(ModuleContractViolationError):
            EvaluationRunRequest(run_id="R", benchmark_suite_id="S", target_checkpoint_id="")

        rep = BenchmarkRunReport(
            run_id="RUN-01",
            benchmark_suite_id="SUITE-NLI",
            target_checkpoint_id="CHK-TARGET",
            timestamp_iso="2026-10-16T00:00:00Z",
            metrics_table={"acc": 0.92},
            regressions_detected=[],
            errors_cataloged=[],
            pass_fail_status=True,
        )
        assert rep.pass_fail_status is True

        with pytest.raises(ModuleContractViolationError):
            BenchmarkRunReport(
                run_id="",
                benchmark_suite_id="S",
                target_checkpoint_id="C",
                timestamp_iso="2026",
                metrics_table={},
                regressions_detected=[],
                errors_cataloged=[],
                pass_fail_status=True,
            )


class TestScientificErrorTaxonomy:
    """Tests failure taxonomy classification, diagnostics, and cataloging."""

    @pytest.mark.parametrize(
        ("exc", "expected_cat"),
        [
            (ProvenanceViolationError("missing coord"), ScientificErrorCategory.PROVENANCE_FAILURE),
            (EpistemicOverreachError("causal leap"), ScientificErrorCategory.EPISTEMIC_FAILURE),
            (UncertaintyCeilingExceededError("U > 1.0"), ScientificErrorCategory.EPISTEMIC_FAILURE),
            (
                MalformedDiscourseSpanError("bad offsets"),
                ScientificErrorCategory.EXTRACTION_FAILURE,
            ),
            (
                ExtractionConfidenceBelowThresholdError("low conf"),
                ScientificErrorCategory.EXTRACTION_FAILURE,
            ),
            (InvalidNLIInputError("empty premise"), ScientificErrorCategory.REASONING_FAILURE),
            (GraphIntegrityError("bad edge"), ScientificErrorCategory.REASONING_FAILURE),
            (InferredEdgeConflationError("conflated"), ScientificErrorCategory.REASONING_FAILURE),
            (HardwareBudgetExceededError("OOM"), ScientificErrorCategory.SYSTEM_FAILURE),
            (WeightStagingError("load fail"), ScientificErrorCategory.SYSTEM_FAILURE),
            (TaskRoutingError("route fail"), ScientificErrorCategory.SYSTEM_FAILURE),
            (CycleDetectedError("cycle loop"), ScientificErrorCategory.SYSTEM_FAILURE),
            (RuntimeError("generic crash"), ScientificErrorCategory.SYSTEM_FAILURE),
        ],
    )
    def test_exception_taxonomic_classification(
        self, exc: Exception, expected_cat: ScientificErrorCategory
    ) -> None:
        """Verify automatic categorization of core LARIS exceptions into error taxons."""
        tax = ScientificErrorTaxonomy()
        assert tax.classify_exception(exc) == expected_cat

    def test_record_error_and_diagnostics(self) -> None:
        """Verify cataloging errors, querying distribution, and checking critical severity."""
        tax = ScientificErrorTaxonomy()
        assert tax.has_critical_errors() is False

        # Record high severity epistemic failure
        tax.record_exception(
            error_id="ERR-1",
            exc=EpistemicOverreachError("Unjustified causal claim"),
            source_layer="Layer 7 Reasoning",
            severity=ErrorSeverity.HIGH,
        )
        assert len(tax.get_catalog()) == 1
        assert tax.has_critical_errors() is False

        # Record critical severity system failure
        tax.record_exception(
            error_id="ERR-2",
            exc=HardwareBudgetExceededError("VRAM ceiling breached"),
            source_layer="Layer 9 Execution",
            severity=ErrorSeverity.CRITICAL,
        )
        assert len(tax.get_catalog()) == 2
        assert tax.has_critical_errors() is True

        dist = tax.get_category_distribution()
        assert dist[ScientificErrorCategory.EPISTEMIC_FAILURE.value] == 1
        assert dist[ScientificErrorCategory.SYSTEM_FAILURE.value] == 1
        assert dist[ScientificErrorCategory.PROVENANCE_FAILURE.value] == 0

        tax.clear_catalog()
        assert len(tax.get_catalog()) == 0


class TestBenchmarkRunnerExecution:
    """Tests benchmark execution, regression gates, and baseline comparison."""

    def test_default_thresholds_initialized(self) -> None:
        """Verify standard regression thresholds are pre-registered."""
        runner = BenchmarkRunner()
        assert runner.get_threshold("nli_accuracy") is not None
        assert runner.get_threshold("contradiction_recall") is not None
        assert runner.get_threshold("citation_precision") is not None
        assert runner.get_threshold("gap_novelty_f1") is not None
        assert runner.get_threshold("peak_vram_gb") is not None

    def test_synthetic_manifest_creation_and_registration(self) -> None:
        """Test constructing and registering a synthetic benchmark manifest."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            manifest_id="SUITE-SYNTH-NLI",
            suite_type=BenchmarkSuiteType.NLI_CONTRADICTION,
            version="1.0.0",
            num_items=5,
        )
        assert len(manifest.items) == 5
        runner.register_manifest(manifest)
        fetched = runner.get_manifest("SUITE-SYNTH-NLI")
        assert fetched.manifest_id == manifest.manifest_id

    def test_unregistered_manifest_lookup_raises_error(self) -> None:
        """Verify looking up non-existent manifest raises ModuleContractViolationError."""
        runner = BenchmarkRunner()
        with pytest.raises(ModuleContractViolationError, match="not found"):
            runner.get_manifest("UNKNOWN-MANIFEST")

    def test_run_evaluation_default_synthetic_pass(self) -> None:
        """Test benchmark evaluation with compliant synthetic metrics satisfies all gates."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-PASS", BenchmarkSuiteType.NLI_CONTRADICTION
        )
        runner.register_manifest(manifest)

        req = EvaluationRunRequest(
            run_id="RUN-PASS",
            benchmark_suite_id="SUITE-PASS",
            target_checkpoint_id="CHK-2026-10",
        )
        report = runner.run_evaluation(req)
        assert report.pass_fail_status is True
        assert len(report.regressions_detected) == 0
        assert report.is_verified_offline is True
        assert len(runner.get_run_history()) == 1

    def test_run_evaluation_floor_metric_regression_failure(self) -> None:
        """Test that dropping below minimum acceptable threshold fails the run report."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-FAIL", BenchmarkSuiteType.NLI_CONTRADICTION
        )
        runner.register_manifest(manifest)

        req = EvaluationRunRequest(
            run_id="RUN-FAIL",
            benchmark_suite_id="SUITE-FAIL",
            target_checkpoint_id="CHK-POOR",
        )
        # NLI accuracy threshold is 0.88; provide 0.80
        failing_metrics = {
            "nli_accuracy": 0.80,
            "contradiction_recall": 0.90,
            "citation_precision": 0.99,
        }
        report = runner.run_evaluation(req, custom_metrics=failing_metrics)
        assert report.pass_fail_status is False
        assert any("failed minimum threshold" in r for r in report.regressions_detected)

    def test_run_evaluation_ceiling_breach_failure(self) -> None:
        """Test that exceeding a ceiling metric (peak_vram_gb > 15.0) fails the run report."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-VRAM", BenchmarkSuiteType.RESOURCE_EFFICIENCY
        )
        runner.register_manifest(manifest)

        req = EvaluationRunRequest(
            run_id="RUN-VRAM",
            benchmark_suite_id="SUITE-VRAM",
            target_checkpoint_id="CHK-HEAVY",
        )
        # peak_vram_gb ceiling is 15.0; provide 15.8
        failing_metrics = {
            "peak_vram_gb": 15.8,
            "nli_accuracy": 0.95,
        }
        report = runner.run_evaluation(req, custom_metrics=failing_metrics)
        assert report.pass_fail_status is False
        assert any("Ceiling breach on 'peak_vram_gb'" in r for r in report.regressions_detected)

    def test_run_evaluation_baseline_regression_drop_failure(self) -> None:
        """Test regression detection when metric drops beyond allowable drop from baseline."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-BASE-REG", BenchmarkSuiteType.NLI_CONTRADICTION
        )
        runner.register_manifest(manifest)

        # Baseline: accuracy 0.96. Maximum allowable drop is 0.03 -> minimum allowed is 0.93
        baseline = BenchmarkBaseline(
            baseline_id="BASE-M8",
            checkpoint_id="CHK-RELEASE-M8",
            metrics={"nli_accuracy": 0.96},
            timestamp_iso="2026-10-15T00:00:00Z",
        )
        runner.register_baseline(baseline)
        assert runner.get_baseline("CHK-RELEASE-M8") is not None

        req = EvaluationRunRequest(
            run_id="RUN-BASE-DROP",
            benchmark_suite_id="SUITE-BASE-REG",
            target_checkpoint_id="CHK-CANDIDATE",
            baseline_checkpoint_id="CHK-RELEASE-M8",
        )
        # Candidate accuracy is 0.90 (drop of 0.06 > 0.03 allowable drop)
        metrics = {
            "nli_accuracy": 0.90,
            "contradiction_recall": 0.91,
            "citation_precision": 0.99,
        }
        report = runner.run_evaluation(req, custom_metrics=metrics)
        assert report.pass_fail_status is False
        assert any("Regression on 'nli_accuracy'" in r for r in report.regressions_detected)

    def test_run_evaluation_with_evaluator_fn_and_exceptions(self) -> None:
        """Test running evaluation with custom evaluator function capturing item exceptions."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-FN", BenchmarkSuiteType.NLI_CONTRADICTION, num_items=3
        )
        runner.register_manifest(manifest)

        def mock_evaluator(item: BenchmarkItem) -> dict[str, float]:
            if "item_001" in item.item_id:
                raise InvalidNLIInputError(f"Simulated reasoning failure on {item.item_id}")
            return {"nli_accuracy": 0.95, "contradiction_recall": 0.92}

        req = EvaluationRunRequest(
            run_id="RUN-CALLBACK",
            benchmark_suite_id="SUITE-FN",
            target_checkpoint_id="CHK-FN",
        )
        report = runner.run_evaluation(req, evaluator_fn=mock_evaluator)
        assert len(report.errors_cataloged) == 1
        assert report.errors_cataloged[0].category == ScientificErrorCategory.REASONING_FAILURE
        assert "nli_accuracy" in report.metrics_table

    def test_schema_edge_cases_and_manifest_contamination_checks(self) -> None:
        """Test schema validation constraints and manifest contamination detection."""
        # Empty item_id
        with pytest.raises(ModuleContractViolationError, match="item_id cannot be empty"):
            BenchmarkItem(
                item_id="",
                suite_type=BenchmarkSuiteType.SEMANTIC_EQUIVALENCE,
                input_payload={"query": "test"},
                expected_output={"label": "entailment"},
            )

        # Contaminated item bypassed into manifest
        clean_item = BenchmarkItem(
            item_id="CLEAN-001",
            suite_type=BenchmarkSuiteType.SEMANTIC_EQUIVALENCE,
            input_payload={"query": "test"},
            expected_output={"label": "entailment"},
        )
        object.__setattr__(clean_item, "is_training_sample", True)

        with pytest.raises(BenchmarkContaminationError, match="Contamination detected"):
            FrozenBenchmarkManifest(
                manifest_id="CONTAM-MANIFEST",
                suite_type=BenchmarkSuiteType.SEMANTIC_EQUIVALENCE,
                version="1.0.0",
                created_at_iso="2026-10-15T00:00:00Z",
                items=[clean_item],
            )

        # BenchmarkRunReport validation errors
        valid_args = {
            "run_id": "RUN-001",
            "benchmark_suite_id": "SUITE-001",
            "target_checkpoint_id": "CHK-001",
            "timestamp_iso": "2026-10-15T00:00:00Z",
            "metrics_table": {"acc": 0.9},
            "regressions_detected": [],
            "errors_cataloged": [],
            "pass_fail_status": True,
        }

        with pytest.raises(
            ModuleContractViolationError, match="benchmark_suite_id cannot be empty"
        ):
            BenchmarkRunReport(**{**valid_args, "benchmark_suite_id": ""})

        with pytest.raises(
            ModuleContractViolationError, match="target_checkpoint_id cannot be empty"
        ):
            BenchmarkRunReport(**{**valid_args, "target_checkpoint_id": ""})

        with pytest.raises(
            ModuleContractViolationError, match="timestamp_iso cannot be empty"
        ):
            BenchmarkRunReport(**{**valid_args, "timestamp_iso": ""})

    def test_manifest_contamination_in_runner_and_unregistered_metric(self) -> None:
        """Test runner contamination verification and handling of unregistered metrics."""
        runner = BenchmarkRunner()
        manifest = runner.create_synthetic_manifest(
            "SUITE-CLEAN", BenchmarkSuiteType.NLI_CONTRADICTION
        )

        # Tamper item after creation
        object.__setattr__(manifest.items[0], "is_training_sample", True)

        with pytest.raises(BenchmarkContaminationError, match="Refusing to register manifest"):
            runner.register_manifest(manifest)

        # Force register to test run_evaluation contamination guard
        object.__setattr__(manifest.items[0], "is_training_sample", False)
        runner.register_manifest(manifest)
        object.__setattr__(manifest.items[0], "is_training_sample", True)

        req = EvaluationRunRequest(
            run_id="RUN-GUARD",
            benchmark_suite_id="SUITE-CLEAN",
            target_checkpoint_id="CHK-001",
        )
        with pytest.raises(BenchmarkContaminationError, match="Contamination detected in suite"):
            runner.run_evaluation(req)

        # Test evaluation with an unregistered metric and soft gate
        object.__setattr__(manifest.items[0], "is_training_sample", False)
        # Register a soft threshold
        soft_threshold = RegressionThreshold(
            metric_name="soft_metric",
            minimum_acceptable_value=0.80,
            maximum_allowable_drop=0.05,
            is_hard_gate=False,
        )
        runner.register_threshold(soft_threshold)

        custom_metrics = {
            "unregistered_custom_metric": 0.999,
            "soft_metric": 0.70,  # Fails minimum, but is soft gate
            "peak_vram_gb": 13.0,
            "nli_accuracy": 0.95,
        }
        report = runner.run_evaluation(req, custom_metrics=custom_metrics)
        # Should pass because soft_metric is not a hard gate, and other metrics pass
        assert report.pass_fail_status is True
        assert any(
            "Metric 'soft_metric' failed minimum threshold" in r
            for r in report.regressions_detected
        )


