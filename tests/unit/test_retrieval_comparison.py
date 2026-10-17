"""Unit tests for retrieval evaluation benchmark and BM25 comparison engine."""

import json

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.language.bm25 import BM25Document, BM25RetrievalBaseline
from laris.language.encoder import CompactSentenceEncoder
from laris.language.retrieval_benchmark import (
    RETRIEVAL_BENCHMARK_VERSION,
    STEM_RETRIEVAL_CORPUS,
    STEM_RETRIEVAL_QUERIES,
    RetrievalBenchmarkItem,
    evaluate_retrieval_comparison,
)
from laris.language.schemas import VocabularyContract
from laris.language.stem_benchmark import get_stem_vocabulary_tokens
from laris.language.tokenizer import ScientificTokenizer


@pytest.fixture
def stem_tokenizer() -> ScientificTokenizer:
    """Fixture providing a ScientificTokenizer initialized with STEM vocabulary."""
    tokens = get_stem_vocabulary_tokens()
    all_tokens = sorted(set(tokens))
    vocab = VocabularyContract.create(all_tokens)
    return ScientificTokenizer(vocab=vocab)


@pytest.fixture
def stem_encoder(stem_tokenizer: ScientificTokenizer) -> CompactSentenceEncoder:
    """Fixture providing a CompactSentenceEncoder with D=384."""
    return CompactSentenceEncoder(
        tokenizer=stem_tokenizer,
        embedding_dim=384,
        seed=42,
    )


def test_retrieval_benchmark_item_invariants() -> None:
    """Verifies validation rules on RetrievalBenchmarkItem."""
    with pytest.raises(ModuleContractViolationError, match="query_id"):
        RetrievalBenchmarkItem(
            query_id="",
            query_text="quantum physics",
            relevant_doc_ids=["doc-01"],
            domain="physics",
        )

    with pytest.raises(ModuleContractViolationError, match="query_text"):
        RetrievalBenchmarkItem(
            query_id="q1",
            query_text="   ",
            relevant_doc_ids=["doc-01"],
            domain="physics",
        )

    with pytest.raises(ModuleContractViolationError, match="relevant_doc_ids"):
        RetrievalBenchmarkItem(
            query_id="q1",
            query_text="quantum physics",
            relevant_doc_ids=[],
            domain="physics",
        )


def test_evaluate_retrieval_comparison_full_suite(
    stem_encoder: CompactSentenceEncoder,
) -> None:
    """Verifies end-to-end evaluation over curated STEM retrieval benchmark."""
    report = evaluate_retrieval_comparison(
        encoder=stem_encoder,
        documents=STEM_RETRIEVAL_CORPUS,
        queries=STEM_RETRIEVAL_QUERIES,
        top_k=5,
    )

    assert report.benchmark_version == RETRIEVAL_BENCHMARK_VERSION
    assert report.num_documents == len(STEM_RETRIEVAL_CORPUS)
    assert report.num_queries == len(STEM_RETRIEVAL_QUERIES)

    # Metric bounds check
    assert 0.0 <= report.dense_mrr <= 1.0
    assert 0.0 <= report.dense_hits_at_1 <= 1.0
    assert 0.0 <= report.dense_hits_at_5 <= 1.0
    assert 0.0 <= report.bm25_mrr <= 1.0
    assert 0.0 <= report.bm25_hits_at_1 <= 1.0
    assert 0.0 <= report.bm25_hits_at_5 <= 1.0

    # Resource constraints (Boundary B: latency < 20ms/sentence, Tier 1 model < 1000MB)
    assert report.avg_dense_latency_ms < 20.0
    assert report.peak_memory_mb < 1000.0

    # Cryptographic integrity
    assert len(report.report_sha256) == 64

    # JSON serialization roundtrip
    json_repr = report.to_json()
    parsed = json.loads(json_repr)
    assert parsed["num_queries"] == len(STEM_RETRIEVAL_QUERIES)
    assert parsed["report_sha256"] == report.report_sha256


def test_evaluate_retrieval_comparison_edge_cases(
    stem_encoder: CompactSentenceEncoder,
) -> None:
    """Verifies error handling on empty documents or queries collections."""
    with pytest.raises(ModuleContractViolationError, match="documents collection"):
        evaluate_retrieval_comparison(
            encoder=stem_encoder,
            documents=[],
            queries=STEM_RETRIEVAL_QUERIES,
        )

    with pytest.raises(ModuleContractViolationError, match="queries collection"):
        evaluate_retrieval_comparison(
            encoder=stem_encoder,
            documents=STEM_RETRIEVAL_CORPUS,
            queries=[],
        )


def test_evaluate_retrieval_custom_corpus_and_perfect_ranking(
    stem_encoder: CompactSentenceEncoder,
) -> None:
    """Verifies MRR computation on a targeted synthetic document-query pair."""
    doc = BM25Document(
        doc_id="custom-phys-01",
        text="Cryogenic superconducting qubit resonators demonstrate microwave coherence.",
        tokens=["cryogenic", "superconducting", "qubit", "resonators", "coherence"],
    )
    query = RetrievalBenchmarkItem(
        query_id="q-custom-01",
        query_text="cryogenic superconducting qubit coherence",
        relevant_doc_ids=["custom-phys-01"],
        domain="physics",
    )

    bm25 = BM25RetrievalBaseline()
    bm25.index_documents([doc])

    report = evaluate_retrieval_comparison(
        encoder=stem_encoder,
        documents=[doc],
        queries=[query],
        bm25_engine=bm25,
        top_k=1,
    )

    assert report.num_queries == 1
    assert report.num_documents == 1
    assert report.bm25_mrr == 1.0
    assert report.bm25_hits_at_1 == 1.0
