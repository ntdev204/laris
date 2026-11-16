"""QA formatters and paraphrase sources of T200: answer location, drop rules, guard, loader."""

import numpy as np
import pytest

from laris.research.corpus.splits.partitioners import pair_sources as P


def check_pointer(row):
    answers = row["answers"]
    for text, start in zip(answers["text"], answers["answer_start"]):
        assert row["context"][start : start + len(text)] == text


def test_locate_answer_exact_then_case_insensitive():
    assert P.locate_answer("The Cat sat. The cat ran.", "cat") == (17, "cat", 1)
    start, text, count = P.locate_answer("Sergeant Jericho spoke.", "sergeant jericho")
    assert (start, text, count) == (0, "Sergeant Jericho", 1)
    assert P.locate_answer("nothing here", "missing") is None
    assert P.locate_answer("anything", "   ") is None


def test_duorc_unanswerable_found_and_abstractive():
    plot = "Melanie Ballard leads the team. Desolation Williams is a prisoner."
    base = {"plot": plot, "title": "Ghosts", "question_id": "q1", "question": "who leads?"}
    row, outcome = P.format_duorc(
        {**base, "answers": ["the team lead", "melanie ballard"], "no_answer": False}, "SelfRC"
    )
    assert outcome == "kept_answer" and row["id"] == "duorc_en::SelfRC::q1"
    assert row["answers"]["text"] == ["Melanie Ballard"]  # taken from the context, case repaired
    check_pointer(row)

    row, outcome = P.format_duorc({**base, "answers": [], "no_answer": True}, "SelfRC")
    assert outcome == "kept_unanswerable" and row["answers"] == {"text": [], "answer_start": []}

    row, outcome = P.format_duorc(
        {**base, "answers": ["she saves Mars"], "no_answer": False}, "SelfRC"
    )
    assert (
        row is None and outcome == "dropped_answer_not_in_context"
    )  # never relabelled "no answer"


def test_duorc_repeated_answer_is_reported():
    base = {
        "plot": "Ann met Ann.",
        "title": "t",
        "question_id": "q",
        "question": "who?",
        "no_answer": False,
    }
    row, outcome = P.format_duorc({**base, "answers": ["Ann"]}, "SelfRC")
    assert outcome == "kept_answer_repeated" and row["answers"]["answer_start"] == [0]


def test_ropes_context_puts_situation_first_and_drops_question_only_answers():
    raw = {
        "id": "r1",
        "background": "Sugar dissolves in water.",
        "situation": "Cup A and cup B hold water. Sugar went into the second one.",
        "question": "Which cup has sugar?",
        "answers": {"text": ["cup B"]},
    }
    row, outcome = P.format_ropes(raw)
    assert outcome == "kept_answer" and row["context"].startswith("Cup A and cup B")
    check_pointer(row)

    row, outcome = P.format_ropes({**raw, "answers": {"text": ["cup C"]}})
    assert row is None and outcome == "dropped_answer_not_in_context"
    row, outcome = P.format_ropes({**raw, "answers": {"text": []}})
    assert row is None and outcome == "dropped_no_answer_label"


def test_quoref_valid_offset_is_kept_and_wrong_offset_repaired():
    raw = {
        "id": "x",
        "title": "T",
        "question": "who?",
        "context": "Catherine saw the plume. Later Catherine left.",
        "answers": {"text": ["Catherine"], "answer_start": [0]},
    }
    row, outcome = P.format_quoref(raw)
    assert outcome == "kept_answer" and row["answers"]["answer_start"] == [0]
    row, outcome = P.format_quoref({**raw, "answers": {"text": ["plume"], "answer_start": [3]}})
    assert outcome == "kept_offset_repaired" and row["answers"]["answer_start"] == [18]
    check_pointer(row)
    row, outcome = P.format_quoref({**raw, "answers": {"text": ["volcano"], "answer_start": [3]}})
    assert row is None and outcome == "dropped_answer_not_in_context"


