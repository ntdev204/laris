"""T278: the STEM router and harness with a scripted model and a scripted solver (no GPU)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from laris.research.stem import harness as h
from laris.research.stem.router import COMPUTABLE, KNOWLEDGE, REASONING, route

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "configs/stem-benchmarks.json").read_text(encoding="utf-8"))
EQ = CONFIG["equivalence"]


def t278_harness() -> Dict[str, Any]:
    """The harness section with the T278 behaviour these tests describe: formalise every
    computable item, review on a disagreement, no self-consistency (T279 turned on early exit and
    self-consistency in the configuration; those levers are tested in test_cost.py)."""
    cfg = json.loads(json.dumps(CONFIG["harness"]))
    cfg["formalise"].update(when="always", review=True)
    cfg["self_consistency"]["enabled"] = False
    return cfg


def _math(question: str = "What is $1+1$?", answer: str = "2") -> Dict[str, Any]:
    return {"id": "m/1", "question": question, "options": [], "answer": answer, "category": "A"}


def _choice(options: List[str], question: str = "Which one?") -> Dict[str, Any]:
    return {"id": "c/1", "question": question, "options": options, "answer": "A", "category": "B"}


class Scripted:
    """A model that answers by step: the prompt's kind decides which scripted text is returned."""

    def __init__(self, **texts: Any) -> None:
        self.texts = {k: list(v) if isinstance(v, list) else [v] for k, v in texts.items()}
        self.calls: List[Tuple[str, int, int]] = []

    def kind(self, prompt: str) -> str:
        if "computer algebra system computed" in prompt:
            return "review_solver"
        if "notes from reference textbooks bear on" in prompt:
            return "review_notes"
        if "Translate the problem" in prompt:
            return "formalise"
        if "Keep the reasoning short" in prompt:
            return "retry"
        return "draft"

    def __call__(self, prompt: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        kind = self.kind(prompt)
        self.calls.append((kind, seed, max_tokens))
        queue = self.texts[kind]
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        truncated = text.startswith("TRUNC:")
        return {
            "text": text.removeprefix("TRUNC:"),
            "prompt_tokens": 10,
            "generated_tokens": 5,
            "truncated": truncated,
            "seconds": 0.5,
        }

    def kinds(self) -> List[str]:
        return [c[0] for c in self.calls]


def _solver(result: Optional[Dict[str, Any]], status: str = "verified"):
    seen: List[Dict[str, Any]] = []

    def solve(problem: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        seen.append(problem)
        return result, status

    solve.seen = seen  # type: ignore[attr-defined]
    return solve


def _harness(model, solve, model_free=None, **overrides: Any) -> h.Harness:
    cfg = t278_harness()
    for key, value in overrides.items():
        cfg[key] = value
    return h.Harness(cfg, CONFIG["baseline"], model, solve, EQ, model_free)


# -- router --------------------------------------------------------------------------------------

ROUTER = CONFIG["harness"]["router"]


def test_router_classes() -> None:
    assert route(_math(), ROUTER).cls == COMPUTABLE
    numbers = ["1.2 J", "3.4 J", "5 J", "kinetic"]
    assert route(_choice(numbers), ROUTER).cls == COMPUTABLE
    words = ["mitochondria", "ribosome", "nucleus", "vacuole"]
    assert route(_choice(words), ROUTER).cls == KNOWLEDGE
    long_question = " ".join(["word"] * (ROUTER["knowledge_max_question_words"] + 1))
    assert route(_choice(words, long_question), ROUTER).cls == REASONING


def test_router_never_reads_the_gold_answer() -> None:
    item = _choice(["alpha", "beta"])
    first = route(item, ROUTER)
    item["answer"] = "B"
    assert route(item, ROUTER) == first


# -- helpers -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, value",
    [("5.6 × 10^-3 M", 5.6e-3), ("3.2e5 J", 3.2e5), ("-12 m/s", -12.0), ("2,5 kg", 2.5),
     ("1.5 x 10^{4} N", 1.5e4), ("no number", None)],
)  # fmt: skip
def test_option_value(text: str, value: Optional[float]) -> None:
    got = h.option_value(text)
    assert got == pytest.approx(value) if value is not None else got is None


def test_match_option_needs_one_close_option() -> None:
    assert h.match_option(11.25, ["10 J", "11.3 J", "20 J"], 0.02) == 1
    assert h.match_option(11.25, ["11.2 J", "11.3 J"], 0.02) is None  # two within tolerance
    assert h.match_option(11.25, ["1 J", "2 J"], 0.02) is None


def test_first_json_object() -> None:
    text = 'Here: ```json\n{"operation": "evaluate", "expression": "a{b}"}\n``` done {"x": 1}'
    assert h.first_json_object(text) == {"operation": "evaluate", "expression": "a{b}"}
    assert h.first_json_object("NONE") is None
    assert h.first_json_object("{not json} [1]") is None


def test_solver_value() -> None:
    assert h.solver_value({"numeric": "11.2500000000000", "answer": "45/4"}) == 11.25
    assert h.solver_value({"answer": "45/4"}) == 11.25
    assert h.solver_value({"answer": ["3"]}) == 3.0
    assert h.solver_value({"answer": ["2", "3"]}) is None


# -- the loop ------------------------------------------------------------------------------------


def test_model_free_answer_skips_the_model() -> None:
    model = Scripted(draft="\\boxed{9}")
    free = lambda item: {"pattern": "compute", "status": "verified", "answer": "2"}  # noqa: E731
    trace = _harness(model, _solver(None), free).answer(_math(), 1)
    assert trace.model_free and trace.final == "2" and trace.final_from == "model_free"
    assert model.calls == [] and trace.model_calls == 0 and trace.solver_calls == 1


def test_model_free_proposal_falls_through_to_the_model() -> None:
    model = Scripted(draft="\\boxed{2}", formalise="NONE")
    free = lambda item: {"pattern": "compute", "status": "proposal", "answer": None}  # noqa: E731
    trace = _harness(model, _solver(None), free).answer(_math(), 1)
    assert not trace.model_free and trace.final == "2" and trace.final_from == "draft"
    assert model.kinds() == ["draft", "formalise"] and trace.solver_status == "not_formalised"


def test_solver_agreement_ends_the_item() -> None:
    model = Scripted(draft="so \\boxed{\\frac{45}{4}}", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "latex": "\\frac{45}{4}", "text": "45/4"})
    trace = _harness(model, solve).answer(_math(answer="45/4"), 1)
    assert trace.agreement is True and trace.final == "\\frac{45}{4}"
    assert model.kinds() == ["draft", "formalise"] and solve.seen == [{"operation": "evaluate"}]


