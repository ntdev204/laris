"""Unit tests for Stripped-Heading Evaluation Benchmark and False-Positive Suite.

Module ID: MOD-SCINLP-002 (Boundary D: Scientific Language Intelligence)
Subtask: M4-SCINLP-002-SUB-02 (Issue #89)
Parent Task: #25
Tests:
- Stripped-heading benchmark evaluation verifying recall >= 80% across multiple scientific domains
- Zero false-positive distractor filtering for corporate, legal, prior-work, and conversational text
- Detection and epistemic uncertainty calibration for subtle scientific caveats
- Domain-specific breakdown (CS, biomedicine, physics)
- Benchmark report formatting in Markdown and JSON
- Edge cases and error handling
"""

import json

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.scientific import (
    HeadingIndependentLimitationDetector,
    LimitationCategory,
    StrippedHeadingBenchmark,
    StrippedHeadingBenchmarkReport,
    StrippedHeadingBenchmarkSample,
    get_default_synthetic_benchmark_corpus,
)


def test_default_corpus_structure():
    """Verify that default synthetic benchmark corpus covers key scientific domains and controls."""
    corpus = get_default_synthetic_benchmark_corpus()
    assert len(corpus) >= 6

    domains = {sample.domain for sample in corpus}
    assert "computer_science" in domains
    assert "biomedicine" in domains
    assert "physics" in domains
    assert "distractor_control" in domains

    for sample in corpus:
        assert isinstance(sample, StrippedHeadingBenchmarkSample)
        assert sample.sample_id
        assert sample.text_with_headings
        if sample.is_negative_control:
            assert len(sample.ground_truth_limitations) == 0
            assert len(sample.ground_truth_assumptions) == 0
            assert len(sample.ground_truth_negative_findings) == 0
        else:
            assert len(sample.all_ground_truth()) > 0


def test_benchmark_execution_and_gate_passage():
    """Verify that benchmark run passes M4-SCINLP-002 gate (Recall >= 80%, Distractor FP == 0)."""
    benchmark = StrippedHeadingBenchmark()
    report = benchmark.run_benchmark()

    assert isinstance(report, StrippedHeadingBenchmarkReport)
    assert report.total_samples >= 6
    assert report.gate_passed is True

    # Check overall metrics
    overall = report.overall_metrics
    assert overall.recall >= 0.80, f"Expected recall >= 0.80, got {overall.recall:.4f}"
    assert overall.precision >= 0.80, f"Expected precision >= 0.80, got {overall.precision:.4f}"
    assert overall.f1_score >= 0.80, f"Expected F1 >= 0.80, got {overall.f1_score:.4f}"
    assert overall.false_positive_rate == 0.0

    # Distractor control must have 0 false positives
    distractor_metrics = report.domain_metrics.get("distractor_control")
    assert distractor_metrics is not None
    assert distractor_metrics.false_positives == 0

    # Epistemic uncertainty distribution coverage
    unc = overall.uncertainty_distribution
    assert unc.get("low", 0) > 0
    assert unc.get("medium", 0) > 0
    assert unc.get("high", 0) > 0


def test_false_positive_distractor_filtering():
    """Verify that false-positive distractors produce zero extractions."""
    detector = HeadingIndependentLimitationDetector()

    # 1. Corporate & Legal text
    legal_text = (
        "Acme BioTech Ltd. and Neural Systems LLC are registered companies. "
        "The authors assume no responsibility or liability for damage. "
        "We disclaim all warranties regarding software stability. "
        "Our engine operates without limitation and has no weaknesses."
    )
    res_legal = detector.detect(legal_text, "doc-legal")
    assert len(res_legal.limitations) == 0
    assert len(res_legal.assumptions) == 0
    assert len(res_legal.negative_findings) == 0

    # 2. Prior work attribution
    prior_work_text = (
        "Prior works suffered from severe computational overhead. "
        "Existing methods exhibit poor generalization on noisy inputs. "
        "Earlier studies were restricted to English texts. "
        "Previous approaches failed to outperform simple heuristics. "
        "Traditional models assumed that features were linear. "
        "Unlike prior works that were limited to 2D topological graphs, "
        "our work models 3D geometries."
    )
    res_prior = detector.detect(prior_work_text, "doc-prior")
    assert len(res_prior.limitations) == 0
    assert len(res_prior.assumptions) == 0
    assert len(res_prior.negative_findings) == 0

    # 3. Conversational / Didactic reader assumptions and denials
    conv_text = (
        "We assume the reader is familiar with differential geometry. "
        "We do not assume that variables are independent across time. "
        "There is no reason to assume that gradient descent diverges. "
        "We did not observe any degradation in accuracy across epochs."
    )
    res_conv = detector.detect(conv_text, "doc-conv")
    assert len(res_conv.limitations) == 0
    assert len(res_conv.assumptions) == 0
    assert len(res_conv.negative_findings) == 0