def test_drop_keeps_spans_only():
    raw = {
        "query_id": "d1",
        "passage": "The Lions scored in the first quarter. Jason Hanson kicked 23 yards.",
        "question": "Who kicked?",
        "answers_spans": {"spans": ["Jason Hanson"], "types": ["span"]},
    }
    row, outcome = P.format_drop(raw)
    assert outcome == "kept_answer" and row["id"] == "drop_en::d1"
    check_pointer(row)
    row, outcome = P.format_drop({**raw, "answers_spans": {"spans": ["23"], "types": ["number"]}})
    assert row is None and outcome == "dropped_not_a_span"
    row, outcome = P.format_drop(
        {**raw, "answers_spans": {"spans": ["Hanson Jason"], "types": ["span"]}}
    )
    assert row is None and outcome == "dropped_answer_not_in_context"


def test_window_index_exact_window_and_clean():
    held = ["The quick brown fox jumps over the lazy dog near the river bank today."]
    index = P.WindowIndex(held)
    assert (
        index.hit("the QUICK brown fox, jumps over the lazy dog near the river bank today")
        == "exact"
    )
    assert index.hit("Yesterday the quick brown fox jumps over the lazy dog and left.") == "window"
    assert index.hit("An unrelated sentence about something else entirely, short.") is None
    assert (
        P.window_hashes("too short").dtype == np.uint64 and len(P.window_hashes("too short")) == 0
    )


def test_paws_rows_carry_label_source_and_reject_bad_rows():
    row = P.paws_row({"sentence1": " a b ", "sentence2": "b a", "label": 0}, P.LABEL_SOURCE_MODEL)
    assert row == {"sentence1": "a b", "sentence2": "b a", "label": 0, "label_source": "model"}
    assert P.paws_row({"sentence1": "a", "sentence2": "", "label": 1}, "human") is None
    assert P.paws_row({"sentence1": "a", "sentence2": "b", "label": 2}, "human") is None
    assert P.pair_key("A b", "c d") == P.pair_key("C d", "a B")


def test_formatted_rows_pass_the_loader_answer_span_rule():
    """The loader refuses an offset that does not point at its text, so every kept row must."""
    pytest.importorskip("pyarrow")
    from laris.shared.language.loading.dataloader import CLS_ID  # noqa: F401  (import guard)

    row, _ = P.format_ropes(
        {
            "id": "r",
            "background": "b",
            "situation": "Cup A and cup B. Sugar in cup B.",
            "question": "q?",
            "answers": {"text": ["cup B"]},
        }
    )
    start = row["answers"]["answer_start"][0]
    assert row["context"][start : start + len("cup B")] == "cup B"
    assert P.QA_SCHEMA.names == ["id", "title", "context", "question", "answers"]
    assert P.PARAPHRASE_SCHEMA.names[-1] == "label_source"


def test_loader_reads_the_new_sources(tmp_path):
    """The T200 directories load: no-answer rows train on [CLS], answered rows on their span,
    and the extra `label_source` column is ignored."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader

    answered, _ = P.format_duorc(
        {
            "plot": "Ann met Bob at the old mill.",
            "title": "t",
            "question_id": "a",
            "question": "who?",
            "answers": ["Bob"],
            "no_answer": False,
        },
        "SelfRC",
    )
    empty, _ = P.format_duorc(
        {
            "plot": "Ann met Bob at the old mill.",
            "title": "t",
            "question_id": "b",
            "question": "why?",
            "answers": [],
            "no_answer": True,
        },
        "SelfRC",
    )
    (tmp_path / "duorc_en").mkdir()
    pq.write_table(
        pa.Table.from_pylist([answered, empty] * 8, schema=P.QA_SCHEMA),
        tmp_path / "duorc_en" / "train.parquet",
    )
    pairs = [
        P.paws_row({"sentence1": f"a b {i}", "sentence2": f"b a {i}", "label": i % 2}, "model")
        for i in range(16)
    ]
    (tmp_path / "paws_unlabeled_en").mkdir()
    pq.write_table(
        pa.Table.from_pylist(pairs, schema=P.PARAPHRASE_SCHEMA),
        tmp_path / "paws_unlabeled_en" / "train.parquet",
    )

    loader = StreamingParquetMultiTaskDataLoader(data_dir=tmp_path, batch_size=4, seed=1)
    qa = loader.generate_batch("qa")
    starts = np.asarray(qa.labels["qa_start_positions"])
    assert (starts == 0).any() and (starts > 0).any()  # one [CLS] label, one span label
    assert loader.generate_batch("paraphrase") is not None
