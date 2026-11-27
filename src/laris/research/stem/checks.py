"""The deterministic steps of the STEM profile that the server calls as one remote tool (T284).

The Rust server runs the profile's loop (route, notes, draft, thinking budget, conclusion, vote,
notes check); the steps below stay in Python, where the reference harness (T278) runs them, so the
server and the harness execute the same code for them:

- `screen`: the prompt filter of T286 (normalised question and options, stop with its rule,
  quantities for the cross-check) and whether the prompt carries a STEM signal;
- `model_free`: the strict patterns of T276 and the solver (`formalise.answer_model_free`);
- `repair`: the mechanical fixes of a model's solver call (`harness.repair`);
- `solver_answer`: a verified solver result as an answer (an option letter or MATH-style LaTeX);
- `equivalent`: the frozen answer protocol (`answers.math_equivalent`);
- `crosscheck`: the numbers of a verified solver call against the quantities of the prompt.

Every operation is deterministic and model-free; none reads a gold answer. The tool is served by
the model service under the name `stem_check` and is not offered to the chat model (it is absent
from `GET /v1/tools`). Inference only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from laris.research.stem.data import LETTERS

OPERATIONS = ("screen", "model_free", "repair", "solver_answer", "equivalent", "crosscheck")


class StemCheckError(ValueError):
    """Bad arguments: `code` is a tool error type, the message carries no input text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _text(args: Dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise StemCheckError("invalid_arguments", f"{key} must be a string")
    return value


def _options(args: Dict[str, Any]) -> List[str]:
    value = args.get("options") or []
    if not isinstance(value, list) or not all(isinstance(o, str) for o in value):
        raise StemCheckError("invalid_arguments", "options must be a list of strings")
    if len(value) > len(LETTERS):
        raise StemCheckError("invalid_arguments", "too many options")
    return value


def _object(args: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = args.get(key)
    if not isinstance(value, dict):
        raise StemCheckError("invalid_arguments", f"{key} must be an object")
    return value


class StemChecks:
    """The operations, configured from `configs/stem-benchmarks.json` (`config`), with relative
    paths resolved against `root` and the solver's limits in `solver`."""

    def __init__(self, config: Path, root: Path, solver: Any) -> None:
        from laris.research.stem import prompt_filter

        cfg = json.loads(config.read_text(encoding="utf-8"))
        self.harness = cfg["harness"]
        self.equivalence = cfg["equivalence"]
        self.solver = solver
        rules = (self.harness.get("filter") or {}).get("rules")
        self.filter = prompt_filter.load(root / rules, root) if rules else None

    def call(self, args: Dict[str, Any]) -> Dict[str, Any]:
        op = args.get("op")
        if op not in OPERATIONS:
            raise StemCheckError("invalid_arguments", "op must be one of " + ", ".join(OPERATIONS))
        return getattr(self, "_" + str(op))(args)

    def _screen(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if self.filter is None:
            raise StemCheckError("rejected", "the prompt filter is not configured")
        question, options = _text(args, "question"), _options(args)
        out = self.filter.screen({"question": question, "options": options})
        signal = False
        if not out.stopped:
            folded = self.filter.fold("\n".join([out.question] + out.options))
            signal = self.filter.stem_signal(folded, out.options, out.quantities)
        return {
            "status": out.status,
            "stopped": out.stopped,
            "rule": out.rule,
            "question": out.question,
            "options": out.options,
            "quantities": [q.as_dict() for q in out.quantities],
            "stem_signal": bool(signal),
            "record": out.record(),
        }

    def _model_free(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from laris.research.stem.formalise import answer_model_free

        item = {"question": _text(args, "question"), "options": []}
        return answer_model_free(item, self.solver)

    def _repair(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from laris.research.stem.harness import repair

        problem, fixes = repair(_object(args, "problem"))
        # the problem as the review prompt shows it (`json.dumps`, key order kept)
        return {
            "problem": problem,
            "fixes": fixes,
            "problem_json": json.dumps(problem, ensure_ascii=False),
        }

    def _solver_answer(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from laris.research.stem.harness import solver_answer

        answer = solver_answer(
            _object(args, "result"),
            _text(args, "question"),
            _options(args),
            float(self.harness["solver_check"]["option_rel_tol"]),
        )
        return {"answer": answer}

    def _equivalent(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from laris.research.stem import answers

        eq = self.equivalence
        equal = answers.math_equivalent(
            _text(args, "a"), _text(args, "b"), float(eq["numeric_rel_tol"]), float(eq["timeout_s"])
        )
        return {"equal": bool(equal)}

    def _crosscheck(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from laris.research.stem.prompt_filter import Quantity, crosscheck

        check = self.harness.get("formalisation_check") or {}
        if not check:
            return {"checked": False}
        raw = args.get("quantities") or []
        if not isinstance(raw, list):
            raise StemCheckError("invalid_arguments", "quantities must be a list")
        quantities = [
            Quantity(float(q["value"]), str(q.get("unit") or ""))
            for q in raw
            if isinstance(q, dict)
        ]
        out = crosscheck(_object(args, "problem"), quantities, check)
        return dict(out, checked=True, action=check.get("action"))


def load(config: str, root: str, solver: Any) -> Optional[StemChecks]:
    """The checks when `config` names a file, else None (the tool is then not served)."""
    if not config:
        return None
    base = Path(root) if root else Path.cwd()
    path = Path(config)
    return StemChecks(path if path.is_absolute() else base / path, base, solver)
