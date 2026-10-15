"""Typed schemas and domain contracts for Layer 0 (Corpus & Data Governance).

Adheres to DOC-SPEC-MOD-001 (Boundary A) and DOC-SPEC-SCHEMA-001.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from laris.core.errors import DuplicateCorpusError, LicenseViolationError


class DatasetSplit(str, Enum):
    """Explicit dataset split assignments."""
    TRAIN = "TRAIN"
    VAL = "VAL"
    TEST = "TEST"
    UNASSIGNED = "UNASSIGNED"


class LicenseType(str, Enum):
    """Canonical registry of redistribution and academic licenses."""
    CC_BY_4_0 = "CC-BY-4.0"
    CC_BY_SA_4_0 = "CC-BY-SA-4.0"
    APACHE_2_0 = "Apache-2.0"
    MIT = "MIT"
    ARXIV_NON_EXCLUSIVE = "arXiv-non-exclusive"
    CUSTOM_PERMISSIVE = "Custom-Permissive"
    PROPRIETARY_UNAUTHORIZED = "Proprietary-Unauthorized"
    UNKNOWN = "Unknown"


PERMITTED_OPEN_ACCESS_LICENSES: Set[LicenseType] = {
    LicenseType.CC_BY_4_0,
    LicenseType.CC_BY_SA_4_0,
    LicenseType.APACHE_2_0,
    LicenseType.MIT,
    LicenseType.ARXIV_NON_EXCLUSIVE,
    LicenseType.CUSTOM_PERMISSIVE,
}

_HEX_SHA256_REGEX = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class LicenseAuthorizationProvenance:
    """Immutable audit record demonstrating affirmative redistribution authorization."""
    declared_license: LicenseType
    verification_source: str
    verified_by: str
    authorized: bool
    license_url: Optional[str] = None
    verification_timestamp: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.verification_source or not self.verification_source.strip():
            raise ValueError("verification_source MUST NOT be empty")
        if not self.verified_by or not self.verified_by.strip():
            raise ValueError("verified_by MUST NOT be empty")
        if self.authorized and self.declared_license == LicenseType.PROPRIETARY_UNAUTHORIZED:
            raise LicenseViolationError(
                "Cannot authorize a document declared as Proprietary-Unauthorized"
            )
        if self.authorized and self.declared_license not in PERMITTED_OPEN_ACCESS_LICENSES:
            raise LicenseViolationError(
                f"License '{self.declared_license.value}' is not in permitted open access registry"
            )


@dataclass(frozen=True)
class ValidatedCorpusItem:
    """Canonical, sanitized, and cryptographic-hashed corpus document record."""
    corpus_id: str
    clean_text: str
    sha256: str
    split: DatasetSplit
    license_provenance: LicenseAuthorizationProvenance
    byte_length: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.corpus_id or not self.corpus_id.strip():
            raise ValueError("corpus_id MUST NOT be empty")
        if not self.clean_text:
            raise ValueError("clean_text MUST NOT be empty")
        if not _HEX_SHA256_REGEX.match(self.sha256):
            raise ValueError(
                f"sha256 must be a 64-character lowercase hexadecimal string, got: {self.sha256}"
            )
        if self.byte_length < 0:
            raise ValueError(f"byte_length must be non-negative, got: {self.byte_length}")

        actual_bytes = len(self.clean_text.encode("utf-8"))
        if self.byte_length != actual_bytes:
            raise ValueError(
                f"Declared byte_length ({self.byte_length}) does not match "
                f"UTF-8 encoded text byte count ({actual_bytes})"
            )


@dataclass
class CorpusManifest:
    """Aggregated manifest tracking an ingested collection of corpus items."""
    manifest_id: str
    created_at: str
    items: List[ValidatedCorpusItem] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.manifest_id or not self.manifest_id.strip():
            raise ValueError("manifest_id MUST NOT be empty")
        if not self.created_at or not self.created_at.strip():
            raise ValueError("created_at MUST NOT be empty")
        # Validate that initial items have no collisions
        seen_ids: Set[str] = set()
        seen_hashes: Set[str] = set()
        for item in self.items:
            if item.corpus_id in seen_ids:
                raise DuplicateCorpusError(f"Duplicate corpus_id in manifest: {item.corpus_id}")
            if item.sha256 in seen_hashes:
                raise DuplicateCorpusError(f"Duplicate content SHA-256 in manifest: {item.sha256}")
            seen_ids.add(item.corpus_id)
            seen_hashes.add(item.sha256)

    def add_item(self, item: ValidatedCorpusItem) -> None:
        """Appends a validated item while checking for ID and content collisions."""
        for existing in self.items:
            if existing.corpus_id == item.corpus_id:
                raise DuplicateCorpusError(f"Item with corpus_id '{item.corpus_id}' already exists")
            if existing.sha256 == item.sha256:
                raise DuplicateCorpusError(
                    f"Item with identical SHA-256 digest already exists: {item.sha256}"
                )
        self.items.append(item)

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def total_bytes(self) -> int:
        return sum(item.byte_length for item in self.items)

    @property
    def split_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {split.value: 0 for split in DatasetSplit}
        for item in self.items:
            counts[item.split.value] += 1
        return counts

    @property
    def license_distribution(self) -> Dict[str, int]:
        dist: Dict[str, int] = {}
        for item in self.items:
            lic = item.license_provenance.declared_license.value
            dist[lic] = dist.get(lic, 0) + 1
        return dist
