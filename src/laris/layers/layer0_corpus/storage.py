"""Storage and serialization utilities for Layer 0 processed corpus artifacts.

Implements serialization, deserialization, and structural integrity verification
for normalized, deduplicated, and partitioned corpus splits stored under
`data/processed/` according to DOC-SPEC-MOD-001 (Boundary A) and ADR-001.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer0_corpus.partition import SplitManifest, SplitRatios
from laris.layers.layer0_corpus.pipeline import Layer0PipelineOutput
from laris.layers.layer0_corpus.schemas import (
    DatasetSplit,
    LicenseAuthorizationProvenance,
    LicenseType,
    ValidatedCorpusItem,
    verify_item_authorization,
    verify_item_content_hash,
)

MANIFEST_FILE_NAME = "manifest.json"
SPLIT_MANIFEST_FILE_NAME = "split_manifest.json"
SPLIT_FILE_NAMES: Dict[DatasetSplit, str] = {
    DatasetSplit.TRAIN: "train.jsonl",
    DatasetSplit.VAL: "val.jsonl",
    DatasetSplit.TEST: "test.jsonl",
}


def _item_to_dict(item: ValidatedCorpusItem) -> Dict[str, Any]:
    """Serializes a ValidatedCorpusItem to a JSON-compatible dictionary."""
    return {
        "corpus_id": item.corpus_id,
        "clean_text": item.clean_text,
        "sha256": item.sha256,
        "split": item.split.value,
        "byte_length": item.byte_length,
        "license_provenance": {
            "declared_license": item.license_provenance.declared_license.value,
            "verification_source": item.license_provenance.verification_source,
            "verified_by": item.license_provenance.verified_by,
            "authorized": item.license_provenance.authorized,
            "license_url": item.license_provenance.license_url,
            "verification_timestamp": item.license_provenance.verification_timestamp,
            "notes": item.license_provenance.notes,
        },
        "metadata": dict(item.metadata),
    }


def _dict_to_item(data: Dict[str, Any]) -> ValidatedCorpusItem:
    """Deserializes a dictionary into a ValidatedCorpusItem with strict contract checks."""
    prov_data = data["license_provenance"]
    provenance = LicenseAuthorizationProvenance(
        declared_license=LicenseType(prov_data["declared_license"]),
        verification_source=prov_data["verification_source"],
        verified_by=prov_data["verified_by"],
        authorized=bool(prov_data["authorized"]),
        license_url=prov_data.get("license_url"),
        verification_timestamp=prov_data.get("verification_timestamp"),
        notes=prov_data.get("notes"),
    )
    item = ValidatedCorpusItem(
        corpus_id=data["corpus_id"],
        clean_text=data["clean_text"],
        sha256=data["sha256"],
        split=DatasetSplit(data["split"]),
        byte_length=data["byte_length"],
        license_provenance=provenance,
        metadata=dict(data.get("metadata", {})),
    )
    raw_bytes = item.clean_text.encode("utf-8")
    if not verify_item_content_hash(item, raw_bytes):
        raise ModuleContractViolationError(
            f"Hash mismatch for item '{item.corpus_id}': declared {item.sha256}"
        )
    if not verify_item_authorization(item):
        lic_name = item.license_provenance.declared_license
        raise ModuleContractViolationError(
            f"Unauthorized item '{item.corpus_id}' with license {lic_name}"
        )
    return item


def _split_manifest_to_dict(manifest: SplitManifest) -> Dict[str, Any]:
    """Serializes a SplitManifest to a JSON-compatible dictionary."""
    return {
        "manifest_id": manifest.manifest_id,
        "seed": manifest.seed,
        "algorithm": manifest.algorithm,
        "spec_version": manifest.spec_version,
        "created_at": manifest.created_at,
        "ratios": {
            "train": manifest.ratios.train,
            "val": manifest.ratios.val,
            "test": manifest.ratios.test,
        },
        "split_counts": dict(manifest.split_counts),
        "split_bytes": dict(manifest.split_bytes),
        "split_sha256_digests": dict(manifest.split_sha256_digests),
        "total_items": manifest.total_items,
        "total_bytes": manifest.total_bytes,
        "author_group_count": manifest.author_group_count,
        "missing_author_policy": manifest.missing_author_policy,
        "large_group_policy": manifest.large_group_policy,
    }


def _dict_to_split_manifest(data: Dict[str, Any]) -> SplitManifest:
    """Deserializes a dictionary into a SplitManifest."""
    ratios_data = data["ratios"]
    ratios = SplitRatios(
        train=ratios_data["train"],
        val=ratios_data["val"],
        test=ratios_data["test"],
    )
    return SplitManifest(
        manifest_id=data["manifest_id"],
        seed=data["seed"],
        algorithm=data["algorithm"],
        spec_version=data["spec_version"],
        created_at=data["created_at"],
        ratios=ratios,
        split_counts=dict(data["split_counts"]),
        split_bytes=dict(data["split_bytes"]),
        split_sha256_digests=dict(data["split_sha256_digests"]),
        total_items=int(data["total_items"]),
        total_bytes=int(data["total_bytes"]),
        author_group_count=int(data["author_group_count"]),
        missing_author_policy=data["missing_author_policy"],
        large_group_policy=data["large_group_policy"],
    )


def export_processed_corpus(
    output: Layer0PipelineOutput,
    target_dir: Union[str, Path],
) -> Dict[str, Path]:
    """Persists partitioned dataset splits and manifests into target_dir.

    Layout:
        target_dir/
            manifest.json
            split_manifest.json
            train.jsonl
            val.jsonl
            test.jsonl
    """
    path = Path(target_dir)
    path.mkdir(parents=True, exist_ok=True)

    paths: Dict[str, Path] = {}

    # 1. Write corpus manifest
    manifest_path = path / MANIFEST_FILE_NAME
    manifest_dict = {
        "manifest_id": output.corpus_manifest.manifest_id,
        "created_at": output.corpus_manifest.created_at,
        "metadata": dict(output.corpus_manifest.metadata),
        "items": [_item_to_dict(item) for item in output.corpus_manifest.items],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_dict, f, indent=2, ensure_ascii=False)
    paths["manifest"] = manifest_path

    # 2. Write split manifest
    split_manifest_path = path / SPLIT_MANIFEST_FILE_NAME
    with open(split_manifest_path, "w", encoding="utf-8") as f:
        json.dump(_split_manifest_to_dict(output.split_manifest), f, indent=2, ensure_ascii=False)
    paths["split_manifest"] = split_manifest_path

    # 3. Write individual split jsonl files
    for split, filename in SPLIT_FILE_NAMES.items():
        split_path = path / filename
        items = output.partitioned_items.get(split, [])
        with open(split_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(_item_to_dict(item), ensure_ascii=False) + "\n")
        paths[split.value.lower()] = split_path

    return paths


def load_processed_split(split_file: Union[str, Path]) -> List[ValidatedCorpusItem]:
    """Loads and validates a single split JSONL file."""
    path = Path(split_file)
    if not path.is_file():
        raise FileNotFoundError(f"Split file not found: {path}")

    items: List[ValidatedCorpusItem] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                items.append(_dict_to_item(record))
            except Exception as err:
                raise ModuleContractViolationError(
                    f"Corrupt record in {path.name} at line {line_num}: {err}"
                ) from err

    return items


def verify_processed_directory_layout(target_dir: Union[str, Path]) -> bool:
    """Verifies that target_dir conforms strictly to the Layer 0 processed storage policy.

    Checks:
    - Existence of manifest.json, split_manifest.json, train.jsonl, val.jsonl, test.jsonl
    - Valid schema and hashes for every item across all splits
    - Agreement between split_manifest counts and actual line counts in split files
    - Agreement between manifest total_items and sum of items across splits
    """
    path = Path(target_dir)
    if not path.is_dir():
        raise ModuleContractViolationError(f"Target directory does not exist: {path}")

    # Check required files
    manifest_path = path / MANIFEST_FILE_NAME
    split_manifest_path = path / SPLIT_MANIFEST_FILE_NAME

    if not manifest_path.is_file():
        raise ModuleContractViolationError(f"Missing {MANIFEST_FILE_NAME} in {path}")
    if not split_manifest_path.is_file():
        raise ModuleContractViolationError(f"Missing {SPLIT_MANIFEST_FILE_NAME} in {path}")

    # Load and verify split manifest
    with open(split_manifest_path, "r", encoding="utf-8") as f:
        split_manifest_dict = json.load(f)
    split_manifest = _dict_to_split_manifest(split_manifest_dict)

    # Load each split and verify items
    total_split_items = 0
    total_split_bytes = 0
    for split, filename in SPLIT_FILE_NAMES.items():
        file_path = path / filename
        if not file_path.is_file():
            raise ModuleContractViolationError(f"Missing split file: {filename}")

        items = load_processed_split(file_path)
        expected_count = split_manifest.split_counts.get(split.value, 0)
        if len(items) != expected_count:
            raise ModuleContractViolationError(
                f"Split {split.value} item count mismatch: manifest expected {expected_count}, "
                f"found {len(items)}"
            )

        total_split_items += len(items)
        total_split_bytes += sum(i.byte_length for i in items)

    if total_split_items != split_manifest.total_items:
        raise ModuleContractViolationError(
            f"Total items mismatch: manifest has {split_manifest.total_items}, "
            f"splits sum to {total_split_items}"
        )

    # Load corpus manifest and cross-check
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    manifest_items = [_dict_to_item(i) for i in manifest_data["items"]]
    if len(manifest_items) != total_split_items:
        raise ModuleContractViolationError(
            f"Manifest items count ({len(manifest_items)}) != split items ({total_split_items})"
        )

    return True
