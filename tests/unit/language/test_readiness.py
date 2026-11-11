"""Formal qualification tests using existing JSON-shaped data only; no model execution."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from language.evaluation.readiness import assess_readiness

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "configs/evaluation/foundation.yaml"


@pytest.fixture
def config():
    return yaml.safe_load(CONFIG.read_text())


@pytest.fixture
def measured(config):
    rows = {}
    for gate in config["gates"]:
        row = rows.setdefault(
            (gate["dataset"], gate["language"]),
            {
                "dataset": gate["dataset"],
                "language": gate["language"],
                "samples": 200,
                "metrics": {},
                "metric_protocols": {},
                "baseline": {},
            },
        )
        row["metrics"][gate["metric"]] = gate["threshold"]
        if gate.get("protocol"):
            row["metric_protocols"][gate["metric"]] = gate["protocol"]
        if gate.get("must_beat_baseline"):
            row["baseline"][gate["metric"]] = 0.5
    return {
        "split": "test",
        "passed": False,
        "model_sha256": "a" * 64,
        "tokenizer_sha256": "b" * 64,
        "dataset_manifest_sha256": "c" * 64,
        "split_isolation_checked": True,
        "datasets": list(rows.values()),
    }


def test_complete_evidence_qualifies_independent_of_baseline_flag(measured, config):
    assert assess_readiness([measured], config)["qualified"]


@pytest.mark.parametrize(
    "defect",
    [
        "val",
        "train",
        "missing_metric",
        "nan",
        "infinity",
        "bool",
        "low_nli",
        "high_fertility",
        "qa_protocol",
        "duplicate",
        "empty_samples",
        "no_baseline",
        "equal_baseline",
        "missing_digest",
        "no_isolation",
        "score_out_of_range",
        "negative_fertility",
        "fractional_samples",
        "negative_baseline",
    ],
)
def test_baseline_pass_cannot_hide_missing_or_incompatible_evidence(measured, config, defect):
    measured["passed"] = True
    if defect in {"val", "train"}:
        measured["split"] = defect
    elif defect in {"missing_metric", "nan", "infinity", "bool", "low_nli"}:
        value = {"nan": float("nan"), "infinity": float("inf"), "bool": True, "low_nli": 0.404}.get(
            defect
        )
        measured["datasets"][0]["metrics"]["macro_f1"] = value
    elif defect == "high_fertility":
        next(r for r in measured["datasets"] if r["dataset"] == "unseen_text")["metrics"][
            "fertility"
        ] = 1.5
    elif defect == "qa_protocol":
        next(r for r in measured["datasets"] if r["dataset"] == "squad")["metric_protocols"][
            "f1"
        ] = "token_span"
    elif defect == "duplicate":
        measured["datasets"].append(copy.deepcopy(measured["datasets"][0]))
    elif defect == "empty_samples":
        measured["datasets"][0]["samples"] = 0
    elif defect in {"no_baseline", "equal_baseline"}:
        row = next(r for r in measured["datasets"] if r["dataset"] == "stem_retrieval")
        row["baseline"] = {} if defect == "no_baseline" else {"mrr": row["metrics"]["mrr"]}
    elif defect == "missing_digest":
        measured.pop("dataset_manifest_sha256")
    elif defect == "no_isolation":
        measured.pop("split_isolation_checked")
    elif defect == "score_out_of_range":
        measured["datasets"][0]["metrics"]["macro_f1"] = 1.2
    elif defect == "negative_fertility":
        next(r for r in measured["datasets"] if r["dataset"] == "unseen_text")["metrics"][
            "fertility"
        ] = -0.1
    elif defect == "fractional_samples":
        measured["datasets"][0]["samples"] = 0.5
    elif defect == "negative_baseline":
        next(r for r in measured["datasets"] if r["dataset"] == "stem_retrieval")["baseline"][
            "mrr"
        ] = -1.0
    result = assess_readiness([measured], config)
    assert not result["qualified"]
    assert result["training_executed"] is False and result["model_executed"] is False


def test_reports_from_different_checkpoints_cannot_be_combined(measured, config):
    other = copy.deepcopy(measured)
    other.update(model_sha256="d" * 64, datasets=[])
    result = assess_readiness([measured, other], config)
    assert not result["qualified"]
    assert any("different model" in issue for issue in result["evidence_issues"])


def test_partial_gate_config_cannot_certify(measured, config):
    config["gates"].pop()
    with pytest.raises(ValueError, match="twelve"):
        assess_readiness([measured], config)


def test_historical_validation_report_is_not_qualified(config):
    data = json.loads((ROOT / "reports/language_encoder/compact-1024-04-best-val.json").read_text())
    result = assess_readiness([data], config)
    assert not result["qualified"]
    assert next(g for g in result["gates"] if g["id"] == "G01")["status"] == "FAIL"
    assert next(g for g in result["gates"] if g["id"] == "G04")["status"] == "MISSING"
    assert next(g for g in result["gates"] if g["id"] == "G07")["status"] == "UNVERIFIED"


def test_gate_config_matches_normative_table(config):
    text = (ROOT / "docs/specifications/LANGUAGE_ENCODER_TRAINING_SPECIFICATION.md").read_text()
    for gate in config["gates"]:
        line = next(line for line in text.splitlines() if line.startswith(f"| {gate['id']} |"))
        assert str(gate["threshold"]) in line
        for field in ("dataset", "language", "metric"):
            assert f"| {gate[field]} |" in line


def test_qa_report_protocol_does_not_claim_answer_text():
    from language.evaluation.evaluator import (
        DatasetResult,
        EvaluationReport,
        report_to_dict,
    )

    report = EvaluationReport(
        "test",
        results=[
            DatasetResult("qa", "squad", "en", 10, {"f1": 0.9, "exact_match": 0.8}, {"f1": 0.0})
        ],
    )
    body = report_to_dict(report)
    assert body["datasets"][0]["metric_protocols"]["f1"] == "token_span"


def test_paraphrase_macro_f1_is_not_positive_class_f1():
    from types import SimpleNamespace

    import torch

    from language.evaluation.evaluator import LanguageEncoderEvaluator

    # Fixed CPU predictions, without constructing a model or invoking optimization.
    evaluator = object.__new__(LanguageEncoderEvaluator)
    batch = SimpleNamespace(labels={"para_labels": torch.tensor([1, 0, 0, 0])})
    evaluator._batches = lambda *args: [(batch, 4)]
    evaluator._forward = lambda *args: {"paraphrase_prob": torch.tensor([[0.8]] * 4)}
    metrics, _ = evaluator._score_paraphrase([], [], 4)
    assert metrics["f1"] == pytest.approx(0.4)
    assert metrics["macro_f1"] == pytest.approx(0.2)
