"""Tests for bilingual expansion dataset acquisition logic (no network access)."""

import io
import lzma
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


class _Acq:
    """Facade exposing the acquisition package modules as one namespace for the tests."""

    from laris.corpus.acquisition import common as _common
    from laris.corpus.acquisition import registry as _registry
    from laris.corpus.acquisition.sources import cc100 as _cc100
    from laris.corpus.acquisition.sources import expansion as _expansion

    REPO_ROOT = _common.REPO_ROOT
    urllib = _common.urllib
    _finalize_entry = staticmethod(_common._finalize_entry)
    EXPANSION_ACQUIRERS = _registry.EXPANSION_ACQUIRERS
    _iter_cc100_documents = staticmethod(_cc100._iter_cc100_documents)
    _resume_cc100_state = staticmethod(_cc100._resume_cc100_state)


@pytest.fixture(scope="module")
def acq():
    return _Acq


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


def test_expansion_registry_covers_all_six_datasets(acq):
    assert set(acq.EXPANSION_ACQUIRERS) == {
        "VINLI",
        "VISTS",
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


def test_owner_approved_dataset_is_verified_with_audit_note(acq, tmp_path):
    entry = _finalize(acq, tmp_path, dataset_id="VINLI", license_approved=False)
    assert entry.acquisition_status == "VERIFIED"
    assert entry.license_status == "APPROVED_BY_OWNER"
    assert "owner" in entry.notes and "not a legal clearance" in entry.notes


def test_owner_approval_does_not_rescue_incomplete_download(acq, tmp_path):
    entry = _finalize(acq, tmp_path, dataset_id="VINLI", license_approved=False, complete=False)
    assert entry.acquisition_status == "SKIPPED_TEMPORARILY"


def test_incomplete_or_empty_download_is_skipped(acq, tmp_path):
    assert _finalize(acq, tmp_path, complete=False).acquisition_status == "SKIPPED_TEMPORARILY"
    assert _finalize(acq, tmp_path, rows=0, records=[]).acquisition_status == "SKIPPED_TEMPORARILY"


def test_row_floor_failure_is_not_verified(acq, tmp_path):
    entry = _finalize(acq, tmp_path, rows=10)
    assert entry.schema_valid is False
    assert entry.acquisition_status == "DOWNLOADED"


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
