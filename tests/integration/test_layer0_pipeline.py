"""End-to-end integration tests for Layer 0 Corpus Ingestion Pipeline.

Verifies DOC-SPEC-MOD-001 (Boundary A) and ADR-001:
- License auditing and quarantine
- Text and math normalization
- Canonical SHA-256 content hashing
- Exact and near-duplicate deduplication
- Leakage-free author-grouped partitioning
- Immutable manifest generation and cryptographic reproducibility
"""

import pytest

from laris.core.errors import LicenseViolationError
from laris.layers.layer0_corpus.dedup import DeduplicationPolicy
from laris.layers.layer0_corpus.partition import (
    SplitRatios,
    verify_split_leakage,
)
from laris.layers.layer0_corpus.pipeline import Layer0Pipeline
from laris.layers.layer0_corpus.schemas import validate_manifest_consistency
from tests.fixtures.synthetic_corpus import (
    get_standard_synthetic_corpus,
    get_synthetic_author_map,
)


def test_layer0_pipeline_end_to_end_execution() -> None:
    """Tests the full Layer 0 ingestion pipeline with the synthetic corpus."""
    corpus = get_standard_synthetic_corpus()
    author_map = get_synthetic_author_map(corpus)

    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus, manifest_id="manifest-e2e-001")

    # 1. Verify Quarantine Behavior
    quarantined_ids = [doc.corpus_id for doc, _ in output.quarantined]
    assert "synth-009-unauthorized" in quarantined_ids
    assert "synth-010-empty" in quarantined_ids
    assert len(output.quarantined) == 2

    # Verify quarantine reasons
    quarantined_dict = {doc.corpus_id: reason for doc, reason in output.quarantined}
    assert "not authorized" in quarantined_dict["synth-009-unauthorized"]
    assert "empty" in quarantined_dict["synth-010-empty"]

    # 2. Verify Deduplication
    dup_ids = [d.duplicate_corpus_id for d in output.duplicates]
    assert "synth-001-dup" in dup_ids
    assert "synth-002-near" in dup_ids

    # synth-001 should be kept as canonical
    unique_ids = {item.corpus_id for item in output.unique_items}
    assert "synth-001" in unique_ids
    assert "synth-001-dup" not in unique_ids
    assert "synth-002-near" not in unique_ids

    # 3. Verify Author Leakage Prevention
    assert verify_split_leakage(output.partitioned_items, author_map)

    # Co-authors Alice, Bob, Charlie, David must all be in the same split
    coauthor_items = [
        item for item in output.unique_items
        if item.corpus_id in ("synth-001", "synth-003", "synth-004")
    ]
    splits = {item.split for item in coauthor_items}
    assert len(splits) == 1, f"Connected co-authors were split across: {splits}"

    # 4. Verify Corpus Manifest & Consistency
    assert output.corpus_manifest.manifest_id == "manifest-e2e-001"
    assert len(output.corpus_manifest.items) == len(output.unique_items)
    validate_manifest_consistency(
        output.corpus_manifest, expected_total_items=len(output.unique_items)
    )

    # 5. Verify Split Manifest
    assert output.split_manifest.manifest_id == "manifest-e2e-001-splits"
    assert output.split_manifest.split_sha256_digests["TRAIN"] != ""
    assert output.split_manifest.total_items == len(output.unique_items)
    assert sum(output.split_manifest.split_counts.values()) == len(output.unique_items)


def test_layer0_pipeline_strict_quarantine_mode() -> None:
    """Verifies that quarantine_unauthorized=False raises immediately on invalid items."""
    corpus = get_standard_synthetic_corpus()
    strict_pipeline = Layer0Pipeline(quarantine_unauthorized=False)

    with pytest.raises(LicenseViolationError, match="not authorized"):
        strict_pipeline.execute(corpus)


def test_layer0_pipeline_reproducibility() -> None:
    """Verifies that two pipeline executions with identical input produce identical output."""
    corpus1 = get_standard_synthetic_corpus()
    corpus2 = get_standard_synthetic_corpus()

    pipeline1 = Layer0Pipeline()
    pipeline2 = Layer0Pipeline()

    output1 = pipeline1.execute(corpus1, manifest_id="run-1", created_at="2026-10-15T12:00:00Z")
    output2 = pipeline2.execute(corpus2, manifest_id="run-1", created_at="2026-10-15T12:00:00Z")

    assert [item.corpus_id for item in output1.unique_items] == [
        item.corpus_id for item in output2.unique_items
    ]
    assert [item.sha256 for item in output1.unique_items] == [
        item.sha256 for item in output2.unique_items
    ]
    assert [item.split for item in output1.unique_items] == [
        item.split for item in output2.unique_items
    ]
    assert (
        output1.split_manifest.split_sha256_digests
        == output2.split_manifest.split_sha256_digests
    )


def test_layer0_pipeline_near_dedup_threshold_override() -> None:
    """Verifies configurable near-deduplication threshold in the pipeline."""
    corpus = get_standard_synthetic_corpus()

    # Setting threshold to 0.99 ensures synth-002-near is NOT flagged as near-duplicate
    strict_dedup_policy = DeduplicationPolicy(near_duplicate_threshold=0.99)
    pipeline = Layer0Pipeline(dedup_policy=strict_dedup_policy)

    output = pipeline.execute(corpus)
    unique_ids = {item.corpus_id for item in output.unique_items}

    assert "synth-001" in unique_ids
    assert "synth-002-near" in unique_ids
    assert "synth-001-dup" not in unique_ids  # Exact duplicate is still eliminated


def test_layer0_pipeline_custom_ratios_and_seed() -> None:
    """Verifies pipeline execution with custom partition ratios and seed."""
    corpus = get_standard_synthetic_corpus()
    author_map = get_synthetic_author_map(corpus)

    custom_ratios = SplitRatios(train=0.70, val=0.15, test=0.15)
    pipeline = Layer0Pipeline(split_ratios=custom_ratios, partition_seed="custom-seed-42")

    output = pipeline.execute(corpus)

    assert verify_split_leakage(output.partitioned_items, author_map)
    validate_manifest_consistency(
        output.corpus_manifest, expected_total_items=len(output.unique_items)
    )
    assert output.split_manifest.split_counts["TRAIN"] > 0
