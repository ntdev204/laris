"""The STEM router of the evaluation profile (T278, ADR-026 section 4): one class per question.

- `computable`: the answer is a value obtained by calculation: every MATH item, and a multiple-
  choice item whose options are mostly numbers or quantities. The harness asks the model for a
  solver formalisation and checks the draft against the solver.
- `knowledge`: a multiple-choice item with word options and a short question: recall of facts and
  definitions; the harness puts notes of the main brain in the prompt and checks the draft against
  them.
- `reasoning`: the other multiple-choice items (word options, a long question: a scenario to reason
  through); notes are retrieved as for knowledge.

The rules read the item's shape only (options, digits, length) with thresholds from the
configuration; they never read the gold answer. Deterministic and model-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict

COMPUTABLE = "computable"
KNOWLEDGE = "knowledge"
REASONING = "reasoning"
CLASSES = (COMPUTABLE, KNOWLEDGE, REASONING)

_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Route:
    cls: str
    rule: str  # which rule decided, for the record
    features: Dict[str, Any] = field(default_factory=dict)  # what the rules read (T287)


def features(item: Dict[str, Any]) -> Dict[str, Any]:
    """The item-shape features the rules read, recorded with every decision (no text)."""
    options = item.get("options") or []
    return {
        "options": len(options),
        "numeric_option_share": round(numeric_share(options), 4),
        "question_words": len(str(item["question"]).split()),
    }


def numeric_share(options: Any) -> float:
    """Share of options that hold a digit."""
    if not options:
        return 0.0
    return sum(1 for o in options if _DIGIT.search(str(o))) / len(options)


def route(item: Dict[str, Any], cfg: Dict[str, Any]) -> Route:
    """The class of `item` under the router settings `cfg` (`numeric_option_share`,
    `knowledge_max_question_words`)."""
    seen = features(item)
    if not seen["options"]:
        return Route(COMPUTABLE, "open_answer", seen)
    if numeric_share(item["options"]) >= float(cfg["numeric_option_share"]):
        return Route(COMPUTABLE, "numeric_options", seen)
    if seen["question_words"] <= int(cfg["knowledge_max_question_words"]):
        return Route(KNOWLEDGE, "word_options_short_question", seen)
    return Route(REASONING, "word_options_long_question", seen)
