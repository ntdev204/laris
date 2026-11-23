"""T279: cost levers (repetition detection, budget forcing, escalation, early exit,
self-consistency) and the run comparison, with a scripted model (no GPU, no training)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from laris.research.stem import cost
from laris.research.stem import harness as h

from .test_harness import CONFIG, EQ, Scripted, _choice, _math, _solver

ROOT = Path(__file__).resolve().parents[3]


# -- repetition --------------------------------------------------------------------------------


def test_repeating_tail_finds_the_shortest_period() -> None:
    loop = "intro " + "so x = 2, check again. " * 8
    assert cost.repeating_tail(loop, 4, 64, 6) == len("so x = 2, check again. ")


def test_repeating_tail_ignores_text_that_does_not_repeat_enough() -> None:
    text = "a long line of reasoning that moves on " + "x = 1; " * 3
    assert cost.repeating_tail(text, 4, 64, 6) is None
    assert cost.repeating_tail("short", 16, 64, 6) is None


def test_watch_checks_only_after_min_chars_and_then_every_n() -> None:
    watch = cost.RepetitionWatch(
        {"enabled": True, "min_period": 4, "max_period": 32, "repeats": 4, "min_chars": 40}
    )
    assert not watch.feed("abcd" * 5)  # 20 characters: too early to look
    assert watch.feed("abcd" * 5) and watch.period == 4
    off = cost.RepetitionWatch({"enabled": False})
    assert not off.feed("abcd" * 1000)


def test_forced_prompt_closes_the_reasoning() -> None:
    raw = "<|im_start|>assistant\n<think>\n"
    forced = cost.forced_prompt(raw, "some reasoning")
    assert forced.startswith(raw + "some reasoning") and forced.endswith("</think>\n\n")


# -- comparison --------------------------------------------------------------------------------


def test_mcnemar_exact() -> None:
    assert cost.mcnemar_exact(0, 0) == 1.0
    assert cost.mcnemar_exact(5, 5) == 1.0
    assert cost.mcnemar_exact(10, 0) == pytest.approx(2 / 1024)


def _row(i: str, correct: bool, seconds: float = 1.0, **extra: Any) -> Dict[str, Any]:
    cost_ = {"seconds": seconds, "generated_tokens": 10, "model_calls": 1}
    return dict(id=i, bench="b", correct=correct, cost=cost_, **extra)


def test_compare_runs_pairs_items() -> None:
    run = {"1": _row("1", True, 2.0), "2": _row("2", False), "3": _row("3", True)}
    ref = {"1": _row("1", False), "2": _row("2", True), "3": _row("3", True), "4": _row("4", True)}
    out = cost.compare_runs(run, ref, "b")
    assert out["items"] == 3 and out["correct"] == 2 and out["reference_correct"] == 2
    assert (out["gained"], out["lost"]) == (1, 1)
    assert out["cost"]["seconds_median"] == 1.0 and out["cost"]["model_calls_mean"] == 1.0


def test_counterfactual_without_review_or_formalisation() -> None:
    rows = [
        _row("1", True, final_from="review_solver", draft_correct=False),
        _row("2", False, final_from="review_solver", draft_correct=True),
        _row("3", True, final_from="solver_fallback"),
        _row("4", True, final_from="draft"),
    ]
    assert cost.counterfactual(rows, "review") == 3
    assert cost.counterfactual(rows, "formalise") == 2
    with pytest.raises(ValueError):
        cost.counterfactual(rows, "other")


# -- harness levers ----------------------------------------------------------------------------


class Raw:
    """Raw completions by call order: each entry is the text (prefix TRUNC: for a cut reply)."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: List[Tuple[str, int, int]] = []

    def __call__(self, raw: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        self.calls.append((raw, seed, max_tokens))
        text = self.texts.pop(0)
        truncated = text.startswith("TRUNC:")
        return {
            "text": text.removeprefix("TRUNC:"),
            "prompt_tokens": 10,
            "generated_tokens": 7,
            "truncated": truncated,
            "seconds": 0.25,
        }


def _template(prompt: str) -> str:
    return f"<user>{prompt}</user><think>\n"


def _cfg(**override: Any) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(CONFIG["harness"]))
    for key, value in override.items():
        cfg[key] = dict(cfg.get(key, {}), **value) if isinstance(value, dict) else value
    return cfg


def _harness(cfg: Dict[str, Any], model: Any, solve: Any, raw: Any = None) -> h.Harness:
    return h.Harness(cfg, CONFIG["baseline"], model, solve, EQ, None, None, raw, _template)


def test_levers_are_off_by_default() -> None:
    cfg = CONFIG["harness"]
    assert cfg["draft"]["thinking"] == {} and not cfg["draft"]["escalate"]["enabled"]
    assert cfg["formalise"]["when"] == "always" and cfg["formalise"]["review"] is True
    assert not cfg["self_consistency"]["enabled"] and not cfg["repetition"]["enabled"]
    for name, lever in CONFIG["cost_levers"].items():
        assert name == "note" or isinstance(lever, dict)


