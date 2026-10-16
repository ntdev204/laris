"""Tests for dataset acquisition manifest, licensing, and schema verification (Issue #200)."""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "acquisition_manifest.json"


@pytest.fixture
def manifest_data():
    """Loads the dataset acquisition manifest."""
    assert MANIFEST_PATH.exists(), f"Acquisition manifest missing at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_manifest_structure(manifest_data):
    """Verifies top-level manifest structure and governance fields."""
    assert manifest_data["manifest_version"] == "1.0.0"
    assert manifest_data["training_freeze_confirmed"] is True
    assert manifest_data["total_datasets_tracked"] >= 10
    assert manifest_data["total_acquired_bytes"] > 50_000_000  # > 50 MB acquired
    assert manifest_data["total_acquired_samples"] > 100_000  # > 100k verified samples


def test_training_freeze_in_manifest(manifest_data):
    """Verifies that no model training was executed."""
    assert manifest_data.get("training_freeze_confirmed") is True


def test_dataset_entries_valid(manifest_data):
    """Verifies that all dataset entries contain required metadata."""
    required_keys = [
        "dataset_id",
        "name",
        "version",
        "official_source_url",
        "license_name",
        "license_status",
        "acquisition_status",
        "language",
        "sample_unit",
        "actual_sample_count",
        "actual_size_bytes",
        "storage_path",
        "schema_valid",
    ]
    for d in manifest_data["datasets"]:
        for k in required_keys:
            assert k in d, f"Dataset {d.get('dataset_id')} missing key '{k}'"
        assert d["license_status"] in [
            "APPROVED_FOR_ACQUISITION",
            "NEEDS_LICENSE_REVIEW",
            "BLOCKED",
            "REJECTED",
        ]
        assert d["acquisition_status"] in [
            "PROPOSED",
            "DOWNLOADED",
            "VERIFIED",
            "SKIPPED_TEMPORARILY",
            "BLOCKED",
        ]


def test_verified_datasets_exist_on_disk(manifest_data):
    """Verifies that datasets marked VERIFIED have valid metadata and files when local."""
    for d in manifest_data["datasets"]:
        if d["acquisition_status"] == "VERIFIED":
            assert d["actual_sample_count"] > 0
            assert d["actual_size_bytes"] > 0
            assert d["schema_valid"] is True
            storage = REPO_ROOT / d["storage_path"]
            if storage.exists():
                files = list(storage.rglob("*"))
                assert any(f.is_file() and f.stat().st_size > 0 for f in files)


def test_english_and_vietnamese_separation(manifest_data):
    """Verifies that English and Vietnamese tracks are separated."""
    en_datasets = [d for d in manifest_data["datasets"] if d["language"] == "English"]
    vi_datasets = [d for d in manifest_data["datasets"] if d["language"] == "Vietnamese"]
    assert len(en_datasets) >= 4
    assert len(vi_datasets) >= 2


def test_s2orc_cap_and_skip_status(manifest_data):
    """Verifies S2ORC is audited with strict caps and skipped responsibly."""
    s2orc_entries = [d for d in manifest_data["datasets"] if "S2ORC" in d["dataset_id"]]
    assert len(s2orc_entries) == 1
    s2orc = s2orc_entries[0]
    assert s2orc["acquisition_status"] == "SKIPPED_TEMPORARILY"
    assert s2orc["actual_size_bytes"] < 20 * (1024**3)  # < 20 GB
    assert s2orc["actual_sample_count"] < 20_000_000  # < 20M samples
    assert "401" in s2orc["notes"] or "Unauthorized" in s2orc["notes"]


def test_laris_gold_specification_status(manifest_data):
    """Verifies LARIS-GOLD is marked PROPOSED without fabricated annotations."""
    gold_entries = [d for d in manifest_data["datasets"] if d["dataset_id"] == "LARIS-GOLD"]
    assert len(gold_entries) == 1
    gold = gold_entries[0]
    assert gold["acquisition_status"] == "PROPOSED"
    assert gold["actual_sample_count"] == 0  # No fabricated annotations


def test_semantic_similarity_coverage_present(manifest_data):
    """Verifies dedicated semantic similarity coverage via STS-B (Issue #205 item 3)."""
    stsb_entries = [d for d in manifest_data["datasets"] if d["dataset_id"] == "STSB"]
    assert len(stsb_entries) == 1
    stsb = stsb_entries[0]
    assert stsb["acquisition_status"] == "VERIFIED"
    assert stsb["actual_sample_count"] == 8628
    assert "0.0-1.0" in stsb["sample_unit"] or "0.0-1.0" in stsb["notes"]


def test_reconciled_doclaynet_count(manifest_data):
    """Verifies DocLayNet does not claim full 80,863 pages as downloaded (Issue #205 item 1)."""
    doclaynet = next(d for d in manifest_data["datasets"] if d["dataset_id"] == "DOCLAYNET-BOUNDED")
    assert doclaynet["actual_sample_count"] == 1  # Verified local artifact count
    assert doclaynet["actual_sample_count"] != 80863


def test_candidate_datasets_coverage(manifest_data):
    """Verifies all four authorized candidate datasets are verified (Issue #205)."""
    expected_ids = {"STSB", "QUORA-DUPLICATES", "ALL-NLI", "SQUAD"}
    found_ids = {
        d["dataset_id"] for d in manifest_data["datasets"] if d["dataset_id"] in expected_ids
    }
    assert found_ids == expected_ids
    for d in manifest_data["datasets"]:
        if d["dataset_id"] in expected_ids:
            assert d["acquisition_status"] == "VERIFIED"
            assert d["schema_valid"] is True
            assert d["actual_sample_count"] > 0

