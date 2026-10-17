"""Layer 6 Hybrid Hierarchical RAG and multi-channel retrieval module.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010.
"""

from laris.retrieval.benchmark import (
    DepthBoundBenchmarkResult,
    DeterministicRankingResult,
    FallbackRobustnessResult,
    FilterAccuracyResult,
    RetrievalBenchmarkReport,
    RetrievalEvaluationBenchmark,
    RetrievalModalityResult,
)
from laris.retrieval.dense_adapter import (
    DenseVectorAdapter,
    DenseVectorItem,
)
from laris.retrieval.engine import HybridRetrievalEngine
from laris.retrieval.fusion import ReciprocalRankFusion
from laris.retrieval.graph_adapter import GraphRetrievalAdapter
from laris.retrieval.interfaces import (
    BaseFusionCombiner,
    BaseRetrievalAdapter,
)
from laris.retrieval.lexical_adapter import (
    LexicalBM25Adapter,
    LexicalDocument,
)
from laris.retrieval.provenance import (
    DocumentProvenanceRecord,
    EvidenceCoordinateValidator,
    ProvenanceAuditReport,
    ProvenanceViolationDetail,
)
from laris.retrieval.schemas import (
    DEFAULT_RRF_K,
    MAX_RETRIEVAL_DEPTH,
    MetadataFilter,
    RetrievalCandidate,
    RetrievalChannel,
    RetrievalQuery,
)

__all__ = [
    "DEFAULT_RRF_K",
    "MAX_RETRIEVAL_DEPTH",
    "RetrievalChannel",
    "MetadataFilter",
    "RetrievalCandidate",
    "RetrievalQuery",
    "BaseRetrievalAdapter",
    "BaseFusionCombiner",
    "LexicalDocument",
    "LexicalBM25Adapter",
    "DenseVectorItem",
    "DenseVectorAdapter",
    "GraphRetrievalAdapter",
    "ReciprocalRankFusion",
    "HybridRetrievalEngine",
    "RetrievalModalityResult",
    "DeterministicRankingResult",
    "DepthBoundBenchmarkResult",
    "FilterAccuracyResult",
    "FallbackRobustnessResult",
    "RetrievalBenchmarkReport",
    "RetrievalEvaluationBenchmark",
    "EvidenceCoordinateValidator",
    "DocumentProvenanceRecord",
    "ProvenanceViolationDetail",
    "ProvenanceAuditReport",
]


