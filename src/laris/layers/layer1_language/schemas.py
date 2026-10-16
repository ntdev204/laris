"""Layer 1 Language Foundation schemas and vocabulary contracts.

Adheres to DOC-SPEC-MOD-001 (Boundary B), ADR-001, and ADR-003:
- Normalized sentence inputs and tokenized sentence outputs
- Strict special token canonical registries and symbol preservation
- Immutable vocabulary contracts with bi-directional bijective mapping and SHA-256 integrity
- Leakage-proof tokenizer training data input specification strictly restricted to TRAIN split
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from laris.core.errors import (
    DataLeakageError,
    EmbeddingDimensionMismatchError,
    HardwareBudgetExceededError,
    ModuleContractViolationError,
    SequenceLengthExceededError,
    VocabularyMismatchError,
)
from laris.layers.layer0_corpus.schemas import CorpusManifest, DatasetSplit

# Special Tokens Canonical Constants
PAD_TOKEN = "[PAD]"
UNK_TOKEN = "[UNK]"
CLS_TOKEN = "[CLS]"
SEP_TOKEN = "[SEP]"
MASK_TOKEN = "[MASK]"
MATH_TOKEN = "[MATH]"
GREEK_TOKEN = "[GREEK]"
UNIT_TOKEN = "[UNIT]"

CANONICAL_SPECIAL_TOKENS: List[str] = [
    PAD_TOKEN,
    UNK_TOKEN,
    CLS_TOKEN,
    SEP_TOKEN,
    MASK_TOKEN,
    MATH_TOKEN,
    GREEK_TOKEN,
    UNIT_TOKEN,
]

DEFAULT_MAX_SEQUENCE_LENGTH = 512
ALLOWED_EMBEDDING_DIMENSIONS: Set[int] = {384, 768}
MIN_VOCAB_SIZE = 100
MAX_VOCAB_SIZE = 128000
DEFAULT_TARGET_VOCAB_SIZE = 32000


@dataclass(frozen=True)
class SpecialTokenConfig:
    """Canonical registry of special tokens and their fixed index allocations."""

    pad_token: str = PAD_TOKEN
    unk_token: str = UNK_TOKEN
    cls_token: str = CLS_TOKEN
    sep_token: str = SEP_TOKEN
    mask_token: str = MASK_TOKEN
    math_token: str = MATH_TOKEN
    greek_token: str = GREEK_TOKEN
    unit_token: str = UNIT_TOKEN

    pad_id: int = 0
    unk_id: int = 1
    cls_id: int = 2
    sep_id: int = 3
    mask_id: int = 4
    math_id: int = 5
    greek_id: int = 6
    unit_id: int = 7

    def to_dict(self) -> Dict[str, int]:
        """Returns mapping from special token string to integer ID."""
        return {
            self.pad_token: self.pad_id,
            self.unk_token: self.unk_id,
            self.cls_token: self.cls_id,
            self.sep_token: self.sep_id,
            self.mask_token: self.mask_id,
            self.math_token: self.math_id,
            self.greek_token: self.greek_id,
            self.unit_token: self.unit_id,
        }

    def __post_init__(self) -> None:
        mapping = self.to_dict()
        if len(mapping) != 8:
            raise ValueError("Special token strings must be distinct")
        ids = list(mapping.values())
        if len(set(ids)) != 8 or any(i < 0 for i in ids):
            raise ValueError("Special token IDs must be unique non-negative integers")


@dataclass(frozen=True)
class NormalizedSentenceInput:
    """Sanitized input sentence adhering to Boundary B contract."""

    text: str
    language: str = "en"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ModuleContractViolationError(
                "NormalizedSentenceInput text must be non-empty string"
            )
        if not isinstance(self.language, str) or len(self.language.strip()) < 2:
            raise ModuleContractViolationError(
                "NormalizedSentenceInput language must be valid code"
            )


@dataclass(frozen=True)
class TokenizedSentenceOutput:
    """Output schema for tokenized sentence and dense representations."""

    token_ids: List[int]
    tokens: List[str]
    embedding: Optional[List[float]] = None
    syntax_tree: Optional[Dict[str, Any]] = None
    max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH

    def __post_init__(self) -> None:
        if len(self.token_ids) != len(self.tokens):
            raise ModuleContractViolationError(
                f"token_ids length ({len(self.token_ids)}) != tokens length ({len(self.tokens)})"
            )
        if len(self.token_ids) > self.max_sequence_length:
            raise SequenceLengthExceededError(
                f"Token count ({len(self.token_ids)}) exceeds capacity ({self.max_sequence_length})"
            )
        if any(tid < 0 for tid in self.token_ids):
            raise ValueError("Token IDs must be non-negative integers")
        if self.embedding is not None:
            dim = len(self.embedding)
            if dim not in ALLOWED_EMBEDDING_DIMENSIONS:
                raise EmbeddingDimensionMismatchError(
                    f"Embedding dimension {dim} not in allowed {ALLOWED_EMBEDDING_DIMENSIONS}"
                )


def compute_vocabulary_sha256(token_to_id: Dict[str, int]) -> str:
    """Computes a deterministic cryptographic hash over vocabulary token assignments."""
    sorted_pairs = sorted(token_to_id.items(), key=lambda item: item[1])
    canonical_repr = "\n".join(f"{tok}\t{tid}" for tok, tid in sorted_pairs)
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VocabularyContract:
    """Immutable, bi-directional vocabulary contract for scientific tokenization."""

    vocab_size: int
    token_to_id: Dict[str, int]
    id_to_token: Dict[int, str]
    special_tokens: SpecialTokenConfig
    vocab_sha256: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (MIN_VOCAB_SIZE <= self.vocab_size <= MAX_VOCAB_SIZE):
            raise ValueError(
                f"vocab_size must be in [{MIN_VOCAB_SIZE}, {MAX_VOCAB_SIZE}], got {self.vocab_size}"
            )
        if len(self.token_to_id) != self.vocab_size:
            raise VocabularyMismatchError(
                f"token_to_id size ({len(self.token_to_id)}) != declared ({self.vocab_size})"
            )
        if len(self.id_to_token) != self.vocab_size:
            raise VocabularyMismatchError(
                f"id_to_token size ({len(self.id_to_token)}) != declared ({self.vocab_size})"
            )

        # Bijective mapping verification
        for token, tid in self.token_to_id.items():
            if self.id_to_token.get(tid) != token:
                raise VocabularyMismatchError(
                    f"Bijective mismatch for token '{token}' with ID {tid}"
                )

        # Verify all special tokens are mapped to their canonical IDs
        for spec_tok, spec_id in self.special_tokens.to_dict().items():
            actual_id = self.token_to_id.get(spec_tok)
            if actual_id != spec_id:
                raise VocabularyMismatchError(
                    f"Special token '{spec_tok}' expected ID {spec_id}, got {actual_id}"
                )

        # Verify cryptographic integrity
        computed_hash = compute_vocabulary_sha256(self.token_to_id)
        if self.vocab_sha256 != computed_hash:
            raise VocabularyMismatchError(
                f"Vocabulary SHA-256 mismatch: declared {self.vocab_sha256}, actual {computed_hash}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the vocabulary contract to a dictionary."""
        return {
            "vocab_size": self.vocab_size,
            "vocab_sha256": self.vocab_sha256,
            "special_tokens": self.special_tokens.to_dict(),
            "token_to_id": dict(self.token_to_id),
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes the vocabulary contract to a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_file(self, target_path: Union[str, Path]) -> None:
        """Writes the vocabulary contract to target_path."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VocabularyContract":
        """Reconstructs a VocabularyContract from a dictionary."""
        token_to_id = {k: int(v) for k, v in data["token_to_id"].items()}
        id_to_token = {int(v): k for k, v in token_to_id.items()}
        return cls(
            vocab_size=int(data["vocab_size"]),
            token_to_id=token_to_id,
            id_to_token=id_to_token,
            special_tokens=SpecialTokenConfig(),
            vocab_sha256=str(data["vocab_sha256"]),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "VocabularyContract":
        """Loads and validates a VocabularyContract from a JSON file."""
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Vocabulary file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    save_to_file = to_file
    load_from_file = from_file

    @classmethod
    def create(
        cls,
        tokens: List[str],
        special_tokens: Optional[SpecialTokenConfig] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "VocabularyContract":
        """Factory helper creating a valid VocabularyContract from an ordered list of tokens."""
        spec = special_tokens or SpecialTokenConfig()
        token_to_id: Dict[str, int] = {}
        id_to_token: Dict[int, str] = {}

        # 1. Insert special tokens first
        for spec_tok, spec_id in sorted(spec.to_dict().items(), key=lambda p: p[1]):
            token_to_id[spec_tok] = spec_id
            id_to_token[spec_id] = spec_tok

        # 2. Insert standard tokens sequentially
        current_id = max(id_to_token.keys()) + 1
        for tok in tokens:
            if tok in token_to_id:
                continue
            token_to_id[tok] = current_id
            id_to_token[current_id] = tok
            current_id += 1

        vocab_size = len(token_to_id)
        vocab_sha256 = compute_vocabulary_sha256(token_to_id)

        return cls(
            vocab_size=vocab_size,
            token_to_id=token_to_id,
            id_to_token=id_to_token,
            special_tokens=spec,
            vocab_sha256=vocab_sha256,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True)
class TokenizerTrainingInputSpec:
    """Specification of training data for tokenizer induction, enforcing zero leakage."""

    source_split: DatasetSplit
    source_manifest_id: str
    document_ids: List[str]
    min_frequency: int = 2
    target_vocab_size: int = DEFAULT_TARGET_VOCAB_SIZE
    special_tokens: SpecialTokenConfig = field(default_factory=SpecialTokenConfig)
    preserve_math: bool = True
    preserve_greek: bool = True
    preserve_units: bool = True

    def __post_init__(self) -> None:
        if self.source_split != DatasetSplit.TRAIN:
            raise DataLeakageError(
                f"Tokenizer training strictly prohibited on split '{self.source_split.value}'. "
                "Only DatasetSplit.TRAIN is permitted to prevent evaluation leakage."
            )
        if not self.document_ids:
            raise ValueError("TokenizerTrainingInputSpec document_ids must not be empty")
        if self.min_frequency < 1:
            raise ValueError(f"min_frequency must be >= 1, got {self.min_frequency}")
        if not (MIN_VOCAB_SIZE <= self.target_vocab_size <= MAX_VOCAB_SIZE):
            raise ValueError(
                f"target_vocab_size must be in [{MIN_VOCAB_SIZE}, {MAX_VOCAB_SIZE}], "
                f"got {self.target_vocab_size}"
            )

    def validate_against_manifest(self, manifest: CorpusManifest) -> None:
        """Verifies that all specified training documents exist in manifest and belong to TRAIN."""
        manifest_items_by_id = {item.corpus_id: item for item in manifest.items}
        for doc_id in self.document_ids:
            item = manifest_items_by_id.get(doc_id)
            if item is None:
                raise ModuleContractViolationError(
                    f"Document ID '{doc_id}' not found in manifest '{manifest.manifest_id}'"
                )
            if item.split != DatasetSplit.TRAIN:
                raise DataLeakageError(
                    f"Document '{doc_id}' belongs to split '{item.split.value}'. "
                    "Tokenizer training input contains non-TRAIN document, causing leakage!"
                )


@dataclass(frozen=True)
class SentenceEncoderContract:
    """Formal contract specification for Boundary B sentence encoders."""

    model_id: str
    embedding_dim: int
    max_sequence_length: int = DEFAULT_MAX_SEQUENCE_LENGTH
    pooling_strategy: str = "mean"
    normalize_embeddings: bool = True
    vocab_sha256: str = ""
    parameters_budget_mb: float = 1000.0

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_id.strip():
            raise ModuleContractViolationError("model_id must be a non-empty string")
        if self.embedding_dim not in ALLOWED_EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionMismatchError(
                f"Embedding dimension {self.embedding_dim} is invalid. "
                f"Allowed dimensions are {sorted(ALLOWED_EMBEDDING_DIMENSIONS)}"
            )
        if self.max_sequence_length <= 0:
            raise ValueError(f"max_sequence_length must be > 0, got {self.max_sequence_length}")
        if self.pooling_strategy not in {"mean", "cls", "max"}:
            raise ModuleContractViolationError(
                f"Invalid pooling_strategy '{self.pooling_strategy}'. Allowed: 'mean', 'cls', 'max'"
            )
        if self.parameters_budget_mb > 1024.0:
            raise ModuleContractViolationError(
                f"Encoder memory budget {self.parameters_budget_mb} MB "
                "exceeds Tier 1 limit (1.0 GB)"
            )


@dataclass(frozen=True)
class EncoderCheckpointMetadata:
    """Metadata recording checkpoint identity, provenance, and cryptographic integrity."""

    checkpoint_id: str
    model_id: str
    embedding_dim: int
    vocab_sha256: str
    weights_sha256: str
    parameter_count: int
    created_at: str
    lineage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.checkpoint_id or not self.checkpoint_id.strip():
            raise ModuleContractViolationError("checkpoint_id must not be empty")
        if self.embedding_dim not in ALLOWED_EMBEDDING_DIMENSIONS:
            allowed = sorted(ALLOWED_EMBEDDING_DIMENSIONS)
            raise EmbeddingDimensionMismatchError(
                f"Embedding dimension {self.embedding_dim} is not in {allowed}"
            )
        if len(self.vocab_sha256) != 64:
            raise ValueError(f"vocab_sha256 must be 64-char hex string, got '{self.vocab_sha256}'")
        if len(self.weights_sha256) != 64:
            raise ValueError(
                f"weights_sha256 must be 64-char hex string, got '{self.weights_sha256}'"
            )
        if self.parameter_count <= 0:
            raise ValueError(f"parameter_count must be > 0, got {self.parameter_count}")

    def to_dict(self) -> Dict[str, Any]:
        """Serializes metadata to dictionary."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "model_id": self.model_id,
            "embedding_dim": self.embedding_dim,
            "vocab_sha256": self.vocab_sha256,
            "weights_sha256": self.weights_sha256,
            "parameter_count": self.parameter_count,
            "created_at": self.created_at,
            "lineage": dict(self.lineage),
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes metadata to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EncoderCheckpointMetadata":
        """Deserializes metadata from dictionary."""
        return cls(
            checkpoint_id=data["checkpoint_id"],
            model_id=data["model_id"],
            embedding_dim=data["embedding_dim"],
            vocab_sha256=data["vocab_sha256"],
            weights_sha256=data["weights_sha256"],
            parameter_count=data["parameter_count"],
            created_at=data["created_at"],
            lineage=dict(data.get("lineage", {})),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "EncoderCheckpointMetadata":
        """Deserializes metadata from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def save_to_file(self, target_path: Union[str, Path]) -> None:
        """Saves metadata to JSON file."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load_from_file(cls, source_path: Union[str, Path]) -> "EncoderCheckpointMetadata":
        """Loads metadata from JSON file."""
        with open(source_path, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())


@dataclass(frozen=True)
class SentenceEmbeddingOutput:
    """Dense vector embedding representation of a single normalized sentence."""

    text: str
    embedding: List[float]
    token_count: int
    embedding_dim: int

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ModuleContractViolationError("SentenceEmbeddingOutput text must not be empty")
        if self.token_count <= 0:
            raise ValueError(f"token_count must be > 0, got {self.token_count}")
        if self.embedding_dim not in ALLOWED_EMBEDDING_DIMENSIONS:
            allowed = sorted(ALLOWED_EMBEDDING_DIMENSIONS)
            raise EmbeddingDimensionMismatchError(
                f"Embedding dimension {self.embedding_dim} must be in {allowed}"
            )
        if len(self.embedding) != self.embedding_dim:
            raise EmbeddingDimensionMismatchError(
                f"Embedding vector length ({len(self.embedding)}) does not match declared "
                f"embedding_dim ({self.embedding_dim})"
            )
        import math

        for idx, val in enumerate(self.embedding):
            if not math.isfinite(val):
                raise ValueError(f"Non-finite value at index {idx}: {val}")


@dataclass(frozen=True)
class EmbeddingBatchOutput:
    """Batch of sentence embedding representations."""

    embeddings: List[SentenceEmbeddingOutput]
    model_id: str
    embedding_dim: int
    batch_size: int

    def __post_init__(self) -> None:
        if not self.embeddings:
            raise ModuleContractViolationError("embeddings list must not be empty")
        if len(self.embeddings) != self.batch_size:
            raise ValueError(
                f"embeddings length ({len(self.embeddings)}) does not match "
                f"batch_size ({self.batch_size})"
            )
        for idx, emb in enumerate(self.embeddings):
            if emb.embedding_dim != self.embedding_dim:
                raise EmbeddingDimensionMismatchError(
                    f"Embedding at index {idx} dimension ({emb.embedding_dim}) does not match "
                    f"batch embedding_dim ({self.embedding_dim})"
                )


@dataclass(frozen=True)
class LanguageTrainingRunManifest:
    """Immutable audit record documenting language model training and evaluation provenance."""

    run_id: str
    model_id: str
    seed: int
    created_at: str
    hardware_info: Dict[str, Any]
    hyperparameters: Dict[str, Any]
    dataset_provenance: Dict[str, Any]
    training_metrics: Dict[str, float]
    evaluation_metrics: Dict[str, Any]
    checkpoint_metadata: EncoderCheckpointMetadata
    manifest_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ModuleContractViolationError("run_id must not be empty")
        if not self.model_id or not self.model_id.strip():
            raise ModuleContractViolationError("model_id must not be empty")
        if not self.created_at:
            raise ValueError("created_at must be provided")

        # Hardware safety envelope check (ADR-001 / ADR-005): RTX 5070 Ti headroom 14.5 GB VRAM
        vram_allocated_gb = self.hardware_info.get("peak_vram_gb", 0.0)
        if vram_allocated_gb > 14.5:
            raise HardwareBudgetExceededError(
                f"Peak VRAM allocation {vram_allocated_gb:.2f} GB exceeds safe threshold (14.5 GB)"
            )

        # Dataset provenance leakage check
        test_overlap_count = self.dataset_provenance.get("test_leakage_overlap_count", 0)
        if test_overlap_count > 0:
            raise DataLeakageError(
                f"Training run detected {test_overlap_count} overlapping documents with TEST split!"
            )

    def compute_sha256(self) -> str:
        """Computes the deterministic SHA-256 digest of the manifest contents."""
        content = {
            "run_id": self.run_id,
            "model_id": self.model_id,
            "seed": self.seed,
            "created_at": self.created_at,
            "hardware_info": self.hardware_info,
            "hyperparameters": self.hyperparameters,
            "dataset_provenance": self.dataset_provenance,
            "training_metrics": self.training_metrics,
            "evaluation_metrics": self.evaluation_metrics,
            "checkpoint_id": self.checkpoint_metadata.checkpoint_id,
            "weights_sha256": self.checkpoint_metadata.weights_sha256,
        }
        raw_json = json.dumps(content, sort_keys=True)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serializes manifest to dictionary."""
        sha = self.manifest_sha256 or self.compute_sha256()
        return {
            "run_id": self.run_id,
            "model_id": self.model_id,
            "seed": self.seed,
            "created_at": self.created_at,
            "hardware_info": dict(self.hardware_info),
            "hyperparameters": dict(self.hyperparameters),
            "dataset_provenance": dict(self.dataset_provenance),
            "training_metrics": dict(self.training_metrics),
            "evaluation_metrics": dict(self.evaluation_metrics),
            "checkpoint_metadata": self.checkpoint_metadata.to_dict(),
            "manifest_sha256": sha,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes manifest to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LanguageTrainingRunManifest":
        """Deserializes manifest from dictionary."""
        chk_meta = EncoderCheckpointMetadata.from_dict(data["checkpoint_metadata"])
        return cls(
            run_id=data["run_id"],
            model_id=data["model_id"],
            seed=data["seed"],
            created_at=data["created_at"],
            hardware_info=dict(data.get("hardware_info", {})),
            hyperparameters=dict(data.get("hyperparameters", {})),
            dataset_provenance=dict(data.get("dataset_provenance", {})),
            training_metrics=dict(data.get("training_metrics", {})),
            evaluation_metrics=dict(data.get("evaluation_metrics", {})),
            checkpoint_metadata=chk_meta,
            manifest_sha256=data.get("manifest_sha256", ""),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "LanguageTrainingRunManifest":
        """Deserializes manifest from JSON string."""
        return cls.from_dict(json.loads(json_str))


