"""Layer 0: Corpus Ingestion and Data Governance."""

from laris.layers.layer0_corpus.dedup import (
    DIGEST_ALGORITHM,
    DIGEST_ENCODING,
    DIGEST_SPEC_VERSION,
    DuplicateRecord,
    ExactDeduplicator,
    compute_canonical_content_digest,
    verify_content_digest,
)
from laris.layers.layer0_corpus.normalizer import normalize_scientific_text
from laris.layers.layer0_corpus.schemas import (
    PERMITTED_OPEN_ACCESS_LICENSES,
    CorpusManifest,
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
    validate_manifest_consistency,
    verify_item_authorization,
    verify_item_content_hash,
)

__all__ = [
    "DatasetSplit",
    "LicenseType",
    "PERMITTED_OPEN_ACCESS_LICENSES",
    "LicenseAuthorizationProvenance",
    "ValidatedCorpusItem",
    "CorpusManifest",
    "verify_item_content_hash",
    "verify_item_authorization",
    "validate_manifest_consistency",
    "normalize_scientific_text",
    "compute_canonical_content_digest",
    "verify_content_digest",
    "DuplicateRecord",
    "ExactDeduplicator",
    "DIGEST_ALGORITHM",
    "DIGEST_ENCODING",
    "DIGEST_SPEC_VERSION",
]
