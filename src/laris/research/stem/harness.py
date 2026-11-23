"""The STEM harness of the evaluation profile (T278, ADR-026 section 4).

One benchmark item in, one final answer out (pass@1), with every step and its cost recorded:

1. **Route** (`router.route`): computable, knowledge or reasoning.
2. **Model-free** (computable, open answer): the strict patterns of T276 and the solver; a verified
   result is the answer and the model is not called (gate B5 counts these).
3. **Notes** (classes in `retrieval.classes`): passages of the frozen brain snapshot, retrieved by
   the caller beforehand, go into the draft prompt. Closed book: nothing else is read.
4. **Draft**: the model answers the benchmark prompt. An unparsed or truncated draft is retried with
   a request to be brief and another seed, up to `draft.max_retries` times.
5. **Formalisation** (classes in `formalise.classes`): the model writes one solver call for the
   quantity asked; the solver computes it. A `verified` result is compared with the draft: an
   agreement ends the item; a disagreement asks the model to review the draft against the result.
   When no draft could be read, the solver's value (or the option it matches) is the answer.
6. **Notes check** (multiple choice with notes): when the notes support exactly one option, by all
   of its content words in one passage, and the draft chose another, the model reviews the draft
   against those notes.

The harness never sees the gold answer; the caller scores the draft and the final answer, so the
effect of every check is measured on the same run. No citations are asked for in this profile
(answers are a letter or a value); the evidence gate of normal chat is unchanged. Inference only.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from laris.research.stem import answers
from laris.research.stem.data import LETTERS
from laris.research.stem.router import COMPUTABLE, route

# A model call: (prompt, seed, max_tokens) -> {"text", "prompt_tokens", "generated_tokens",
# "truncated", "seconds"}; `text` may hold a <think> block, which the harness drops.
ModelCall = Callable[[str, int, int], Dict[str, Any]]
# A solver call: problem -> (result or None, status: "verified" | "proposal" | "refused:<code>")
SolverCall = Callable[[Dict[str, Any]], Tuple[Optional[Dict[str, Any]], str]]
# The model-free path: item -> {"pattern", "status", "answer"} (formalise.answer_model_free)
ModelFree = Callable[[Dict[str, Any]], Dict[str, Any]]

_STOP = frozenset(
    "the and for are but not with that this from was were has have had its into than then them "
    "they their there which what when where who whom whose why how all any each both few more most "
    "other some such only own same can will just should would could may might must also very "
    "does did doing been being one two used use uses using between because over under about".split()
)
_NUMBER = re.compile(
    r"(?<![\w.])([-+−]?\d+(?:[.,]\d+)?)(?:\s*(?:×|x|\*|\\times)\s*10\s*\^?\s*\{?\s*([-+−]?\d+)\s*\}?"
    r"|\s*[eE]\s*([-+−]?\d+))?"
)


def content_words(text: str) -> List[str]:
    """Lowercase words of three letters or more, without common function words."""
    return [w for w in re.findall(r"[a-z][a-z-]{2,}", text.lower()) if w not in _STOP]


def option_value(text: str) -> Optional[float]:
    """The first number of an option ("5.6 × 10^-3 M" -> 0.0056), or None."""
    match = _NUMBER.search(str(text))
    if not match:
        return None
    mantissa = float(match.group(1).replace("−", "-").replace(",", "."))
    exponent = match.group(2) or match.group(3)
    if exponent:
        mantissa *= 10.0 ** int(exponent.replace("−", "-"))
    return mantissa


def solver_value(result: Dict[str, Any]) -> Optional[float]:
    """A real number from a solver result (`numeric`, or a one-value answer), or None."""
    from fractions import Fraction

    candidates: List[Any] = [result.get("numeric")]
    answer = result.get("answer")
    if isinstance(answer, list) and len(answer) == 1:
        answer = answer[0]
    if isinstance(answer, (str, int, float)):
        candidates.append(answer)
    for value in candidates:
        if value is None:
            continue
        try:
            return float(Fraction(str(value).strip()))
        except (ValueError, ZeroDivisionError):
            try:
                return float(str(value).strip())
            except ValueError:
                continue
    return None


def match_option(value: float, options: List[str], rel_tol: float) -> Optional[int]:
    """The index of the one option whose number lies within `rel_tol` of `value`, else None."""
    close = []
    for index, option in enumerate(options):
        number = option_value(option)
        if number is None:
            continue
        scale = max(abs(value), abs(number), 1e-300)
        if abs(number - value) <= rel_tol * scale:
            close.append(index)
    return close[0] if len(close) == 1 else None


def first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """The first balanced `{...}` of `text` that parses as a JSON object, or None."""
    start = text.find("{")
    while start != -1:
        depth, quoted, escaped = 0, False, False
        for end in range(start, len(text)):
            char = text[end]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : end + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


_IDENT = r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"
_ASSIGNMENT = re.compile(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*=(?!=)(.+)\Z", re.S)


def _rename(text: Any, old: str, new: str) -> Any:
    if isinstance(text, str):
        return re.sub(_IDENT.format(re.escape(old)), lambda _: new, text)
    if isinstance(text, list):
        return [_rename(t, old, new) for t in text]
    return text


def repair(problem: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Mechanical fixes of a model's solver call, each named in the returned list; the meaning is
    unchanged and the solver still checks the result.

    - `evaluate` of `name = formula`: the formula.
    - a name the solver keeps for itself (`E`, `I`, `pi`, a function, a Python keyword) used as a
      variable: renamed with a `_v` suffix wherever it appears.
    - `substitutions` on an operation that does not read them: numbers and plain expressions are
      written into the expression(s) in parentheses; a constant lookup is left, so the solver
      refuses the call.
    - a field the operation does not read: dropped.
    """
    import keyword

    from laris.model.solver.engine import COMMON, OPERATIONS
    from laris.model.solver.expr import CONSTANTS, FUNCTIONS

    fixed = dict(problem)
    notes: List[str] = []
    operation = fixed.get("operation")
    if operation not in OPERATIONS:
        return fixed, notes
    fields = set(OPERATIONS[operation][2]) | set(COMMON)
    text_keys = [k for k in ("expression", "expressions", "variable", "variables") if k in fixed]
    expression = fixed.get("expression")
    if operation == "evaluate" and isinstance(expression, str):
        match = _ASSIGNMENT.match(expression)
        if match:
            fixed["expression"] = match.group(1).strip()
            notes.append("assignment")
    subs = fixed.get("substitutions")
    subs = dict(subs) if isinstance(subs, dict) else None
    reserved = set(CONSTANTS) | set(FUNCTIONS)
    names = set(subs or {})
    for key in ("variable", "variables"):
        value = fixed.get(key)
        names |= (
            {value} if isinstance(value, str) else set(v for v in value or [] if isinstance(v, str))
        )
    for word in keyword.kwlist:
        if any(re.search(_IDENT.format(word), str(fixed.get(k))) for k in text_keys):
            names.add(word)
    for name in sorted(names):
        if name in reserved or keyword.iskeyword(name):
            new = name + "_v"
            for key in text_keys:
                fixed[key] = _rename(fixed[key], name, new)
            if subs is not None and name in subs:
                subs[new] = subs.pop(name)
            notes.append("renamed")
    if subs is not None:
        fixed["substitutions"] = subs
        if "substitutions" not in fields:
            plain = all(isinstance(v, (int, float, str)) for v in subs.values())
            if plain and any(k in fixed for k in ("expression", "expressions")):
                for name, value in subs.items():
                    for key in ("expression", "expressions"):
                        if key in fixed:
                            fixed[key] = _rename(fixed[key], name, f"({value})")
                del fixed["substitutions"]
                notes.append("inlined")
    for key in [k for k in fixed if k not in fields]:
        if key == "substitutions" and "inlined" not in notes and fixed[key]:
            continue  # a constant lookup the operation cannot take: the solver refuses it
        del fixed[key]
        notes.append("dropped")
    return fixed, notes


