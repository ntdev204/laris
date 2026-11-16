"""Formatters and held-out guards for the T200 QA and paraphrase sources.

QA: DuoRC, ROPES, Quoref and DROP are converted to the loader's QA schema (`id`, `title`, `context`,
`question`, `answers{text, answer_start}`). A row is kept only when its answer can be pointed at in
the context; a row that cannot is dropped and counted, never relabelled "no answer". The only
unanswerable rows are the ones the source itself marks (DuoRC `no_answer`).

Paraphrase: PAWS-Wiki swap and unlabeled rows get a `label_source` column (`human` or `model`).

Both families are checked against held-out data with the rule of T197: normalised exact match and
an eight-word window. Nothing here trains or fits.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import numpy as np
import pyarrow as pa

WINDOW = 8
LABEL_SOURCE_HUMAN = "human"
LABEL_SOURCE_MODEL = "model"
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

QA_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("title", pa.string()),
        ("context", pa.string()),
        ("question", pa.string()),
        (
            "answers",
            pa.struct([("text", pa.list_(pa.string())), ("answer_start", pa.list_(pa.int32()))]),
        ),
    ]
)
PARAPHRASE_SCHEMA = pa.schema(
    [
        ("sentence1", pa.string()),
        ("sentence2", pa.string()),
        ("label", pa.int64()),
        ("label_source", pa.string()),
    ]
)


# --------------------------------------------------------------------------- text keys


def normalise(text: str) -> str:
    """Lower-case and keep letters and digits only (the rule of T197 and check_sts_leakage.py)."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def window_hashes(text: str, size: int = WINDOW) -> np.ndarray:
    """64-bit hashes of every run of `size` normalised words (empty when the text is shorter)."""
    words = normalise(text).split()
    return np.fromiter(
        (
            int.from_bytes(
                hashlib.blake2b(" ".join(words[i : i + size]).encode(), digest_size=8).digest(),
                "big",
            )
            for i in range(len(words) - size + 1)
        ),
        dtype=np.uint64,
    )


class WindowIndex:
    """Sorted eight-word window hashes of held-out texts, plus their normalised exact strings."""

    def __init__(self, texts: Iterable[str]) -> None:
        chunks: List[np.ndarray] = []
        self.exact: Set[str] = set()
        for text in texts:
            norm = normalise(text)
            if norm:
                self.exact.add(norm)
            chunks.append(window_hashes(text))
        self.hashes = np.unique(np.concatenate(chunks)) if chunks else np.empty(0, np.uint64)

    def hit(self, text: str) -> Optional[str]:
        """'exact' when the normalised text is held out, 'window' on an eight-word overlap."""
        norm = normalise(text)
        if norm and norm in self.exact:
            return "exact"
        grams = window_hashes(text)
        if len(grams) and len(self.hashes):
            # `hashes` is sorted and unique: a binary search per window (np.isin would re-sort it).
            at = np.searchsorted(self.hashes, grams)
            at[at == len(self.hashes)] = 0
            if (self.hashes[at] == grams).any():
                return "window"
        return None


# --------------------------------------------------------------------------- answer location


def locate_answer(context: str, answer: str) -> Optional[Tuple[int, str, int]]:
    """(character start, text as written in the context, occurrences) or None.

    An exact match wins; otherwise a case-insensitive match, whose text is taken from the
    context so that `context[start:start + len(text)] == text` always holds.
    """
    answer = (answer or "").strip()
    if not answer:
        return None
    start = context.find(answer)
    if start >= 0:
        return start, answer, len(re.findall(re.escape(answer), context))
    matches = list(re.finditer(re.escape(answer), context, flags=re.IGNORECASE))
    if not matches:
        return None
    return matches[0].start(), matches[0].group(0), len(matches)


def _first_located(context: str, candidates: Sequence[str]) -> Optional[Tuple[int, str, int]]:
    """The first candidate found verbatim, else the first found ignoring case."""
    for candidate in candidates:
        if candidate.strip() and context.find(candidate.strip()) >= 0:
            return locate_answer(context, candidate)
    for candidate in candidates:
        found = locate_answer(context, candidate)
        if found:
            return found
    return None


