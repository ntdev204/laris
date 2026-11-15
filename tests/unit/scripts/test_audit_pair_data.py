"""Fixture tests of the T193 pair-data audit counters (no model, no tokenizer fit, no training)."""

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SPEC = importlib.util.spec_from_file_location(
    "audit_pair_data", Path(__file__).resolve().parents[3] / "scripts/audit_pair_data.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules["audit_pair_data"] = audit  # dataclasses resolve string annotations through sys.modules
SPEC.loader.exec_module(audit)


def whitespace_encoder() -> "audit.Encoder":
    return audit.Encoder(lambda texts: [t.split() for t in texts])


def test_auc_counts_ties_as_half():
    assert audit.auc([0.1, 0.2, 0.9, 0.8], [0, 0, 1, 1]) == 1.0
    assert audit.auc([0.5, 0.5], [0, 1]) == 0.5
    assert audit.auc([0.9, 0.1], [0, 1]) == 0.0
    assert audit.auc([0.3, 0.4], [1, 1]) is None


def test_spearman_and_ranks():
    assert audit.spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert audit.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert list(audit.average_ranks([5, 5, 1])) == [2.5, 2.5, 1.0]


def test_pair_cut_follows_build_sequence():
    # L = 13: inner 10, first segment at most 5, second gets 10 - kept first.
    cut = audit.pair_cut(np.array([3, 6, 5]), np.array([7, 2, 6]), 13)
    # row 0: a=3 kept, b cap 7 -> no cut; row 1: a cut (6>5); row 2: b cap 5 < 6 -> cut
    assert cut == {
        "first_cut": round(1 / 3, 4),
        "second_cut": round(1 / 3, 4),
        "any_cut": round(2 / 3, 4),
    }


def test_qa_window_matches_loader_rule():
    # L = 13, question 2 tokens: context offset 4, limit min(12, 4 + 8) = 12, last end index 11.
    assert audit.qa_answer_window(q_len=2, prefix_len=6, answer_len=2, seq_len=13)  # ends at 11
    assert not audit.qa_answer_window(q_len=2, prefix_len=7, answer_len=2, seq_len=13)  # ends at 12
    assert not audit.qa_answer_window(q_len=2, prefix_len=0, answer_len=0, seq_len=13)


def test_pair_key_order_and_normalisation():
    assert audit.pair_key("A cat.", "a dog", ordered=False) == audit.pair_key(
        "A dog!", "a CAT", ordered=False
    )
    assert audit.pair_key("A cat.", "a dog", ordered=True) != audit.pair_key(
        "a dog", "A cat.", ordered=True
    )


def test_naive_bayes_and_baselines_learn_a_word_cue():
    train = {
        "s": (
            ["a not b", "c not d", "a b", "c d"],
            ["contradiction", "contradiction", "entailment", "entailment"],
        )
    }
    val = {"s": (["x not y", "x y"], ["contradiction", "entailment"])}
    out = audit.nli_baselines(train, val)
    src = out["per_source"]["s"]
    assert src["hypothesis_only_own"]["accuracy"] == 1.0
    assert src["source_majority"]["accuracy"] == 0.5
    assert out["pooled_val"]["rows"] == 2


def test_negation_cue_and_triplets():
    cue = audit.negation_cue(
        ["He is not here", "He is here", "Nobody came"], ["contradiction", "entailment", "neutral"]
    )
    assert cue["rows_with_negation"] == 2
    assert cue["label_prior_given_negation"]["contradiction"]["rows"] == 1
    trip = audit.nli_triplets(["P", "P", "Q"], ["entailment", "contradiction", "entailment"])
    assert trip == {"distinct_premises": 2, "premises_with_entailment_and_contradiction": 1}


def test_passage_runs_counts_consecutive_pairs():
    runs = audit.PassageRuns()
    for rid in ["d1#0", "d1#1", "d1#3", "d2#0", "d3#0", "d3#1", "plain"]:
        runs.add(rid)
    r = runs.result()
    assert r["passages"] == 7
    assert r["documents"] == 4 and r["documents_contiguous"]
    assert r["documents_with_two_or_more_passages"] == 2
    assert r["consecutive_passage_pairs"] == 2  # d1#0-d1#1 and d3#0-d3#1, not d1#1-d1#3


def test_mlm_text_counts():
    texts = pa.array(["One. Two here. Three!", "No boundary here", "Para one.\n\nPara two."])
    c = audit.mlm_text_counts(texts)
    assert c["passages_with_two_or_more_sentences"] == 2
    assert c["adjacent_sentence_pairs"] == 3
    assert c["passages_with_two_or_more_paragraphs"] == 1


def test_locate_answer():
    assert audit.locate("the cat sat", "cat", 4) == ("offset", 4)
    assert audit.locate("the cat sat", "cat", 0) == ("bad_offset", -1)
    assert audit.locate("the cat sat", "sat", None) == ("found", 8)
    assert audit.locate("the cat sat", "dog", None) == ("not_found", -1)
    assert audit.locate("the cat sat", None, None) == ("none", -1)


def test_overlap_counts_rows_in_held_out():
    status = {"a": "in_mixture", "b": "in_mixture", "c": "candidate"}
    keys = {
        ("a", "train"): np.array([1, 2, 3, 3]),
        ("a", "val"): np.array([3, 9]),
        ("b", "train"): np.array([9, 4]),
        ("b", "test"): np.array([5]),
        ("c", "train"): np.array([5, 1, 7]),
    }
    out = audit.overlap_counts(keys, {}, status)
    assert out["a/train"]["duplicate_rows_within_split"] == 1
    assert out["a/train"]["rows_in_any_held_out_split"] == 2  # both 3s are in a/val
    assert out["b/train"]["rows_in_any_held_out_split"] == 1  # 9 in a/val
    assert out["c/train"]["rows_in_any_held_out_split"] == 1  # 5 in b/test
    assert out["c/train"]["rows_in_other_sources"] == 2  # 5 and 1


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_run_on_fixture_tree(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    monkeypatch.setattr(
        audit,
        "TASK_DATASET_DIRS",
        {
            "mlm": ["m"],
            "nli": ["n"],
            "paraphrase": ["p"],
            "similarity": ["stsb"],
            "qa": ["q"],
        },
    )
    nli = [
        {"premise": "a b c", "hypothesis": "a b", "label": "entailment"},
        {"premise": "a b c", "hypothesis": "not a", "label": "contradiction"},
    ]
    _write(processed / "n/train.parquet", nli)
    _write(processed / "n/val.parquet", nli[:1])
    _write(
        processed / "p/train.parquet",
        [
            {"sentence1": "x y", "sentence2": "x y", "label": "1"},
            {"sentence1": "x y", "sentence2": "z w", "label": "0"},
        ],
    )
    _write(
        processed / "stsb/train.parquet", [{"sentence1": "x y", "sentence2": "x z", "score": "0.5"}]
    )
    _write(
        processed / "stsb/val.parquet", [{"sentence1": "x y", "sentence2": "q r", "score": "0.2"}]
    )
    _write(
        processed / "q/train.parquet",
        [
            {
                "question": "who",
                "context": "the cat sat",
                "answers": {"text": ["cat"], "answer_start": [4]},
            },
            {"question": "what", "context": "nothing", "answers": {"text": [], "answer_start": []}},
        ],
    )
    _write(
        processed / "m/train.parquet",
        [{"id": "d#0", "text": "One. Two."}, {"id": "d#1", "text": "Three"}],
    )
    args = Namespace(
        processed=str(processed),
        raw=str(tmp_path / "raw"),
        tokenizer="ws",
        seq_len=[16],
        hard_negative_jaccard=0.5,
        no_candidates=True,
        no_mlm=False,
        no_mlm_text=False,
        mlm_batch_rows=10,
    )
    report = audit.run(args, whitespace_encoder())
    json.dumps(report)  # serialisable
    t = report["tasks"]
    assert t["nli"]["sources"]["n"]["train"]["label_prior"]["entailment"]["rows"] == 1
    assert t["nli"]["overlap"]["n/train"]["rows_in_any_held_out_split"] == 1
    assert (
        t["nli"]["sources"]["n"]["train"]["supply"]["premises_with_entailment_and_contradiction"]
        == 1
    )
    assert t["paraphrase"]["sources"]["p"]["train"]["word_overlap_auc"] == 1.0
    assert t["qa"]["sources"]["q"]["train"]["unanswerable"] == 1
    assert t["qa"]["sources"]["q"]["train"]["window"]["16"]["answer_outside_window"] == 0
    assert report["stsb_heldout_sentence_overlap"]["p/train"] == 2
    assert report["mlm"]["m"]["train"]["consecutive_passage_pairs"] == 1