def fill(template: str, **values: str) -> str:
    """`template` with each `{name}` replaced by its value (no other braces are touched)."""
    for name, value in values.items():
        template = template.replace("{" + name + "}", value)
    return template


def prompt_for(item: Dict[str, Any], prompts: Dict[str, str]) -> str:
    """The benchmark prompt of T275 (`baseline.prompts`), unchanged."""
    if not item["options"]:
        return prompts["math"].replace("{question}", item["question"])
    letters = LETTERS[: len(item["options"])]
    return (
        prompts["choice"]
        .replace("{letters}", ", ".join(letters))
        .replace("{question}", item["question"])
        .replace("{options}", options_block(item))
    )


def options_block(item: Dict[str, Any]) -> str:
    letters = LETTERS[: len(item["options"])]
    return "\n".join(f"{letters[i]}. {text}" for i, text in enumerate(item["options"]))


@dataclass
class Trace:
    """What the harness did for one item: steps, answers and cost (no item text)."""

    cls: str
    rule: str
    features: Dict[str, Any] = field(default_factory=dict)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    model_free: bool = False
    brain_only: bool = False
    draft: Optional[str] = None
    final: Optional[str] = None
    final_from: str = ""
    truncated: bool = False
    solver_status: str = ""
    agreement: Optional[bool] = None
    notes: int = 0
    crosscheck: Optional[Dict[str, Any]] = None
    prompt_tokens: int = 0
    generated_tokens: int = 0
    model_calls: int = 0
    solver_calls: int = 0
    model_seconds: float = 0.0
    solver_seconds: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class Harness:
    """The evaluation profile's loop over one item; `cfg` is the `harness` section of
    `configs/stem-benchmarks.json`, `base` its `baseline` section (prompts and modes) and
    `equivalence` its `equivalence` section (the frozen answer protocol)."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        base: Dict[str, Any],
        model: ModelCall,
        solve: SolverCall,
        equivalence: Dict[str, Any],
        model_free: Optional[ModelFree] = None,
        choose: Optional[Callable[[Dict[str, Any], "Trace"], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        self.cfg = cfg
        self.equivalence = equivalence
        self.base = base
        self.mode = base["modes"][cfg["mode"]]
        self.prompts = cfg["prompts"]
        self.model = model
        self.solve = solve
        self.model_free = model_free
        # T287: after the deterministic steps, a router network may name another path; `choose`
        # returns that path's harness settings, or None to keep the rule router's
        self.choose = choose

    # -- steps ---------------------------------------------------------------------------------

    def _call(self, trace: Trace, step: str, prompt: str, seed: int, max_tokens: int) -> Dict:
        from laris.model.inference.open_llm import split_reasoning

        out = self.model(prompt, seed, max_tokens)
        trace.model_calls += 1
        trace.prompt_tokens += int(out["prompt_tokens"])
        trace.generated_tokens += int(out["generated_tokens"])
        trace.model_seconds += float(out["seconds"])
        _, text = split_reasoning(out["text"])
        out = dict(out, answer_text=text)
        trace.steps.append(
            {"step": step, "truncated": bool(out["truncated"]), "tokens": out["generated_tokens"]}
        )
        return out

    def _extract(self, item: Dict[str, Any], text: str) -> Optional[str]:
        if item["options"]:
            return answers.extract_choice(text, LETTERS[: len(item["options"])])
        return answers.extract_math_answer(text)

    def _solver(self, trace: Trace, problem: Dict[str, Any]) -> Tuple[Optional[Dict], str]:
        began = time.perf_counter()
        result, status = self.solve(problem)
        trace.solver_calls += 1
        trace.solver_seconds += time.perf_counter() - began
        trace.steps.append({"step": "solver", "status": status})
        return result, status

    def _draft(self, item: Dict[str, Any], trace: Trace, prompt: str, seed: int) -> Optional[str]:
        out = self._call(trace, "draft", prompt, seed, int(self.mode["max_new_tokens"]))
        answer = self._extract(item, out["answer_text"])
        truncated = bool(out["truncated"])
        for attempt in range(1, int(self.cfg["draft"]["max_retries"]) + 1):
            if answer is not None and not truncated:
                break
            retry = prompt + self.prompts["retry_suffix"]
            out = self._call(
                trace, "retry", retry, seed + 1000 * attempt, int(self.mode["max_new_tokens"])
            )
            again = self._extract(item, out["answer_text"])
            if again is not None:
                answer, truncated = again, bool(out["truncated"])
            elif answer is None:
                truncated = bool(out["truncated"])
        trace.truncated = truncated and answer is None
        return answer

    def _formalise(
        self, item: Dict[str, Any], trace: Trace, seed: int, quantities: Optional[List[Any]] = None
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """The model's solver call and the solver's verified result (or None for either)."""
        template = self.prompts["formalise_choice" if item["options"] else "formalise_math"]
        prompt = template.replace("{question}", item["question"])
        if item["options"]:
            prompt = prompt.replace("{options}", options_block(item))
        out = self._call(trace, "formalise", prompt, seed, int(self.cfg["formalise"]["max_tokens"]))
        problem = first_json_object(out["answer_text"])
        operation = problem.get("operation") if problem is not None else None
        if problem is None or not isinstance(operation, str) or operation.strip().upper() == "NONE":
            trace.solver_status = "not_formalised"
            return None, None
        problem, fixes = repair(problem)
        if fixes:
            trace.steps.append({"step": "repair", "fixes": sorted(set(fixes))})
        result, status = self._solver(trace, problem)
        trace.solver_status = status
        if status != "verified" or result is None:
            return problem, None
        check = self.cfg.get("formalisation_check") or {}
        if quantities is not None and check:
            from laris.research.stem.prompt_filter import crosscheck

            trace.crosscheck = crosscheck(problem, quantities, check)
            trace.steps.append(dict(step="crosscheck", **trace.crosscheck))
            if check.get("action") == "gate" and trace.crosscheck["ungrounded"]:
                trace.solver_status = "verified_ungrounded"
                return problem, None
        return problem, result

    def _solver_answer(self, item: Dict[str, Any], result: Dict[str, Any]) -> Optional[str]:
        """The solver's result as an answer: an option letter, or MATH-style LaTeX."""
        from laris.research.stem.formalise import _complex, math_style

        if item["options"]:
            value = solver_value(result)
            if value is None:
                return None
            index = match_option(
                value, item["options"], float(self.cfg["solver_check"]["option_rel_tol"])
            )
            return LETTERS[index] if index is not None else None
        if _complex(result) and not re.search(r"(?<![A-Za-z\\])i(?![A-Za-z])", item["question"]):
            return None  # SymPy's principal branch where the problem means a real value
        text = result.get("latex") or result.get("text")
        return math_style(text) if isinstance(text, str) and text else None

    def _agrees(self, item: Dict[str, Any], draft: str, solved: str) -> bool:
        if item["options"]:
            return draft == solved
        eq = self.equivalence
        return bool(
            answers.math_equivalent(
                draft, solved, float(eq["numeric_rel_tol"]), float(eq["timeout_s"])
            )
        )

    def _review(self, item: Dict[str, Any], trace: Trace, prompt: str, seed: int) -> Optional[str]:
        out = self._call(trace, "review", prompt, seed, int(self.mode["max_new_tokens"]))
        return self._extract(item, out["answer_text"])

    def _supported_option(self, item: Dict[str, Any], notes: List[str]) -> Optional[int]:
        """The one option whose content words all appear in one note, else None."""
        least = int(self.cfg["notes_check"]["min_option_words"])
        lowered = [set(content_words(n)) for n in notes]
        supported = []
        for index, option in enumerate(item["options"]):
            words = set(content_words(option))
            if len(words) < least:
                continue
            if any(words <= note for note in lowered):
                supported.append(index)
        return supported[0] if len(supported) == 1 else None

    # -- the loop ------------------------------------------------------------------------------

    def answer(
        self,
        item: Dict[str, Any],
        seed: int,
        notes: Optional[List[str]] = None,
        certain: Optional[List[str]] = None,
        quantities: Optional[List[Any]] = None,
    ) -> Trace:
        """`notes` are the passages shown to the model; `certain` the texts of the retrieved
        Claims that are certain (T285, `laris-server brain retrieve` with source classes), the
        only ones a brain-only answer may rest on; `quantities` those the prompt filter found in
        the question (T286), read only to cross-check the model's solver formalisation."""
        decided = route(item, self.cfg["router"])
        trace = Trace(cls=decided.cls, rule=decided.rule, features=dict(decided.features))
        notes = list(notes or [])

        only = self.cfg.get("brain_only") or {}
        if only.get("enabled") and item["options"] and certain:
            index = brain_only_option(item, certain, int(only["min_option_words"]))
            trace.steps.append(
                {"step": "brain_only", "answered": index is not None, "certain": len(certain)}
            )
            if index is not None:
                trace.brain_only = True
                trace.final, trace.final_from = LETTERS[index], "brain_only"
                return trace

        if decided.cls == COMPUTABLE and not item["options"] and self.model_free is not None:
            began = time.perf_counter()
            free = self.model_free(item)
            trace.solver_seconds += time.perf_counter() - began
            if free.get("pattern"):
                trace.solver_calls += 1
            trace.steps.append({"step": "model_free", "status": free["status"]})
            if free.get("answer") is not None:
                trace.model_free = True
                trace.final = str(free["answer"])
                trace.final_from = "model_free"
                trace.solver_status = "verified"
                return trace

        if self.cfg.get("deterministic_only"):
            return trace  # T287 path: the model-free and brain-only steps alone, no model

        if self.choose is not None:
            other = self.choose(item, trace)
            if other is not None:
                sub = Harness(
                    dict(other, model_free=False, brain_only={"enabled": False}),
                    self.base,
                    self.model,
                    self.solve,
                    self.equivalence,
                )
                chosen = sub.answer(item, seed, notes, certain, quantities)
                chosen.cls, chosen.rule, chosen.features = trace.cls, trace.rule, trace.features
                chosen.steps = trace.steps + chosen.steps
                chosen.solver_calls += trace.solver_calls
                chosen.solver_seconds += trace.solver_seconds
                return chosen

        base_prompt = prompt_for(item, self.base["prompts"])
        prompt = base_prompt
        if notes and decided.cls in self.cfg["retrieval"]["classes"]:
            cap = int(self.cfg["retrieval"]["max_chars_per_note"])
            shown = "\n".join(f"- {n[:cap].strip()}" for n in notes)
            prompt = self.prompts["notes_prefix"].replace("{notes}", shown) + base_prompt
            trace.notes = len(notes)
        trace.draft = self._draft(item, trace, prompt, seed)
        trace.final, trace.final_from = trace.draft, "draft"

        if decided.cls in self.cfg["formalise"]["classes"]:
            problem, result = self._formalise(item, trace, seed + 7, quantities)
            solved = self._solver_answer(item, result) if result is not None else None
            if solved is not None:
                if trace.draft is None:
                    trace.final, trace.final_from = solved, "solver_fallback"
                    return trace
                trace.agreement = self._agrees(item, trace.draft, solved)
                if trace.agreement:
                    return trace
                shown_value = result.get("text") if result else ""
                review = base_prompt + fill(
                    self.prompts["review_solver"],
                    draft=trace.draft,
                    problem=json.dumps(problem, ensure_ascii=False),
                    value=str(shown_value),
                )
                final = self._review(item, trace, review, seed + 13)
                if final is not None:
                    trace.final, trace.final_from = final, "review_solver"
                return trace

        if (
            item["options"]
            and trace.notes
            and trace.draft is not None
            and self.cfg["notes_check"]["enabled"]
        ):
            index = self._supported_option(item, notes)
            if index is not None and LETTERS[index] != trace.draft:
                cap = int(self.cfg["retrieval"]["max_chars_per_note"])
                shown = "\n".join(f"- {n[:cap].strip()}" for n in notes)
                review = base_prompt + fill(
                    self.prompts["review_notes"],
                    draft=trace.draft,
                    letter=LETTERS[index],
                    notes=shown,
                )
                trace.steps.append({"step": "notes_check", "supported": LETTERS[index]})
                final = self._review(item, trace, review, seed + 17)
                if final is not None:
                    trace.final, trace.final_from = final, "review_notes"
        return trace


