"""Normalised answer-text QA metrics and their evaluator wiring (forward-only, no training)."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from laris.language.evaluation import metrics as M

REPO_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- pure metrics
def test_normalisation_drops_case_punctuation_and_english_articles():
    assert M.normalize_answer("The  Denver, Broncos!") == "denver broncos"
    assert M.normalize_answer("an apple, a day") == "apple day"
    assert M.normalize_answer("$5+3=8") == "538"


def test_vietnamese_keeps_tone_marks_and_every_syllable():
    assert M.normalize_answer("Hoa Kỳ.", "vi") == "hoa kỳ"
    assert M.normalize_answer("a và the", "vi") == "a và the"  # no English article rule
    decomposed = "Việt Nam"  # NFC makes it equal to the precomposed spelling
    assert M.normalize_answer(decomposed, "vi") == M.normalize_answer("Việt Nam", "vi")


def test_multiple_gold_answers_take_the_best_score():
    golds = ["the Denver Broncos", "Broncos"]
    assert M.answer_scores("Denver Broncos", golds) == (1.0, 1.0)
    em, f1 = M.answer_scores("Denver", ["Denver Broncos"])
    assert em == 0.0 and f1 == pytest.approx(2 * 1.0 * 0.5 / 1.5)


def test_no_answer_is_correct_only_for_an_empty_prediction():
    assert M.answer_scores("", []) == (1.0, 1.0)
    assert M.answer_scores("", ["", "  "]) == (1.0, 1.0)
    assert M.answer_scores("Paris", []) == (0.0, 0.0)
    assert M.answer_scores("", ["Paris"]) == (0.0, 0.0)


def test_f1_uses_token_counts_not_sets():
    em, f1 = M.answer_scores("x b b", ["b b c"])
    assert em == 0.0 and f1 == pytest.approx(2 / 3)


def test_span_selection_never_decodes_the_question_or_special_tokens():
    start, end = np.full(12, -5.0), np.full(12, -5.0)
    start[2], end[3] = 9.0, 9.0  # inside the question: must be ignored
    start[7], end[8] = 3.0, 3.0
    assert M.select_answer_span(start, end, 6, 10) == (7, 8)


def test_span_selection_returns_none_when_the_null_score_wins():
    start, end = np.full(12, -5.0), np.full(12, -5.0)
    start[0], end[0] = 4.0, 4.0
    start[7], end[8] = 1.0, 1.0
    assert M.select_answer_span(start, end, 6, 10) is None
    assert M.select_answer_span(start, end, 11, 10) is None  # empty context window


def test_span_selection_honours_the_maximum_answer_length():
    start, end = np.full(20, -9.0), np.full(20, -9.0)
    start[6], end[15] = 8.0, 8.0  # 10 tokens long
    assert M.select_answer_span(start, end, 5, 19, max_answer_tokens=3) != (6, 15)


def test_protocol_name_matches_every_formal_qa_gate():
    config = yaml.safe_load((REPO_ROOT / "configs/evaluation/foundation.yaml").read_text())
    qa = [g for g in config["gates"] if g["dataset"] in {"squad", "viquad_v2"}]
    assert len(qa) == 4
    assert {g["protocol"] for g in qa} == {M.ANSWER_TEXT_PROTOCOL}


# --------------------------------------------------------------------- evaluator wiring
torch = pytest.importorskip("torch")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from laris.language.evaluation.evaluator import (  # noqa: E402
    DatasetResult,
    EvaluationReport,
    LanguageEncoderEvaluator,
    report_to_dict,
)
from laris.language.training.dataloader import SEP_ID  # noqa: E402

SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("title", pa.string()),
        ("context", pa.string()),
        ("question", pa.string()),
        (
            "answers",
            pa.struct([("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]),
        ),
    ]
)


class WordTokenizer:
    """Whitespace tokenizer with a reversible vocabulary (decode is what the metric needs)."""

    def __init__(self):
        self.ids, self.words = {}, {}

    def encode_as_ids(self, text):
        out = []
        for word in text.split():
            if word not in self.ids:
                self.ids[word] = 10 + len(self.ids)
                self.words[self.ids[word]] = word
            out.append(self.ids[word])
        return out

    def decode_ids(self, ids):
        return " ".join(self.words[i] for i in ids)


class ScriptedQAModel:
    """Forward-only stand-in whose predicted span follows a script, one record per call."""

    def __init__(self, tokenizer, script):
        self.tokenizer, self.script = tokenizer, list(script)

    def eval(self):
        return self

    def __call__(self, token_ids, attention_mask=None):
        rows = token_ids.numpy()
        logits = np.full((*rows.shape, 2), -5.0, dtype=np.float32)
        for i, row in enumerate(rows):
            plan = self.script.pop(0)
            if plan == "null":
                logits[i, 0] = 9.0
                continue
            which, words = plan
            seps = [j for j, t in enumerate(row) if t == SEP_ID]
            target = [self.tokenizer.ids[w] for w in words.split()]
            hits = [
                j
                for j in range(seps[0] + 1, len(row) - len(target) + 1)
                if list(row[j : j + len(target)]) == target
            ]
            pos = hits[0] if which == "first" else hits[-1]
            logits[i, pos, 0] = 9.0
            logits[i, pos + len(target) - 1, 1] = 9.0
        return {"qa_logits": torch.from_numpy(logits)}


def make_evaluator(tmp_path, records, script, seq_len=64):
    tokenizer = WordTokenizer()
    for rec in records:  # fix the vocabulary before the model looks words up
        tokenizer.encode_as_ids(rec["question"] + " " + rec["context"])
    folder = tmp_path / "squad"
    folder.mkdir()
    pq.write_table(pa.Table.from_pylist(records, schema=SCHEMA), folder / "val.parquet")
    encoder = SimpleNamespace(
        model=ScriptedQAModel(tokenizer, script),
        tokenizer=tokenizer,
        config=SimpleNamespace(vocab_size=1000, max_sequence_length=seq_len),
        seq_len=seq_len,
        device="cpu",
    )
    evaluator = LanguageEncoderEvaluator(encoder, tmp_path, {}, batch_size=1, max_samples=100)
    return evaluator, [folder / "val.parquet"]


def record(qid, context, question, texts, starts=None):
    return {
        "id": qid,
        "title": "t",
        "context": context,
        "question": question,
        "answers": {"text": texts, "answer_start": starts if starts is not None else []},
    }


def score(evaluator, files, n):
    return evaluator._score_qa(files, [], n, dataset="squad")


def test_same_text_at_another_position_is_correct_for_answer_text_not_for_token_span(tmp_path):
    context = "Paris is big . Later we visited Paris again"
    recs = [record("1", context, "Which city ?", ["Paris"], [0])]
    evaluator, files = make_evaluator(tmp_path, recs, [("last", "Paris")])
    metrics, _ = score(evaluator, files, 1)
    assert metrics["exact_match"] == 1.0 and metrics["f1"] == 1.0
    assert metrics["token_span_exact_match"] == 0.0 and metrics["token_span_f1"] == 0.0


def test_any_acceptable_gold_answer_counts_and_partial_overlap_gets_partial_f1(tmp_path):
    context = "The Denver Broncos won the game"
    question = "Who won ?"
    recs = [
        record("1", context, question, ["The Denver Broncos", "Broncos"], [0, 11]),
        record("2", context, question, ["The Denver Broncos"], [0]),
    ]
    evaluator, files = make_evaluator(tmp_path, recs, [("first", "Broncos"), ("first", "Denver")])
    metrics, _ = score(evaluator, files, 2)
    assert metrics["exact_match"] == pytest.approx(0.5)
    assert metrics["f1"] == pytest.approx((1.0 + 2 * 1.0 * 0.5 / 1.5) / 2)


def test_no_answer_questions_need_an_empty_prediction(tmp_path):
    recs = [
        record("1", "Paris is big", "Which city ?", []),
        record("2", "Paris is big", "Which city ?", []),
    ]
    evaluator, files = make_evaluator(tmp_path, recs, ["null", ("first", "Paris")])
    metrics, baseline = score(evaluator, files, 2)
    assert metrics["no_answer_exact_match"] == pytest.approx(0.5)
    assert metrics["has_answer_exact_match"] == 0.0  # no has-answer rows: reported as 0.0
    assert evaluator._details["squad"]["no_answer_rows"] == 2
    assert baseline[0]["exact_match"] == 1.0  # always answering nothing is right here


def test_truncated_gold_answers_are_kept_and_counted_not_dropped(tmp_path):
    words = " ".join(f"w{i}" for i in range(40))
    context = words + " target"
    recs = [record("1", context, "Which ?", ["target"], [context.index("target")])]
    evaluator, files = make_evaluator(tmp_path, recs, ["null"], seq_len=16)
    metrics, _ = score(evaluator, files, 1)
    details = evaluator._details["squad"]
    assert details["scored_rows"] == 1 and details["answer_outside_window_rows"] == 1
    assert metrics["answer_outside_window_rate"] == 1.0 and metrics["context_truncated_rate"] == 1.0
    assert metrics["exact_match"] == 0.0  # unreachable answer counts against the model


def test_report_records_protocols_and_provenance(tmp_path):
    recs = [record("1", "Paris is big", "Which city ?", ["Paris"], [0])]
    evaluator, files = make_evaluator(tmp_path, recs, [("first", "Paris")])
    metrics, (baseline, source) = score(evaluator, files, 1)
    result = DatasetResult(
        "qa", "squad", "en", 1, metrics, baseline, source, evaluator._details.pop("squad")
    )
    body = report_to_dict(EvaluationReport("test", [result], [], False))
    row = body["datasets"][0]
    assert row["metric_protocols"]["exact_match"] == M.ANSWER_TEXT_PROTOCOL
    assert row["metric_protocols"]["f1"] == M.ANSWER_TEXT_PROTOCOL
    assert row["metric_protocols"]["token_span_f1"] == "token_span"
    details = row["protocol_details"]
    assert details["complete_split"] is True and details["split_rows"] == 1
    assert details["truncation_policy"] and details["span_decoding"]["restricted_to_context"]
    assert details["qa_protocol_version"] and details["answer_normalization"]


def test_partial_split_is_flagged_as_incomplete(tmp_path):
    recs = [record(str(i), "Paris is big", "Which city ?", ["Paris"], [0]) for i in range(3)]
    evaluator, files = make_evaluator(tmp_path, recs, [("first", "Paris")] * 3)
    score(evaluator, files, 2)
    details = evaluator._details["squad"]
    assert details["scored_rows"] == 2 and details["split_rows"] == 3
    assert details["complete_split"] is False


def test_protocol_is_not_claimed_without_answer_text_provenance():
    result = DatasetResult("qa", "squad", "en", 1, {"f1": 0.9, "exact_match": 0.8}, {"f1": 0.0})
    row = report_to_dict(EvaluationReport("test", [result], [], False))["datasets"][0]
    assert row["metric_protocols"] == {"exact_match": "token_span", "f1": "token_span"}
    assert "protocol_details" not in row
