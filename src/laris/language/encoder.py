"""Sentence encoder interfaces, compact representations, and checkpoint contracts.

Adheres to DOC-SPEC-MOD-001 (Boundary B / MOD-LANG-002) and ADR-002:
- Base abstract interface for in-house sentence encoders
- Compact local sentence encoder without mandatory external pretrained models
- Deterministic subword projection, pooling strategies, and unit L2 normalization
- Strict error types: SequenceLengthExceededError, EmbeddingDimensionMismatchError
"""

import hashlib
import math
from abc import ABC, abstractmethod
from typing import List, Tuple

from laris.core.errors import (
    EmbeddingDimensionMismatchError,
    ModuleContractViolationError,
    SequenceLengthExceededError,
)
from laris.language.schemas import (
    ALLOWED_EMBEDDING_DIMENSIONS,
    DEFAULT_MAX_SEQUENCE_LENGTH,
    EmbeddingBatchOutput,
    EncoderCheckpointMetadata,
    SentenceEmbeddingOutput,
    SentenceEncoderContract,
)
from laris.language.tokenizer import ScientificTokenizer


class BaseSentenceEncoder(ABC):
    """Abstract base class defining the contract for all LARIS sentence encoders."""

    @abstractmethod
    def encode_sentence(self, text: str, truncate: bool = False) -> SentenceEmbeddingOutput:
        """Encodes a single normalized sentence into a dense embedding vector."""

    @abstractmethod
    def encode_batch(
        self, texts: List[str], truncate: bool = False
    ) -> EmbeddingBatchOutput:
        """Encodes a batch of normalized sentences into dense embedding vectors."""

    @abstractmethod
    def get_contract(self) -> SentenceEncoderContract:
        """Returns the formal contract specification for this encoder."""

    @abstractmethod
    def get_checkpoint_metadata(self) -> EncoderCheckpointMetadata:
        """Returns the cryptographic metadata and provenance of the current weights."""


