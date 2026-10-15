"""Scientific retrieval benchmark engine and comparison report generator.

Adheres to DOC-SPEC-MOD-001 (Boundary B / MOD-LANG-002) and ADR-002:
- Curated versioned STEM retrieval corpus and evaluation queries
- Comparative retrieval evaluation: Compact Neural Embeddings vs Lexical BM25
- Metrics: Mean Reciprocal Rank (MRR), Hits@1, Hits@5, query latency, memory envelope
- Cryptographically verifiable report format with SHA-256 integrity
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer1_language.bm25 import (
    BM25Document,
    BM25RetrievalBaseline,
)
from laris.layers.layer1_language.encoder import BaseSentenceEncoder

RETRIEVAL_BENCHMARK_VERSION = "1.0.0"


@dataclass(frozen=True)
class RetrievalBenchmarkItem:
    """A benchmark query paired with ground-truth relevant document IDs."""

    query_id: str
    query_text: str
    relevant_doc_ids: List[str]
    domain: str

    def __post_init__(self) -> None:
        if not self.query_id or not self.query_id.strip():
            raise ModuleContractViolationError("query_id must not be empty")
        if not self.query_text or not self.query_text.strip():
            raise ModuleContractViolationError("query_text must not be empty")
        if not self.relevant_doc_ids:
            raise ModuleContractViolationError("relevant_doc_ids must not be empty")


@dataclass(frozen=True)
class RetrievalComparisonReport:
    """Evaluation report comparing dense embedding retrieval against BM25 baseline."""

    benchmark_version: str
    num_queries: int
    num_documents: int
    dense_mrr: float
    dense_hits_at_1: float
    dense_hits_at_5: float
    bm25_mrr: float
    bm25_hits_at_1: float
    bm25_hits_at_5: float
    avg_dense_latency_ms: float
    peak_memory_mb: float
    report_sha256: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes report to dictionary."""
        return {
            "benchmark_version": self.benchmark_version,
            "num_queries": self.num_queries,
            "num_documents": self.num_documents,
            "dense_mrr": round(self.dense_mrr, 4),
            "dense_hits_at_1": round(self.dense_hits_at_1, 4),
            "dense_hits_at_5": round(self.dense_hits_at_5, 4),
            "bm25_mrr": round(self.bm25_mrr, 4),
            "bm25_hits_at_1": round(self.bm25_hits_at_1, 4),
            "bm25_hits_at_5": round(self.bm25_hits_at_5, 4),
            "avg_dense_latency_ms": round(self.avg_dense_latency_ms, 2),
            "peak_memory_mb": round(self.peak_memory_mb, 2),
            "report_sha256": self.report_sha256,
            "metadata": dict(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


STEM_RETRIEVAL_CORPUS: List[BM25Document] = [
    BM25Document(
        doc_id="ret-phys-01",
        text=(
            "Quantum electrodynamics in cavity optomechanics demonstrates "
            "photon-phonon coupling at 15 mK."
        ),
        tokens=[
            "quantum", "electrodynamics", "cavity", "optomechanics", "photon", "phonon", "coupling"
        ],
        metadata={"domain": "physics"},
    ),
    BM25Document(
        doc_id="ret-phys-02",
        text=(
            "Majorana zero-bias conductance anomalies in "
            "superconductor-semiconductor heterostructures."
        ),
        tokens=[
            "majorana", "conductance", "anomalies", "superconductor", "semiconductor",
            "heterostructures",
        ],
        metadata={"domain": "physics"},
    ),
    BM25Document(
        doc_id="ret-chem-01",
        text=(
            "Zeolite-catalyzed cracking of polyolefin oligomers yields "
            "high-octane branched hydrocarbons."
        ),
        tokens=["zeolite", "catalyzed", "cracking", "polyolefin", "oligomers", "hydrocarbons"],
        metadata={"domain": "chemistry"},
    ),
    BM25Document(
        doc_id="ret-chem-02",
        text=(
            "Organometallic ruthenium phosphine complexes catalyze "
            "olefin metathesis reactions efficiently."
        ),
        tokens=[
            "organometallic", "ruthenium", "phosphine", "complexes",
            "catalyze", "olefin", "metathesis",
        ],
        metadata={"domain": "chemistry"},
    ),
    BM25Document(
        doc_id="ret-bio-01",
        text=(
            "CRISPR-Cas9 ribonucleoprotein complexes mediate targeted "
            "double-strand endonuclease cleavage."
        ),
        tokens=["crispr", "cas9", "ribonucleoprotein", "endonuclease", "cleavage", "targeted"],
        metadata={"domain": "biology"},
    ),
    BM25Document(
        doc_id="ret-bio-02",
        text=(
            "G-protein coupled transmembrane receptors undergo "
            "conformational isomerization on ligand binding."
        ),
        tokens=[
            "transmembrane", "receptors", "conformational",
            "isomerization", "ligand", "binding",
        ],
        metadata={"domain": "biology"},
    ),
    BM25Document(
        doc_id="ret-cs-01",
        text=(
            "Graph convolutional message-passing networks compute "
            "equivariant representations on hypergraphs."
        ),
        tokens=["graph", "convolutional", "message", "passing", "equivariant", "hypergraphs"],
        metadata={"domain": "computer_science"},
    ),
    BM25Document(
        doc_id="ret-cs-02",
        text=(
            "Static single assignment form optimizes register allocation "
            "and dead-code elimination."
        ),
        tokens=["static", "single", "assignment", "register", "allocation", "dead", "code"],
        metadata={"domain": "computer_science"},
    ),
    BM25Document(
        doc_id="ret-math-01",
        text=(
            "Cohomological operations on differentiable symplectic manifolds "
            "characterize topological invariants."
        ),
        tokens=["cohomological", "symplectic", "manifolds", "topological", "invariants"],
        metadata={"domain": "mathematics"},
    ),
    BM25Document(
        doc_id="ret-math-02",
        text=(
            "The spectral radius of non-negative irreducible Perron-Frobenius operators "
            "dominates ergodic measure."
        ),
        tokens=[
            "spectral", "radius", "irreducible", "perron",
            "frobenius", "operators", "ergodic",
        ],
        metadata={"domain": "mathematics"},
    ),
]


STEM_RETRIEVAL_QUERIES: List[RetrievalBenchmarkItem] = [
    RetrievalBenchmarkItem(
        query_id="q-phys-01",
        query_text="cryogenic cavity optomechanics photon phonon resonance",
        relevant_doc_ids=["ret-phys-01"],
        domain="physics",
    ),
    RetrievalBenchmarkItem(
        query_id="q-phys-02",
        query_text="Majorana topological superconducting phase transition",
        relevant_doc_ids=["ret-phys-02"],
        domain="physics",
    ),
    RetrievalBenchmarkItem(
        query_id="q-chem-01",
        query_text="zeolite catalyst polyolefin cracking branched products",
        relevant_doc_ids=["ret-chem-01"],
        domain="chemistry",
    ),
    RetrievalBenchmarkItem(
        query_id="q-chem-02",
        query_text="ruthenium phosphine complex olefin metathesis catalysis",
        relevant_doc_ids=["ret-chem-02"],
        domain="chemistry",
    ),
    RetrievalBenchmarkItem(
        query_id="q-bio-01",
        query_text="targeted endonuclease cleavage using CRISPR ribonucleoproteins",
        relevant_doc_ids=["ret-bio-01"],
        domain="biology",
    ),
    RetrievalBenchmarkItem(
        query_id="q-bio-02",
        query_text="G-protein transmembrane receptor conformational changes",
        relevant_doc_ids=["ret-bio-02"],
        domain="biology",
    ),
    RetrievalBenchmarkItem(
        query_id="q-cs-01",
        query_text="equivariant graph convolutional message passing architectures",
        relevant_doc_ids=["ret-cs-01"],
        domain="computer_science",
    ),
    RetrievalBenchmarkItem(
        query_id="q-cs-02",
        query_text="static single assignment compiler optimization register allocation",
        relevant_doc_ids=["ret-cs-02"],
        domain="computer_science",
    ),
    RetrievalBenchmarkItem(
        query_id="q-math-01",
        query_text="symplectic manifold cohomology topological invariants",
        relevant_doc_ids=["ret-math-01"],
        domain="mathematics",
    ),
    RetrievalBenchmarkItem(
        query_id="q-math-02",
        query_text="Perron Frobenius operator spectral radius ergodic dynamics",
        relevant_doc_ids=["ret-math-02"],
        domain="mathematics",
    ),
]


def _compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Computes dot product between two unit-normalized vectors."""
    return sum(a * b for a, b in zip(vec_a, vec_b))


def evaluate_retrieval_comparison(
    encoder: BaseSentenceEncoder,
    documents: Optional[List[BM25Document]] = None,
    queries: Optional[List[RetrievalBenchmarkItem]] = None,
    bm25_engine: Optional[BM25RetrievalBaseline] = None,
    top_k: int = 10,
) -> RetrievalComparisonReport:
    """Evaluates and compares compact neural embeddings against BM25 lexical retrieval."""
    docs = documents if documents is not None else STEM_RETRIEVAL_CORPUS
    eval_queries = queries if queries is not None else STEM_RETRIEVAL_QUERIES

    if not docs:
        raise ModuleContractViolationError("documents collection must not be empty")
    if not eval_queries:
        raise ModuleContractViolationError("queries collection must not be empty")

    # Initialize and index BM25 baseline
    bm25 = bm25_engine if bm25_engine is not None else BM25RetrievalBaseline()
    if bm25.doc_count == 0:
        bm25.index_documents(docs)

    # Encode documents with dense encoder
    doc_embeddings: Dict[str, List[float]] = {}
    for doc in docs:
        emb_output = encoder.encode_sentence(doc.text, truncate=True)
        doc_embeddings[doc.doc_id] = emb_output.embedding

    # Run query evaluations
    dense_reciprocal_ranks: List[float] = []
    dense_hits_1: List[float] = []
    dense_hits_5: List[float] = []

    bm25_reciprocal_ranks: List[float] = []
    bm25_hits_1: List[float] = []
    bm25_hits_5: List[float] = []

    total_query_latency = 0.0

    for q in eval_queries:
        q_start = time.perf_counter()
        q_emb = encoder.encode_sentence(q.query_text, truncate=True)
        q_elapsed = (time.perf_counter() - q_start) * 1000.0
        total_query_latency += q_elapsed

        # Rank documents by cosine similarity
        dense_scores = [
            (doc_id, _compute_cosine_similarity(q_emb.embedding, emb))
            for doc_id, emb in doc_embeddings.items()
        ]
        dense_ranked = [
            doc_id for doc_id, _ in sorted(dense_scores, key=lambda x: x[1], reverse=True)
        ][:top_k]

        # Calculate dense metrics
        relevant_set = set(q.relevant_doc_ids)
        dense_rr = 0.0
        for rank, doc_id in enumerate(dense_ranked, start=1):
            if doc_id in relevant_set:
                dense_rr = 1.0 / rank
                break
        dense_reciprocal_ranks.append(dense_rr)
        dense_hits_1.append(1.0 if dense_ranked and dense_ranked[0] in relevant_set else 0.0)
        dense_hits_5.append(
            1.0 if any(d in relevant_set for d in dense_ranked[:5]) else 0.0
        )

        # BM25 Search
        bm25_results = bm25.search(q.query_text, top_k=top_k)
        bm25_ranked = [res.doc_id for res in bm25_results]

        bm25_rr = 0.0
        for rank, doc_id in enumerate(bm25_ranked, start=1):
            if doc_id in relevant_set:
                bm25_rr = 1.0 / rank
                break
        bm25_reciprocal_ranks.append(bm25_rr)
        bm25_hits_1.append(1.0 if bm25_ranked and bm25_ranked[0] in relevant_set else 0.0)
        bm25_hits_5.append(
            1.0 if any(d in relevant_set for d in bm25_ranked[:5]) else 0.0
        )

    num_queries = len(eval_queries)
    avg_dense_mrr = sum(dense_reciprocal_ranks) / num_queries
    avg_dense_h1 = sum(dense_hits_1) / num_queries
    avg_dense_h5 = sum(dense_hits_5) / num_queries

    avg_bm25_mrr = sum(bm25_reciprocal_ranks) / num_queries
    avg_bm25_h1 = sum(bm25_hits_1) / num_queries
    avg_bm25_h5 = sum(bm25_hits_5) / num_queries

    avg_latency = total_query_latency / num_queries
    # Parameter and tensor memory estimation (Tier 1 model envelope <= 1.0 GB VRAM)
    param_count = encoder.get_checkpoint_metadata().parameter_count
    # 4 bytes per float parameter
    memory_mb = (param_count * 4.0) / (1024.0 * 1024.0)

    # Compute report SHA-256
    report_dict_for_hash = {
        "version": RETRIEVAL_BENCHMARK_VERSION,
        "dense_mrr": round(avg_dense_mrr, 4),
        "bm25_mrr": round(avg_bm25_mrr, 4),
        "num_queries": num_queries,
        "num_documents": len(docs),
    }
    report_sha256 = hashlib.sha256(
        json.dumps(report_dict_for_hash, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return RetrievalComparisonReport(
        benchmark_version=RETRIEVAL_BENCHMARK_VERSION,
        num_queries=num_queries,
        num_documents=len(docs),
        dense_mrr=avg_dense_mrr,
        dense_hits_at_1=avg_dense_h1,
        dense_hits_at_5=avg_dense_h5,
        bm25_mrr=avg_bm25_mrr,
        bm25_hits_at_1=avg_bm25_h1,
        bm25_hits_at_5=avg_bm25_h5,
        avg_dense_latency_ms=avg_latency,
        peak_memory_mb=memory_mb,
        report_sha256=report_sha256,
        metadata={
            "model_id": encoder.get_contract().model_id,
            "embedding_dim": encoder.get_contract().embedding_dim,
            "top_k": top_k,
        },
    )