def _row(
    source: str,
    native_id: str,
    title: str,
    context: str,
    question: str,
    answer: Optional[Tuple[int, str]],
) -> Dict[str, Any]:
    return {
        "id": f"{source}::{native_id}",
        "title": title or "",
        "context": context,
        "question": question,
        "answers": {
            "text": [answer[1]] if answer else [],
            "answer_start": [answer[0]] if answer else [],
        },
    }


def _strings(value: Any) -> List[str]:
    return [] if value is None else [str(v) for v in list(value) if v is not None]


def _kept(count: int) -> str:
    return "kept_answer" if count == 1 else "kept_answer_repeated"


# --------------------------------------------------------------------------- QA formatters
# Each returns (row or None, outcome): "kept_*" or "dropped_<reason>".


def format_duorc(row: Mapping[str, Any], variant: str) -> Tuple[Optional[Dict[str, Any]], str]:
    context, question = row.get("plot") or "", row.get("question") or ""
    native = f"{variant}::{row.get('question_id')}"
    title = row.get("title") or ""
    if not context.strip() or not question.strip():
        return None, "dropped_empty_text"
    if row.get("no_answer"):
        return _row("duorc_en", native, title, context, question, None), "kept_unanswerable"
    found = _first_located(context, _strings(row.get("answers")))
    if not found:
        return None, "dropped_answer_not_in_context"
    return _row("duorc_en", native, title, context, question, found[:2]), _kept(found[2])


def format_ropes(row: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    background, situation = row.get("background") or "", row.get("situation") or ""
    question = row.get("question") or ""
    if not situation.strip() or not question.strip():
        return None, "dropped_empty_text"
    # The situation comes first: it holds the answer, so a window cut falls on the background.
    context = f"{situation.strip()}\n\n{background.strip()}".strip()
    answers = row.get("answers")
    texts = _strings(answers.get("text") if isinstance(answers, Mapping) else answers)
    if not texts:
        return None, "dropped_no_answer_label"
    found = _first_located(context, texts)
    if not found:
        return None, "dropped_answer_not_in_context"
    return _row("ropes_en", str(row.get("id")), "", context, question, found[:2]), _kept(found[2])


def format_quoref(row: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    context, question = row.get("context") or "", row.get("question") or ""
    if not context.strip() or not question.strip():
        return None, "dropped_empty_text"
    answers = row.get("answers") or {}
    texts, starts = _strings(answers.get("text")), list(answers.get("answer_start") or [])
    if not texts or not texts[0]:
        return None, "dropped_no_answer_label"
    title, native = row.get("title") or "", str(row.get("id"))
    if starts and int(starts[0]) >= 0:
        start = int(starts[0])
        if context[start : start + len(texts[0])] == texts[0]:
            return _row("quoref_en", native, title, context, question, (start, texts[0])), (
                "kept_answer"
            )
    found = _first_located(context, texts)  # a wrong offset is repaired from the answer text
    if not found:
        return None, "dropped_answer_not_in_context"
    return _row("quoref_en", native, title, context, question, found[:2]), "kept_offset_repaired"


def format_drop(row: Mapping[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Span answers only: a number or date is usually computed, so the same string found in the
    passage would be a coincidence, not the answer."""
    context, question = row.get("passage") or "", row.get("question") or ""
    if not context.strip() or not question.strip():
        return None, "dropped_empty_text"
    answers = row.get("answers_spans") or {}
    spans, types = _strings(answers.get("spans")), _strings(answers.get("types"))
    if not spans:
        return None, "dropped_no_answer_label"
    if not types or types[0] != "span":
        return None, "dropped_not_a_span"
    found = _first_located(context, spans[:1])
    if not found:
        return None, "dropped_answer_not_in_context"
    return _row("drop_en", str(row.get("query_id")), "", context, question, found[:2]), _kept(
        found[2]
    )


# --------------------------------------------------------------------------- paraphrase


def paws_row(row: Mapping[str, Any], label_source: str) -> Optional[Dict[str, Any]]:
    first, second = (row.get("sentence1") or "").strip(), (row.get("sentence2") or "").strip()
    if not first or not second or row.get("label") not in (0, 1):
        return None
    return {
        "sentence1": first,
        "sentence2": second,
        "label": int(row["label"]),
        "label_source": label_source,
    }


def pair_key(a: str, b: str) -> str:
    x, y = sorted((normalise(a), normalise(b)))
    return f"{x}\x1f{y}"