class CompactSentenceEncoder(BaseSentenceEncoder):
    """Compact in-house sentence encoder adhering to Tier 1 local compute envelope (<1 GB VRAM).

    Implements deterministic token representation projection and pooling:
    - Zero external cloud/pretrained dependencies
    - Fully reproducible initialization from vocabulary contract and model seed
    - Dimension verification ($D \\in \\{384, 768\\}$)
    - Unit L2 normalization for cosine similarity search
    """

    def __init__(
        self,
        tokenizer: ScientificTokenizer,
        embedding_dim: int = 384,
        max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH,
        pooling_strategy: str = "mean",
        normalize_embeddings: bool = True,
        seed: int = 42,
        model_id: str = "laris-compact-stem-encoder-v1",
    ) -> None:
        if embedding_dim not in ALLOWED_EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionMismatchError(
                f"Embedding dimension {embedding_dim} not in {sorted(ALLOWED_EMBEDDING_DIMENSIONS)}"
            )

        self.tokenizer = tokenizer
        self.embedding_dim = embedding_dim
        self.max_sequence_length = max_sequence_length
        self.pooling_strategy = pooling_strategy
        self.normalize_embeddings = normalize_embeddings
        self.seed = seed
        self.model_id = model_id

        self.contract = SentenceEncoderContract(
            model_id=self.model_id,
            embedding_dim=self.embedding_dim,
            max_sequence_length=self.max_sequence_length,
            pooling_strategy=self.pooling_strategy,
            normalize_embeddings=self.normalize_embeddings,
            vocab_sha256=self.tokenizer.vocab_contract.vocab_sha256,
        )

        # Initialize deterministic token embedding table
        self._embedding_table, self._weights_sha256 = self._init_deterministic_weights()

    def _init_deterministic_weights(self) -> Tuple[List[List[float]], str]:
        """Initializes deterministic token embedding weights using hash-based PRNG."""
        vocab_size = self.tokenizer.vocab_contract.vocab_size
        table: List[List[float]] = []
        hasher = hashlib.sha256()

        for token_id in range(vocab_size):
            row: List[float] = []
            # Hash seed + token_id + dim to get deterministic pseudo-random float in [-1, 1]
            for d in range(self.embedding_dim):
                key = f"{self.seed}:{token_id}:{d}".encode("utf-8")
                h = hashlib.sha256(key).digest()
                # Unpack first 4 bytes as unsigned integer
                raw_int = int.from_bytes(h[:4], byteorder="big", signed=False)
                # Normalize to standard Gaussian approximation via Box-Muller-like scaling
                val = ((raw_int / 4294967295.0) * 2.0 - 1.0) / math.sqrt(self.embedding_dim)
                row.append(val)
                hasher.update(h[:4])
            table.append(row)

        return table, hasher.hexdigest()

    def get_contract(self) -> SentenceEncoderContract:
        """Returns the formal contract specification."""
        return self.contract

    def get_checkpoint_metadata(self) -> EncoderCheckpointMetadata:
        """Returns checkpoint metadata with cryptographic hashes."""
        vocab_size = self.tokenizer.vocab_contract.vocab_size
        parameter_count = vocab_size * self.embedding_dim
        return EncoderCheckpointMetadata(
            checkpoint_id=f"{self.model_id}-seed{self.seed}",
            model_id=self.model_id,
            embedding_dim=self.embedding_dim,
            vocab_sha256=self.tokenizer.vocab_contract.vocab_sha256,
            weights_sha256=self._weights_sha256,
            parameter_count=parameter_count,
            created_at="2026-10-15T00:00:00Z",
            lineage={
                "seed": self.seed,
                "vocab_size": vocab_size,
                "pooling_strategy": self.pooling_strategy,
            },
        )

    def encode_sentence(self, text: str, truncate: bool = False) -> SentenceEmbeddingOutput:
        """Encodes a single normalized sentence into a dense embedding vector."""
        if not text or not text.strip():
            raise ModuleContractViolationError("Sentence text must not be empty or whitespace-only")

        tokenized = self.tokenizer.encode(text=text)
        token_ids = tokenized.token_ids
        token_count = len(token_ids)

        if not truncate and token_count > self.max_sequence_length:
            raise SequenceLengthExceededError(
                f"Token count {token_count} exceeds maximum length {self.max_sequence_length}"
            )

        if truncate and token_count > self.max_sequence_length:
            token_ids = token_ids[: self.max_sequence_length]
            token_count = len(token_ids)

        # Lookup embeddings
        vectors: List[List[float]] = []
        for tid in token_ids:
            if 0 <= tid < len(self._embedding_table):
                vectors.append(self._embedding_table[tid])
            else:
                vectors.append([0.0] * self.embedding_dim)

        # Apply pooling
        if self.pooling_strategy == "cls":
            pooled = list(vectors[0]) if vectors else [0.0] * self.embedding_dim
        elif self.pooling_strategy == "max":
            pooled = [
                max(vectors[i][d] for i in range(len(vectors)))
                for d in range(self.embedding_dim)
            ]
        else:  # mean pooling
            pooled = [
                sum(vectors[i][d] for i in range(len(vectors))) / len(vectors)
                for d in range(self.embedding_dim)
            ]

        # Unit L2 Normalization
        if self.normalize_embeddings:
            norm = math.sqrt(sum(x * x for x in pooled))
            if norm > 1e-12:
                pooled = [x / norm for x in pooled]

        return SentenceEmbeddingOutput(
            text=text,
            embedding=pooled,
            token_count=token_count,
            embedding_dim=self.embedding_dim,
        )

    def encode_batch(
        self, texts: List[str], truncate: bool = False
    ) -> EmbeddingBatchOutput:
        """Encodes a batch of normalized sentences."""
        if not texts:
            raise ModuleContractViolationError("texts list must not be empty")

        embeddings = [self.encode_sentence(t, truncate=truncate) for t in texts]
        return EmbeddingBatchOutput(
            embeddings=embeddings,
            model_id=self.model_id,
            embedding_dim=self.embedding_dim,
            batch_size=len(embeddings),
        )
