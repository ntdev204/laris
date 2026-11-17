"""Preparation and merge of LLM-graded similarity pairs (T208); no model, no grader call."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import llm_similarity as ls  # noqa: E402


def test_spearman_known_values() -> None:
    assert ls.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert ls.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert ls.spearman([1, 1, 1], [1, 2, 3]) == 0.0  # constant input has no rank correlation


def test_shards_are_blind_and_sized(tmp_path: Path) -> None:
    rows = [
        {"id": f"x{i}", "sentence1": "a", "sentence2": "b", "relation": "entailment", "human": 0.9}
        for i in range(ls.SHARD_SIZE + 5)
    ]
    names = ls.write_shards(rows, tmp_path, "t")
    assert len(names) == 2
    first = json.loads((tmp_path / names[0]).read_text())
    assert len(first) == ls.SHARD_SIZE and set(first[0]) == {"id", "sentence1", "sentence2"}


def test_scores_must_be_on_the_half_point_scale(tmp_path: Path) -> None:
    good = tmp_path / "sel_000.graded.json"
    good.write_text(json.dumps([{"id": "a", "score": 3.5}, {"id": "b", "score": 0}]))
    assert ls._read_scores(tmp_path, "sel") == {"a": 3.5, "b": 0.0}
    for bad in (5.5, -0.5, 2.3):
        good.write_text(json.dumps([{"id": "a", "score": bad}]))
        with pytest.raises(ValueError, match="steps of 0.5"):
            ls._read_scores(tmp_path, "sel")


def test_overlap_is_jaccard_of_normalised_words() -> None:
    assert ls.overlap("The cat sat.", "the CAT sat") == 1.0
    assert ls.overlap("a b c d", "c d e f") == pytest.approx(2 / 6)
    assert ls.overlap("", "") == 0.0
