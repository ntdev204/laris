"""T280: development-iteration levers of the harness, with a scripted model (no GPU, no
training): a reply cut at its token cap is concluded into its answer."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from laris.research.stem import answers
from laris.research.stem import harness as h

from .test_cost import _cfg
from .test_harness import CONFIG, EQ, Scripted, _choice, _math, _solver

PROMPTS = CONFIG["harness"]["prompts"]


class Conclude:
    """Continuations by call order; records (prompt, partial, seed, max_tokens)."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: List[Tuple[str, str, int, int]] = []

    def __call__(self, prompt: str, partial: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        self.calls.append((prompt, partial, seed, max_tokens))
        return {
            "text": self.texts.pop(0),
            "prompt_tokens": 100,
            "generated_tokens": 3,
            "truncated": False,
            "seconds": 0.1,
        }


def _harness(cfg: Dict[str, Any], model: Any, conclude: Any) -> h.Harness:
    return h.Harness(
        cfg, CONFIG["baseline"], model, _solver(None), EQ, None, None, None, None, conclude
    )


def _on(**extra: Any) -> Dict[str, Any]:
    return _cfg(
        conclude=dict(CONFIG["harness"]["conclude"], enabled=True, replace_retry=False) | extra
    )


def test_the_frozen_candidate_concludes_first_and_thinks_on_knowledge() -> None:
    cfg = CONFIG["harness"]
    assert cfg["conclude"]["enabled"] is True and cfg["conclude"]["replace_retry"] is True
    assert cfg["draft"]["thinking"] == {"computable": 56000, "knowledge": 2048}  # T290, D67
    assert cfg["seed_offset"] == 0
    assert CONFIG["cost_levers"]["conclude"] == {"conclude": {"enabled": True}}
    assert CONFIG["cost_levers"]["conclude_first"]["conclude"]["replace_retry"] is True


def test_the_openings_lead_to_an_answer_the_extractors_read() -> None:
    assert (
        answers.extract_math_answer(PROMPTS["conclude_math"] + "\\frac{1}{2}}$") == "\\frac{1}{2}"
    )
    assert answers.extract_choice(PROMPTS["conclude_choice"] + " C", ["A", "B", "C", "D"]) == "C"


def test_a_retry_cut_again_is_concluded() -> None:
    model = Scripted(draft="TRUNC:long", retry="TRUNC:still long", formalise="NONE")
    more = Conclude("7}$")
    trace = _harness(_on(), model, more).answer(_math(), 100)
    assert trace.final == "7" and trace.concluded == 1 and not trace.truncated
    (prompt, partial, seed, cap) = more.calls[0]
    assert prompt.endswith(PROMPTS["retry_suffix"]) and partial.startswith("still long")
    assert partial.endswith(PROMPTS["conclude_math"]) and (seed, cap) == (1600, 96)
    step = [s for s in trace.steps if s["step"] == "conclude"][0]
    assert step == {"step": "conclude", "of": "retry", "tokens": 3, "answered": True}
    assert model.kinds() == ["draft", "retry", "formalise"]  # no second retry


def test_a_reply_that_ends_is_not_concluded() -> None:
    model = Scripted(draft="TRUNC:long", retry="\\boxed{2}", formalise="NONE")
    more = Conclude()
    trace = _harness(_on(), model, more).answer(_math(), 1)
    assert trace.final == "2" and trace.concluded == 0 and more.calls == []


def test_replace_retry_concludes_the_cut_draft_and_counts_as_retried() -> None:
    model = Scripted(draft="TRUNC:Answer: maybe A, but", formalise="NONE")
    item = _choice(["1 m", "2 m", "3 m", "4 m"], "How long is the rod in metres?")
    more = Conclude(" B")
    trace = _harness(_on(replace_retry=True), model, more).answer(item, 10)
    assert trace.draft == "B" and trace.retried and trace.concluded == 1
    assert "retry" not in model.kinds() and more.calls[0][2:] == (510, 16)


def test_cut_samples_of_the_vote_are_concluded() -> None:
    # the samples of a retried draft are drawn on the retry prompt
    model = Scripted(draft="TRUNC:a", retry=["TRUNC:r", "TRUNC:s", "TRUNC:t"], formalise="NONE")
    cfg = _on()
    cfg["self_consistency"] = {"enabled": True, "samples": 2, "when": ["retried"]}
    more = Conclude("5}$", "6}$", "5}$")
    trace = _harness(cfg, model, more).answer(_math(), 1)
    assert [c[1][0] for c in more.calls] == ["r", "s", "t"]
    assert trace.votes == {"5": 2, "6": 1} and trace.final == "5" and trace.concluded == 3


def test_concluding_needs_the_continuation_call() -> None:
    model = Scripted(draft="TRUNC:long", retry="TRUNC:long", formalise="NONE")
    with pytest.raises(ValueError):
        _harness(_on(), model, None).answer(_math(), 1)
