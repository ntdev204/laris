"""Tests for bilingual expansion dataset acquisition logic (no network access)."""

import importlib.util
import io
import lzma
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def acq():
    spec = importlib.util.spec_from_file_location(
        "acquire_datasets_under_test", REPO_ROOT / "scripts" / "acquire_datasets.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _finalize(acq, tmp_path, **overrides):
    kwargs = dict(
        dataset_id="X",
        name="X",
        version="v",
        source_url="u",
        license_name="MIT",
        license_approved=True,
        language="Vietnamese",
        sample_unit="pair",
        expected="n",
        dest_dir=acq.REPO_ROOT / "data" / "raw" / "x",
        records=[{"sha256": "abc"}],
        size=10,
        rows=100,
        complete=True,
        min_rows=50,
        notes="",
    )
    kwargs.update(overrides)
    return acq._finalize_entry(**kwargs)


def test_expansion_registry_covers_all_seven_datasets(acq):
    assert set(acq.EXPANSION_ACQUIRERS) == {
        "VINLI",
        "VISTS",
        "VI-PAWS",
        "CC100-VI-CLEAN",
        "HOTPOTQA",
        "FEVER",
        "UIT-VIQUAD-V2",
    }


def test_verified_requires_approved_license_and_row_floor(acq, tmp_path):
    entry = _finalize(acq, tmp_path)
    assert entry.acquisition_status == "VERIFIED"
    assert entry.license_status == "APPROVED_FOR_ACQUISITION"
    assert entry.schema_valid is True


def test_unapproved_license_is_downloaded_not_verified(acq, tmp_path):
    entry = _finalize(acq, tmp_path, license_approved=False)
    assert entry.acquisition_status == "DOWNLOADED"
    assert entry.license_status == "NEEDS_LICENSE_REVIEW"


def test_incomplete_or_empty_download_is_skipped(acq, tmp_path):
    assert _finalize(acq, tmp_path, complete=False).acquisition_status == "SKIPPED_TEMPORARILY"
    assert _finalize(acq, tmp_path, rows=0, records=[]).acquisition_status == "SKIPPED_TEMPORARILY"


def test_row_floor_failure_is_not_verified(acq, tmp_path):
    entry = _finalize(acq, tmp_path, rows=10)
    assert entry.schema_valid is False
    assert entry.acquisition_status == "DOWNLOADED"


def test_vi_paws_is_blocked_without_fabricated_data(acq):
    entry = acq.record_vi_paws_status()
    assert entry.acquisition_status == "BLOCKED"
    assert entry.actual_sample_count == 0
    assert entry.files == []


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_cc100_stream_splits_documents_on_blank_lines(acq, monkeypatch):
    text = "dòng một\ndòng hai\n\nbài hai\n\n\nbài ba\n\n"
    payload = lzma.compress(text.encode("utf-8"))
    monkeypatch.setattr(
        acq.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    docs = list(acq._iter_cc100_documents("http://example.invalid/vi.txt.xz", max_docs=10))
    assert docs == ["dòng một\ndòng hai", "bài hai", "bài ba"]


def test_cc100_stream_respects_max_docs(acq, monkeypatch):
    payload = lzma.compress(("doc\n\n" * 20).encode("utf-8"))
    monkeypatch.setattr(
        acq.urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(payload)
    )
    docs = list(acq._iter_cc100_documents("http://example.invalid/vi.txt.xz", max_docs=5))
    assert len(docs) == 5


def test_cc100_resume_state_rebuilds_digests_and_counts(acq, tmp_path):
    import hashlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    for idx, texts in enumerate([["a", "b"], ["c"]]):
        table = pa.table({"text": texts})
        pq.write_table(table, tmp_path / f"{idx:04d}.parquet")
    (tmp_path / "0002.parquet.tmp").write_bytes(b"partial")

    seen, kept, next_shard = acq._resume_cc100_state(tmp_path)

    assert kept == 3
    assert next_shard == 2
    assert hashlib.sha256(b"b").digest()[:16] in seen
    assert not list(tmp_path.glob("*.tmp"))
