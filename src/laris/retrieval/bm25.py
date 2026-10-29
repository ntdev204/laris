"""Lexical BM25 retrieval baseline implementation for scientific documents.

Adheres to DOC-SPEC-MOD-001 (Boundary B / MOD-LANG-002) and M2-LANG-002:
- Deterministic Okapi BM25 scoring with Robertson-Spärck Jones IDF
- Inverted index over pre-tokenized scientific documents
- Pure Python offline execution without external search engine dependencies
- Baseline for comparison against compact neural embeddings
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.language.tokenization.tokenizer import ScientificTokenizer


@dataclass(frozen=True)
class BM25Document:
    """Document representation for BM25 lexical indexing."""

    doc_id: str
    text: str
    tokens: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.doc_id or not self.doc_id.strip():
            raise ModuleContractViolationError("BM25Document doc_id must not be empty")
        if not self.text or not self.text.strip():
            raise ModuleContractViolationError("BM25Document text must not be empty")
        if not self.tokens:
            raise ModuleContractViolationError("BM25Document tokens must not be empty")


@dataclass(frozen=True)
class BM25SearchResult:
    """A scored search result returned by BM25 retrieval."""

    doc_id: str
    score: float
    rank: int


class BM25RetrievalBaseline:
    """Deterministic Okapi BM25 indexer and scoring engine for scientific text retrieval."""

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Optional[ScientificTokenizer] = None,
    ) -> None:
        if k1 < 0:
            raise ValueError(f"k1 must be non-negative, got {k1}")
        if not (0.0 <= b <= 1.0):
            raise ValueError(f"b must be in [0.0, 1.0], got {b}")

        self.k1 = k1
        self.b = b
        self.tokenizer = tokenizer

        # Inverted index: term -> {doc_id: term_frequency}
        self._inverted_index: Dict[str, Dict[str, int]] = {}
        # Document lengths: doc_id -> token_count
        self._doc_lengths: Dict[str, int] = {}
        # Document storage: doc_id -> BM25Document
        self._documents: Dict[str, BM25Document] = {}
        self._avg_doc_length: float = 0.0

    @property
    def doc_count(self) -> int:
        """Returns the number of documents in the index."""
        return len(self._documents)

    def has_document(self, doc_id: str) -> bool:
        """Checks if a document is present in the index."""
        return doc_id in self._documents

    def index_documents(self, documents: List[BM25Document]) -> None:
        """Indexes a collection of pre-tokenized documents."""
        if not documents:
            raise ModuleContractViolationError("documents list must not be empty")

        total_length = 0
        for doc in documents:
            if doc.doc_id in self._documents:
                raise ValueError(f"Duplicate doc_id '{doc.doc_id}' in document collection")

            self._documents[doc.doc_id] = doc
            doc_len = len(doc.tokens)
            self._doc_lengths[doc.doc_id] = doc_len
            total_length += doc_len

            # Compute term frequencies within the document
            term_counts: Dict[str, int] = {}
            for t in doc.tokens:
                term_lower = t.lower()
                term_counts[term_lower] = term_counts.get(term_lower, 0) + 1

            for term, count in term_counts.items():
                if term not in self._inverted_index:
                    self._inverted_index[term] = {}
                self._inverted_index[term][doc.doc_id] = count

        self._avg_doc_length = total_length / len(self._documents)

    def _tokenize_query(self, query: str) -> List[str]:
        """Extracts normalized query tokens using tokenizer or regex fallback."""
        if self.tokenizer is not None:
            return self.tokenizer.pre_tokenize(query)
        # Fallback whitespace / word tokenization
        return [t.lower() for t in re.findall(r"\w+|[^\s\w]", query) if t.strip()]

    def search(self, query: str, top_k: int = 10) -> List[BM25SearchResult]:
        """Searches indexed documents for the given query using Okapi BM25 scoring."""
        if not self._documents:
            raise ModuleContractViolationError("Cannot search an empty BM25 index")
        if not query or not query.strip():
            raise ModuleContractViolationError("Search query must not be empty or whitespace-only")
        if top_k <= 0:
            raise ValueError(f"top_k must be > 0, got {top_k}")

        query_tokens = [t.lower() for t in self._tokenize_query(query)]
        scores: Dict[str, float] = {doc_id: 0.0 for doc_id in self._documents}
        num_docs = len(self._documents)

        for term in query_tokens:
            posting = self._inverted_index.get(term)
            if not posting:
                continue

            # Document frequency of term
            df = len(posting)
            # Robertson-Spärck Jones IDF with smoothing
            idf = math.log(1.0 + (num_docs - df + 0.5) / (df + 0.5))

            for doc_id, tf in posting.items():
                doc_len = self._doc_lengths[doc_id]
                # Length normalization component
                len_norm = 1.0 - self.b + self.b * (doc_len / self._avg_doc_length)
                # BM25 term saturation
                tf_component = (tf * (self.k1 + 1.0)) / (tf + self.k1 * len_norm)
                scores[doc_id] += idf * tf_component

        # Filter documents with positive scores and sort descending
        ranked = sorted(
            [(doc_id, score) for doc_id, score in scores.items() if score > 0.0],
            key=lambda x: x[1],
            reverse=True,
        )

        results: List[BM25SearchResult] = []
        for rank, (doc_id, score) in enumerate(ranked[:top_k], start=1):
            results.append(BM25SearchResult(doc_id=doc_id, score=score, rank=rank))

        return results