def test_escalation_replaces_the_retry_with_budget_forcing() -> None:
    model = Scripted(draft="TRUNC:on and on", formalise="NONE")
    raw = Raw("TRUNC:thinking without end", "so \\boxed{2}")
    cfg = _cfg(draft={"escalate": {"enabled": True, "thinking_budget": 300, "answer_tokens": 50}})
    trace = _harness(cfg, model, _solver(None), raw).answer(_math(), 100)
    assert trace.final == "2" and trace.retried and not trace.truncated
    assert model.kinds() == ["draft", "formalise"]  # no thinking-off retry
    (first, s1, n1), (second, s2, n2) = raw.calls
    assert (s1, n1, s2, n2) == (1100, 300, 1101, 50)
    assert second == cost.forced_prompt(first, "thinking without end")
    step = [s for s in trace.steps if s["step"] == "escalate"][0]
    assert step["forced"] and step["thinking"] and step["tokens"] == 14
    assert trace.model_calls == 4 and trace.generated_tokens == 5 + 14 + 5


def test_thinking_that_closes_in_budget_is_not_forced() -> None:
    model = Scripted(draft="unused", formalise="NONE")
    raw = Raw("short thought</think>The answer is \\boxed{2}")
    cfg = _cfg(draft={"thinking": {"computable": 500}})
    trace = _harness(cfg, model, _solver(None), raw).answer(_math(), 1)
    assert trace.final == "2" and len(raw.calls) == 1 and model.kinds() == ["formalise"]
    assert trace.steps[0] == {
        "step": "draft",
        "truncated": False,
        "tokens": 7,
        "thinking": True,
        "forced": False,
    }


def test_a_thinking_budget_needs_the_raw_completion() -> None:
    cfg = _cfg(draft={"thinking": {"computable": 500}})
    harness = h.Harness(cfg, CONFIG["baseline"], Scripted(draft="x"), _solver(None), EQ)
    with pytest.raises(ValueError):
        harness.answer(_math(), 1)


def test_early_exit_skips_formalisation_of_a_sure_draft() -> None:
    model = Scripted(draft="\\boxed{2}", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "latex": "3", "text": "3"})
    cfg = _cfg(formalise={"when": "uncertain", "review": False})
    trace = _harness(cfg, model, solve).answer(_math(), 1)
    assert trace.final == "2" and model.kinds() == ["draft"] and solve.seen == []


def test_early_exit_formalises_a_retried_draft_and_keeps_it_on_disagreement() -> None:
    model = Scripted(draft="TRUNC:...", retry="\\boxed{2}", formalise='{"operation": "evaluate"}')
    solve = _solver({"status": "verified", "latex": "3", "text": "3"})
    cfg = _cfg(formalise={"when": "uncertain", "review": False})
    trace = _harness(cfg, model, solve).answer(_math(), 1)
    assert trace.agreement is False and trace.final == "2" and trace.final_from == "draft"
    assert model.kinds() == ["draft", "retry", "formalise"]


def test_self_consistency_votes_with_the_solver_on_a_disagreement() -> None:
    model = Scripted(
        draft=["\\boxed{11}", "\\boxed{12}", "\\boxed{13}"], formalise='{"operation": "e"}'
    )
    solve = _solver({"status": "verified", "latex": "12", "text": "12"})
    cfg = _cfg(self_consistency={"enabled": True, "samples": 2, "when": ["disagree"]})
    trace = _harness(cfg, model, solve).answer(_math(), 1)
    assert trace.final == "12" and trace.final_from == "vote"
    assert trace.votes == {"11": 1, "12": 2, "13": 1}
    assert model.kinds() == ["draft", "formalise", "draft", "draft"]
    assert [c[1] for c in model.calls[2:]] == [32, 63]


def test_self_consistency_tie_keeps_the_draft() -> None:
    model = Scripted(draft=["\\boxed{B}", "Answer: A", "Answer: C"])
    item = _choice(["alpha beta", "gamma delta", "epsilon zeta", "eta theta"])
    item["question"] = "Which of these words is the right one to pick in this case?"
    cfg = _cfg(
        self_consistency={"enabled": True, "samples": 2, "when": ["retried"]},
        draft={"max_retries": 1},
    )
    model.texts["draft"] = ["TRUNC:...", "Answer: A", "Answer: C"]
    model.texts["retry"] = ["Answer: B", "Answer: A", "Answer: C"]
    trace = _harness(cfg, model, _solver(None)).answer(item, 1)
    assert trace.retried and trace.draft == "B"
    assert trace.votes == {"B": 1, "A": 1, "C": 1} and trace.final == "B"


def test_lever_overrides_merge_into_the_harness_section() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("sb", ROOT / "scripts/stem_benchmarks.py")
    assert spec and spec.loader
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    merged = sb.merge_path(CONFIG["harness"], CONFIG["cost_levers"]["early_exit"])
    assert merged["formalise"]["when"] == "uncertain" and merged["formalise"]["review"] is False
    assert merged["formalise"]["classes"] == ["computable"]
