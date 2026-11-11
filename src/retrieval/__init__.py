"""Layer 6 Hybrid Hierarchical RAG and multi-channel retrieval module.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010.
"""

from retrieval.benchmark import (
    DepthBoundBenchmarkResult,
    DeterministicRankingResult,
    FallbackRobustnessResult,
    FilterAccuracyResult,
    RetrievalBenchmarkReport,
    RetrievalEvaluationBenchmark,
    RetrievalModalityResult,
)
from retrieval.dense_adapter import (
    DenseVectorAdapter,
    DenseVectorItem,
)
from retrieval.engine import HybridRetrievalEngine
from retrieval.fusion import ReciprocalRankFusion
from retrieval.graph_adapter import GraphRetrievalAdapter
from retrieval.interfaces import (
    BaseFusionCombiner,
    BaseRetrievalAdapter,
)
from retrieval.lexical_adapter import (
    LexicalBM25Adapter,
    LexicalDocument,
)
from retrieval.provenance import (
    DocumentProvenanceRecord,
    EvidenceCoordinateValidator,
    ProvenanceAuditReport,
    ProvenanceViolationDetail,
)
from retrieval.schemas import (
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


