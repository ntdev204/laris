"""Canonical content hashing and exact/near deduplication engine for Layer 0.

Adheres to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
Provides 100% deterministic SHA-256 content digest computation,
exact duplicate detection, and configurable near-duplicate similarity filtering
across ingested scientific corpus items.
"""

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

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


@dataclass(frozen=True)
class DeduplicationPolicy:
    """Configurable policy governing exact and near-duplicate document detection."""

    exact_deduplication: bool = True
    near_deduplication: bool = True
    near_duplicate_threshold: float = 0.85
    shingle_k: int = 3

    def __post_init__(self) -> None:
        if not (0.0 < self.near_duplicate_threshold <= 1.0):
            raise ValueError(
                "near_duplicate_threshold must be in (0.0, 1.0], "
                f"got {self.near_duplicate_threshold}"
            )
        if self.shingle_k < 1:
            raise ValueError(f"shingle_k must be >= 1, got {self.shingle_k}")


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


def generate_word_shingles(text: str, k: int = 3) -> Set[str]:
    """Generates a set of contiguous word k-shingles from text.

    If text contains fewer words than k, returns a single shingle containing all words,
    or an empty set if no words exist.
    """
    if not isinstance(text, str):
        raise TypeError(f"Expected str input for shingling, got {type(text).__name__}")
    if k < 1:
        raise ValueError("Shingle size k must be >= 1")
    words = text.split()
    if not words:
        return set()
    if len(words) < k:
        return {" ".join(words)}
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def compute_jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Computes the Jaccard similarity coefficient |A ∩ B| / |A ∪ B|."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return float(intersection) / float(union) if union > 0 else 0.0


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


class DeduplicationEngine:
    """Integrated exact and near-duplicate detection engine for scientific literature.

    Provides deterministic document deduplication according to a `DeduplicationPolicy`:
    1. Exact SHA-256 match -> EXACT duplicate (similarity = 1.0).
    2. Near-duplicate shingle Jaccard similarity >= near_duplicate_threshold -> NEAR_DUPLICATE.
    3. Below threshold -> CANONICAL item registered into the index.
    """

    def __init__(self, policy: Optional[DeduplicationPolicy] = None) -> None:
        self.policy = policy or DeduplicationPolicy()
        self._exact_index: Dict[str, str] = {}
        self._shingle_index: List[Tuple[str, Set[str]]] = []

    def is_exact_duplicate(self, sha256_hash: str) -> bool:
        """Checks if a content hash has already been registered."""
        return sha256_hash.lower() in self._exact_index

    def get_canonical_id(self, sha256_hash: str) -> Optional[str]:
        """Returns the canonical corpus ID associated with a digest, if registered."""
        return self._exact_index.get(sha256_hash.lower())

    def process_item(
        self, corpus_id: str, text: str, normalize: bool = True
    ) -> Tuple[str, bool, Optional[DuplicateRecord]]:
        """Processes a corpus item, detecting exact or near duplicates.

        Returns:
            Tuple of (digest, is_unique, duplicate_record).
        """
        if not corpus_id:
            raise ValueError("corpus_id MUST NOT be empty")
        if not isinstance(text, str):
            raise TypeError(f"Expected str input, got {type(text).__name__}")

        target_text = normalize_scientific_text(text) if normalize else text
        digest = compute_canonical_content_digest(target_text, normalize=False)

        # 1. Exact duplicate check
        if self.policy.exact_deduplication and digest in self._exact_index:
            canonical_id = self._exact_index[digest]
            record = DuplicateRecord(
                duplicate_corpus_id=corpus_id,
                canonical_corpus_id=canonical_id,
                content_sha256=digest,
                similarity_score=1.0,
                match_type="EXACT",
                rationale=(
                    f"Exact SHA-256 content collision with canonical item '{canonical_id}'"
                ),
            )
            return digest, False, record

        # 2. Near duplicate check
        if self.policy.near_deduplication:
            shingles = generate_word_shingles(target_text, k=self.policy.shingle_k)
            if shingles:
                best_sim = 0.0
                best_canonical_id = ""
                for canon_id, canon_shingles in self._shingle_index:
                    sim = compute_jaccard_similarity(shingles, canon_shingles)
                    if sim > best_sim:
                        best_sim = sim
                        best_canonical_id = canon_id

                if best_sim >= self.policy.near_duplicate_threshold:
                    record = DuplicateRecord(
                        duplicate_corpus_id=corpus_id,
                        canonical_corpus_id=best_canonical_id,
                        content_sha256=digest,
                        similarity_score=round(best_sim, 4),
                        match_type="NEAR_DUPLICATE",
                        rationale=(
                            f"Near-duplicate detected (Jaccard similarity {best_sim:.4f} >= "
                            f"threshold {self.policy.near_duplicate_threshold}) with "
                            f"canonical item '{best_canonical_id}'"
                        ),
                    )
                    return digest, False, record

        # 3. Unique item: register in indexes
        self._exact_index[digest] = corpus_id
        if self.policy.near_deduplication:
            shingles = generate_word_shingles(target_text, k=self.policy.shingle_k)
            if shingles:
                self._shingle_index.append((corpus_id, shingles))

        return digest, True, None

    def deduplicate_batch(
        self, items: Iterable[ValidatedCorpusItem]
    ) -> Tuple[List[ValidatedCorpusItem], List[DuplicateRecord]]:
        """Deduplicates a batch of ValidatedCorpusItem instances with stable output ordering."""
        unique_items: List[ValidatedCorpusItem] = []
        duplicates: List[DuplicateRecord] = []

        for item in items:
            _, is_unique, dup_record = self.process_item(
                item.corpus_id, item.clean_text, normalize=True
            )
            if is_unique:
                unique_items.append(item)
            elif dup_record is not None:
                duplicates.append(dup_record)

        # Stable output ordering: sort duplicates deterministically by descending similarity,
        # then ascending duplicate_corpus_id
        duplicates.sort(key=lambda d: (-d.similarity_score, d.duplicate_corpus_id))
        return unique_items, duplicates

    def __len__(self) -> int:
        return len(self._exact_index)

    def clear(self) -> None:
        """Resets both exact and near-duplicate indexes."""
        self._exact_index.clear()
        self._shingle_index.clear()
