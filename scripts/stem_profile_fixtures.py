"""T284: parity fixtures for the server's STEM profile.

Runs the Python reference harness (`laris.research.stem.harness.Harness`, the harness section of
`configs/stem-benchmarks.json`, i.e. the frozen candidate) on scripted scenarios: a scripted model,
solver and model-free path, and a scripted chat template. It records, in order, every call the
harness made (chat prompts, raw completions, solver problems; with seeds and token caps), the
results of its deterministic steps (repair, solver answer, answer equivalence, cross-check; the
server takes them from the `stem_check` tool) and the trace. The Rust test
`crates/laris-server/src/stem/tests.rs` replays the same replies through the server's loop and
must make the same calls and reach the same trace.

    python scripts/stem_profile_fixtures.py [--check]

No model, no network, no item of any benchmark: the questions are written here.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "crates/laris-server/tests/fixtures/stem_parity.json"

from laris.research.stem import answers, prompt_filter  # noqa: E402
from laris.research.stem import harness as H  # noqa: E402


def key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def reply(text: str, truncated: bool = False, tokens: int = 10) -> Dict[str, Any]:
    return {"text": text, "truncated": truncated, "generated_tokens": tokens, "prompt_tokens": 7}


def run(scenario: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    hcfg = copy.deepcopy(cfg["harness"])
    for path, value in scenario.get("override", {}).items():
        node = hcfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    replies = list(scenario["replies"])
    solver = list(scenario.get("solver", []))
    calls: List[Dict[str, Any]] = []
    tables: Dict[str, Dict[str, Any]] = {
        "repair": {},
        "solver_answer": {},
        "equivalent": {},
        "crosscheck": {},
    }

    def template(prompt: str, thinking: bool = True) -> str:
        return f"<T{int(thinking)}>{prompt}</T>"

    def pop(call: Dict[str, Any]) -> Dict[str, Any]:
        calls.append(call)
        out = dict(replies.pop(0))
        out["seconds"] = 0.0
        return out

    def model(prompt: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        return pop({"kind": "chat", "text": prompt, "seed": seed, "max_tokens": max_tokens})

    def complete(raw: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        return pop(
            {
                "kind": "complete",
                "text": raw,
                "seed": seed,
                "max_tokens": max_tokens,
                "mode": "thinking_on",
            }
        )

    def conclude(prompt: str, partial: str, seed: int, max_tokens: int) -> Dict[str, Any]:
        raw = template(prompt, thinking=False) + partial
        return pop(
            {
                "kind": "complete",
                "text": raw,
                "seed": seed,
                "max_tokens": max_tokens,
                "mode": hcfg["mode"],
            }
        )

    def solve(problem: Dict[str, Any]):
        calls.append({"kind": "solve", "problem": problem})
        result, status = solver.pop(0)
        return result, status

    def model_free(item: Dict[str, Any]) -> Dict[str, Any]:
        return scenario["model_free"]

    real_repair, real_answer = H.repair, H.solver_answer
    real_equiv, real_cross = answers.math_equivalent, prompt_filter.crosscheck

    def repair(problem: Dict[str, Any]):
        fixed, fixes = real_repair(problem)
        tables["repair"][key(problem)] = {
            "problem": fixed,
            "fixes": fixes,
            "problem_json": json.dumps(fixed, ensure_ascii=False),
        }
        return fixed, fixes

    def solver_answer(result: Dict[str, Any], question: str, options: List[str], tol: float):
        out = real_answer(result, question, options, tol)
        tables["solver_answer"][key(result)] = out
        return out

    def equivalent(a: str, b: str, tol: float, timeout: float) -> bool:
        out = bool(real_equiv(a, b, tol, timeout))
        tables["equivalent"][key([a, b])] = out
        return out

    def crosscheck(problem: Dict[str, Any], quantities: List[Any], check: Dict[str, Any]):
        out = real_cross(problem, quantities, check)
        tables["crosscheck"][key(problem)] = out
        return out

    H.repair, H.solver_answer = repair, solver_answer
    answers.math_equivalent, prompt_filter.crosscheck = equivalent, crosscheck
    try:
        harness = H.Harness(
            hcfg,
            cfg["baseline"],
            model,
            solve,
            cfg["equivalence"],
            model_free if hcfg["model_free"] else None,
            None,
            complete,
            template,
            conclude,
        )
        quantities = scenario.get("quantities")
        if quantities is not None:
            quantities = [prompt_filter.Quantity(q["value"], q["unit"]) for q in quantities]
        trace = harness.answer(
            scenario["item"],
            scenario["seed"],
            scenario.get("notes"),
            scenario.get("certain"),
            quantities,
        )
    finally:
        H.repair, H.solver_answer = real_repair, real_answer
        answers.math_equivalent, prompt_filter.crosscheck = real_equiv, real_cross
    assert not replies, f"{scenario['name']}: {len(replies)} replies unused"
    expected = trace.as_dict()
    for k in ("model_seconds", "solver_seconds"):
        expected.pop(k)
    return dict(
        scenario,
        override=scenario.get("override", {}),
        calls=calls,
        tables=tables,
        expected=expected,
    )


MATH = {"question": "Let $f(x) = 2x + 3$. What is $f(1)$?", "options": []}
CHOICE_NUM = {
    "question": "A cart of mass 2 kg moves at 3 m/s. What is its momentum?",
    "options": ["6 kg m/s", "5 kg m/s", "1.5 kg m/s", "9 kg m/s"],
}
KNOWLEDGE = {
    "question": "Which organelle makes most of the cell's ATP?",
    "options": ["mitochondrion inner membrane", "ribosome", "golgi apparatus", "cell wall"],
}
LONG = {
    "question": " ".join(
        ["Consider a population of finches on an island where drought changes seeds."] * 6
    ),
    "options": ["directional selection", "genetic drift", "gene flow", "balancing selection"],
}
CLOSED = "reasoning here</think>\n\nSo \\boxed{5}."
VERIFIED = {"status": "verified", "answer": "5", "numeric": "5", "text": "5", "latex": "5"}
SEVEN = {"status": "verified", "answer": "7", "numeric": "7", "text": "7", "latex": "7"}
FORMAL = '{"operation": "evaluate", "expression": "x = 2*1+3", "unit": "none"}'

SCENARIOS: List[Dict[str, Any]] = [
    {
        "name": "model_free_answers_without_the_model",
        "item": MATH,
        "seed": 47624,
        "model_free": {"pattern": "evaluate", "status": "verified", "answer": "5"},
        "replies": [],
    },
    {
        "name": "thinking_budget_closes_and_the_draft_stands",
        "item": MATH,
        "seed": 47624,
        "model_free": {"pattern": None, "status": "not_formalised", "answer": None},
        "replies": [reply(CLOSED, tokens=900)],
    },
    {
        "name": "a_budget_that_runs_out_is_closed_and_answered",
        "item": MATH,
        "seed": 47624,
        "model_free": {"pattern": None, "status": "not_formalised", "answer": None},
        "replies": [reply("long reasoning", truncated=True, tokens=56000), reply("\\boxed{5}")],
    },
    {
        "name": "a_cut_draft_is_concluded_then_voted_against_the_solver",
        "item": MATH,
        "seed": 1234,
        "quantities": [],
        "model_free": {"pattern": None, "status": "not_formalised", "answer": None},
        "replies": [
            reply("long reasoning", truncated=True, tokens=56000),
            reply("the value is", truncated=True, tokens=1024),
            reply("5}"),
            reply(FORMAL),
            reply("\\boxed{7}"),
            reply("Final answer: 7"),
        ],
        "solver": [[SEVEN, "verified"]],
    },
    {
        "name": "no_draft_takes_the_solver_answer",
        "item": MATH,
        "seed": 99,
        "quantities": [{"value": 2.0, "unit": ""}, {"value": 3.0, "unit": ""}],
        "override": {"conclude.enabled": False, "draft.thinking": {}},
        "model_free": {"pattern": None, "status": "not_formalised", "answer": None},
        "replies": [
            reply("no answer", truncated=True, tokens=4096),
            reply("still nothing", truncated=True, tokens=4096),
            reply(FORMAL),
        ],
        "solver": [[VERIFIED, "verified"]],
    },
    {
        "name": "computable_choice_concluded_and_agreeing_with_the_solver",
        "item": CHOICE_NUM,
        "seed": 777,
        "replies": [
            reply("p = mv</think>\n\nso the answer", truncated=True, tokens=1024),
            reply("A"),
            reply('{"operation": "evaluate", "expression": "2*3"}'),
        ],
        "solver": [[{"status": "verified", "numeric": "6", "text": "6"}, "verified"]],
    },
    {
        "name": "knowledge_with_notes_and_the_notes_check",
        "item": KNOWLEDGE,
        "seed": 5,
        "notes": [
            "The mitochondrion inner membrane holds the electron transport chain that makes ATP.",
            "Ribosomes translate mRNA.",
        ],
        "replies": [reply("thinking</think>\n\nAnswer: B"), reply("Answer: A")],
    },
    {
        "name": "reasoning_without_support_keeps_the_draft",
        "item": LONG,
        "seed": 8,
        "notes": ["Finches on islands were studied for decades."],
        "replies": [reply("Answer: A")],
    },
    {
        "name": "a_cut_reasoning_draft_is_voted_on_the_retry_prompt",
        "item": LONG,
        "seed": 8,
        "replies": [
            reply("I think", truncated=True, tokens=4096),
            reply(" C"),
            reply("Answer: C"),
            reply("Answer: D"),
        ],
    },
    {
        "name": "without_conclusion_a_cut_draft_is_retried_and_reviewed",
        "item": MATH,
        "seed": 3,
        "override": {
            "conclude.enabled": False,
            "self_consistency.enabled": False,
            "formalise.review": True,
            "draft.thinking": {},
        },
        "model_free": {"pattern": None, "status": "not_formalised", "answer": None},
        "replies": [
            reply("cut", truncated=True, tokens=4096),
            reply("\\boxed{5}"),
            reply(FORMAL),
            reply("\\boxed{7}"),
        ],
        "solver": [[SEVEN, "verified"]],
    },
]


def build() -> Dict[str, Any]:
    cfg = json.loads((ROOT / "configs/stem-benchmarks.json").read_text(encoding="utf-8"))
    return {
        "note": "generated by scripts/stem_profile_fixtures.py from the Python reference harness;"
        " do not edit",
        "scenarios": [run(s, cfg) for s in SCENARIOS],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the fixture is stale")
    args = parser.parse_args(argv)
    text = json.dumps(build(), indent=1, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is stale: run scripts/stem_profile_fixtures.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
