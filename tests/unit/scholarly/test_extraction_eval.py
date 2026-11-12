import json
from pathlib import Path

from laris.research.evaluation.extraction import (
    baseline_from,
    dumps,
    evaluate,
    extract_spans,
    gate,
    load_annotations,
    match,
)

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "extraction"
DOCS = load_annotations(FIX / "annotations.json")
BASELINE = json.loads((FIX / "baseline.json").read_text())


def test_matching_counts_on_a_known_case():
    gold = [("method", 0, 6), ("method", 10, 15), ("claim", 20, 60)]
    pred = [("method", 0, 6), ("method", 40, 45), ("claim", 22, 58), ("dataset", 0, 4)]
    c = match(pred, gold)
    assert c["method"] == {"tp": 1, "fp": 1, "fn": 1}
    assert c["claim"] == {"tp": 1, "fp": 0, "fn": 0}
    assert c["dataset"] == {"tp": 0, "fp": 1, "fn": 0}


def test_report_is_reproducible_and_matches_the_stored_baseline():
    first, second = evaluate(DOCS), evaluate(DOCS)
    assert dumps(first) == dumps(second)
    print("macro F1", first["macro_f1"], {k: v["f1"] for k, v in first["per_type"].items()})
    assert first["micro"]["precision"] >= 0.95  # nothing invented on the fixture
    assert gate(first, BASELINE) == []
    assert baseline_from(first) == BASELINE


def test_a_regression_fails_the_gate():
    def degraded(text):  # an extractor that lost its method detector
        return [s for s in extract_spans(text) if s[0] != "method"]

    worse = evaluate(DOCS, degraded)
    problems = gate(worse, BASELINE)
    assert any(p.startswith("method:") for p in problems) and any("macro" in p for p in problems)

    def noisy(text):  # an extractor that invents entities
        return extract_spans(text) + [("claim", 0, 5)]

    assert (
        gate(evaluate(DOCS, noisy), BASELINE) != []
        or evaluate(DOCS, noisy)["micro"]["precision"] < evaluate(DOCS)["micro"]["precision"]
    )


def test_no_entities_text_yields_no_predictions():
    quiet = next(d for d in DOCS if d["id"] == "no-entities")
    assert extract_spans(quiet["text"]) == [] and quiet["spans"] == []
