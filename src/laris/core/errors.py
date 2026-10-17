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


class CycleDetectedError(CyclicExecutionError, ModuleContractViolationError):
    """Raised when an orchestration task DAG contains a directed cycle or self-loop."""
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


class UncertaintyCeilingExceededError(ModuleContractViolationError):
    """Raised when an uncertainty score violates valid bounds [0.0, 1.0]
    or exceeds operational threshold.
    """
    pass


class DiscourseParseError(LarisError):
    """Raised when discourse relation parsing fails or encounters unparseable structure."""
    pass


class InvalidNLIInputError(ModuleContractViolationError):
    """Raised when an NLI input premise or hypothesis is empty, malformed, or invalid."""
    pass


class ProbabilityValidationError(ModuleContractViolationError):
    """Raised when class probabilities fail valid range or sum-to-one constraints."""
    pass


class ExtractionConfidenceBelowThresholdError(ModuleContractViolationError):
    """Raised when discourse entity extraction confidence falls below minimum threshold."""
    pass


class MalformedDiscourseSpanError(ModuleContractViolationError):
    """Raised when a discourse entity span has invalid character offsets or malformed content."""
    pass


class UnitConversionError(ModuleContractViolationError):
    """Raised when an unparseable or incompatible unit conversion is requested."""
    pass


class GraphIntegrityError(ModuleContractViolationError):
    """Raised when an evidence graph violates node/edge referential integrity or contracts."""
    pass


class InferredEdgeConflationError(GraphIntegrityError):
    """Raised when an inferred relation is conflated with or masquerades as author assertion."""
    pass



class SchemaMigrationError(LarisError):
    """Raised when an evidence graph fails schema version migration or compatibility checks."""
    pass


class RetrievalError(LarisError):
    """Base exception for Layer 6 multi-channel retrieval failures."""
    pass


class RetrievalDepthExceededError(RetrievalError, ModuleContractViolationError):
    """Raised when retrieval traversal depth exceeds configured safety ceilings."""
    pass


class WeightStagingError(LarisError):
    """Raised when specialist weight staging, offloading, or cache eviction fails."""
    pass


class TaskRoutingError(LarisError):
    """Raised when adaptive task routing, policy validation, or fallback fails."""
    pass


class BenchmarkRegressionError(LarisError):
    """Raised when an evaluation metric violates regression gate thresholds."""
    pass


class BenchmarkContaminationError(LarisError):
    """Raised when benchmark evaluation data is contaminated by training data."""
    pass


class PolicyRewardValidationError(LarisError):
    """Raised when policy evaluation reward signals are unverified, unnormalized, or corrupted."""
    pass


class UnanchoredAssertionError(LarisError):
    """Raised when a factual report assertion cannot be resolved to valid evidence coordinates."""
    pass


class ReportSchemaValidationError(LarisError):
    """Raised when a research report fails schema, section, or structural constraints."""
    pass


class EvidenceInspectionError(LarisError):
    """Base exception for evidence inspection and coordinate resolution failures."""
    pass


class CoordinateResolutionError(EvidenceInspectionError):
    """Raised when an evidence coordinate ID cannot be resolved to its source."""
    pass


class LineageError(LarisError):
    """Base exception for version lineage registry and DAG navigation failures."""
    pass


class LineageNotFoundError(LineageError):
    """Raised when a requested corpus, run, or report version is not found in lineage."""
    pass


class LineageCycleError(LineageError):
    """Raised when adding a parent or version edge creates a cycle in lineage DAG."""
    pass


class InterventionAuditError(LarisError):
    """Base exception for user intervention recording and audit trail failures."""
    pass


class AuditIntegrityError(InterventionAuditError):
    """Raised when an immutable intervention audit log fails cryptographic verification."""
    pass


class InvalidInterventionError(InterventionAuditError):
    """Raised when a user intervention action, target, or modification payload is invalid."""
    pass


class TrainingExecutionProhibitedError(LarisError):
    """Raised when prohibited model training, tokenizer training, or weight updates are run."""
    pass
