"""TF-IDF over sparse dict vectors: smoothed idf, optional sublinear tf, L2 norm, cosine, top-k.

Pure Python and deterministic. Counting document frequencies is statistics over the given
documents, not neural training. A vector is a `Dict[term, weight]` holding only positive weights;
with `idf_offset=0` a term present in every document has idf 0 and is dropped, which is the
behaviour `shared.scholarly.mining.group_documents` has always had.
"""

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

Vector = Dict[str, float]


def term_frequencies(tokens: Iterable[str]) -> Dict[str, int]:
    """Occurrences per term, in order of first appearance."""
    tf: Dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def idf(n_documents: int, document_frequency: int, offset: float = 0.0) -> float:
    """Smoothed inverse document frequency `ln((1 + n) / (1 + df)) + offset`."""
    return math.log((1 + n_documents) / (1 + document_frequency)) + offset


def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Dot product of two vectors (the cosine when both are L2-normalised)."""
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def top_terms(vector: Mapping[str, float], k: int) -> List[Tuple[str, float]]:
    """The `k` heaviest terms, ties broken alphabetically."""
    return sorted(vector.items(), key=lambda x: (-x[1], x[0]))[: max(0, k)]


def nearest(
    query: Mapping[str, float],
    vectors: Mapping[str, Mapping[str, float]],
    k: int,
    exclude: Optional[str] = None,
    min_similarity: float = 0.0,
) -> List[Tuple[str, float]]:
    """The `k` most similar vectors by cosine, ties broken by id; `exclude` skips one id."""
    scored = [(doc_id, cosine(query, vec)) for doc_id, vec in vectors.items() if doc_id != exclude]
    scored = [(i, s) for i, s in scored if s > min_similarity]
    return sorted(scored, key=lambda x: (-x[1], x[0]))[: max(0, k)]


@dataclass(frozen=True)
class TfidfModel:
    """Document frequencies of a collection plus the weighting options."""

    n_documents: int
    document_frequency: Mapping[str, int]
    sublinear_tf: bool = False
    idf_offset: float = 0.0

    @classmethod
    def from_term_counts(
        cls,
        counts: Iterable[Mapping[str, int]],
        sublinear_tf: bool = False,
        idf_offset: float = 0.0,
    ) -> "TfidfModel":
        df: Dict[str, int] = {}
        n = 0
        for tf in counts:
            n += 1
            for t in tf:
                df[t] = df.get(t, 0) + 1
        return cls(n, df, sublinear_tf, idf_offset)

    @classmethod
    def from_documents(cls, documents: Iterable[Sequence[str]], **options: object) -> "TfidfModel":
        return cls.from_term_counts((term_frequencies(d) for d in documents), **options)  # type: ignore[arg-type]

    def idf(self, term: str) -> float:
        return idf(self.n_documents, self.document_frequency.get(term, 0), self.idf_offset)

    def vector(self, counts: Mapping[str, int]) -> Vector:
        """L2-normalised tf-idf vector of one bag of terms (terms with weight <= 0 are dropped)."""
        raw = {
            t: (1.0 + math.log(c) if self.sublinear_tf else c) * self.idf(t) + 0.0
            for t, c in counts.items()
        }
        norm = math.sqrt(sum(v * v for v in raw.values())) or 1.0
        return {t: v / norm for t, v in raw.items() if v > 0}

    def transform(self, tokens: Iterable[str]) -> Vector:
        return self.vector(term_frequencies(tokens))
