"""Shared dataclasses, hashing, download and manifest-entry helpers for dataset acquisition."""

import hashlib
import json
import shutil
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[4]


DATA_DIR = REPO_ROOT / "data"


RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"


MANIFEST_PATH = DATA_DIR / "acquisition_manifest.json"


@dataclass
class DatasetEntry:
    dataset_id: str
    name: str
    version: str
    official_source_url: str
    license_name: str
    license_status: str  # APPROVED_FOR_ACQUISITION, NEEDS_LICENSE_REVIEW, BLOCKED, REJECTED
    acquisition_status: str  # DOWNLOADED, VERIFIED, SKIPPED_TEMPORARILY, BLOCKED
    language: str
    sample_unit: str
    expected_sample_count: str
    actual_sample_count: int
    actual_size_bytes: int
    sha256_checksum: str
    storage_path: str
    schema_valid: bool
    notes: str
    files: List[Dict[str, Any]] = field(default_factory=list)


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a local file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest_path: Path, max_retries: int = 3) -> bool:
    """Downloads a file with User-Agent header and progress reporting."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists() and dest_path.stat().st_size > 0:
        print(f"  [CACHE] File already exists: {dest_path.name} ({dest_path.stat().st_size} bytes)")
        return True

    print(f"  [DOWNLOADING] {url} -> {dest_path.name}...")
    headers = {"User-Agent": "LARIS-Research-Agent/1.0 (+https://github.com/ntdev204/laris)"}
    req = urllib.request.Request(url, headers=headers)

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            print(f"  [DONE] {dest_path.name} ({dest_path.stat().st_size} bytes)")
            return True
        except Exception as e:
            print(f"  [WARN] Attempt {attempt+1} failed for {url}: {e}")
            if dest_path.exists():
                dest_path.unlink()
    return False


def count_conllu_sentences(file_path: Path) -> int:
    """Counts sentences in a CoNLL-U format file (# text = ... or # sent_id = ...)."""
    count = 0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("# sent_id ="):
                count += 1
    return count


def count_jsonl_lines(file_path: Path) -> int:
    """Counts valid lines in a JSONL file."""
    count = 0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def count_viquad_questions(file_path: Path) -> int:
    """Counts questions in a SQuAD/ViQuAD format JSON file."""
    count = 0
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        for article in data.get("data", []):
            for paragraph in article.get("paragraphs", []):
                count += len(paragraph.get("qas", []))
    return count


def count_parquet_rows(file_path: Path) -> int:
    """Counts rows in a Parquet file using pyarrow."""
    try:
        import pyarrow.parquet as pq
        return int(pq.read_metadata(file_path).num_rows)
    except Exception:
        return 0


HF_RESOLVE = "https://huggingface.co/datasets/{repo}/resolve/{rev}/{path}"


HF_PARQUET_REV = "refs%2Fconvert%2Fparquet"


def _record_files(
    dest_dir: Path, names: Sequence[str], counter
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Builds manifest file records (bytes, rows, SHA-256) for already downloaded files."""
    records: List[Dict[str, Any]] = []
    total_size = 0
    total_rows = 0
    for name in names:
        fpath = dest_dir / name
        if not fpath.exists():
            continue
        size = fpath.stat().st_size
        rows = counter(fpath)
        total_size += size
        total_rows += rows
        records.append({
            "filename": name,
            "bytes": size,
            "sample_count": rows,
            "sha256": compute_sha256(fpath),
        })
    return records, total_size, total_rows


def _acquire_remote_files(
    dest_dir: Path,
    files: Sequence[Tuple[str, str]],
    counter,
) -> Tuple[List[Dict[str, Any]], int, int, bool]:
    """Downloads (remote_url, local_name) pairs; returns records, bytes, rows, all_ok."""
    all_ok = True
    for url, local_name in files:
        if not download_file(url, dest_dir / local_name):
            all_ok = False
    records, size, rows = _record_files(dest_dir, [n for _, n in files], counter)
    return records, size, rows, all_ok and len(records) == len(files)


def _blocked_entry(
    dataset_id: str,
    name: str,
    version: str,
    source_url: str,
    license_name: str,
    language: str,
    sample_unit: str,
    expected: str,
    storage: str,
    notes: str,
) -> DatasetEntry:
    return DatasetEntry(
        dataset_id=dataset_id,
        name=name,
        version=version,
        official_source_url=source_url,
        license_name=license_name,
        license_status="BLOCKED",
        acquisition_status="BLOCKED",
        language=language,
        sample_unit=sample_unit,
        expected_sample_count=expected,
        actual_sample_count=0,
        actual_size_bytes=0,
        sha256_checksum="",
        storage_path=storage,
        schema_valid=False,
        notes=notes,
        files=[],
    )


# Datasets whose publisher declares no usable license but whose use the project owner approved.
# This is an owner decision recorded for governance, not a legal clearance.
OWNER_APPROVED_DATASETS = {
    "VINLI": "2026-10-29",
    "UIT-VIQUAD-V2": "2026-10-29",
    "CC100-VI-CLEAN": "2026-10-29",
}
LICENSE_APPROVED = "APPROVED_FOR_ACQUISITION"
LICENSE_OWNER_APPROVED = "APPROVED_BY_OWNER"
APPROVED_LICENSE_STATUSES = frozenset({LICENSE_APPROVED, LICENSE_OWNER_APPROVED})


def _finalize_entry(
    *,
    dataset_id: str,
    name: str,
    version: str,
    source_url: str,
    license_name: str,
    license_approved: bool,
    language: str,
    sample_unit: str,
    expected: str,
    dest_dir: Path,
    records: List[Dict[str, Any]],
    size: int,
    rows: int,
    complete: bool,
    min_rows: int,
    notes: str,
) -> DatasetEntry:
    """VERIFIED requires complete download, row floor met, and an approved license."""
    owner_approved = not license_approved and dataset_id in OWNER_APPROVED_DATASETS
    if owner_approved:
        notes = (
            f"{notes} License not declared by the publisher; use approved by the project owner "
            f"on {OWNER_APPROVED_DATASETS[dataset_id]} (owner decision, not a legal clearance)."
        ).strip()
    schema_valid = complete and rows >= min_rows
    if not complete or rows == 0:
        status = "SKIPPED_TEMPORARILY"
    elif schema_valid and (license_approved or owner_approved):
        status = "VERIFIED"
    else:
        status = "DOWNLOADED"
    return DatasetEntry(
        dataset_id=dataset_id,
        name=name,
        version=version,
        official_source_url=source_url,
        license_name=license_name,
        license_status=(
            LICENSE_APPROVED
            if license_approved
            else LICENSE_OWNER_APPROVED
            if owner_approved
            else "NEEDS_LICENSE_REVIEW"
        ),
        acquisition_status=status,
        language=language,
        sample_unit=sample_unit,
        expected_sample_count=expected,
        actual_sample_count=rows,
        actual_size_bytes=size,
        sha256_checksum=records[0]["sha256"] if records else "",
        storage_path=str(dest_dir.relative_to(REPO_ROOT)),
        schema_valid=schema_valid,
        notes=notes,
        files=records,
    )
