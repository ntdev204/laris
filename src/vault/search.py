"""BM25 over vault notes (title, properties' text and body), deterministic and dependency-free."""

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from vault.index import VaultIndex

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
K1, B = 1.5, 0.75
TITLE_WEIGHT = 3  # a title word counts as this many body words


def tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


@dataclass(frozen=True)
class Hit:
    path: str
    score: float


class NoteSearch:
    def __init__(self, index: VaultIndex, folders: Sequence[str] = ()) -> None:
        self.index = index
        self._docs: Dict[str, Dict[str, int]] = {}
        self._len: Dict[str, int] = {}
        for path, note in sorted(index.notes.items()):
            if folders and path.split("/")[0] not in folders:
                continue
            words = tokens(note.body) + tokens(note.title) * TITLE_WEIGHT
            counts: Dict[str, int] = {}
            for word in words:
                counts[word] = counts.get(word, 0) + 1
            self._docs[path] = counts
            self._len[path] = len(words)
        self._avg = (sum(self._len.values()) / len(self._len)) if self._len else 0.0
        self._df: Dict[str, int] = {}
        for counts in self._docs.values():
            for word in counts:
                self._df[word] = self._df.get(word, 0) + 1

    def search(self, query: str, limit: int = 10) -> List[Hit]:
        terms = sorted(set(tokens(query)))
        n = len(self._docs)
        scored: List[Tuple[float, str]] = []
        for path, counts in self._docs.items():
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                norm = tf + K1 * (1 - B + B * self._len[path] / (self._avg or 1.0))
                score += idf * tf * (K1 + 1) / norm
            if score > 0:
                scored.append((round(score, 8), path))
        scored.sort(key=lambda r: (-r[0], r[1]))
        return [Hit(path, score) for score, path in scored[:limit]]
