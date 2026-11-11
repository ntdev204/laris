"""Literature mining over a set of documents: overview, term trends, near-duplicates, groups.

Every result carries a `scope` (how many documents, which years, what was left out) so a statistic
is never read as covering more than it did. All functions are deterministic.
"""

import hashlib
import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from scholarly.biblio import Bibliography, extract

_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
STOP = frozenset(
    "the and for that with this from are was were have has not but can which their also such than "
    "these those into our using used use based show shows however while where when then they them "
    "its been being more most other some each both between over under about after before one two "
    "một những của và là có được trong cho các này khi với không theo từ đã để".split()
)
MAX_DOCS = 2000


@dataclass
class Doc:
    doc_id: str
    source: str
    text: str
    bib: Bibliography = field(default_factory=Bibliography)

    @property
    def year(self) -> int:
        return self.bib.year or 0


def docs_from_chunks(chunks: Iterable[Any], head_chars: int = 3000) -> List[Doc]:
    """One Doc per document id, text rebuilt from its passages, bibliography read from its head."""
    from vault.entities import document_text

    by_doc: Dict[str, List[Any]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    docs = []
    for doc_id, group in sorted(by_doc.items()):
        text = document_text(group)
        docs.append(Doc(doc_id, group[0].source, text, extract(text[:head_chars])))
    return docs


def tokens(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text) if w.lower() not in STOP]


def _limit(docs: Sequence[Doc], max_docs: int) -> Tuple[List[Doc], int]:
    kept = list(docs)[:max_docs]
    return kept, len(docs) - len(kept)


# -- overview ------------------------------------------------------------------------------------
def overview(docs: Sequence[Doc]) -> Dict[str, Any]:
    years: Dict[int, int] = {}
    for d in docs:
        if d.bib.year:
            years[d.bib.year] = years.get(d.bib.year, 0) + 1
    return {
        "scope": {
            "documents": len(docs),
            "documents_with_year": sum(years.values()),
            "year_range": [min(years), max(years)] if years else [],
        },
        "chars_total": sum(len(d.text) for d in docs),
        "chars_mean": round(sum(len(d.text) for d in docs) / len(docs), 1) if docs else 0,
        "with_doi": sum(1 for d in docs if d.bib.doi),
        "with_arxiv": sum(1 for d in docs if d.bib.arxiv),
        "per_year": {str(y): n for y, n in sorted(years.items())},
        "note": "documents without a stated year are counted in 'documents' only",
    }


# -- term trends ---------------------------------------------------------------------------------
def term_trends(docs: Sequence[Doc], top: int = 10, min_docs: int = 2) -> Dict[str, Any]:
    dated = [d for d in docs if d.bib.year]
    per_year_docs: Dict[int, int] = {}
    df: Dict[str, Dict[int, int]] = {}
    for d in dated:
        per_year_docs[d.bib.year or 0] = per_year_docs.get(d.bib.year or 0, 0) + 1
        for term in set(tokens(d.text)):
            row = df.setdefault(term, {})
            row[d.bib.year or 0] = row.get(d.bib.year or 0, 0) + 1
    ranked = sorted(
        ((sum(r.values()), t) for t, r in df.items() if sum(r.values()) >= min_docs),
        key=lambda x: (-x[0], x[1]),
    )[:top]
    return {
        "scope": {
            "documents": len(docs),
            "documents_with_year": len(dated),
            "years": sorted(per_year_docs),
            "min_docs": min_docs,
        },
        "docs_per_year": {str(y): n for y, n in sorted(per_year_docs.items())},
        "terms": {t: {str(y): n for y, n in sorted(df[t].items())} for _, t in ranked},
        "note": "counts are documents containing the term, not occurrences",
    }


# -- near duplicates -------------------------------------------------------------------------------
_PRIME = (1 << 61) - 1
HASHES, BANDS = 64, 16


def _shingles(text: str, k: int) -> Set[int]:
    words = _WORD.findall(text.lower())
    return {
        int.from_bytes(
            hashlib.blake2b(" ".join(words[i : i + k]).encode(), digest_size=8).digest(), "big"
        )
        for i in range(max(0, len(words) - k + 1))
    }