def test_subtle_scientific_caveats():
    """Verify that subtle scientific caveats are correctly extracted and categorized."""
    detector = HeadingIndependentLimitationDetector()

    # Subtle scope restriction caveat
    text_scope = (
        "Although promising, our evaluation is restricted to 2D topological graphs "
        "and does not consider 3D folds."
    )
    res_scope = detector.detect(text_scope, "doc-scope")
    assert len(res_scope.limitations) == 1
    assert res_scope.limitations[0].category == LimitationCategory.SCOPE_RESTRICTION.value

    # Subtle data sparsity caveat
    text_data = (
        "Our empirical evaluation was restricted to English monolingual corpora "
        "due to lack of labeled data."
    )
    res_data = detector.detect(text_data, "doc-data")
    assert len(res_data.limitations) == 1
    assert res_data.limitations[0].category == LimitationCategory.DATA_SPARSITY.value

    # Subtle computational caveat
    text_comp = (
        "A potential caveat of our approach is that computational overhead scales quadratically "
        "with sequence length."
    )
    res_comp = detector.detect(text_comp, "doc-comp")
    assert len(res_comp.limitations) == 1
    assert res_comp.limitations[0].category == LimitationCategory.COMPUTATIONAL_RESOURCE.value

    # Subtle generalization caveat with hedges
    text_gen = (
        "Our model struggles with out-of-domain failure and poor generalization "
        "when exposed to severe distribution shift."
    )
    res_gen = detector.detect(text_gen, "doc-gen")
    assert len(res_gen.limitations) == 1
    assert res_gen.limitations[0].category == LimitationCategory.GENERALIZATION_BOUND.value

    # Subtle negative finding
    text_neg = (
        "We observed that our method yielded comparable or inferior results "
        "on noisy synthetic sequences."
    )
    res_neg = detector.detect(text_neg, "doc-neg")
    assert len(res_neg.negative_findings) == 1
    assert res_neg.negative_findings[0].is_null_result is True


def test_domain_breakdown_metrics():
    """Verify per-domain metrics calculation in the benchmark report."""
    benchmark = StrippedHeadingBenchmark()
    report = benchmark.run_benchmark()

    cs_metrics = report.domain_metrics.get("computer_science")
    assert cs_metrics is not None
    assert cs_metrics.recall >= 0.80
    assert cs_metrics.precision >= 0.80

    bio_metrics = report.domain_metrics.get("biomedicine")
    assert bio_metrics is not None
    assert bio_metrics.recall >= 0.80
    assert bio_metrics.precision >= 0.80

    phys_metrics = report.domain_metrics.get("physics")
    assert phys_metrics is not None
    assert phys_metrics.recall >= 0.80
    assert phys_metrics.precision >= 0.80


def test_report_formatting_markdown_and_json():
    """Verify Markdown and JSON export capabilities of the benchmark report."""
    benchmark = StrippedHeadingBenchmark()
    report = benchmark.run_benchmark()

    # Markdown export
    md = report.format_markdown_report()
    assert "# Stripped-Heading Limitation & Assumption Evaluation Report" in md
    assert "Overall Benchmark Metrics" in md
    assert "Epistemic Uncertainty Distribution" in md
    assert "Domain Breakdown" in md
    assert "PASSED" in md

    # JSON export
    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert parsed["gate_passed"] is True
    assert parsed["overall_metrics"]["recall"] >= 0.80
    assert "domain_metrics" in parsed
    assert "distractor_control" in parsed["domain_metrics"]


def test_benchmark_empty_corpus_rejection():
    """Verify rejection when running benchmark on an empty corpus."""
    benchmark = StrippedHeadingBenchmark()
    with pytest.raises(ModuleContractViolationError, match="Benchmark corpus cannot be empty"):
        benchmark.run_benchmark(samples=[])


def test_single_sample_evaluation():
    """Verify direct single-sample evaluation helper method."""
    benchmark = StrippedHeadingBenchmark()
    corpus = get_default_synthetic_benchmark_corpus()
    sample = corpus[0]

    result, metrics = benchmark.evaluate_sample(sample)
    assert result.document_id == sample.sample_id
    assert metrics.recall >= 0.80
    assert metrics.domain == "computer_science"


def test_detector_false_positive_helpers_directly():
    """Verify direct boolean output from detector false positive filter helpers."""
    detector = HeadingIndependentLimitationDetector()

    # Limitation false positive helper
    assert detector.is_false_positive_limitation("Prior works suffered from high latency.") is True
    assert detector.is_false_positive_limitation("The algorithm never fails.") is True
    assert detector.is_false_positive_limitation("DeepMind Technologies Ltd. operates.") is True
    assert detector.is_false_positive_limitation("Our approach is limited to 2D graphs.") is False

    # Assumption false positive helper
    assert (
        detector.is_false_positive_assumption("We assume no liability for third-party tools.")
        is True
    )
    assert detector.is_false_positive_assumption("We do not assume that variables are iid.") is True
    assert (
        detector.is_false_positive_assumption("We assume that token embeddings are normalized.")
        is False
    )

    # Negative finding false positive helper
    assert (
        detector.is_false_positive_negative_finding(
            "We did not observe any degradation in accuracy."
        )
        is True
    )
    assert (
        detector.is_false_positive_negative_finding(
            "No statistically significant improvement was detected."
        )
        is False
    )
