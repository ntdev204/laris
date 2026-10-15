"""Canonical content hashing and exact deduplication engine for Layer 0.

Adheres to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
Provides 100% deterministic SHA-256 content digest computation and
exact duplicate detection across ingested scientific corpus items.
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from laris.core.errors import DuplicateCorpusError
from laris.layers.layer0_corpus.normalizer import normalize_scientific_text
from laris.layers.layer0_corpus.schemas import ValidatedCorpusItem

# Explicit algorithm and encoding contracts
DIGEST_ALGORITHM = "SHA-256"
DIGEST_ENCODING = "utf-8"
DIGEST_SPEC_VERSION = "1.0"


@dataclass(frozen=True)
class DuplicateRecord:
    """Immutable audit record detailing an identified duplicate document."""

    duplicate_corpus_id: str
    canonical_corpus_id: str
    content_sha256: str
    similarity_score: float = 1.0
    match_type: str = "EXACT"
    rationale: str = ""


def compute_canonical_content_digest(text: str, normalize: bool = True) -> str:
    """Computes a deterministic cryptographic SHA-256 digest over document text.

    Contract:
    - Input must be a string (`str`). Non-string inputs raise `TypeError`.
    - If `normalize` is True, text is first processed by `normalize_scientific_text`
      to ensure invariance against typographic ligatures, invisible codepoints,
      fullwidth Unicode, and SI unit formatting differences.
    - Encoded explicitly as UTF-8 without Byte Order Mark (BOM).
    - Returns a 64-character lowercase hexadecimal SHA-256 string.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str input for content digest, got {type(text).__name__}")

    target_text = normalize_scientific_text(text) if normalize else text
    raw_bytes = target_text.encode(DIGEST_ENCODING)
    return hashlib.sha256(raw_bytes).hexdigest()


def verify_content_digest(
    text: str, expected_sha256: str, normalize: bool = True
) -> bool:
    """Cryptographically verifies whether document text matches an expected SHA-256 digest."""
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        return False
    try:
        actual_digest = compute_canonical_content_digest(text, normalize=normalize)
        return actual_digest == expected_sha256.lower()
    except (TypeError, ValueError):
        return False


class ExactDeduplicator:
    """Deterministic, bounded in-memory registry for exact duplicate detection.

    Guarantees:
    - 100% precision on exact SHA-256 content matches.
    - Deterministic resolution: the first-registered corpus item is retained as canonical.
    - Explainable collision reporting via `DuplicateRecord`.
    """

    def __init__(self) -> None:
        self._index: Dict[str, str] = {}  # sha256 -> canonical_corpus_id

    def is_duplicate(self, sha256_hash: str) -> bool:
        """Checks if a content hash has already been registered."""
        return sha256_hash.lower() in self._index

    def get_canonical_id(self, sha256_hash: str) -> Optional[str]:
        """Returns the canonical corpus ID associated with a digest, if registered."""
        return self._index.get(sha256_hash.lower())

    def register(
        self, corpus_id: str, text: str, normalize: bool = True
    ) -> Tuple[str, bool, Optional[DuplicateRecord]]:
        """Registers a document by ID and text content.

        Returns:
            Tuple of (digest, is_unique, duplicate_record).
            - If unique: returns (digest, True, None).
            - If duplicate: returns (digest, False, DuplicateRecord).
        """
        if not corpus_id:
            raise ValueError("corpus_id MUST NOT be empty")

        digest = compute_canonical_content_digest(text, normalize=normalize)
        existing_id = self.get_canonical_id(digest)

        if existing_id is not None:
            record = DuplicateRecord(
                duplicate_corpus_id=corpus_id,
                canonical_corpus_id=existing_id,
                content_sha256=digest,
                similarity_score=1.0,
                match_type="EXACT",
                rationale=(
                    f"Exact SHA-256 content collision with canonical item '{existing_id}'"
                ),
            )
            return digest, False, record

        self._index[digest] = corpus_id
        return digest, True, None

    def register_or_raise(
        self, corpus_id: str, text: str, normalize: bool = True
    ) -> str:
        """Registers document content or raises `DuplicateCorpusError` on collision."""
        digest, is_unique, dup_record = self.register(
            corpus_id, text, normalize=normalize
        )
        if not is_unique and dup_record is not None:
            raise DuplicateCorpusError(
                f"Duplicate corpus item '{corpus_id}': exact SHA-256 collision with "
                f"canonical item '{dup_record.canonical_corpus_id}' (digest: {digest})"
            )
        return digest

    def deduplicate_batch(
        self, items: Iterable[ValidatedCorpusItem], auto_register: bool = True
    ) -> Tuple[List[ValidatedCorpusItem], List[DuplicateRecord]]:
        """Partitions an iterable of corpus items into unique items and duplicate records."""
        unique_items: List[ValidatedCorpusItem] = []
        duplicates: List[DuplicateRecord] = []

        for item in items:
            existing_id = self.get_canonical_id(item.sha256)
            if existing_id is not None:
                duplicates.append(
                    DuplicateRecord(
                        duplicate_corpus_id=item.corpus_id,
                        canonical_corpus_id=existing_id,
                        content_sha256=item.sha256,
                        similarity_score=1.0,
                        match_type="EXACT",
                        rationale=(
                            f"Exact SHA-256 collision with canonical item '{existing_id}'"
                        ),
                    )
                )
            else:
                if auto_register:
                    self._index[item.sha256] = item.corpus_id
                unique_items.append(item)

        return unique_items, duplicates

    def __len__(self) -> int:
        return len(self._index)

    def clear(self) -> None:
        """Resets the deduplication registry."""
        self._index.clear()