def _jaccard(a: Set[int], b: Set[int]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def near_duplicates(
    docs: Sequence[Doc], threshold: float = 0.8, shingle: int = 5, max_docs: int = MAX_DOCS
) -> Dict[str, Any]:
    """Pairs whose shingle Jaccard similarity is at least `threshold` (MinHash buckets find the
    candidates, the exact similarity decides)."""
    kept, dropped = _limit(docs, max_docs)
    sets = {d.doc_id: _shingles(d.text, shingle) for d in kept}
    rng = random.Random(17)
    coeffs = [(rng.randrange(1, _PRIME), rng.randrange(0, _PRIME)) for _ in range(HASHES)]
    buckets: Dict[Tuple[int, Tuple[int, ...]], List[str]] = {}
    for doc_id, s in sets.items():
        if not s:
            continue
        sig = [min((a * h + b) % _PRIME for h in s) for a, b in coeffs]
        rows = HASHES // BANDS
        for band in range(BANDS):
            buckets.setdefault((band, tuple(sig[band * rows : (band + 1) * rows])), []).append(
                doc_id
            )
    candidates: Set[Tuple[str, str]] = set()
    for members in buckets.values():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                candidates.add((a, b) if a < b else (b, a))
    pairs = []
    for a, b in sorted(candidates):
        sim = _jaccard(sets[a], sets[b])
        if sim >= threshold:
            pairs.append({"a": a, "b": b, "similarity": round(sim, 4)})
    return {
        "scope": {
            "documents": len(kept),
            "documents_left_out": dropped,
            "threshold": threshold,
            "shingle_words": shingle,
        },
        "pairs": pairs,
    }


def exact_duplicates(
    docs: Sequence[Doc], threshold: float, shingle: int = 5
) -> List[Tuple[str, str]]:
    """Brute force reference used to measure precision and recall of `near_duplicates`."""
    sets = {d.doc_id: _shingles(d.text, shingle) for d in docs}
    ids = sorted(sets)
    return [
        (a, b)
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
        if _jaccard(sets[a], sets[b]) >= threshold
    ]


# -- grouping ------------------------------------------------------------------------------------
def group_documents(
    docs: Sequence[Doc], threshold: float = 0.25, label_terms: int = 3, max_docs: int = MAX_DOCS
) -> Dict[str, Any]:
    """Single-link groups of documents whose TF-IDF cosine similarity reaches `threshold`."""
    kept, dropped = _limit(docs, max_docs)
    counts = {d.doc_id: _tf(d.text) for d in kept}
    n = len(kept)
    df: Dict[str, int] = {}
    for tf in counts.values():
        for t in tf:
            df[t] = df.get(t, 0) + 1
    vec: Dict[str, Dict[str, float]] = {}
    for doc_id, tf in counts.items():
        raw = {t: c * math.log((1 + n) / (1 + df[t])) + 0.0 for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in raw.values())) or 1.0
        vec[doc_id] = {t: v / norm for t, v in raw.items() if v > 0}
    parent = {d.doc_id: d.doc_id for d in kept}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = sorted(parent)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if _cos(vec[a], vec[b]) >= threshold:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    groups: Dict[str, List[str]] = {}
    for doc_id in ids:
        groups.setdefault(find(doc_id), []).append(doc_id)
    out = []
    for members in sorted(groups.values(), key=lambda g: (-len(g), g[0])):
        weights: Dict[str, float] = {}
        for m in members:
            for t, w in vec[m].items():
                weights[t] = weights.get(t, 0.0) + w
        label = [t for t, _ in sorted(weights.items(), key=lambda x: (-x[1], x[0]))[:label_terms]]
        out.append({"documents": members, "label_terms": label})
    return {
        "scope": {"documents": len(kept), "documents_left_out": dropped, "threshold": threshold},
        "groups": out,
    }


def _tf(text: str) -> Dict[str, int]:
    tf: Dict[str, int] = {}
    for t in tokens(text):
        tf[t] = tf.get(t, 0) + 1
    return tf


def _cos(a: Dict[str, float], b: Dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def to_markdown(kind: str, result: Dict[str, Any]) -> str:
    """A readable summary for an Analysis note (scope first)."""
    scope = ", ".join(f"{k}: {v}" for k, v in result.get("scope", {}).items())
    lines = [f"Scope: {scope}", ""]
    if kind == "overview":
        lines += [
            f"- {k}: {v}" for k, v in result.items() if k not in {"scope", "per_year", "note"}
        ]
        lines += [f"- {y}: {n} document(s)" for y, n in result.get("per_year", {}).items()]
    elif kind == "trends":
        for term, row in result["terms"].items():
            lines.append(f"- {term}: " + ", ".join(f"{y}: {n}" for y, n in row.items()))
    elif kind == "duplicates":
        lines += [f"- {p['a']} ~ {p['b']} ({p['similarity']})" for p in result["pairs"]] or [
            "- none"
        ]
    elif kind == "groups":
        for i, g in enumerate(result["groups"], 1):
            lines.append(
                f"- Group {i} ({', '.join(g['label_terms'])}): {', '.join(g['documents'])}"
            )
    if result.get("note"):
        lines += ["", result["note"]]
    return "\n".join(lines)
