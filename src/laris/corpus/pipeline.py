"""End-to-end ingestion and governance pipeline for Layer 0.

Adheres to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
Orchestrates:
1. License authorization verification and non-compliant quarantine
2. Deterministic text and math normalization
3. Cryptographic SHA-256 digest computation
4. Exact and near-duplicate deduplication
5. Leakage-proof author/document grouped partitioning
6. Immutable manifest and cryptographic fingerprint generation
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from laris.core.errors import LicenseViolationError
from laris.corpus.dedup import (
    DeduplicationEngine,
    DeduplicationPolicy,
    DuplicateRecord,
    compute_canonical_content_digest,
)
from laris.corpus.normalizer import normalize_scientific_text
from laris.corpus.partition import (
    DEFAULT_PARTITION_SEED,
    DatasetPartitionEngine,
    LargeGroupPolicy,
    MissingAuthorPolicy,
    SplitManifest,
    SplitRatios,
)
from laris.corpus.schemas import (
    CorpusManifest,
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
)


@dataclass(frozen=True)
class RawDocumentInput:
    """Raw unnormalized document payload ingested into Layer 0."""

    corpus_id: str
    raw_text: str
    declared_license: LicenseType
    verification_source: str
    verified_by: str
    authorized: bool = True
    authors: List[str] = field(default_factory=list)
    license_url: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Layer0PipelineOutput:
    """Immutable result payload of the executed Layer 0 ingestion pipeline."""

    unique_items: List[ValidatedCorpusItem]
    partitioned_items: Dict[DatasetSplit, List[ValidatedCorpusItem]]
    duplicates: List[DuplicateRecord]
    quarantined: List[Tuple[RawDocumentInput, str]]
    corpus_manifest: CorpusManifest
    split_manifest: SplitManifest


class Layer0Pipeline:
    """Configurable, deterministic end-to-end ingestion pipeline for Layer 0."""

    def __init__(
        self,
        dedup_policy: Optional[DeduplicationPolicy] = None,
        split_ratios: Optional[SplitRatios] = None,
        partition_seed: str = DEFAULT_PARTITION_SEED,
        missing_author_policy: MissingAuthorPolicy = MissingAuthorPolicy.DOCUMENT_AS_GROUP,
        large_group_policy: LargeGroupPolicy = LargeGroupPolicy.FORCE_TO_TRAIN,
        quarantine_unauthorized: bool = True,
    ) -> None:
        self.dedup_engine = DeduplicationEngine(policy=dedup_policy)
        self.partition_engine = DatasetPartitionEngine(
            ratios=split_ratios,
            seed=partition_seed,
            missing_author_policy=missing_author_policy,
            large_group_policy=large_group_policy,
        )
        self.quarantine_unauthorized = quarantine_unauthorized

    def execute(
        self,
        raw_documents: List[RawDocumentInput],
        manifest_id: str = "manifest-m1-e2e",
        created_at: str = "2026-10-15T00:00:00Z",
    ) -> Layer0PipelineOutput:
        """Executes the full Layer 0 ingestion, normalization, dedup, and partition flow."""
        validated_raw_items: List[Tuple[RawDocumentInput, ValidatedCorpusItem]] = []
        quarantined: List[Tuple[RawDocumentInput, str]] = []

        # Step 1: License Audit & Normalization
        for raw_doc in raw_documents:
            try:
                provenance = LicenseAuthorizationProvenance(
                    declared_license=raw_doc.declared_license,
                    verification_source=raw_doc.verification_source,
                    verified_by=raw_doc.verified_by,
                    authorized=raw_doc.authorized,
                    license_url=raw_doc.license_url,
                )
                if not provenance.authorized:
                    raise LicenseViolationError(
                        f"Document '{raw_doc.corpus_id}' is not authorized for redistribution"
                    )

                # Step 2: Normalization
                clean_text = normalize_scientific_text(raw_doc.raw_text)
                if not clean_text:
                    raise ValueError(f"Normalized text for '{raw_doc.corpus_id}' is empty")

                # Step 3: Canonical Content Hash Computation
                sha256_digest = compute_canonical_content_digest(clean_text, normalize=False)
                raw_bytes = clean_text.encode("utf-8")

                item = ValidatedCorpusItem(
                    corpus_id=raw_doc.corpus_id,
                    clean_text=clean_text,
                    sha256=sha256_digest,
                    split=DatasetSplit.TRAIN,  # Temporary split assignment
                    license_provenance=provenance,
                    byte_length=len(raw_bytes),
                    metadata=dict(raw_doc.metadata),
                )
                validated_raw_items.append((raw_doc, item))

            except (LicenseViolationError, ValueError) as err:
                if self.quarantine_unauthorized:
                    quarantined.append((raw_doc, str(err)))
                else:
                    raise

        # Step 4: Content Hashing & Deduplication
        candidate_items = [item for _, item in validated_raw_items]
        unique_items, duplicates = self.dedup_engine.deduplicate_batch(candidate_items)

        # Step 5: Author-Grouped Dataset Partitioning
        author_map = {
            raw_doc.corpus_id: raw_doc.authors
            for raw_doc, _ in validated_raw_items
        }
        partitioned = self.partition_engine.partition_items(
            unique_items, author_map=author_map
        )

        # Flatten partitioned items back to updated list of unique items
        final_unique_items: List[ValidatedCorpusItem] = []
        for split in (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST):
            final_unique_items.extend(partitioned[split])

        # Step 6: Manifest Generation
        corpus_manifest = CorpusManifest(
            manifest_id=manifest_id,
            created_at=created_at,
            items=final_unique_items,
        )
        split_manifest = self.partition_engine.generate_manifest(
            partitioned,
            manifest_id=f"{manifest_id}-splits",
            created_at=created_at,
        )

        return Layer0PipelineOutput(
            unique_items=final_unique_items,
            partitioned_items=partitioned,
            duplicates=duplicates,
            quarantined=quarantined,
            corpus_manifest=corpus_manifest,
            split_manifest=split_manifest,
        )