def test_solver_disagreement_asks_for_a_review() -> None:
    model = Scripted(
        draft="\\boxed{11}", formalise='{"operation": "evaluate"}', review_solver="\\boxed{45/4}"
    )
    solve = _solver({"status": "verified", "latex": "\\frac{45}{4}", "text": "45/4"})
    trace = _harness(model, solve).answer(_math(), 1)
    assert trace.agreement is False and trace.final == "45/4"
    assert trace.final_from == "review_solver" and trace.draft == "11"
    assert model.kinds() == ["draft", "formalise", "review_solver"]
    assert trace.model_calls == 3 and trace.generated_tokens == 15 and trace.solver_calls == 1


def test_unreadable_review_keeps_the_draft() -> None:
    model = Scripted(draft="\\boxed{11}", formalise='{"operation": "x"}', review_solver="hmm")
    solve = _solver({"status": "verified", "latex": "12", "text": "12"})
    trace = _harness(model, solve).answer(_math(), 1)
    assert trace.final == "11" and trace.final_from == "draft"


def test_a_proposal_is_not_used() -> None:
    model = Scripted(draft="\\boxed{11}", formalise='{"operation": "solve"}')
    trace = _harness(model, _solver({"latex": "12"}, "proposal")).answer(_math(), 1)
    assert trace.final == "11" and trace.agreement is None and trace.solver_status == "proposal"
    assert model.kinds() == ["draft", "formalise"]


def test_truncated_draft_is_retried_with_another_seed() -> None:
    model = Scripted(draft="TRUNC:going on and on", retry="\\boxed{2}", formalise="NONE")
    trace = _harness(model, _solver(None)).answer(_math(), 100)
    assert trace.final == "2" and not trace.truncated
    assert [c[:2] for c in model.calls[:2]] == [("draft", 100), ("retry", 1100)]


def test_unreadable_draft_and_retry_fall_back_to_the_solver() -> None:
    model = Scripted(draft="TRUNC:...", retry="TRUNC:...", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "numeric": "11.25", "answer": "45/4", "text": "45/4"})
    item = _choice(["10 J", "11.3 J", "20 J", "40 J"])
    trace = _harness(model, solve).answer(item, 1)
    assert trace.draft is None and trace.truncated
    assert trace.final == "B" and trace.final_from == "solver_fallback"


