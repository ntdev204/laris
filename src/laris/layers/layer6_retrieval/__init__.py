"""Layer 6 Hybrid Hierarchical RAG and multi-channel retrieval module.

Adheres to DOC-SPEC-MOD-001 (Boundary F), ADR-001, ADR-004, and ADR-010.
"""

from laris.layers.layer6_retrieval.benchmark import (
    DepthBoundBenchmarkResult,
    DeterministicRankingResult,
    FallbackRobustnessResult,
    FilterAccuracyResult,
    RetrievalBenchmarkReport,
    RetrievalEvaluationBenchmark,
    RetrievalModalityResult,
)
from laris.layers.layer6_retrieval.dense_adapter import (
    DenseVectorAdapter,
    DenseVectorItem,
)
from laris.layers.layer6_retrieval.engine import HybridRetrievalEngine
from laris.layers.layer6_retrieval.fusion import ReciprocalRankFusion
from laris.layers.layer6_retrieval.graph_adapter import GraphRetrievalAdapter
from laris.layers.layer6_retrieval.interfaces import (
    BaseFusionCombiner,
    BaseRetrievalAdapter,
)
from laris.layers.layer6_retrieval.lexical_adapter import (
    LexicalBM25Adapter,
    LexicalDocument,
)
from laris.layers.layer6_retrieval.provenance import EvidenceCoordinateValidator
from laris.layers.layer6_retrieval.schemas import (
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
]


