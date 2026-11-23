"""13-gram leakage scanner (T275, ADR-026 gate B6).

Benchmark questions and options are cut into word n-grams (lower case, letters and digits only);
every note under a folder is cut the same way, and every shared n-gram is a hit. A hit names the
note, the item id and the n-gram's SHA-256, never the text, so a report on GPQA leaks nothing.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set

_WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> List[str]:
    return _WORD.findall(text.lower())


def ngrams(text: str, n: int) -> Set[str]:
    tokens = words(text)
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _hash(gram: str) -> str:
    return hashlib.sha256(gram.encode("utf-8")).hexdigest()


def item_index(items: Iterable[Dict], n: int) -> Dict[str, Set[str]]:
    """n-gram -> ids of the items whose question or an option contains it."""
    index: Dict[str, Set[str]] = {}
    for item in items:
        texts = [item["question"], *item.get("options", [])]
        grams: Set[str] = set()
        for text in texts:
            grams |= ngrams(text, n)
        for gram in grams:
            index.setdefault(gram, set()).add(item["id"])
    return index


def scan_texts(texts: Dict[str, str], index: Dict[str, Set[str]], n: int) -> List[Dict]:
    """Hits of named texts against an item index, sorted by name and item id."""
    hits = []
    for name in sorted(texts):
        for gram in sorted(ngrams(texts[name], n) & index.keys()):
            for item_id in sorted(index[gram]):
                hits.append({"note": name, "item": item_id, "ngram_sha256": _hash(gram)})
    return sorted(hits, key=lambda h: (h["note"], h["item"], h["ngram_sha256"]))


def scan_folder(
    folder: Path, items: Iterable[Dict], n: int = 13, suffixes: Sequence[str] = (".md", ".txt")
) -> List[Dict]:
    """Hits of every note under `folder` (by suffix) against the benchmark items."""
    texts = {
        str(path.relative_to(folder)): path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(Path(folder).rglob("*"))
        if path.is_file() and path.suffix in suffixes
    }
    return scan_texts(texts, item_index(items, n), n)
