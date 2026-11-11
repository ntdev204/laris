"""Graph-aware retrieval over the project vault, and navigation-first retrieval over the brain.

Notes: BM25 finds seed notes; the links around each seed are added with a decayed score (a note
that explains a hit is usually next to it, even when it shares no words with the query); results
are fused with the corpus search by reciprocal rank. Every result carries its provenance. The brain
is navigated first (route to a hub, expand along typed links) and searched only as a fallback; the
token use of what was returned is reported. Everything is deterministic.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

from vault.index import VaultIndex
from vault.project import source_title
from vault.search import NoteSearch

RRF_K = 60


@dataclass(frozen=True)
class Result:
    path: str
    score: float
    via: str  # bm25 | link | corpus
    seed: str = ""  # for a link result: the note whose neighbourhood brought it in
    detail: str = ""


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    return int(math.ceil(len(text) / chars_per_token))


class GraphRetriever:
    def __init__(
        self,
        index: VaultIndex,
        folders: Sequence[str] = (),
        seeds: int = 5,
        link_weight: float = 0.4,
        decay: float = 0.8,
    ) -> None:
        self.index = index
        self.folders = tuple(folders)
        self.search = NoteSearch(index, folders)
        self.seeds, self.link_weight, self.decay = seeds, link_weight, decay

    def _allowed(self, path: str) -> bool:
        return not self.folders or path.split("/")[0] in self.folders

    def retrieve(self, query: str, k: int = 10) -> List[Result]:
        base = self.search.search(query, self.seeds)
        if not base:
            return []
        top = base[0].score or 1.0
        scores: Dict[str, float] = {}
        meta: Dict[str, Result] = {}
        for rank, hit in enumerate(base):
            value = hit.score / top
            scores[hit.path] = value
            meta[hit.path] = Result(hit.path, value, "bm25", detail=f"rank {rank + 1}")
        for hit in base:
            seed_value = hit.score / top
            for other in self.index.neighbours(hit.path):
                if not self._allowed(other) or other in {h.path for h in base}:
                    continue
                gain = seed_value * self.link_weight * self.decay
                scores[other] = scores.get(other, 0.0) + gain
                if other not in meta:
                    meta[other] = Result(other, 0.0, "link", seed=hit.path, detail="linked")
        ordered = sorted(scores.items(), key=lambda r: (-round(r[1], 10), r[0]))[:k]
        return [
            Result(p, round(s, 8), meta[p].via, meta[p].seed, meta[p].detail) for p, s in ordered
        ]


def fuse_with_corpus(
    notes: Sequence[Result], corpus_sources: Sequence[str], k: int = 10
) -> List[Result]:
    """Reciprocal-rank fusion of note results and corpus hits (ordered source file names).
    A corpus hit joins the note of its Source when one exists."""
    ranks: Dict[str, float] = {}
    meta: Dict[str, Result] = {}
    for rank, item in enumerate(notes):
        ranks[item.path] = ranks.get(item.path, 0.0) + 1.0 / (RRF_K + rank + 1)
        meta[item.path] = item
    seen: Set[str] = set()
    for rank, source in enumerate(corpus_sources):
        path = f"Sources/{source_title(source)}.md"
        if path in seen:
            continue
        seen.add(path)
        ranks[path] = ranks.get(path, 0.0) + 1.0 / (RRF_K + rank + 1)
        if path not in meta:
            meta[path] = Result(path, 0.0, "corpus", detail=source)
    ordered = sorted(ranks.items(), key=lambda r: (-round(r[1], 12), r[0]))[:k]
    return [Result(p, round(s, 10), meta[p].via, meta[p].seed, meta[p].detail) for p, s in ordered]


# -- navigation-first over the brain -----------------------------------------------------------
def navigate(
    brain: Any, task: str, workflow: str = "", chars_per_token: float = 4.0
) -> Dict[str, Any]:
    """Route by task, expand along typed links through the consult; search only when no hub
    matches. Returns the brief, the ids visited and the estimated token use."""
    consult = brain.consult(task, workflow)
    if consult is not None:
        return {
            "mode": "navigate",
            "trace": list(consult.trace),
            "brief": consult.brief,
            "tokens": estimate_tokens(consult.brief, chars_per_token),
        }
    found = brain.search(task)
    hits = found.get("hits", [])
    text = "; ".join(str(h.get("id", "")) for h in hits)
    return {
        "mode": "search",
        "trace": [str(h.get("id", "")) for h in hits],
        "brief": text,
        "tokens": estimate_tokens(text, chars_per_token),
    }


# -- metrics -------------------------------------------------------------------------------------
def recall_at_k(ranked: Sequence[str], relevant: Set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 0.0


def mrr(ranked: Sequence[str], relevant: Set[str]) -> float:
    for i, item in enumerate(ranked):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def evaluate(queries: Dict[str, Set[str]], retrieve: Any, k: int = 5) -> Dict[str, float]:
    """Mean Recall@k, MRR and nDCG@k of `retrieve(query) -> [path, ...]`."""
    rows = [(retrieve(q), rel) for q, rel in sorted(queries.items())]
    n = len(rows) or 1
    return {
        f"recall@{k}": round(sum(recall_at_k(r, rel, k) for r, rel in rows) / n, 4),
        "mrr": round(sum(mrr(r, rel) for r, rel in rows) / n, 4),
        f"ndcg@{k}": round(sum(ndcg_at_k(r, rel, k) for r, rel in rows) / n, 4),
    }


def tokens_of(results: Sequence[Result], index: VaultIndex, chars_per_token: float = 4.0) -> int:
    """Estimated tokens of the note bodies in a result list (what the model would read)."""
    return sum(
        estimate_tokens(index.notes[r.path].body, chars_per_token)
        for r in results
        if r.path in index.notes
    )


def best(results: Sequence[Result]) -> Optional[Result]:
    return results[0] if results else None
