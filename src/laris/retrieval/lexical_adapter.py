"""Lexical BM25 retrieval adapter for Layer 6 Hybrid Retrieval.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010:
- Deterministic Okapi BM25 scoring with Robertson-Spärck Jones IDF
- Full metadata filtering and evidence coordinate provenance retention
- Pluggable scientific tokenizer with regex fallback
- Pure Python offline execution without external search engine daemons
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.core.schemas import EvidenceCoordinate
from laris.language.tokenizer import ScientificTokenizer
from laris.retrieval.interfaces import BaseRetrievalAdapter
from laris.retrieval.schemas import (
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)


@dataclass(frozen=True)
class LexicalDocument:
    """Document representation for lexical indexing with coordinates and metadata."""

    doc_id: str
    text: str
    tokens: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    coordinates: List[EvidenceCoordinate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.doc_id or not self.doc_id.strip():
            raise ModuleContractViolationError("LexicalDocument doc_id must not be empty.")
        if not self.text or not self.text.strip():
            raise ModuleContractViolationError("LexicalDocument text must not be empty.")


class LexicalBM25Adapter(BaseRetrievalAdapter):
    """Okapi BM25 retrieval adapter implementing BaseRetrievalAdapter."""

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Optional[ScientificTokenizer] = None,
        max_index_size: int = 100000,
    ) -> None:
        if k1 < 0.0:
            raise ModuleContractViolationError(f"k1 must be >= 0.0, got {k1}.")
        if not (0.0 <= b <= 1.0):
            raise ModuleContractViolationError(f"b must be in [0.0, 1.0], got {b}.")
        if max_index_size < 1:
            raise ModuleContractViolationError(
                f"max_index_size must be >= 1, got {max_index_size}."
            )


        self.k1 = k1
        self.b = b
        self.tokenizer = tokenizer
        self.max_index_size = max_index_size

        self._documents: Dict[str, LexicalDocument] = {}
        self._doc_lengths: Dict[str, int] = {}
        self._inverted_index: Dict[str, Dict[str, int]] = {}
        self._avg_doc_length: float = 0.0

    @property
    def channel(self) -> RetrievalChannel:
        """Returns LEXICAL channel identifier."""
        return RetrievalChannel.LEXICAL

    @property
    def total_items(self) -> int:
        """Returns number of indexed documents."""
        return len(self._documents)

    def has_item(self, item_id: str) -> bool:
        """Checks if a document identifier exists in the index."""
        return item_id in self._documents

    def _tokenize(self, text: str) -> List[str]:
        """Tokenizes text using scientific tokenizer or regex fallback."""
        if self.tokenizer is not None:
            return [t.lower() for t in self.tokenizer.pre_tokenize(text)]
        return [t.lower() for t in re.findall(r"\w+|[^\s\w]", text) if t.strip()]

    def add_documents(self, documents: List[LexicalDocument]) -> None:
        """Indexes a batch of LexicalDocuments into the inverted index."""
        if not documents:
            raise ModuleContractViolationError("documents list must not be empty.")
        if len(self._documents) + len(documents) > self.max_index_size:
            raise ModuleContractViolationError(
                f"Adding {len(documents)} documents exceeds maximum index capacity "
                f"({self.max_index_size})."
            )

        total_length = self._avg_doc_length * len(self._documents)

        for doc in documents:
            if doc.doc_id in self._documents:
                raise ModuleContractViolationError(
                    f"Duplicate doc_id '{doc.doc_id}' in index collection."
                )

            tokens = doc.tokens if doc.tokens is not None else self._tokenize(doc.text)
            if not tokens:
                raise ModuleContractViolationError(
                    f"Document '{doc.doc_id}' contains zero valid tokens."
                )

            self._documents[doc.doc_id] = doc
            doc_len = len(tokens)
            self._doc_lengths[doc.doc_id] = doc_len
            total_length += doc_len

            term_counts: Dict[str, int] = {}
            for t in tokens:
                term_lower = t.lower()
                term_counts[term_lower] = term_counts.get(term_lower, 0) + 1

            for term, count in term_counts.items():
                if term not in self._inverted_index:
                    self._inverted_index[term] = {}
                self._inverted_index[term][doc.doc_id] = count

        self._avg_doc_length = total_length / len(self._documents)

    def retrieve(self, query: RetrievalQuery) -> List[RetrievalCandidate]:
        """Executes BM25 search over indexed documents with metadata filtering."""
        if not self._documents:
            return []

        query_tokens = self._tokenize(query.text)
        num_docs = len(self._documents)
        scores: Dict[str, float] = {}

        for term in query_tokens:
            posting = self._inverted_index.get(term)
            if not posting:
                continue

            df = len(posting)
            idf = math.log(1.0 + (num_docs - df + 0.5) / (df + 0.5))

            for doc_id, tf in posting.items():
                doc = self._documents[doc_id]
                # Apply metadata filter early
                if query.filter is not None and not query.filter.matches(doc.metadata):
                    continue

                doc_len = self._doc_lengths[doc_id]
                len_norm = 1.0 - self.b + self.b * (doc_len / self._avg_doc_length)
                tf_component = (tf * (self.k1 + 1.0)) / (tf + self.k1 * len_norm)
                term_score = idf * tf_component
                scores[doc_id] = scores.get(doc_id, 0.0) + term_score

        # Deterministic sorting: score descending, then doc_id ascending
        sorted_docs = sorted(
            [(doc_id, score) for doc_id, score in scores.items() if score > 0.0],
            key=lambda x: (-x[1], x[0]),
        )

        candidates: List[RetrievalCandidate] = []
        for rank, (doc_id, score) in enumerate(sorted_docs[: query.top_k], start=1):
            doc = self._documents[doc_id]
            candidates.append(
                RetrievalCandidate(
                    candidate_id=doc_id,
                    content=doc.text,
                    score=score,
                    channel=RetrievalChannel.LEXICAL,
                    rank=rank,
                    metadata=doc.metadata,
                    coordinates=list(doc.coordinates),
                    source_scores={"lexical": score},
                )
            )

        return candidates
