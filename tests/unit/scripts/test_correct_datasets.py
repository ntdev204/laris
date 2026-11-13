"""STS-B cross-split removal and ViQuAD offset correction (T96) on tiny synthetic rows."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "correct_datasets.py"
spec = importlib.util.spec_from_file_location("correct_datasets", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(a: str, b: str) -> dict:
    return {"sentence1": a, "sentence2": b, "score": 0.5}


def test_stsb_pairs_shared_with_a_later_split_leave_the_earlier_split() -> None:
    rows = {
        "train": [row("A  cat", "a dog"), row("x", "y"), row("p", "q")],
        "val": [
            row("a DOG", "a  cat"),
            row("m", "n"),
        ],  # same pair as train[0], order and case differ
        "test": [row("m", "n"), row("u", "v")],
    }
    out, info = mod.correct_stsb(rows)
    assert info["rows_removed"] == {"train": 1, "val": 1, "test": 0}
    assert out["test"] == rows["test"]
    assert [r["sentence1"] for r in out["val"]] == ["a DOG"]
    assert {r["sentence1"] for r in out["train"]} == {"x", "p"}


def test_misplaced_offset_moves_to_unique_occurrence_and_ambiguous_is_dropped() -> None:
    context = "ab cd ef cd"
    ok = {
        "id": "1",
        "context": "xx hello world",
        "answers": {"text": ["hello"], "answer_start": [2]},
    }
    fixed, stats = mod.fix_answers(ok)
    assert fixed["answers"]["answer_start"] == [3] and stats["offset_moved"] == 1
    ambiguous = {"id": "2", "context": context, "answers": {"text": ["cd"], "answer_start": [4]}}
    fixed, stats = mod.fix_answers(ambiguous)
    assert fixed["answers"]["text"] == [] and stats["answer_dropped"] == 1
    valid = {"id": "3", "context": context, "answers": {"text": ["ef"], "answer_start": [6]}}
    assert mod.fix_answers(valid)[1] == {}
