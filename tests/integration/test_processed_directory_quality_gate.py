"""Quality gate and storage policy integration tests for Layer 0 (M1 Exit Gate).

Verifies:
- Processed directory layout conventions and schema validation
- Serialization, loading, and tamper detection of corpus splits
- `.gitignore` and `.gitkeep` enforcement preventing corpus data from leaking into git
- Comprehensive verification of all Milestone M1 exit criteria
"""

import json
import subprocess
from pathlib import Path

import pytest

from laris.core.errors import ModuleContractViolationError
from laris.layers.layer0_corpus.pipeline import Layer0Pipeline
from laris.layers.layer0_corpus.schemas import DatasetSplit
from laris.layers.layer0_corpus.storage import (
    MANIFEST_FILE_NAME,
    SPLIT_MANIFEST_FILE_NAME,
    export_processed_corpus,
    load_processed_split,
    verify_processed_directory_layout,
)
from tests.fixtures.synthetic_corpus import get_standard_synthetic_corpus


def test_processed_directory_export_and_layout(tmp_path: Path) -> None:
    """Verifies exporting Layer0Pipeline output creates a compliant directory structure."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus, manifest_id="manifest-gate-001")

    export_paths = export_processed_corpus(output, tmp_path)

    # Check returned paths
    assert export_paths["manifest"].is_file()
    assert export_paths["split_manifest"].is_file()
    assert export_paths["train"].is_file()
    assert export_paths["val"].is_file()
    assert export_paths["test"].is_file()

    # Check directory layout verification passes
    assert verify_processed_directory_layout(tmp_path)

    # Check contents of loaded splits match output
    for split in (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST):
        split_items = load_processed_split(export_paths[split.value.lower()])
        expected_items = output.partitioned_items[split]
        assert len(split_items) == len(expected_items)
        assert [i.corpus_id for i in split_items] == [i.corpus_id for i in expected_items]
        assert [i.sha256 for i in split_items] == [i.sha256 for i in expected_items]


def test_processed_directory_tamper_detection(tmp_path: Path) -> None:
    """Verifies that corrupted files or mismatched counts trigger ModuleContractViolationError."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)
    export_paths = export_processed_corpus(output, tmp_path)

    # 1. Missing target dir
    with pytest.raises(ModuleContractViolationError, match="does not exist"):
        verify_processed_directory_layout(tmp_path / "nonexistent")

    # 2. Corrupt train.jsonl with invalid hash
    train_path = export_paths["train"]
    with open(train_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if lines:
        record = json.loads(lines[0])
        record["sha256"] = "0" * 64  # Invalid sha256 that does not match clean_text
        corrupt_lines = [json.dumps(record) + "\n"] + lines[1:]
        with open(train_path, "w", encoding="utf-8") as f:
            f.writelines(corrupt_lines)

        with pytest.raises(ModuleContractViolationError, match="Hash mismatch"):
            verify_processed_directory_layout(tmp_path)

    # 3. Missing manifest file
    (tmp_path / MANIFEST_FILE_NAME).unlink()
    with pytest.raises(ModuleContractViolationError, match="Missing manifest.json"):
        verify_processed_directory_layout(tmp_path)


def test_processed_directory_split_count_mismatch(tmp_path: Path) -> None:
    """Verifies that split file with count differing from split_manifest raises."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)
    export_paths = export_processed_corpus(output, tmp_path)

    # Empty out the test split file while split_manifest still expects items
    test_path = export_paths["test"]
    # Check if test split had items
    if output.split_manifest.split_counts.get("TEST", 0) > 0:
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("")  # Clear lines

        with pytest.raises(ModuleContractViolationError, match="item count mismatch"):
            verify_processed_directory_layout(tmp_path)


def test_gitignore_data_directory_rules() -> None:
    """Verifies git ignore behavior for data/ directory according to project policy."""
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Test that data files in raw, processed, and cache are ignored
    files_to_be_ignored = [
        "data/raw/sample_paper.pdf",
        "data/raw/corpus.txt",
        "data/processed/train.jsonl",
        "data/processed/manifest.json",
        "data/processed/split_manifest.json",
        "data/cache/tokens.bin",
    ]

    for rel_path in files_to_be_ignored:
        result = subprocess.run(
            ["git", "check-ignore", rel_path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Expected {rel_path} to be ignored by git"

    # Test that .gitkeep files in data subdirectories are tracked (NOT ignored)
    gitkeep_files = [
        "data/raw/.gitkeep",
        "data/processed/.gitkeep",
        "data/cache/.gitkeep",
    ]

    for rel_path in gitkeep_files:
        result = subprocess.run(
            ["git", "check-ignore", rel_path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, f"Expected {rel_path} to NOT be ignored by git"


def test_m1_exit_gate_comprehensive_verification(tmp_path: Path) -> None:
    """Consolidated end-to-end M1 exit gate verification against all Layer 0 specifications."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus, manifest_id="m1-final-exit-gate")

    # M1-Exit-1: License Verification & Quarantine
    assert len(output.quarantined) == 2
    for item in output.unique_items:
        assert item.license_provenance.authorized is True

    # M1-Exit-2: Text Normalization
    for item in output.unique_items:
        assert item.clean_text != ""
        assert "\u200b" not in item.clean_text  # No zero-width spaces
        assert "ﬁ" not in item.clean_text  # No ligatures

    # M1-Exit-3: Canonical SHA-256 Content Hashing
    for item in output.unique_items:
        assert len(item.sha256) == 64
        assert int(item.sha256, 16) > 0

    # M1-Exit-4: Exact & Near-Duplicate Deduplication
    canonical_ids = {item.corpus_id for item in output.unique_items}
    assert "synth-001" in canonical_ids
    assert "synth-001-dup" not in canonical_ids
    assert "synth-002-near" not in canonical_ids

    # M1-Exit-5: Zero Author Leakage
    train_authors = set()
    val_authors = set()
    test_authors = set()
    author_map = {doc.corpus_id: doc.authors for doc in corpus}

    for item in output.partitioned_items[DatasetSplit.TRAIN]:
        train_authors.update(author_map.get(item.corpus_id, []))
    for item in output.partitioned_items[DatasetSplit.VAL]:
        val_authors.update(author_map.get(item.corpus_id, []))
    for item in output.partitioned_items[DatasetSplit.TEST]:
        test_authors.update(author_map.get(item.corpus_id, []))

    assert train_authors.isdisjoint(val_authors)
    assert train_authors.isdisjoint(test_authors)
    assert val_authors.isdisjoint(test_authors)

    # M1-Exit-6: Processed Directory Artifact Integrity
    export_paths = export_processed_corpus(output, tmp_path)
    assert verify_processed_directory_layout(tmp_path)

    # Verify that split files match output byte lengths and counts
    for split in (DatasetSplit.TRAIN, DatasetSplit.VAL, DatasetSplit.TEST):
        loaded = load_processed_split(export_paths[split.value.lower()])
        assert len(loaded) == output.split_manifest.split_counts[split.value]


def test_storage_edge_cases_and_error_handling(tmp_path: Path) -> None:
    """Tests edge cases, missing files, and unauthorized records in storage."""
    # 1. load_processed_split on non-existent file
    with pytest.raises(FileNotFoundError, match="not found"):
        load_processed_split(tmp_path / "missing.jsonl")

    # 2. Corrupt JSON in split file
    corrupt_jsonl = tmp_path / "corrupt.jsonl"
    with open(corrupt_jsonl, "w", encoding="utf-8") as f:
        f.write("\n\n  \n")  # Empty lines should be safely skipped
        f.write("{invalid json}\n")
    with pytest.raises(ModuleContractViolationError, match="Corrupt record"):
        load_processed_split(corrupt_jsonl)

    # 3. Unauthorized item in split file
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)
    export_paths = export_processed_corpus(output, tmp_path)

    val_path = export_paths["val"]
    with open(val_path, "r", encoding="utf-8") as f:
        val_lines = f.readlines()

    if val_lines:
        record = json.loads(val_lines[0])
        record["license_provenance"]["declared_license"] = "Proprietary-Unauthorized"
        with open(val_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        with pytest.raises(ModuleContractViolationError, match="Unauthorized item"):
            load_processed_split(val_path)

    # 4. Missing split_manifest.json
    (tmp_path / SPLIT_MANIFEST_FILE_NAME).unlink()
    with pytest.raises(ModuleContractViolationError, match="Missing split_manifest.json"):
        verify_processed_directory_layout(tmp_path)


def test_storage_split_file_missing_and_mismatches(tmp_path: Path) -> None:
    """Tests missing split file and manifest item count mismatch."""
    corpus = get_standard_synthetic_corpus()
    pipeline = Layer0Pipeline()
    output = pipeline.execute(corpus)
    export_paths = export_processed_corpus(output, tmp_path)

    # 1. Missing a split file
    export_paths["val"].unlink()
    with pytest.raises(ModuleContractViolationError, match="Missing split file"):
        verify_processed_directory_layout(tmp_path)

    # Re-export clean
    export_processed_corpus(output, tmp_path)

    # 2. Tamper total_items in split_manifest.json
    sm_path = tmp_path / SPLIT_MANIFEST_FILE_NAME
    with open(sm_path, "r", encoding="utf-8") as f:
        sm_data = json.load(f)
    sm_data["total_items"] = 9999
    with open(sm_path, "w", encoding="utf-8") as f:
        json.dump(sm_data, f)
    with pytest.raises(ModuleContractViolationError, match="Total items mismatch"):
        verify_processed_directory_layout(tmp_path)

    # 3. Tamper items list in manifest.json
    m_path = tmp_path / MANIFEST_FILE_NAME
    with open(m_path, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    m_data["items"] = m_data["items"][:-1]  # Drop one item
    with open(m_path, "w", encoding="utf-8") as f:
        json.dump(m_data, f)
    # Re-write valid split_manifest so only manifest count mismatches
    sm_data["total_items"] = len(output.unique_items)
    with open(sm_path, "w", encoding="utf-8") as f:
        json.dump(sm_data, f)
    with pytest.raises(ModuleContractViolationError, match="Manifest items count"):
        verify_processed_directory_layout(tmp_path)