def brain_only_option(item: Dict[str, Any], certain: List[str], least: int) -> Optional[int]:
    """The one option whose content words (at least `least` of them) all appear in one certain
    Claim while no other option's do, else None (T285). Only certain Claims are read; the rule
    never sees the gold answer."""
    claims = [set(content_words(text)) for text in certain]
    backed = []
    for index, option in enumerate(item["options"]):
        words = set(content_words(option))
        if len(words) >= least and any(words <= claim for claim in claims):
            backed.append(index)
    return backed[0] if len(backed) == 1 else None


# -- summaries ---------------------------------------------------------------------------------


def summarise_records(
    rows: List[Dict[str, Any]], baseline: Optional[Dict[str, bool]] = None
) -> Dict[str, Any]:
    """Accuracy, cost and what each step changed, over harness records (`correct`,
    `draft_correct`, `final_from`, `cls`, `model_free`, `cost`); `baseline` maps item ids to the
    T275 bare-model verdict, so the same items are compared."""
    from laris.research.stem import stats

    out = stats.summarise(rows)
    out["draft_correct"] = sum(1 for r in rows if r.get("draft_correct"))
    out["model_calls_mean"] = (
        sum(r["cost"]["model_calls"] for r in rows) / len(rows) if rows else 0.0
    )
    out["solver_calls_mean"] = (
        sum(r["cost"]["solver_calls"] for r in rows) / len(rows) if rows else 0.0
    )
    free = [r for r in rows if r.get("model_free")]
    out["model_free"] = {"answered": len(free), "wrong": sum(1 for r in free if not r["correct"])}
    alone = [r for r in rows if r.get("final_from") == "brain_only"]
    out["brain_only"] = {"answered": len(alone), "wrong": sum(1 for r in alone if not r["correct"])}
    sources: Dict[str, Dict[str, int]] = {}
    for r in rows:
        slot = sources.setdefault(r.get("final_from") or "none", {"items": 0, "correct": 0})
        slot["items"] += 1
        slot["correct"] += int(bool(r["correct"]))
    out["final_from"] = sources
    reviews: Dict[str, Dict[str, int]] = {}
    for r in rows:
        how = r.get("final_from")
        if how not in ("review_solver", "review_notes"):
            continue
        slot = reviews.setdefault(how, {"to_right": 0, "to_wrong": 0, "same": 0})
        if r["correct"] and not r.get("draft_correct"):
            slot["to_right"] += 1
        elif r.get("draft_correct") and not r["correct"]:
            slot["to_wrong"] += 1
        else:
            slot["same"] += 1
    out["review_flips"] = reviews
    checked = [r for r in rows if r.get("crosscheck")]
    ungrounded = [r for r in checked if r["crosscheck"]["ungrounded"]]
    out["crosscheck"] = {
        "checked": len(checked),
        "ungrounded": len(ungrounded),
        "ungrounded_correct": sum(1 for r in ungrounded if r["correct"]),
        "ungrounded_agreed": sum(1 for r in ungrounded if r.get("agreement") is True),
        # what `action: gate` would have scored: an ungrounded solver result is ignored, so the
        # draft stands (and an item that had only the solver's answer has none)
        "gate_correct": sum(
            1 for r in rows if (r.get("draft_correct") if r in ungrounded else r["correct"])
        ),
    }
    out["filter_stops"] = sum(1 for r in rows if r.get("final_from") == "filter_stop")
    agreed = [r for r in rows if r.get("agreement") is True]
    out["solver_agreed"] = {"items": len(agreed), "correct": sum(1 for r in agreed if r["correct"])}
    if baseline is not None:
        paired = [r for r in rows if r["id"] in baseline]
        base_right = sum(1 for r in paired if baseline[r["id"]])
        out["baseline"] = {
            "items": len(paired),
            "correct": base_right,
            "accuracy": base_right / len(paired) if paired else 0.0,
            "harness_correct": sum(1 for r in paired if r["correct"]),
            "gained": sum(1 for r in paired if r["correct"] and not baseline[r["id"]]),
            "lost": sum(1 for r in paired if baseline[r["id"]] and not r["correct"]),
        }
    return out
