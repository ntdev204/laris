"""Canonical exception and error hierarchies for LARIS."""

class LarisError(Exception):
    """Base exception class for all LARIS system failures."""
    pass


class ProvenanceViolationError(LarisError):
    """Raised when an extracted claim or report assertion lacks verified evidence coordinates."""
    pass


class EpistemicOverreachError(LarisError):
    """Raised when a correlational finding is described as causal,
    or absence of evidence is claimed as negation.
    """
    pass


class HardwareBudgetExceededError(LarisError):
    """Raised when an operation would exceed the 14.5 GB safety threshold on the RTX 5070 Ti."""
    pass


class ModuleContractViolationError(LarisError):
    """Raised when input or output data violates the interface contract of a module boundary."""
    pass


class CyclicExecutionError(LarisError):
    """Raised when an agent enters an infinite recursion or dispatches duplicate tool calls."""
    pass


class LicenseViolationError(LarisError):
    """Raised when an ingested document lacks a permitted open-access redistribution license."""
    pass


class EncodingCorruptError(LarisError):
    """Raised when text encoding cannot be deterministically normalized to valid UTF-8."""
    pass


class DuplicateCorpusError(LarisError):
    """Raised when an identical or near-duplicate document is detected in the corpus."""
    pass


class DataLeakageError(LarisError):
    """Raised when an entity or author overlaps between training and evaluation splits."""
    pass


class SequenceLengthExceededError(LarisError):
    """Raised when an input sequence length exceeds the maximum sequence capacity."""
    pass


class VocabularyMismatchError(LarisError):
    """Raised when token IDs or vocabulary mappings conflict with vocabulary contracts."""
    pass


class EmbeddingDimensionMismatchError(LarisError):
    """Raised when an output embedding dimension does not match the configured model dimension."""
    pass


class DataIntegrityError(LarisError):
    """Raised when an artifact cryptographic hash or checksum fails verification."""
    pass

