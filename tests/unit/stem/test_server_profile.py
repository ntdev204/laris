"""T284: the runner's path to the server's STEM profile (records, parity table); no server runs."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "stem_benchmarks", ROOT / "scripts/stem_benchmarks.py"
)
sb = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(sb)

EQ = {"timeout_s": 5, "numeric_rel_tol": 1e-9}


def test_a_server_record_has_the_python_record_form() -> None:
    item = {"id": "m/1", "category": "algebra", "options": [], "answer": "5", "question": "Q"}
    got = {
        "id": "m/1",
        "seed": 47624,
        "cls": "computable",
        "rule": "open_answer",
        "steps": [{"step": "draft"}],
        "draft": "5",
        "final": "5",
        "final_from": "draft",
        "model_free": False,
        "prompt_tokens": 9,
        "generated_tokens": 900,
        "model_calls": 1,
        "solver_calls": 0,
        "seconds": 3.5,
        "filter": {"status": "pass"},
        "profile_config_sha256": "abc",
    }
    record = sb.server_record("math500", item, got, "thinking_off", EQ, 123)
    assert record["correct"] and record["draft_correct"] and record["via"] == "server"
    assert record["cost"]["generated_tokens"] == 900 and record["cost"]["peak_vram_bytes"] == 123
    assert record["final_from"] == "draft" and record["filter"] == {"status": "pass"}
    assert "Q" not in json.dumps(record)


def test_a_filter_stop_from_the_server_scores_zero() -> None:
    item = {"id": "m/2", "category": "algebra", "options": [], "answer": "5", "question": "Q"}
    got = {
        "id": "m/2",
        "final": None,
        "final_from": "filter_stop",
        "cls": "computable",
        "steps": [],
    }
    record = sb.server_record("math500", item, got, "thinking_off", EQ, 0)
    assert not record["correct"] and record["cost"]["model_calls"] == 0


def test_the_parity_table_pairs_items_and_counts_discordant_verdicts() -> None:
    a = {
        "1": {"bench": "math500", "correct": True, "final": "5", "cls": "computable"},
        "2": {"bench": "math500", "correct": False, "final": "3", "cls": "computable"},
        "3": {"bench": "math500", "correct": True, "final": "1", "cls": "computable"},
    }
    b = {
        "1": {"bench": "math500", "correct": True, "final": "5", "cls": "computable"},
        "2": {"bench": "math500", "correct": True, "final": "4", "cls": "computable"},
        "4": {"bench": "math500", "correct": True, "final": "9", "cls": "computable"},
    }
    row = sb.parity_table(a, b)["math500"]
    assert row["items"] == 2 and row["same_final"] == 1 and row["same_verdict"] == 1
    assert (row["b_right_a_wrong"], row["a_right_b_wrong"]) == (1, 0)
    assert row["mcnemar_p"] == 1.0
