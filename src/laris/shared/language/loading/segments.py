"""Two-segment sequences from MLM passages (T194): pair-format MLM and sentence-order records.

A passage is cut at a sentence or paragraph boundary into two consecutive segments `a` and `b`
of one document. Pair-format MLM uses `[CLS] a [SEP] b [SEP]`; the sentence-order task labels
each two-segment sequence with one of three classes:

* ``ORDER_IN_ORDER`` (0): `a` then `b`;
* ``ORDER_SWAPPED`` (1): `b` then `a`;
* ``ORDER_OTHER_DOCUMENT`` (2): `a` then a segment of another document of the same split.

When a segment is too long for the window, `a` keeps its tail and `b` its head, so the
junction between the two consecutive segments survives truncation.
"""

import random
import re
import zlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

ORDER_IN_ORDER, ORDER_SWAPPED, ORDER_OTHER_DOCUMENT = 0, 1, 2
ORDER_CLASSES = ("in_order", "swapped", "other_document")
IGNORE_INDEX = -100

# End of a sentence (punctuation, optional closing quote or bracket, whitespace, then an
# optional opening quote and a capital letter) or a blank line between paragraphs. The same
# rule as the T193 supply count, in Python syntax.
_BOUNDARY = re.compile(r"(?<=[.!?])[\"'\)\]”’]*\s+(?=[\"'“]?[A-Z])|\n\s*\n")


def document_id(record: Dict[str, Any]) -> str:
    """Document of an MLM row: `doc#k` -> `doc`; without an id, a checksum of the text."""
    raw = record.get("id")
    if raw is None or raw == "":
        text = record.get("text") or record.get("content") or record.get("document") or ""
        return f"crc:{zlib.crc32(str(text).encode('utf-8'))}"
    doc, sep, num = str(raw).rpartition("#")
    return doc if sep and num.isdigit() else str(raw)


def split_units(text: str) -> List[str]:
    """Sentences and paragraphs of a passage, in order, without empty pieces."""
    return [piece.strip() for piece in _BOUNDARY.split(text) if piece and piece.strip()]


def cut_two_segments(text: str, rng: random.Random) -> Optional[Tuple[str, str]]:
    """Two consecutive segments of one passage, cut at a boundary chosen uniformly.

    Returns None when the passage has fewer than two sentences or paragraphs.
    """
    units = split_units(text)
    if len(units) < 2:
        return None
    cut = rng.randint(1, len(units) - 1)
    return " ".join(units[:cut]), " ".join(units[cut:])


def fit_pair(first: List[int], second: List[int], budget: int) -> Tuple[List[int], List[int]]:
    """Shorten two segments to `budget` tokens in total, keeping the tokens at their junction.

    Each segment gets half of the budget; a short segment gives its unused share to the other.
    The first segment keeps its tail and the second its head.
    """
    budget = max(0, budget)
    if len(first) + len(second) <= budget:
        return list(first), list(second)
    half = budget // 2
    keep_first = min(len(first), max(half, budget - len(second)))
    keep_second = min(len(second), budget - keep_first)
    return list(first[len(first) - keep_first :]), list(second[:keep_second])


def build_pair_sequence(
    first: List[int],
    second: List[int],
    seq_len: int,
    cls_id: int,
    sep_id: int,
    pad_id: int,
) -> Tuple[List[int], List[int]]:
    """`[CLS] first [SEP] second [SEP]` padded to `seq_len`, with its attention mask."""
    head, tail = fit_pair(first, second, seq_len - 3)
    seq = [cls_id] + head + [sep_id] + tail + [sep_id]
    pad = max(0, seq_len - len(seq))
    return seq[:seq_len] + [pad_id] * pad, [1] * min(len(seq), seq_len) + [0] * pad


def draw_order_class(rng: random.Random, shares: Sequence[float]) -> int:
    """One of the three order classes with the configured shares."""
    return rng.choices((ORDER_IN_ORDER, ORDER_SWAPPED, ORDER_OTHER_DOCUMENT), weights=shares)[0]


def validate_shares(shares: Sequence[float]) -> Tuple[float, float, float]:
    """Three finite, non-negative order-class shares with a positive sum."""
    values = tuple(float(s) for s in shares)
    if len(values) != 3 or any(not (s >= 0.0 and s < float("inf")) for s in values):
        raise ValueError("order_class_shares needs three finite, non-negative values")
    if sum(values) <= 0.0:
        raise ValueError("order_class_shares must not all be zero")
    return values[0], values[1], values[2]