def test_choice_draft_agrees_with_the_matching_option() -> None:
    model = Scripted(draft="Answer: B", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "numeric": "11.25", "text": "45/4"})
    trace = _harness(model, solve).answer(_choice(["10 J", "11.3 J", "20 J", "40 J"]), 1)
    assert trace.agreement is True and trace.final == "B"


def test_complex_branch_is_not_a_math_answer() -> None:
    model = Scripted(draft="\\boxed{-243}", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "latex": "-243 (-1)^{2/3}", "text": "-243*(-1)^(2/3)"})
    trace = _harness(model, solve).answer(_math("Evaluate $(-27)^{5/3}$."), 1)
    assert trace.agreement is None and trace.final == "-243"


NOTES = ["The ribosome is the site of protein synthesis in the cell."]


def test_notes_go_into_the_prompt_of_retrieval_classes() -> None:
    model = Scripted(draft="Answer: A")
    item = _choice(["mitochondria", "ribosome site protein", "nucleus", "vacuole"])
    seen: List[str] = []

    def spy(prompt: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        seen.append(prompt)
        return model(prompt, seed, max_tokens)

    _harness(spy, _solver(None), notes_check={"enabled": False, "min_option_words": 2}).answer(
        item, 1, NOTES
    )
    assert "Notes from reference textbooks" in seen[0] and NOTES[0] in seen[0]


def test_notes_check_asks_for_a_review_when_notes_back_another_option() -> None:
    model = Scripted(draft="Answer: A", review_notes="Answer: B")
    item = _choice(["mitochondria energy", "ribosome protein synthesis", "nucleus dna", "vacuole"])
    trace = _harness(model, _solver(None)).answer(item, 1, NOTES)
    assert trace.cls == KNOWLEDGE and trace.final == "B" and trace.final_from == "review_notes"
    assert model.kinds() == ["draft", "review_notes"]


def test_notes_check_is_quiet_when_the_draft_has_the_supported_option() -> None:
    model = Scripted(draft="Answer: B")
    item = _choice(["mitochondria energy", "ribosome protein synthesis", "nucleus dna", "vacuole"])
    trace = _harness(model, _solver(None)).answer(item, 1, NOTES)
    assert trace.final == "B" and model.kinds() == ["draft"]


def test_trace_holds_no_item_text() -> None:
    model = Scripted(draft="\\boxed{11}", formalise='{"operation": "x"}', review_solver="ok")
    solve = _solver({"status": "verified", "latex": "2", "text": "2"})
    item = _math("A secret question text about apples?")
    text = json.dumps(_harness(model, solve).answer(item, 1).as_dict())
    assert "apples" not in text


# -- summary -------------------------------------------------------------------------------------


def _row(i: int, correct: bool, draft: bool, final_from: str, **extra: Any) -> Dict[str, Any]:
    cost = {"seconds": 1.0 + i, "prompt_tokens": 1, "generated_tokens": 10, "model_calls": 2,
            "solver_calls": 1, "peak_vram_bytes": 5}  # fmt: skip
    return {"id": f"x/{i}", "correct": correct, "draft_correct": draft, "extracted": "A",
            "final_from": final_from, "cls": "computable", "cost": cost, **extra}  # fmt: skip


def test_summary_counts_flips_and_compares_with_the_baseline() -> None:
    rows = [
        _row(0, True, False, "review_solver"),
        _row(1, False, True, "review_solver"),
        _row(2, True, True, "draft", agreement=True),
        _row(3, True, True, "model_free", model_free=True),
    ]
    out = h.summarise_records(rows, {"x/0": False, "x/1": True, "x/2": True, "x/9": True})
    assert out["correct"] == 3 and out["draft_correct"] == 3
    assert out["review_flips"]["review_solver"] == {"to_right": 1, "to_wrong": 1, "same": 0}
    assert out["model_free"] == {"answered": 1, "wrong": 0}
    assert out["solver_agreed"] == {"items": 1, "correct": 1}
    assert out["baseline"] == {"items": 3, "correct": 2, "accuracy": 2 / 3,
                               "harness_correct": 2, "gained": 1, "lost": 1}  # fmt: skip


# -- repair --------------------------------------------------------------------------------------


def test_repair_takes_the_formula_of_an_assignment() -> None:
    fixed, notes = h.repair({"operation": "evaluate", "expression": "T2 = T1*2", "units": "K"})
    assert fixed == {"operation": "evaluate", "expression": "T1*2"}
    assert notes == ["assignment", "dropped"]


def test_repair_renames_names_the_solver_keeps() -> None:
    problem = {"operation": "evaluate", "expression": "V*I + lambda/E",
               "substitutions": {"I": 4, "V": 120, "lambda": 2, "E": 1}}  # fmt: skip
    fixed, notes = h.repair(problem)
    assert fixed["expression"] == "V*I_v + lambda_v/E_v"
    assert fixed["substitutions"] == {"V": 120, "I_v": 4, "lambda_v": 2, "E_v": 1}
    assert set(notes) == {"renamed"}


def test_repair_inlines_substitutions_of_solve() -> None:
    problem = {"operation": "solve", "expression": "v^2 = 2*g*y", "variable": "v",
               "substitutions": {"g": 32.174, "y": "2^8"}}  # fmt: skip
    fixed, notes = h.repair(problem)
    assert fixed == {"operation": "solve", "expression": "v^2 = 2*(32.174)*(2^8)", "variable": "v"}
    assert notes == ["inlined"]


def test_repair_leaves_a_constant_lookup_it_cannot_inline() -> None:
    problem = {"operation": "solve", "expression": "x = h", "variable": "x",
               "substitutions": {"h": {"constant": "h"}}}  # fmt: skip
    fixed, _ = h.repair(problem)
    assert fixed["substitutions"] == {"h": {"constant": "h"}}  # the solver refuses it


def test_repaired_calls_pass_the_real_solver() -> None:
    from laris.model.solver import SolverSettings
    from laris.model.solver.engine import solve

    settings = SolverSettings()
    problem = {
        "operation": "evaluate",
        "expression": "P = V*I",
        "substitutions": {"V": 120, "I": 4},
    }
    fixed, _ = h.repair(problem)
    assert solve(fixed, settings)["answer"] == "480"
    problem = {"operation": "solve", "expression": "v^2 = 2*g*y", "variable": "v",
               "domain": "real", "substitutions": {"g": 2, "y": 4}}  # fmt: skip
    out = solve(h.repair(problem)[0], settings)
    assert sorted(out["answer"]) == ["-4", "4"]


# -- T285: the brain-only path, from certain Claims only ----------------------------------------

_CELLS = ["ribosome translation protein", "membrane lipid bilayer", "nucleus chromatin dna"]
_CERTAIN = ["Ribosomes carry out translation of messenger RNA into protein; a ribosome is large."]


def test_brain_only_is_off_by_default() -> None:
    assert CONFIG["harness"]["brain_only"]["enabled"] is False
    model = Scripted(draft="Answer: B")
    trace = _harness(model, _solver(None)).answer(_choice(_CELLS), 1, [], _CERTAIN)
    assert trace.final_from == "draft" and not trace.brain_only


def test_brain_only_answers_from_one_certain_claim_without_the_model() -> None:
    model = Scripted(draft="Answer: B")
    on = {"enabled": True, "min_option_words": 2}
    trace = _harness(model, _solver(None), brain_only=on).answer(_choice(_CELLS), 1, [], _CERTAIN)
    assert trace.brain_only and trace.final == "A" and trace.final_from == "brain_only"
    assert model.calls == []


def test_brain_only_abstains_on_two_backed_options_or_uncertain_notes() -> None:
    model = Scripted(draft="Answer: B", review_notes="Answer: B")
    on = {"enabled": True, "min_option_words": 2}
    both = _CERTAIN + ["The membrane is a lipid bilayer around the cell."]
    trace = _harness(model, _solver(None), brain_only=on).answer(_choice(_CELLS), 1, [], both)
    assert not trace.brain_only and trace.final_from == "draft"
    # passages that are only notes (not certain) never answer alone
    trace = _harness(model, _solver(None), brain_only=on).answer(_choice(_CELLS), 1, _CERTAIN, [])
    assert not trace.brain_only


def test_summary_counts_brain_only_answers() -> None:
    rows = [_row(0, True, False, "brain_only"), _row(1, False, False, "brain_only")]
    out = h.summarise_records(rows)
    assert out["brain_only"] == {"answered": 2, "wrong": 1}
